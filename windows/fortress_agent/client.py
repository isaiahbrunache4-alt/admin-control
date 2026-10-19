"""Talks to Core's Agent API (docs/agent_protocol.md). The Python twin of the Kotlin
CoreClient; it reuses fortress_core.agents for the proofs and the request signature."""

import json
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from fortress_core import agents, crypto

DEFAULT_PORT = 47801
TIMEOUT = 10


class CoreError(Exception):
    """Core refused, or could not be reached. `kind` is Core's error code."""

    def __init__(self, status: int, kind: str, message: str):
        super().__init__(message)
        self.status = status
        self.kind = kind


def normalize_base_url(address: str) -> str:
    """'192.168.1.20' -> 'http://192.168.1.20:47801'."""
    a = address.strip()
    if "://" not in a:
        a = "http://" + a
    a = a.rstrip("/")
    from urllib.parse import urlparse

    u = urlparse(a)
    if not u.hostname:
        raise ValueError(f"not an address: {address!r}")
    port = u.port or DEFAULT_PORT
    return f"{u.scheme}://{u.hostname}:{port}"


class CoreClient:
    def __init__(self, base_url: str, device_id: str, signer, *, clock=None):
        self.base_url = normalize_base_url(base_url)
        self.device_id = device_id
        self.signer = signer
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ---- enrolment (§2) --------------------------------------------------------------

    def enrol(self, code: str) -> dict:
        key = agents.enrol_key(code)
        pub = crypto.b64e(self.signer.public_key_der)
        nonce = crypto.b64e(os.urandom(16))
        body = {
            "device_id": self.device_id,
            "public_key": pub,
            "nonce": nonce,
            "proof": agents.agent_proof(key, self.device_id, pub, nonce),
        }
        answer = self._send("POST", "/agent/v1/enrol", json.dumps(body).encode(), signed=False)
        core_pub = answer["core_public_key"]
        expected = agents.core_proof(key, self.device_id, pub, nonce, core_pub)
        if not secrets.compare_digest(expected, answer["proof"]):
            raise CoreError(0, "bad_core_proof", "this is not the Fortress that made the code")
        if answer["key_id"] != crypto.key_id(crypto.b64d(core_pub)):
            raise CoreError(0, "bad_core_proof", "Core's key id does not match its key")
        return answer

    # ---- signed requests (§3, §4) ----------------------------------------------------

    def fetch_bundle(self) -> dict:
        return self._send("GET", "/agent/v1/bundle", b"", signed=True)

    def check_in(self, version: int, agent_version: str, enforcing: bool, events: list[dict]) -> dict:
        body = json.dumps({
            "version": version, "agent_version": agent_version,
            "enforcing": enforcing, "events": events,
        }).encode()
        return self._send("POST", "/agent/v1/checkin", body, signed=True)

    # ---- plumbing --------------------------------------------------------------------

    def _signed_headers(self, method: str, path: str, body: bytes) -> dict:
        now = str(int(self.clock().timestamp()))
        nonce = crypto.b64e(os.urandom(16))
        msg = agents.request_message(method, path, self.device_id, now, nonce, body)
        sig = self.signer.sign(msg)
        return {
            "X-Fortress-Device": self.device_id,
            "X-Fortress-Time": now,
            "X-Fortress-Nonce": nonce,
            "X-Fortress-Signature": crypto.b64e(sig),
        }

    def _send(self, method: str, path: str, body: bytes, *, signed: bool) -> dict:
        headers = {"Accept": "application/json"}
        if method != "GET":
            headers["Content-Type"] = "application/json"
        if signed:
            headers.update(self._signed_headers(method, path, body))
        req = urllib.request.Request(
            self.base_url + path, data=(None if method == "GET" else body), method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read() or b"{}")
            except ValueError:
                err = {}
            raise CoreError(e.code, err.get("error", f"http_{e.code}"),
                            err.get("message", f"Core answered {e.code}")) from None
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise CoreError(0, "unreachable", f"cannot reach Fortress Core at {self.base_url} ({e})") from None


def verify_core_signature(public_key_raw: bytes, data: bytes, signature: bytes) -> bool:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(signature, data)
        return True
    except (InvalidSignature, ValueError):
        return False
