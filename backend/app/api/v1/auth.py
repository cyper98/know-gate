"""Auth API endpoints (6 routes per brainstorm §5.1 F1).

Per the auth model:
- POST /auth/register         — bootstrap first user (admin) only; second+ rejected
- POST /auth/login            — email + password → JWT pair
- POST /auth/oauth/{provider}  — generate authorize URL (returns JSON with redirect URL)
- GET  /auth/oauth/{provider}/callback — provider redirect target
- POST /auth/magic-link       — request a magic-link email
- GET  /auth/magic-link/verify — consume a magic-link token
- POST /auth/refresh          — exchange refresh token for new access token (rotation)
- POST /auth/logout           — revoke current access token (jti → Redis)
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.audit.log import log_event
from app.auth.jwt import (
    TokenError,
    create_access_token,
    create_refresh_token,
    verify_token,
)
from app.auth.magic_link import request_magic_link, verify_magic_link
from app.auth.oauth import get_authorization_url
from app.auth.oauth import handle_callback as oauth_handle_callback
from app.auth.password import hash_password, needs_rehash, verify_password
from app.auth.permissions import CurrentUser
from app.cache.helpers import check_ip_rate_limit, revoke_jti
from app.config import get_settings
from app.db.enums import UserStatus
from app.db.models import User, UserRole
from app.db.models.role import Role
from app.db.session import get_session_factory

from app.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# === Request/Response schemas ===

class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MagicLinkRequest(BaseModel):
    email: EmailStr


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


# === Helpers ===

def _build_jwt_pair(user_id: str, role_names: list[str]) -> tuple[str, str, int]:
    """Mint access + refresh tokens, return (access, refresh, expires_in)."""
    access_token, _, _ = create_access_token(user_id, role_names)
    refresh_token, _, _ = create_refresh_token(user_id)
    expires_in = 15 * 60  # 15 minutes
    return access_token, refresh_token, expires_in


def _user_response(user: User, role_names: list[str]) -> dict:
    """Build the `user` sub-object of auth responses (no password hash)."""
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "language_pref": user.language_pref,
        "status": user.status,
        "roles": role_names,
    }


async def _load_user_with_roles(user_id: str) -> tuple[User, list[str]] | None:
    """Fetch user + role names. Returns None if user missing/inactive."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None or user.status != UserStatus.ACTIVE.value:
            return None
        ur_result = await session.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        role_names = [row[0] for row in ur_result.all()]
        return user, role_names


# === Endpoints ===

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
) -> dict:
    """Bootstrap-only: create the FIRST user as admin, OR reject if users exist.

    Disabled once any user exists. New users are created via admin invite flow
    (separate endpoint, added in a later iteration).
    """
    factory = get_session_factory()
    async with factory() as session:
        # Reject if any user already exists
        count_result = await session.execute(select(func.count(User.id)))
        user_count = count_result.scalar_one() or 0
        if user_count > 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is closed. Contact your admin to be invited.",
            )

        # Reject duplicate email
        existing = await session.execute(select(User).where(User.email == body.email))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        user = User(
            email=body.email,
            display_name=body.display_name,
            password_hash=hash_password(body.password),
            language_pref="en",
            status=UserStatus.ACTIVE.value,
        )
        session.add(user)
        await session.flush()

        # Assign admin role
        role_result = await session.execute(select(Role).where(Role.name == "admin"))
        admin_role = role_result.scalar_one_or_none()
        if admin_role:
            session.add(
                UserRole(
                    user_id=user.id,
                    role_id=admin_role.id,
                    granted_at=datetime.now(UTC),
                )
            )

        await session.commit()
        user_id = user.id

    # Audit (best-effort, non-blocking)
    import asyncio
    asyncio.create_task(  # noqa: RUF006 — fire-and-forget by design
        log_event(
            actor_id=user_id,
            actor_email=body.email,
            action="user.register",
            target_type="user",
            target_id=user_id,
            after={"email": body.email, "display_name": body.display_name, "role": "admin"},
            ip_address=getattr(request.state, "client_ip", None)
            or (request.client.host if request.client else None),
        )
    )

    access, refresh, expires_in = _build_jwt_pair(user_id, ["admin"])
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": {
            "id": user_id,
            "email": body.email,
            "display_name": body.display_name,
            "language_pref": "en",
            "status": UserStatus.ACTIVE.value,
            "roles": ["admin"],
        },
    }


@router.post("/login", response_model=TokenPairResponse)
async def login(
    body: LoginRequest,
    request: Request,
) -> dict:
    """Email + password login. Rate limited: 5 attempts per 15 min per IP+email."""
    settings = get_settings()
    # Prefer the X-Forwarded-For-aware client IP captured by ClientIPMiddleware
    # (correct behind a proxy), fall back to the direct connection host.
    client_ip = (
        getattr(request.state, "client_ip", None)
        or (request.client.host if request.client else None)
        or "unknown"
    )
    # Hash the email before using it in the rate-limit key so plaintext PII
    # is not stored in the Redis keyspace.
    import hashlib

    email_hash = hashlib.sha256(body.email.lower().encode("utf-8")).hexdigest()[:16]
    rate_key = f"{client_ip}:{email_hash}"
    _count, allowed = await check_ip_rate_limit(
        rate_key, window=900, limit=settings.rate_limit_login_per_15min
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in 15 minutes.",
            headers={"Retry-After": "900"},
        )

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == body.email))
        user = result.scalar_one_or_none()

    if user is None or user.status != UserStatus.ACTIVE.value:
        # Don't reveal which is wrong (avoid user-enumeration)
        # Still run a hash compare to keep timing constant
        if user is not None and user.password_hash:
            verify_password(body.password, user.password_hash)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Load roles
    async with factory() as session:
        ur_result = await session.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
        role_names = [row[0] for row in ur_result.all()]

    # Update last_login_at (best-effort)
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        u = result.scalar_one()
        u.last_login_at = datetime.now(UTC)
        await session.commit()

    # If hash uses outdated params, re-hash transparently
    if needs_rehash(user.password_hash):
        async with factory() as session:
            result = await session.execute(select(User).where(User.id == user.id))
            u = result.scalar_one()
            u.password_hash = hash_password(body.password)
            await session.commit()

    access, refresh, expires_in = _build_jwt_pair(user.id, role_names)

    # Audit
    import asyncio
    asyncio.create_task(  # noqa: RUF006 — fire-and-forget by design
        log_event(
            actor_id=user.id,
            actor_email=user.email,
            action="user.login",
            target_type="user",
            target_id=user.id,
            ip_address=client_ip,
        )
    )

    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": _user_response(user, role_names),
    }


@router.post("/oauth/{provider}")
async def oauth_start(provider: str) -> dict:
    """Start OAuth flow: returns JSON with `authorize_url` to redirect the user to.

    Client (web UI or CLI) then redirects the user to `authorize_url`. The
    provider will redirect back to `/auth/oauth/{provider}/callback?code=...&state=...`.
    """
    try:
        url = await get_authorization_url(provider)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    return {"authorize_url": url}


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
) -> dict:
    """OAuth callback endpoint (provider redirects user here). Issues JWT pair.

    On success, returns the same `TokenPairResponse` shape as `/auth/login`.
    """
    result = await oauth_handle_callback(provider, code, state)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state. Please try signing in again.",
        )
    return {
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "token_type": "bearer",
        "expires_in": 15 * 60,
        "user": result["user"],
        "roles": result["role_names"],
    }


@router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
async def magic_link_request(
    body: MagicLinkRequest,
) -> dict:
    """Request a magic-link sign-in email. Always returns 202 (don't leak account existence)."""
    settings = get_settings()
    base_url = f"http://{settings.kg_domain}:3000"  # web UI handles the actual click
    await request_magic_link(body.email, base_url)
    return {"message": "If an account exists for this email, a sign-in link has been sent."}


@router.get("/magic-link/verify")
async def magic_link_verify(token: str = Query(...)) -> dict:
    """Consume a magic-link token. Returns JWT pair on success."""
    result = await verify_magic_link(token)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired magic link.",
        )
    return {
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "token_type": "bearer",
        "expires_in": 15 * 60,
        "user": result["user"],
        "roles": result["role_names"],
    }


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(body: RefreshRequest) -> dict:
    """Exchange refresh token for new access + refresh pair (rotation).

    The old refresh token's `jti` is revoked (added to the Redis revocation
    set for its remaining lifetime) so a stolen refresh token can only be
    used once.
    """
    from datetime import datetime as _dt

    try:
        claims = verify_token(body.refresh_token, expected_type="refresh")
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e

    user_id = claims["sub"]
    loaded = await _load_user_with_roles(user_id)
    if loaded is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists or is inactive",
        )
    user, role_names = loaded

    # Revoke the old refresh token's jti for the remainder of its lifetime.
    old_jti = claims.get("jti")
    old_exp = claims.get("exp")
    if old_jti and old_exp:
        ttl = max(0, int(old_exp) - int(_dt.now(UTC).timestamp()))
        if ttl > 0:
            await revoke_jti(old_jti, ttl)

    access, refresh_token, expires_in = _build_jwt_pair(user.id, role_names)
    return {
        "access_token": access,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": _user_response(user, role_names),
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(user: CurrentUser, request: Request):
    """Revoke the current access token (jti in Redis until original exp)."""
    client_ip = (
        getattr(request.state, "client_ip", None)
        or (request.client.host if request.client else None)
    )
    jti = user.get("jti")
    exp = user.get("exp")
    if jti and exp:
        # Revoke for the remaining lifetime
        now = int(datetime.now(UTC).timestamp())
        ttl = max(0, exp - now)
        if ttl > 0:
            await revoke_jti(jti, ttl)

    import asyncio
    asyncio.create_task(  # noqa: RUF006 — fire-and-forget by design
        log_event(
            actor_id=user["id"],
            actor_email=None,  # already in claims
            action="user.logout",
            target_type="user",
            target_id=user["id"],
            ip_address=client_ip,
        )
    )
