"""Password hashing (argon2id per OWASP)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

# OWASP recommended parameters (2024): memory=64MB, time=3, parallelism=4
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(plaintext: str) -> str:
    """Hash a password with argon2id. Returns the encoded hash string.

    The returned string includes the algorithm, parameters, salt, and digest
    in PHC format: `$argon2id$v=19$m=65536,t=3,p=4$<salt>$<digest>`.
    """
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, encoded_hash: str) -> bool:
    """Verify a plaintext password against a stored argon2 hash.

    Returns True on match, False on mismatch. Argon2 verify is constant-time
    relative to the hash but variable-time relative to the plaintext (depends
    on the time_cost); for the configured 3 iterations this is ~50-100ms.
    """
    try:
        return _hasher.verify(encoded_hash, plaintext)
    except (VerifyMismatchError, InvalidHash):
        return False


def needs_rehash(encoded_hash: str) -> bool:
    """Return True if the hash uses outdated parameters and should be re-computed.

    Useful on successful login: if True, re-hash with current parameters and
    persist the new hash. Keeps the parameter set current without forcing
    password resets.
    """
    try:
        return _hasher.check_needs_rehash(encoded_hash)
    except InvalidHash:
        return True
