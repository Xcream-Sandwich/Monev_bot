"""
lib/crypto.py — Fernet encryption helpers (no change in logic from root crypto.py).
Key is sourced from lib.config.ENCRYPTION_KEY.
"""
from cryptography.fernet import Fernet
from lib import config


def generate_key() -> str:
    """Generate a new Fernet base64 32-byte key string."""
    return Fernet.generate_key().decode("utf-8")


def _get_fernet(key: str | None = None) -> Fernet:
    target_key = key or config.ENCRYPTION_KEY
    if not target_key:
        raise ValueError(
            "ENCRYPTION_KEY belum diatur. Harap set ENCRYPTION_KEY di environment variables."
        )
    try:
        return Fernet(target_key.encode("utf-8"))
    except Exception as e:
        raise ValueError(f"Format ENCRYPTION_KEY tidak valid: {e}")


def encrypt_str(plain_text: str, key: str | None = None) -> str:
    """Encrypt a plain text string using Fernet. Returns empty string for empty input."""
    if not plain_text:
        return ""
    return _get_fernet(key).encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_str(cipher_text: str, key: str | None = None) -> str:
    """Decrypt a Fernet ciphertext string. Returns empty string for empty input."""
    if not cipher_text:
        return ""
    return _get_fernet(key).decrypt(cipher_text.encode("utf-8")).decode("utf-8")
