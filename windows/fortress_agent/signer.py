"""The PC's device key: ECDSA P-256 (docs/agent_protocol.md §2).

On Windows the private key file is sealed with DPAPI so only this machine and account can
read it; elsewhere (tests) it is stored as plain PKCS8. Either way it never leaves the PC
and is never sent to Core. The key signs every request; it cannot sign rules, so holding
it does not let the PC change anything.
"""

import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_der_private_key,
)

_DPAPI_PREFIX = b"FORTRESS-DPAPI\0"


def _dpapi_available() -> bool:
    return os.name == "nt"


def _dpapi_protect(data: bytes) -> bytes:
    import ctypes
    import ctypes.wintypes as wt

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b: bytes) -> BLOB:
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    out = BLOB()
    inp = blob(data)
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes
    import ctypes.wintypes as wt

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b: bytes) -> BLOB:
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    out = BLOB()
    inp = blob(data)
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


class DeviceSigner:
    """Loads the device key, or makes one on first use. The key file is 0600 and, on
    Windows, DPAPI-sealed, so a copy of the PC's files off the machine cannot use it."""

    def __init__(self, key_path: str | Path):
        self.path = Path(key_path)
        self._key = self._load_or_create()

    def _load_or_create(self) -> ec.EllipticCurvePrivateKey:
        if self.path.exists():
            raw = self.path.read_bytes()
            if raw.startswith(_DPAPI_PREFIX):
                raw = _dpapi_unprotect(raw[len(_DPAPI_PREFIX):])
            return load_der_private_key(raw, password=None)
        key = ec.generate_private_key(ec.SECP256R1())
        der = key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if _dpapi_available():
            der = _DPAPI_PREFIX + _dpapi_protect(der)
        self.path.write_bytes(der)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return key

    @property
    def public_key_der(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message, ec.ECDSA(hashes.SHA256()))

    def reset(self) -> None:
        """Forget the key, for a fresh enrolment."""
        self.path.unlink(missing_ok=True)
        self._key = self._load_or_create()
