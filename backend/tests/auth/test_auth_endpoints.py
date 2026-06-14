"""Unit-level tests for auth endpoint helpers and JWT pair builder.

These don't hit the network or the database — they exercise the pure helpers
and validate request/response schema shape. Integration tests that hit the
real /auth/* routes are marked with `pytest.mark.integration` and require
docker-compose up.
"""

from __future__ import annotations

import pytest

# === Schema validation: request models reject bad input ===

def test_register_request_rejects_short_password() -> None:
    """Pydantic v2 should reject passwords < 8 chars at the schema level."""
    from pydantic import ValidationError

    from app.api.v1.auth import RegisterRequest

    with pytest.raises(ValidationError):
        RegisterRequest(email="alice@example.com", display_name="Alice", password="short")


def test_register_request_rejects_invalid_email() -> None:
    from pydantic import ValidationError

    from app.api.v1.auth import RegisterRequest

    with pytest.raises(ValidationError):
        RegisterRequest(
            email="not-an-email", display_name="Alice", password="longenough"
        )


def test_login_request_accepts_minimal_shape() -> None:
    from app.api.v1.auth import LoginRequest

    req = LoginRequest(email="alice@example.com", password="any")
    assert req.email == "alice@example.com"


def test_token_pair_response_includes_both_tokens_and_user() -> None:
    from app.api.v1.auth import TokenPairResponse

    resp = TokenPairResponse(
        access_token="a", refresh_token="r", expires_in=900, user={"id": "u"}
    )
    assert resp.token_type == "bearer"
    assert resp.expires_in == 900


def test_refresh_request_requires_token() -> None:
    from pydantic import ValidationError

    from app.api.v1.auth import RefreshRequest

    with pytest.raises(ValidationError):
        RefreshRequest()  # missing required field


# === Magic-link URL builder ===

def test_magic_link_url_uses_token_query_param() -> None:
    """The link the user clicks in the email must carry the token in the
    query string and point at the verify endpoint."""
    from app.auth.magic_link import _build_magic_link_url

    url = _build_magic_link_url("http://localhost:3000", "abc123")
    assert url == "http://localhost:3000/api/v1/auth/magic-link/verify?token=abc123"


def test_magic_link_url_strips_trailing_slash_from_base() -> None:
    from app.auth.magic_link import _build_magic_link_url

    url = _build_magic_link_url("http://localhost:3000/", "tok")
    # No double slash between host and /api/v1
    assert "//api" not in url
    assert "/api/v1/auth/magic-link/verify?token=tok" in url


# === Magic-link token hashing ===

def test_magic_link_token_hash_is_sha256_hex_64_chars() -> None:
    from app.auth.magic_link import _hash_token

    h = _hash_token("any-token-value")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_magic_link_token_hash_is_deterministic() -> None:
    from app.auth.magic_link import _hash_token

    assert _hash_token("same") == _hash_token("same")
    assert _hash_token("a") != _hash_token("b")


# === Magic-link token hash uses SHA-256 (not plaintext) at rest ===

def test_magic_link_hash_does_not_contain_plaintext() -> None:
    """A leaked DB row must not contain the original token."""
    from app.auth.magic_link import _hash_token

    plaintext = "this-is-a-magic-link-token"
    assert plaintext not in _hash_token(plaintext)


# === Token pair builder ===

def test_jwt_pair_builder_returns_two_different_tokens() -> None:
    from app.api.v1.auth import _build_jwt_pair

    access, refresh, expires_in = _build_jwt_pair("user-1", ["admin"])
    assert access and refresh
    assert access != refresh
    assert expires_in == 15 * 60


# === User response builder ===

def test_user_response_does_not_include_password_hash() -> None:
    """The auth response must never leak the password hash field."""
    from types import SimpleNamespace

    from app.api.v1.auth import _user_response

    user = SimpleNamespace(
        id="u-1",
        email="alice@example.com",
        display_name="Alice",
        language_pref="en",
        status="active",
        password_hash="$argon2id$v=19$m=...$hash",
    )
    resp = _user_response(user, ["admin"])
    assert "password_hash" not in resp
    assert resp["id"] == "u-1"
    assert resp["email"] == "alice@example.com"
    assert resp["roles"] == ["admin"]
