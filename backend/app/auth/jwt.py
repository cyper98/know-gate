"""JWT utilities (RS256, 15-min access + 30-day refresh with rotation).

Private key + public key live in `secrets/` (gitignored) — see `make secrets`.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Mapping
from typing import Any

import jwt as pyjwt
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    InvalidSignatureError,
    InvalidTokenError,
)

# Default lifetimes (overridable via env in app.config.Settings)
DEFAULT_ACCESS_TTL_SECONDS = 15 * 60  # 15 minutes
DEFAULT_REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

_ALGORITHM = "RS256"
_TOKEN_TYPE_CLAIM = "typ"
_TOKEN_TYPE_ACCESS = "access"
_TOKEN_TYPE_REFRESH = "refresh"


def _load_private_key(path: str) -> str:
    """Load RSA private key from PEM file."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _load_public_key(path: str) -> str:
    """Load RSA public key from PEM file."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def create_access_token(
    user_id: str,
    role_names: list[str],
    *,
    ttl_seconds: int = DEFAULT_ACCESS_TTL_SECONDS,
    private_key_path: str = "./secrets/jwt_private.pem",
    extra_claims: Mapping[str, Any] | None = None,
) -> tuple[str, str, int]:
    """Create a short-lived access token (RS256 JWT).

    Returns:
        (token, jti, expires_in_seconds)
    """
    now = int(time.time())
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": user_id,  # subject = user id
        "iat": now,
        "nbf": now,
        "exp": now + ttl_seconds,
        "jti": jti,
        _TOKEN_TYPE_CLAIM: _TOKEN_TYPE_ACCESS,
        "roles": role_names,
    }
    if extra_claims:
        payload.update(extra_claims)
    token = pyjwt.encode(payload, _load_private_key(private_key_path), algorithm=_ALGORITHM)
    return token, jti, ttl_seconds


def create_refresh_token(
    user_id: str,
    *,
    ttl_seconds: int = DEFAULT_REFRESH_TTL_SECONDS,
    private_key_path: str = "./secrets/jwt_private.pem",
) -> tuple[str, str, int]:
    """Create a long-lived refresh token (RS256 JWT). Used to mint new access tokens.

    Returns:
        (token, jti, expires_in_seconds)
    """
    now = int(time.time())
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "iat": now,
        "nbf": now,
        "exp": now + ttl_seconds,
        "jti": jti,
        _TOKEN_TYPE_CLAIM: _TOKEN_TYPE_REFRESH,
    }
    token = pyjwt.encode(payload, _load_private_key(private_key_path), algorithm=_ALGORITHM)
    return token, jti, ttl_seconds


class TokenError(Exception):
    """Raised on any token verification failure (expired, invalid signature, etc.)."""


def verify_token(
    token: str,
    expected_type: str,
    public_key_path: str = "./secrets/jwt_public.pem",
) -> dict[str, Any]:
    """Verify a JWT and return its claims.

    Args:
        token: the encoded JWT string
        expected_type: "access" or "refresh" (must match the token's `typ` claim)
        public_key_path: path to the RSA public key PEM

    Returns:
        Decoded claims dict (with `sub` = user_id, `jti`, `roles`, `exp`, etc.)

    Raises:
        TokenError: on any verification failure (expired, bad signature, wrong type)
    """
    try:
        claims = pyjwt.decode(
            token,
            _load_public_key(public_key_path),
            algorithms=[_ALGORITHM],
        )
    except ExpiredSignatureError as e:
        raise TokenError("token expired") from e
    except InvalidSignatureError as e:
        raise TokenError("invalid signature") from e
    except DecodeError as e:
        raise TokenError("malformed token") from e
    except InvalidTokenError as e:
        raise TokenError(f"invalid token: {e}") from e

    if claims.get(_TOKEN_TYPE_CLAIM) != expected_type:
        raise TokenError(f"expected {expected_type} token, got {claims.get(_TOKEN_TYPE_CLAIM)}")
    return claims


def generate_random_token(nbytes: int = 32) -> str:
    """Generate a URL-safe random token (e.g. for magic links, OAuth state).

    Returns ~43 chars for 32 bytes (base64-url no padding).
    """
    return secrets.token_urlsafe(nbytes)
