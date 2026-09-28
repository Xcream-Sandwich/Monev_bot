import pytest
from crypto import generate_key, encrypt_str, decrypt_str


def test_generate_and_encrypt_decrypt():
    key = generate_key()
    assert isinstance(key, str)
    assert len(key) > 20

    secret = "PasswordSuperRahasia123!@#"
    encrypted = encrypt_str(secret, key=key)
    assert encrypted != secret
    assert isinstance(encrypted, str)

    decrypted = decrypt_str(encrypted, key=key)
    assert decrypted == secret


def test_empty_string_handling():
    key = generate_key()
    assert encrypt_str("", key=key) == ""
    assert decrypt_str("", key=key) == ""


def test_invalid_key():
    with pytest.raises(ValueError):
        encrypt_str("test", key="invalid-key-format")
