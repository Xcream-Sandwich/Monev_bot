from cryptography.fernet import Fernet
import config


def generate_key() -> str:
    """Generate a new Fernet base64 32-byte key string."""
    return Fernet.generate_key().decode("utf-8")


def _get_fernet(key: str | None = None) -> Fernet:
    target_key = key or config.ENCRYPTION_KEY
    if not target_key:
        raise ValueError(
            "ENCRYPTION_KEY belum diatur. Harap set ENCRYPTION_KEY di file .env atau panggil generate_key()."
        )
    try:
        return Fernet(target_key.encode("utf-8"))
    except Exception as e:
        raise ValueError(f"Format ENCRYPTION_KEY tidak valid: {str(e)}")


def encrypt_str(plain_text: str, key: str | None = None) -> str:
    """Encrypt a plain text string into a Fernet base64 ciphertext string."""
    if plain_text is None:
        return ""
    if not plain_text:
        return ""
    f = _get_fernet(key)
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_str(cipher_text: str, key: str | None = None) -> str:
    """Decrypt a Fernet base64 ciphertext string into plain text."""
    if not cipher_text:
        return ""
    f = _get_fernet(key)
    return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
