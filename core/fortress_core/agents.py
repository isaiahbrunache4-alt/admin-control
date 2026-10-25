"""The Agent side of Core: enrolment, signed requests and check-ins.

Spec: docs/agent_protocol.md. The Console's API (api.py) stays on localhost; this one
listens on the home network for the Agents on the phone, the tablet and the PC.
"""

import binascii
import hashlib
import hmac
import json
import re
import secrets
import socket
import threading
from datetime import datetime, timedelta

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key

from . import crypto, rules

DEFAULT_AGENT_PORT = 47801
ENROL_MINUTES = 30
ENROL_MAX_FAILURES = 5
CLOCK_SKEW_SECONDS = 300
NONCE_MEMORY_SECONDS = 600
MAX_EVENTS = 200
MAX_REPORTS = 8                    # sources per check-in, e.g. "block_trainer"
MAX_REPORT_BYTES = 32 * 1024       # each report, as compact JSON
MAX_BODY_BYTES = 256 * 1024
ENROL_CODE_LENGTH = 10

_EVENT_KIND = re.compile(r"^[a-z0-9_]{1,40}$")
_REPORT_SOURCE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class AgentError(Exception):
    def __init__(self, status: int, kind: str, message: str):
        super().__init__(message)
        self.status = status
        self.kind = kind


# ---- protocol primitives (docs/agent_protocol.md §2, §3) --------------------------------

def new_enrolment_code() -> str:
    raw = "".join(secrets.choice(crypto.CODE_ALPHABET) for _ in range(ENROL_CODE_LENGTH))
    return raw[:5] + "-" + raw[5:]


def enrol_key(code: str) -> bytes:
    return hashlib.sha256(b"fortress-enrol-v1:" + crypto.normalize_recovery_code(code).encode()).digest()


def _hmac(key: bytes, *parts: str) -> str:
    msg = "\n".join(("fortress-enrol-v1",) + parts).encode("utf-8")
    return crypto.b64e(hmac.new(key, msg, hashlib.sha256).digest())


def agent_proof(key: bytes, device_id: str, public_key: str, nonce: str) -> str:
    return _hmac(key, "agent", device_id, public_key, nonce)


def core_proof(key: bytes, device_id: str, public_key: str, nonce: str, core_public_key: str) -> str:
    return _hmac(key, "core", device_id, public_key, nonce, core_public_key)


def request_message(method: str, path: str, device_id: str, time: str, nonce: str, body: bytes) -> bytes:
    return "\n".join([
        "fortress-agent-v1", method.upper(), path, device_id, time, nonce,
        hashlib.sha256(body).hexdigest(),
    ]).encode("utf-8")


def load_device_key(public_key_b64: str) -> ec.EllipticCurvePublicKey:
    try:
        key = load_der_public_key(crypto.b64d(public_key_b64))
    except (ValueError, binascii.Error, TypeError):
        raise AgentError(400, "invalid", "public_key is not a DER public key") from None
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise AgentError(400, "invalid", "device keys must be ECDSA P-256")
    return key


def verify_device_signature(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    try:
        sig = crypto.b64d(signature_b64)
        load_device_key(public_key_b64).verify(sig, message, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, binascii.Error, AgentError):
        return False


def lan_addresses() -> list[str]:
    """This PC's IPv4 addresses on the local network, for the enrolment screen."""
    found = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))          # picks the outgoing interface; sends nothing
            found.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127."))


# ---- the gate every Agent request passes ------------------------------------------------

class AgentGate:
    """Enrols devices and authenticates their requests. Call under the shared lock."""

    def __init__(self, fortress):
        self.f = fortress
        self._nonces: dict[str, dict[str, datetime]] = {}

    # enrolment (§2)
    def enrol(self, body: dict) -> dict:
        try:
            device_id = str(body["device_id"])
            public_key = str(body["public_key"])
            nonce = str(body["nonce"])
            proof = str(body["proof"])
        except (KeyError, TypeError):
            raise AgentError(400, "invalid", "need device_id, public_key, nonce and proof") from None
        load_device_key(public_key)
        try:
            if len(crypto.b64d(nonce)) < 16:
                raise ValueError
        except (ValueError, binascii.Error):
            raise AgentError(400, "invalid", "nonce must be 16 random bytes, base64") from None

        s = self.f.store
        pending = s.enrolment(device_id)
        if pending is None:
            raise AgentError(404, "no_enrolment", "no enrolment is waiting for this device")
        now = self.f.clock()
        if now >= rules.parse_utc(pending["expires_at"]) or pending["failures"] >= ENROL_MAX_FAILURES:
            s.delete_enrolment(device_id)
            raise AgentError(410, "expired", "the enrolment code has expired; make a new one")
        device = s.device(device_id)
        if device is None or device["released"]:
            s.delete_enrolment(device_id)
            raise AgentError(404, "no_enrolment", "no enrolment is waiting for this device")

        key = bytes.fromhex(pending["key"])
        if not hmac.compare_digest(agent_proof(key, device_id, public_key, nonce), proof):
            n = s.count_enrolment_failure(device_id)
            self.f._log("enrolment_failed", f"{device_id}, wrong code ({n} of {ENROL_MAX_FAILURES})")
            if n >= ENROL_MAX_FAILURES:
                s.delete_enrolment(device_id)
            raise AgentError(403, "bad_proof", "wrong enrolment code")

        s.delete_enrolment(device_id)
        s.set_device_key(device_id, public_key, rules.format_utc(now))
        self._nonces.pop(device_id, None)
        self.f._log("device_enrolled", f"{device_id} ({device['platform']})")
        core_pub = crypto.b64e(self.f.public_key)
        return {
            "core_public_key": core_pub,
            "key_id": crypto.key_id(self.f.public_key),
            "proof": core_proof(key, device_id, public_key, nonce, core_pub),
            "bundle": self.f.latest_bundle(),
        }

    # signed requests (§3)
    def authenticate(self, method: str, path: str, headers, body: bytes) -> dict:
        device_id = headers.get("x-fortress-device") or ""
        time_text = headers.get("x-fortress-time") or ""
        nonce = headers.get("x-fortress-nonce") or ""
        signature = headers.get("x-fortress-signature") or ""
        device = self.f.store.device(device_id) if device_id else None
        if device is None or not device["public_key"]:
            raise AgentError(401, "not_enrolled", "unknown or unenrolled device")
        now = self.f.clock()
        try:
            sent = datetime.fromtimestamp(int(time_text), tz=now.tzinfo)
        except (ValueError, OverflowError, OSError):
            raise AgentError(401, "bad_time", "X-Fortress-Time must be Unix seconds") from None
        if abs((now - sent).total_seconds()) > CLOCK_SKEW_SECONDS:
            raise AgentError(401, "bad_time", "device clock is more than 5 minutes off")
        if not 16 <= len(nonce) <= 64:
            raise AgentError(401, "bad_nonce", "X-Fortress-Nonce is missing")
        seen = self._nonces.setdefault(device_id, {})
        for n, at in list(seen.items()):
            if (now - at).total_seconds() > NONCE_MEMORY_SECONDS:
                del seen[n]
        if nonce in seen:
            raise AgentError(401, "replay", "this request was already used")
        msg = request_message(method, path, device_id, time_text, nonce, body)
        if not verify_device_signature(device["public_key"], msg, signature):
            raise AgentError(401, "bad_signature", "request signature does not verify")
        seen[nonce] = now
        return device

    # endpoints (§4)
    def bundle(self, device: dict) -> dict:
        return self.f.latest_bundle()

    def check_in(self, device: dict, body: dict) -> dict:
        version = body.get("version")
        if type(version) is not int or version < 0:
            raise AgentError(400, "invalid", "version must be a whole number")
        agent_version = str(body.get("agent_version", ""))[:40]
        events = body.get("events") or []
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise AgentError(400, "invalid", f"events must be a list of at most {MAX_EVENTS}")
        now = self.f.clock()
        clean = []
        for e in events:
            if not isinstance(e, dict) or not _EVENT_KIND.match(str(e.get("kind", ""))):
                raise AgentError(400, "invalid", "each event needs a kind of a-z, 0-9 and _")
            try:
                at = rules.format_utc(rules.parse_utc(str(e.get("at", ""))))
            except rules.RuleError:
                at = rules.format_utc(now)
            clean.append((at, str(e["kind"]), str(e.get("detail", ""))[:500]))
        reports = self._reports(body.get("reports"))

        self.f.store.record_check_in(device["id"], rules.format_utc(now), version, agent_version)
        for source, report in reports.items():
            self.f.store.put_report(device["id"], source, rules.format_utc(now), report)
        if body.get("enforcing") is False and not device["released"]:
            clean.append((rules.format_utc(now), "not_enforcing", "Agent reports it is not enforcing"))
        for at, kind, detail in clean:
            self.f.store.log(at, "device", f"{device['id']}: {kind}" + (f": {detail}" if detail else ""))
        return {"latest_version": self.f.store.get("version"), "released": bool(device["released"])}

    @staticmethod
    def _reports(reports) -> dict:
        """Latest summaries other apps on the device handed to its Agent, e.g. Block
        Trainer's logged workouts. Core keeps the newest per source; it never acts on them."""
        if reports is None:
            return {}
        if not isinstance(reports, dict) or len(reports) > MAX_REPORTS:
            raise AgentError(400, "invalid", f"reports must be an object of at most {MAX_REPORTS} sources")
        for source, report in reports.items():
            if not _REPORT_SOURCE.match(source):
                raise AgentError(400, "invalid", "report sources are a-z, 0-9 and _, starting with a letter")
            if not isinstance(report, dict):
                raise AgentError(400, "invalid", f"report {source} must be an object")
            if len(json.dumps(report, separators=(",", ":"))) > MAX_REPORT_BYTES:
                raise AgentError(400, "invalid", f"report {source} is larger than {MAX_REPORT_BYTES} bytes")
        return reports


# ---- the HTTP app for the home network --------------------------------------------------

def create_agent_app(fortress, guard: threading.Lock | None = None):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool

    app = FastAPI(title="Fortress Core (Agents)", docs_url=None, redoc_url=None, openapi_url=None)
    guard = guard or threading.Lock()
    gate = AgentGate(fortress)
    app.state.gate = gate

    @app.exception_handler(AgentError)
    def _agent_error(request, e: AgentError):
        return JSONResponse({"error": e.kind, "message": str(e)}, e.status)

    async def read(request: Request) -> bytes:
        size = request.headers.get("content-length")
        if size and int(size) > MAX_BODY_BYTES:
            raise AgentError(413, "too_large", "request body too large")
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise AgentError(413, "too_large", "request body too large")
        return body

    def parse(body: bytes) -> dict:
        try:
            obj = json.loads(body or b"{}")
        except ValueError:
            raise AgentError(400, "invalid", "body is not JSON") from None
        if not isinstance(obj, dict):
            raise AgentError(400, "invalid", "body must be a JSON object")
        return obj

    def locked(fn, *args):
        with guard:
            return fn(*args)

    @app.post("/agent/v1/enrol")
    async def enrol(request: Request):
        body = parse(await read(request))
        return await run_in_threadpool(locked, gate.enrol, body)

    @app.get("/agent/v1/bundle")
    async def bundle(request: Request):
        body = await read(request)

        def work():
            device = gate.authenticate("GET", request.url.path, request.headers, body)
            return gate.bundle(device)
        return await run_in_threadpool(locked, work)

    @app.post("/agent/v1/checkin")
    async def check_in(request: Request):
        body = await read(request)

        def work():
            device = gate.authenticate("POST", request.url.path, request.headers, body)
            return gate.check_in(device, parse(body))
        return await run_in_threadpool(locked, work)

    return app


def enrolment_expiry(now: datetime) -> datetime:
    return now + timedelta(minutes=ENROL_MINUTES)
