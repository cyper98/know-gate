"""Magic link sign-in (email a short-lived URL, click to authenticate).

Per brainstorm §5.1 F1: tokens are 32 random bytes, stored SHA-256 hashed,
single-use, 15-min TTL. The plaintext token is sent via email; only the
hash lives in DB. Verification hashes the inbound token and looks up the row.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select

from app.auth.jwt import create_access_token, create_refresh_token, generate_random_token
from app.db.models import User
from app.db.session import get_session_factory
from app.services.email import send_magic_link_email

from app.logging import get_logger

logger = get_logger(__name__)

# TTL for magic link tokens
DEFAULT_MAGIC_LINK_TTL_MINUTES = 15


def _hash_token(plaintext_token: str) -> str:
    """SHA-256 hash of the magic-link token (for at-rest storage)."""
    return hashlib.sha256(plaintext_token.encode("utf-8")).hexdigest()


def _build_magic_link_url(base_url: str, token: str) -> str:
    """Build the full magic-link URL the user clicks in their email."""
    return f"{base_url.rstrip('/')}/api/v1/auth/magic-link/verify?token={token}"


async def request_magic_link(email: str, base_url: str) -> bool:
    """Send a magic-link email. Returns True on send (regardless of whether user exists).

    Privacy: if the user doesn't exist, we still return True (don't leak
    account existence). The email is silently skipped.
    """
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            # Don't leak account existence — silently no-op
            logger.info("magic_link_requested_for_unknown_email", email=email)
            return True
        if user.status != "active":
            logger.warning("magic_link_requested_for_inactive_user", email=email, status=user.status)
            return True

        # Generate plaintext token + store SHA-256 hash
        plaintext = generate_random_token(32)
        token_hash = _hash_token(plaintext)
        # NOTE: tokens are stored in `users.password_hash` field? No — better
        # to add a dedicated `magic_link_tokens` table. For this scaffold,
        # we keep the token in-memory + email only (one-shot verification
        # requires the plaintext at consume time, so we keep it in Redis
        # with TTL — see Redis store below).
        from app.cache.client import get_redis_client

        redis_client = get_redis_client()
        ttl = DEFAULT_MAGIC_LINK_TTL_MINUTES * 60
        await redis_client.setex(f"kg:magic:{token_hash}", ttl, user.id)

        link = _build_magic_link_url(base_url, plaintext)
        sent = await send_magic_link_email(to=email, link=link, expires_minutes=DEFAULT_MAGIC_LINK_TTL_MINUTES)
        if sent:
            logger.info("magic_link_sent", email=email, user_id=user.id, expires_minutes=DEFAULT_MAGIC_LINK_TTL_MINUTES)
        return sent


async def verify_magic_link(token: str) -> dict | None:
    """Verify a magic-link token (consume one-time).

    Returns:
        Dict with `user` and JWT pair on success, None on invalid/expired/used.

    Side effects:
        - Deletes the token from Redis (one-time use)
        - Returns access + refresh JWT pair
    """
    token_hash = _hash_token(token)
    from app.cache.client import get_redis_client

    redis_client = get_redis_client()
    # Atomic get + delete (one-time use)
    async with redis_client.pipeline(transaction=True) as pipe:
        await pipe.get(f"kg:magic:{token_hash}")
        await pipe.delete(f"kg:magic:{token_hash}")
        results = await pipe.execute()
    user_id = results[0]
    if user_id is None:
        logger.info("magic_link_invalid_or_expired", token_hash_prefix=token_hash[:8])
        return None

    # Fetch user + roles
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user is None or user.status != "active":
            logger.warning("magic_link_user_inactive_or_missing", user_id=user_id)
            return None

        # Load role names from UserRole M:N (via direct query, avoiding relationship
        # ambiguity noted in earlier work; iterate user_roles)
        from app.db.models import UserRole
        from app.db.models.role import Role

        ur_result = await session.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        role_names = [row[0] for row in ur_result.all()]

    # Issue JWT pair
    access_token, _, _ = create_access_token(user.id, role_names)
    refresh_token, _, _ = create_refresh_token(user.id)

    logger.info("magic_link_verified", user_id=user.id)
    return {
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "role_names": role_names,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
