import os
import hashlib
import json

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_SEED = b'ai_grade_internal_seed_v1'


def _derive_key():
    try:
        from .hwid import generate_hwid
    except ImportError:
        from hwid import generate_hwid  # type: ignore
    material = _KEY_SEED + generate_hwid().encode()
    return hashlib.sha256(material).digest()


def encrypt_data(plaintext: bytes) -> bytes:
    key = _derive_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt_data(encrypted: bytes) -> bytes:
    key = _derive_key()
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def secure_read_json(filepath):
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'rb') as f:
        encrypted = f.read()
    plaintext = decrypt_data(encrypted)
    return json.loads(plaintext.decode())


def secure_write_json(filepath, data):
    plaintext = json.dumps(data, ensure_ascii=False, indent=2).encode()
    encrypted = encrypt_data(plaintext)
    with open(filepath, 'wb') as f:
        f.write(encrypted)
