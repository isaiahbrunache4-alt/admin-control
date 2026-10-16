"""Password-derived keys, sealing, and Ed25519 signatures.

The signing key is never stored in the clear. It is sealed (AES-256-GCM) under a key
derived from the password with Argon2id, so a wrong password simply fails to unseal.
That failure *is* the password check: there is no separate hash to compare.
"""

import base64
import hashlib
import os
import secrets

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

# Argon2id cost. OWASP's recommended minimum is m=19 MiB, t=2; these are above it.
ARGON2_TIME_COST = 3
ARGON2_MEMORY_KIB = 64 * 1024
ARGON2_PARALLELISM = 4

# Recovery code alphabet: no 0/O, 1/I/L, so it survives being written down.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_CODE_LENGTH = 24


class InvalidSecret(Exception):
    """The password or recovery code did not unseal the key."""


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def derive_key(secret: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        secret.encode("utf-8"),
        salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=32,
        type=Type.ID,
    )


def seal(data: bytes, secret: str) -> dict:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    ct = AESGCM(derive_key(secret, salt)).encrypt(nonce, data, b"fortress-seal-v1")
    return {
        "kdf": "argon2id",
        "t": ARGON2_TIME_COST,
        "m": ARGON2_MEMORY_KIB,
        "p": ARGON2_PARALLELISM,
        "salt": b64e(salt),
        "nonce": b64e(nonce),
        "ct": b64e(ct),
    }


def unseal(sealed: dict, secret: str) -> bytes:
    key = hash_secret_raw(
        secret.encode("utf-8"),
        b64d(sealed["salt"]),
        time_cost=sealed["t"],
        memory_cost=sealed["m"],
        parallelism=sealed["p"],
        hash_len=32,
        type=Type.ID,
    )
    try:
        return AESGCM(key).decrypt(b64d(sealed["nonce"]), b64d(sealed["ct"]), b"fortress-seal-v1")
    except InvalidTag:
        raise InvalidSecret() from None


def new_signing_key() -> tuple[bytes, bytes]:
    """Return (private_raw, public_raw), 32 bytes each."""
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_raw, pub_raw


def sign(priv_raw: bytes, data: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(priv_raw).sign(data)


def verify(pub_raw: bytes, data: bytes, sig: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(sig, data)
        return True
    except InvalidSignature:
        return False


def key_id(pub_raw: bytes) -> str:
    return hashlib.sha256(pub_raw).hexdigest()[:16]


def new_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
    return "-".join(raw[i:i + 4] for i in range(0, RECOVERY_CODE_LENGTH, 4))


def normalize_recovery_code(code: str) -> str:
    return "".join(c for c in code.upper() if c.isalnum())
