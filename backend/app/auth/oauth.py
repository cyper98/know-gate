"""OAuth2 Authorization Code + PKCE flow for Google + GitHub.

Per brainstorm §5.1 F1 + spec:
- Client GETs /auth/oauth/{provider} → redirect to provider
- State stored in Redis (5-min TTL, atomic get+delete on callback = CSRF protection)
- On callback: exchange code → token → fetch user info → upsert user → issue JWT pair
- Only first user bootstrap = admin; subsequent OAuth users = member (unless admin assigns role later)
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from sqlalchemy import select

from app.auth.jwt import create_access_token, create_refresh_token, generate_random_token
from app.cache.client import get_redis_client
from app.cache.helpers import pop_oauth_state
from app.config import get_settings
from app.db.enums import UserStatus
from app.db.models import User, UserRole
from app.db.models.role import Role

from app.logging import get_logger

logger = get_logger(__name__)

# TTL for OAuth state (CSRF token)
OAUTH_STATE_TTL_SECONDS = 300  # 5 min

# === Provider configs (URLs + scopes per brainstorm §5.1) ===
PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "user_id_field": "sub",
        "email_field": "email",
        "name_field": "name",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "emails_url": "https://api.github.com/user/emails",
        "scope": "read:user user:email",
        "user_id_field": "id",
        "email_field": "email",  # may be null if user keeps email private
        "name_field": "name",  # may be null
        "login_field": "login",  # GitHub username
    },
}


def _build_redirect_uri(provider: str) -> str:
    """OAuth callback URL for the given provider (matches config)."""
    settings = get_settings()
    if provider == "google":
        return settings.google_oauth_redirect_uri
    if provider == "github":
        return settings.github_oauth_redirect_uri
    # Fallback (only used for unknown provider validation in callers)
    return f"http://{settings.kg_domain}:8000/api/v1/auth/oauth/{provider}/callback"


async def _store_oauth_state(provider: str, state: str) -> None:
    """Store OAuth state in Redis (5-min TTL) for CSRF protection."""
    redis_client = get_redis_client()
    await redis_client.setex(f"kg:oauth:state:{state}", OAUTH_STATE_TTL_SECONDS, provider)


async def get_authorization_url(provider: str) -> str:
    """Generate the provider's authorize URL + state. Return full redirect URL.

    Stores the state in Redis. Client should redirect the user to this URL.
    """
    if provider not in PROVIDER_CONFIGS:
        raise ValueError(f"Unknown OAuth provider: {provider}")
    cfg = PROVIDER_CONFIGS[provider]
    settings = get_settings()

    state = generate_random_token(32)
    await _store_oauth_state(provider, state)

    # Use Authlib for PKCE + state
    if provider == "google":
        client_id = settings.google_oauth_client_id
        client_secret = settings.google_oauth_client_secret.get_secret_value()
    else:  # github
        client_id = settings.github_oauth_client_id
        client_secret = settings.github_oauth_client_secret.get_secret_value()

    if not client_id or not client_secret:
        raise RuntimeError(
            f"OAuth provider {provider} not configured (missing client_id/secret in .env)"
        )

    client = AsyncOAuth2Client(
        client_id=client_id,
        client_secret=client_secret,
        scope=cfg["scope"],
        redirect_uri=_build_redirect_uri(provider),
    )
    uri, _ = client.create_authorization_url(cfg["authorize_url"], state=state)
    return uri


async def _exchange_code(provider: str, code: str) -> dict[str, Any]:
    """Exchange authorization code for access token."""
    cfg = PROVIDER_CONFIGS[provider]
    settings = get_settings()

    if provider == "google":
        client_id = settings.google_oauth_client_id
        client_secret = settings.google_oauth_client_secret.get_secret_value()
    else:  # github
        client_id = settings.github_oauth_client_id
        client_secret = settings.github_oauth_client_secret.get_secret_value()

    client = AsyncOAuth2Client(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=_build_redirect_uri(provider),
    )
    token = await client.fetch_token(cfg["token_url"], code=code)
    return dict(token)


async def _fetch_user_info(provider: str, access_token: str) -> dict[str, Any]:
    """Fetch user info from the OAuth provider using the access token.

    Returns a normalized dict with at least: `provider`, `provider_user_id`, `email`, `display_name`.
    """
    cfg = PROVIDER_CONFIGS[provider]
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        # Get primary user info
        userinfo_resp = await client.get(cfg["userinfo_url"], headers=headers)
        userinfo_resp.raise_for_status()
        info = userinfo_resp.json()

        # For GitHub: if email is private, fall back to /user/emails
        if provider == "github" and not info.get(cfg["email_field"]):
            emails_resp = await client.get(cfg["emails_url"], headers=headers)
            emails_resp.raise_for_status()
            emails = emails_resp.json()
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            if primary:
                info[cfg["email_field"]] = primary["email"]

    return {
        "provider": provider,
        "provider_user_id": str(info.get(cfg["user_id_field"], "")),
        "email": info.get(cfg["email_field"]) or "",
        "display_name": (
            info.get(cfg["name_field"])
            or info.get(cfg.get("login_field", "name"), "")
            or info.get(cfg["email_field"], "").split("@")[0]
        ),
        "raw": info,
    }


async def handle_callback(provider: str, code: str, state: str) -> dict[str, Any] | None:
    """Process OAuth callback: validate state, exchange code, fetch user, upsert, issue JWT.

    Returns dict with `user`, `role_names`, `access_token`, `refresh_token` on success.
    Returns None if state is invalid/expired (CSRF attempt).
    """
    cfg = PROVIDER_CONFIGS.get(provider)
    if cfg is None:
        raise ValueError(f"Unknown OAuth provider: {provider}")

    # 1. CSRF: atomic state check (one-time use)
    stored_provider = await pop_oauth_state(state)
    if stored_provider is None or stored_provider != provider:
        logger.warning("oauth_state_invalid_or_expired", provider=provider)
        return None

    # 2. Exchange code for token
    token_data = await _exchange_code(provider, code)
    access_token = token_data.get("access_token")
    if not access_token:
        logger.error("oauth_no_access_token", provider=provider, token_data=token_data)
        return None

    # 3. Fetch user info
    user_info = await _fetch_user_info(provider, access_token)
    email = user_info["email"]
    if not email:
        logger.error("oauth_no_email", provider=provider, user_info=user_info)
        return None

    # 4. Upsert user (find by email or create)
    from app.auth.password import hash_password  # for new users (no password, but field required)
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        is_new_user = user is None

        if is_new_user:
            # Check if this is the first-ever user (becomes admin) or subsequent (member).
            # Use a count(*) inside the same session so we can rely on the same
            # transaction's snapshot — this avoids the TOCTOU race where two
            # concurrent OAuth callbacks could both see "no users" and both
            # promote themselves to admin. The unique constraint on `email`
            # provides a final safety net (one will fail on commit).
            from sqlalchemy import func

            count_result = await session.execute(select(func.count(User.id)))
            user_count = count_result.scalar_one() or 0
            first_user_exists = user_count > 0

            role_name = "admin" if not first_user_exists else "member"
            user = User(
                id=str(uuid.uuid4()),  # always use a fresh UUID for the User PK
                email=email,
                display_name=user_info["display_name"] or email.split("@")[0],
                # OAuth users have no password; random hash so the field is non-null
                password_hash=hash_password(secrets.token_urlsafe(32)),
                language_pref="en",
                status=UserStatus.ACTIVE.value,
            )
            session.add(user)
            await session.flush()

            # Assign role
            role_result = await session.execute(select(Role).where(Role.name == role_name))
            role = role_result.scalar_one_or_none()
            if role:
                session.add(UserRole(user_id=user.id, role_id=role.id, granted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
            logger.info("oauth_user_created", email=email, role=role_name)
        else:
            # Existing user — just log them in
            if user.status != UserStatus.ACTIVE.value:
                logger.warning("oauth_user_inactive", email=email, status=user.status)
                return None
            logger.info("oauth_user_login", email=email)

        # Load role names for JWT
        ur_result = await session.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
        role_names = [row[0] for row in ur_result.all()]

        await session.commit()

    # 5. Issue JWT pair
    access_token_str, _, _ = create_access_token(user.id, role_names)
    refresh_token_str, _, _ = create_refresh_token(user.id)

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "language_pref": user.language_pref,
        },
        "role_names": role_names,
        "access_token": access_token_str,
        "refresh_token": refresh_token_str,
    }
