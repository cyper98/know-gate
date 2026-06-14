"""Unit tests for the argon2 password hasher."""

from __future__ import annotations

from app.auth.password import hash_password, needs_rehash, verify_password


def test_hash_password_returns_argon2id_string() -> None:
    """Hash should be in PHC format starting with $argon2id$."""
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$"), f"unexpected hash format: {h[:30]}"


def test_verify_password_returns_true_for_correct_password() -> None:
    h = hash_password("hello world")
    assert verify_password("hello world", h) is True


def test_verify_password_returns_false_for_wrong_password() -> None:
    h = hash_password("hello world")
    assert verify_password("goodbye world", h) is False


def test_verify_password_returns_false_for_invalid_hash() -> None:
    """Verify on a non-argon2 hash should return False (not raise)."""
    assert verify_password("anything", "not-a-real-hash") is False


def test_hash_is_salted_each_call() -> None:
    """Two hashes of the same password should differ (random salt)."""
    h1 = hash_password("same password")
    h2 = hash_password("same password")
    assert h1 != h2


def test_both_hashes_verify_against_their_plaintext() -> None:
    """Despite differing, both salts must verify against the same plaintext."""
    h1 = hash_password("same password")
    h2 = hash_password("same password")
    assert verify_password("same password", h1) is True
    assert verify_password("same password", h2) is True


def test_needs_rehash_returns_false_for_current_params() -> None:
    """A hash with the current hasher's params should not need rehash."""
    h = hash_password("any")
    # We can't easily simulate "outdated params" without rebuilding the hasher;
    # the simplest invariant is: a fresh hash should not need rehash.
    assert needs_rehash(h) is False


def test_needs_rehash_returns_true_for_invalid_hash() -> None:
    """Invalid hash formats should report `needs_rehash=True` so the caller
    re-hashes (and effectively rejects the user, since invalid format = corrupt
    data)."""
    assert needs_rehash("garbage") is True
