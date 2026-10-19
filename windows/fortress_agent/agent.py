"""The Windows Agent's decisions, independent of how Windows enforces them: enrol, hold
the latest signed bundle, check in, fetch newer rules. Mirrors the Kotlin Agent."""

import json
from datetime import datetime, timezone
from pathlib import Path

from fortress_core import crypto
from fortress_core.bundle import BundleRejected, BundleVerifier

from . import AGENT_VERSION
from .client import CoreClient, CoreError

MAX_EVENTS = 200


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AgentState:
    """Everything kept between runs. Nothing secret: the key is in signer.py, the bundle
    is signed. Stored as JSON next to the key."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._d = self._read()

    def _read(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text("utf-8"))
            except (ValueError, OSError):
                pass
        return {"highest_version": 0, "released": False, "events": []}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._d, indent=2), "utf-8")
        tmp.replace(self.path)

    # fields
    @property
    def enrolled(self) -> bool:
        return bool(self._d.get("device_id") and self._d.get("core_url") and self._d.get("core_public_key"))

    device_id = property(lambda s: s._d.get("device_id"))
    core_url = property(lambda s: s._d.get("core_url"))
    core_public_key = property(lambda s: s._d.get("core_public_key"))
    envelope = property(lambda s: s._d.get("envelope"))
    highest_version = property(lambda s: s._d.get("highest_version", 0))
    released = property(lambda s: s._d.get("released", False))
    last_sync = property(lambda s: s._d.get("last_sync"))
    last_error = property(lambda s: s._d.get("last_error"))

    @property
    def events(self) -> list[dict]:
        return list(self._d.get("events", []))

    def set(self, **kw) -> None:
        self._d.update(kw)

    def add_event(self, kind: str, detail: str = "", now: datetime | None = None) -> None:
        ev = self._d.setdefault("events", [])
        ev.append({"at": _stamp(now or _utcnow()), "kind": kind, "detail": detail[:500]})
        del ev[:-MAX_EVENTS]


class Agent:
    def __init__(self, state: AgentState, signer, *, clock=_utcnow):
        self.state = state
        self.signer = signer
        self.clock = clock

    def _client(self) -> CoreClient:
        return CoreClient(self.state.core_url, self.state.device_id, self.signer, clock=self.clock)

    def enrol(self, address: str, device_id: str, code: str) -> None:
        """Enrol once (contract A1): verify Core's proof, pin its key, accept its bundle."""
        client = CoreClient(address, device_id, self.signer, clock=self.clock)
        answer = client.enrol(code)
        core_pub = crypto.b64d(answer["core_public_key"])
        payload = BundleVerifier(core_pub).accept(answer["bundle"])
        now = self.clock()
        self.state.set(
            device_id=device_id,
            core_url=client.base_url,
            core_public_key=answer["core_public_key"],
            envelope=answer["bundle"],
            highest_version=payload["version"],
            released=device_id in payload.get("released", []),
            last_sync=_stamp(now),
            last_error=None,
        )
        self.state.add_event("enrolled", f"key {answer['key_id']}, rules version {payload['version']}", now)
        self.state.save()

    def current_payload(self) -> dict | None:
        """The rules this PC enforces: the stored bundle, signature checked again."""
        if not self.state.enrolled or not self.state.envelope:
            return None
        try:
            return BundleVerifier(crypto.b64d(self.state.core_public_key)).accept(self.state.envelope)
        except BundleRejected:
            return None

    def log(self, kind: str, detail: str = "") -> None:
        self.state.add_event(kind, detail, self.clock())
        self.state.save()

    def sync(self, enforcing: bool) -> tuple[bool, str | None]:
        """Check in, upload events, fetch a newer bundle. Returns (rules_changed, error)."""
        if not self.state.enrolled:
            return False, "not enrolled"
        now = self.clock()
        client = self._client()
        sending = self.state.events
        changed = False
        try:
            answer = client.check_in(self.state.highest_version, AGENT_VERSION, enforcing, sending)
            # Drop the events we successfully uploaded; keep any added meanwhile.
            self.state.set(events=self.state.events[len(sending):])
            if answer["latest_version"] > self.state.highest_version:
                env = client.fetch_bundle()
                try:
                    p = BundleVerifier(crypto.b64d(self.state.core_public_key), self.state.highest_version).accept(env)
                    self.state.set(envelope=env, highest_version=p["version"],
                                   released=self.state.device_id in p.get("released", []))
                    self.state.add_event("bundle_accepted", f"version {p['version']}", now)
                    changed = True
                except BundleRejected as e:
                    self.state.add_event("bundle_rejected", str(e), now)
            self.state.set(last_sync=_stamp(now), last_error=None)
            self.state.save()
            return changed, None
        except CoreError as e:
            self.state.set(last_error=str(e))
            self.state.save()
            return False, str(e)
