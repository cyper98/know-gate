"""AES-256-GCM symmetric encryption helper for secrets at rest (e.g. OAuth tokens).

Key comes from `KG_ENCRYPTION_KEY` env var (32 bytes, base64-encoded).
The validator in `app.config.Settings` ensures the key length is correct.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 96-bit nonce (12 bytes) is the recommended size for AES-GCM
_NONCE_SIZE = 12


def _derive_key(key_b64: str) -> bytes:
    """Decode base64 key (32 bytes raw)."""
    return base64.b64decode(key_b64)


def encrypt(plaintext: bytes | str, key_b64: str) -> bytes:
    """Encrypt plaintext with AES-256-GCM.

    Output format: nonce (12 bytes) || ciphertext || tag (16 bytes).
    Each call uses a fresh random nonce (AES-GCM security requirement).

    Args:
        plaintext: bytes or str to encrypt (str is UTF-8 encoded)
        key_b64: 32-byte key as base64 string

    Returns:
        nonce-prefixed ciphertext (binary blob, safe for TEXT/BYTEA storage)
    """
    key = _derive_key(key_b64)
    if len(key) != 32:
        raise ValueError(f"AES-256-GCM requires a 32-byte key, got {len(key)}")

    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_SIZE)
    data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
    return nonce + aesgcm.encrypt(nonce, data, associated_data=None)


def decrypt(ciphertext: bytes, key_b64: str) -> bytes:
    """Decrypt AES-256-GCM ciphertext. Returns raw bytes (decoded as UTF-8 by caller if needed)."""
    key = _derive_key(key_b64)
    if len(key) != 32:
        raise ValueError(f"AES-256-GCM requires a 32-byte key, got {len(key)}")
    if len(ciphertext) < _NONCE_SIZE + 16:
        raise ValueError("Ciphertext too short (must be nonce + ct + tag)")

    aesgcm = AESGCM(key)
    nonce = ciphertext[:_NONCE_SIZE]
    ct_with_tag = ciphertext[_NONCE_SIZE:]
    return aesgcm.decrypt(nonce, ct_with_tag, associated_data=None)


def encrypt_str(plaintext: str, key_b64: str) -> str:
    """Encrypt string and return base64-encoded ciphertext (for storage in TEXT columns)."""
    return base64.b64encode(encrypt(plaintext, key_b64)).decode("ascii")


def decrypt_str(ciphertext_b64: str, key_b64: str) -> str:
    """Decrypt base64-encoded ciphertext back to string."""
    return decrypt(base64.b64decode(ciphertext_b64), key_b64).decode("utf-8")
