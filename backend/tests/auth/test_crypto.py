"""Unit tests for the AES-256-GCM encryption helper."""

from __future__ import annotations

import base64

import pytest

from app.crypto.aes import decrypt, decrypt_str, encrypt, encrypt_str

# A fixed test key (32 bytes, base64 encoded) so tests are deterministic
TEST_KEY = base64.b64encode(b"\x00" * 32).decode("ascii")
# A different fixed key (for negative test: wrong key must fail to decrypt)
WRONG_KEY = base64.b64encode(b"\xff" * 32).decode("ascii")


def test_encrypt_returns_nonce_prefixed_bytes() -> None:
    ct = encrypt("hello", TEST_KEY)
    # 12-byte nonce || ciphertext || 16-byte GCM tag
    assert isinstance(ct, bytes)
    # Plaintext "hello" is 5 bytes; ciphertext is 5; tag is 16; total 33
    assert len(ct) == 12 + 5 + 16


def test_decrypt_round_trip_with_str_input() -> None:
    plaintext = "the quick brown fox jumps over the lazy dog"
    ct = encrypt(plaintext, TEST_KEY)
    assert decrypt(ct, TEST_KEY) == plaintext.encode("utf-8")


def test_decrypt_round_trip_with_bytes_input() -> None:
    payload = b"\x00\x01\x02\x03binary\xff\xfe"
    ct = encrypt(payload, TEST_KEY)
    assert decrypt(ct, TEST_KEY) == payload


def test_encrypt_uses_fresh_nonce_each_call() -> None:
    """AES-GCM security requires a unique nonce per call (with the same key)."""
    a = encrypt("same plaintext", TEST_KEY)
    b = encrypt("same plaintext", TEST_KEY)
    # First 12 bytes (nonce) must differ
    assert a[:12] != b[:12]
    # But both must decrypt to the same plaintext
    assert decrypt(a, TEST_KEY) == decrypt(b, TEST_KEY) == b"same plaintext"


def test_decrypt_with_wrong_key_raises() -> None:
    from cryptography.exceptions import InvalidTag

    ct = encrypt("secret", TEST_KEY)
    with pytest.raises(InvalidTag):
        decrypt(ct, WRONG_KEY)


def test_decrypt_rejects_short_ciphertext() -> None:
    """Ciphertext shorter than nonce + tag must be rejected."""
    with pytest.raises(ValueError, match="too short"):
        decrypt(b"x" * 10, TEST_KEY)


def test_encrypt_rejects_wrong_key_length() -> None:
    bad_key = base64.b64encode(b"only-16-bytes").decode("ascii")  # 16 bytes
    with pytest.raises(ValueError, match="32-byte key"):
        encrypt("hello", bad_key)


def test_encrypt_str_round_trip() -> None:
    s = "UTF-8 chars: tiếng việt, émojis 🚀"
    b64_ct = encrypt_str(s, TEST_KEY)
    assert decrypt_str(b64_ct, TEST_KEY) == s


def test_encrypt_str_returns_ascii_base64() -> None:
    """The base64 envelope must be ASCII-safe (safe for TEXT columns)."""
    b64_ct = encrypt_str("any", TEST_KEY)
    b64_ct.encode("ascii")  # must not raise
