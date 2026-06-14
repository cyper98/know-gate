"""Unit tests for the RS256 JWT helpers."""

from __future__ import annotations

import pytest

from app.auth.jwt import (
    TokenError,
    create_access_token,
    create_refresh_token,
    generate_random_token,
    verify_token,
)


def test_create_access_token_returns_string_jti_and_ttl() -> None:
    token, jti, ttl = create_access_token("user-123", ["admin"])
    assert isinstance(token, str) and len(token) > 50
    assert isinstance(jti, str) and len(jti) >= 32
    assert ttl == 15 * 60  # 15 minutes default


def test_create_refresh_token_has_longer_default_ttl() -> None:
    _token, _jti, ttl = create_refresh_token("user-123")
    assert ttl == 30 * 24 * 60 * 60  # 30 days


def test_verify_token_round_trip_returns_claims() -> None:
    token, expected_jti, _ttl = create_access_token("user-1", ["admin", "editor"])
    claims = verify_token(token, expected_type="access")
    assert claims["sub"] == "user-1"
    assert claims["jti"] == expected_jti
    assert claims["roles"] == ["admin", "editor"]
    assert claims["typ"] == "access"


def test_verify_refresh_token_with_access_type_raises() -> None:
    """A refresh token must not verify as an access token (and vice versa)."""
    refresh, _jti, _ttl = create_refresh_token("user-1")
    with pytest.raises(TokenError, match="expected access token"):
        verify_token(refresh, expected_type="access")


def test_verify_access_token_with_refresh_type_raises() -> None:
    token, _jti, _ttl = create_access_token("user-1", ["member"])
    with pytest.raises(TokenError, match="expected refresh token"):
        verify_token(token, expected_type="refresh")


def test_verify_token_raises_on_tampered_signature() -> None:
    token, _jti, _ttl = create_access_token("user-1", ["admin"])
    # Flip a character in the signature (last segment of `header.payload.sig`)
    parts = token.rsplit(".", 1)
    tampered = parts[0] + "." + ("A" if parts[1][0] != "A" else "B") + parts[1][1:]
    with pytest.raises(TokenError):
        verify_token(tampered, expected_type="access")


def test_verify_token_raises_on_malformed_string() -> None:
    with pytest.raises(TokenError):
        verify_token("not-a-jwt", expected_type="access")


def test_verify_token_raises_on_expired_token() -> None:
    # Mint a token that expired 1 second ago
    token, _jti, _ttl = create_access_token(
        "user-1", ["admin"], ttl_seconds=-1
    )
    with pytest.raises(TokenError, match="expired"):
        verify_token(token, expected_type="access")


def test_generate_random_token_returns_url_safe_string() -> None:
    t = generate_random_token(32)
    # URL-safe base64: only [A-Za-z0-9_-], no padding
    assert all(c.isalnum() or c in "-_" for c in t)
    # 32 bytes -> 43 chars in base64-url (no padding)
    assert len(t) >= 42


def test_two_consecutive_random_tokens_differ() -> None:
    a = generate_random_token(32)
    b = generate_random_token(32)
    assert a != b
