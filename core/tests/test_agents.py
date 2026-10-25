"""The Agent protocol (docs/agent_protocol.md), driven by a software Agent."""

import json
import os
import time
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from fortress_core import agents, crypto
from fortress_core.api import create_app
from fortress_core.bundle import BundleVerifier
from fortress_core.core import Locked

from .conftest import PASSWORD


class SoftAgent:
    """What a real Agent does, with its key in memory instead of hardware."""

    def __init__(self, client, device_id, clock):
        self.client, self.device_id, self.clock = client, device_id, clock
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public_key = crypto.b64e(self.key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo))

    def enrol(self, code, nonce=None):
        nonce = nonce or crypto.b64e(os.urandom(16))
        k = agents.enrol_key(code)
        r = self.client.post("/agent/v1/enrol", json={
            "device_id": self.device_id, "public_key": self.public_key, "nonce": nonce,
            "proof": agents.agent_proof(k, self.device_id, self.public_key, nonce)})
        if r.status_code == 200:
            body = r.json()
            expect = agents.core_proof(k, self.device_id, self.public_key, nonce, body["core_public_key"])
            assert body["proof"] == expect
            assert body["key_id"] == crypto.key_id(crypto.b64d(body["core_public_key"]))
        return r

    def headers(self, method, path, body=b"", *, when=None, nonce=None, key=None):
        when = str(int((when or self.clock.now).timestamp()))
        nonce = nonce or crypto.b64e(os.urandom(16))
        msg = agents.request_message(method, path, self.device_id, when, nonce, body)
        sig = (key or self.key).sign(msg, ec.ECDSA(hashes.SHA256()))
        return {"X-Fortress-Device": self.device_id, "X-Fortress-Time": when,
                "X-Fortress-Nonce": nonce, "X-Fortress-Signature": crypto.b64e(sig)}

    def get_bundle(self, **kw):
        return self.client.get("/agent/v1/bundle", headers=self.headers("GET", "/agent/v1/bundle", **kw))

    def check_in(self, payload, **kw):
        body = json.dumps(payload).encode()
        h = self.headers("POST", "/agent/v1/checkin", body, **kw)
        return self.client.post("/agent/v1/checkin", content=body, headers={**h, "Content-Type": "application/json"})


@pytest.fixture
def agent_client(fortress):
    with TestClient(agents.create_agent_app(fortress), base_url="http://192.168.1.20:47801") as c:
        yield c


@pytest.fixture
def tablet(fortress, agent_client, clock):
    fortress.unlock(PASSWORD)
    fortress.add_device("tablet", "Idea Tab", "android")
    code, _ = fortress.start_enrolment("tablet")
    fortress.lock()
    a = SoftAgent(agent_client, "tablet", clock)
    a.code = code
    return a


def test_enrolment_needs_unlock(fortress):
    with pytest.raises(Locked):
        fortress.start_enrolment("tablet")


def test_enrol_and_verify_bundle(fortress, tablet):
    r = tablet.enrol(tablet.code)
    assert r.status_code == 200, r.text
    body = r.json()
    assert crypto.b64d(body["core_public_key"]) == fortress.public_key
    assert BundleVerifier(fortress.public_key).accept(body["bundle"])["version"] == 1
    d = fortress.store.device("tablet")
    assert d["public_key"] == tablet.public_key and d["enrolled_at"]
    assert fortress.store.enrolment("tablet") is None
    assert fortress.store.activity()[0]["kind"] == "device_enrolled"


def test_code_works_once(tablet):
    assert tablet.enrol(tablet.code).status_code == 200
    r = tablet.enrol(tablet.code)
    assert r.status_code == 404 and r.json()["error"] == "no_enrolment"


def test_code_format_is_forgiving(tablet):
    assert tablet.enrol(tablet.code.lower().replace("-", " ")).status_code == 200


def test_wrong_code_counts_and_cancels(fortress, tablet):
    for i in range(1, agents.ENROL_MAX_FAILURES + 1):
        r = tablet.enrol("AAAAA-AAAAA")
        assert r.status_code == 403 and r.json()["error"] == "bad_proof"
    assert tablet.enrol(tablet.code).status_code == 404       # cancelled after 5
    assert fortress.store.device("tablet")["public_key"] is None


def test_expired_code(tablet, clock):
    clock.advance(minutes=agents.ENROL_MINUTES)
    r = tablet.enrol(tablet.code)
    assert r.status_code == 410 and r.json()["error"] == "expired"


def test_non_p256_key_refused(tablet):
    ed = ed25519.Ed25519PrivateKey.generate().public_key()
    tablet.public_key = crypto.b64e(ed.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo))
    r = tablet.enrol(tablet.code)
    assert r.status_code == 400 and "P-256" in r.json()["message"]


def test_fake_core_cannot_prove_the_code(tablet):
    """The Agent's check of Core's proof is what stops a fake Core on the Wi-Fi."""
    k_right = agents.enrol_key(tablet.code)
    k_wrong = agents.enrol_key("BBBBB-BBBBB")
    args = ("tablet", tablet.public_key, "bm9uY2Vub25jZW5vbmNlMQ==", "a2V5")
    assert agents.core_proof(k_right, *args) != agents.core_proof(k_wrong, *args)


def test_signed_requests(fortress, tablet, clock):
    tablet.enrol(tablet.code)
    r = tablet.get_bundle()
    assert r.status_code == 200
    assert BundleVerifier(fortress.public_key).accept(r.json())["version"] == 1


@pytest.mark.parametrize("break_it,kind", [
    (lambda a: a.headers("GET", "/agent/v1/bundle", key=ec.generate_private_key(ec.SECP256R1())), "bad_signature"),
    (lambda a: a.headers("GET", "/agent/v1/checkin"), "bad_signature"),                  # signed for another path
    (lambda a: a.headers("GET", "/agent/v1/bundle", when=a.clock.now - timedelta(seconds=301)), "bad_time"),
    (lambda a: {**a.headers("GET", "/agent/v1/bundle"), "X-Fortress-Device": "pixel"}, "not_enrolled"),
    (lambda a: {k: v for k, v in a.headers("GET", "/agent/v1/bundle").items() if k != "X-Fortress-Nonce"}, "bad_nonce"),
])
def test_bad_requests_refused(tablet, break_it, kind):
    tablet.enrol(tablet.code)
    r = tablet.client.get("/agent/v1/bundle", headers=break_it(tablet))
    assert r.status_code == 401 and r.json()["error"] == kind


def test_replay_refused(tablet):
    tablet.enrol(tablet.code)
    h = tablet.headers("GET", "/agent/v1/bundle")
    assert tablet.client.get("/agent/v1/bundle", headers=h).status_code == 200
    r = tablet.client.get("/agent/v1/bundle", headers=h)
    assert r.status_code == 401 and r.json()["error"] == "replay"


def test_tampered_body_refused(tablet):
    tablet.enrol(tablet.code)
    body = json.dumps({"version": 1}).encode()
    h = tablet.headers("POST", "/agent/v1/checkin", body)
    r = tablet.client.post("/agent/v1/checkin", content=b'{"version": 2}', headers=h)
    assert r.status_code == 401 and r.json()["error"] == "bad_signature"


def test_check_in(fortress, tablet, clock):
    tablet.enrol(tablet.code)
    assert fortress.device_status(fortress.store.device("tablet")) == "never"
    r = tablet.check_in({"version": 1, "agent_version": "0.1.0", "enforcing": True, "events": [
        {"at": "2026-10-19T11:59:00Z", "kind": "bundle_accepted", "detail": "version 1"},
        {"at": "not a time", "kind": "apps_suspended", "detail": "2 apps"},
    ]})
    assert r.status_code == 200, r.text
    assert r.json() == {"latest_version": 1, "released": False}
    d = fortress.store.device("tablet")
    assert d["version_held"] == 1 and d["agent_version"] == "0.1.0"
    assert fortress.device_status(d) == "ok"
    details = [a["detail"] for a in fortress.store.activity() if a["kind"] == "device"]
    assert "tablet: bundle_accepted: version 1" in details
    assert "tablet: apps_suspended: 2 apps" in details


def test_check_in_flags_an_agent_not_enforcing(fortress, tablet):
    tablet.enrol(tablet.code)
    tablet.check_in({"version": 1, "enforcing": False})
    assert "tablet: not_enforcing" in fortress.store.activity()[0]["detail"]


def test_check_in_stores_app_reports(fortress, tablet):
    tablet.enrol(tablet.code)
    report = {"at": "2026-10-19T11:58:00Z", "data": {"v": 1, "bodyweight": [{"date": "2026-10-19", "weight": 251.4}]}}
    assert tablet.check_in({"version": 1, "reports": {"block_trainer": report}}).status_code == 200
    got = fortress.store.reports()
    assert [(r["device_id"], r["source"]) for r in got] == [("tablet", "block_trainer")]
    assert got[0]["data"] == report
    # A newer report replaces it; a check-in without reports leaves it alone.
    newer = {"at": "2026-10-19T12:30:00Z", "data": {"v": 1}}
    tablet.check_in({"version": 1, "reports": {"block_trainer": newer}})
    tablet.check_in({"version": 1})
    assert fortress.store.reports()[0]["data"] == newer


@pytest.mark.parametrize("reports", [
    "x", {"Bad Name": {}}, {"block_trainer": "not an object"},
    {f"s{i}": {} for i in range(agents.MAX_REPORTS + 1)},
    {"block_trainer": {"blob": "x" * agents.MAX_REPORT_BYTES}},
])
def test_bad_reports_refused(fortress, tablet, reports):
    tablet.enrol(tablet.code)
    assert tablet.check_in({"version": 1, "reports": reports}).status_code == 400
    assert fortress.store.reports() == []
    assert fortress.store.device("tablet")["version_held"] is None   # nothing recorded


@pytest.mark.parametrize("payload", [
    {"version": "1"}, {"version": -1}, {"version": 1, "events": "x"},
    {"version": 1, "events": [{"kind": "Has Spaces"}]},
    {"version": 1, "events": [{"kind": "x"}] * (agents.MAX_EVENTS + 1)},
])
def test_bad_check_ins(tablet, payload):
    tablet.enrol(tablet.code)
    assert tablet.check_in(payload).status_code == 400


def test_released_device_gets_its_release(fortress, tablet):
    tablet.enrol(tablet.code)
    fortress.unlock(PASSWORD)
    fortress.remove_device("tablet")
    fortress.lock()
    assert tablet.check_in({"version": 1}).json() == {"latest_version": 2, "released": True}
    p = BundleVerifier(fortress.public_key, 1).accept(tablet.get_bundle().json())
    assert p["released"] == ["tablet"]


def test_re_enrolment_replaces_the_key(fortress, tablet, agent_client, clock):
    tablet.enrol(tablet.code)
    fortress.unlock(PASSWORD)
    code, _ = fortress.start_enrolment("tablet")
    fortress.lock()
    assert tablet.get_bundle().status_code == 200          # old key works until replaced
    new = SoftAgent(agent_client, "tablet", clock)
    assert new.enrol(code).status_code == 200
    assert tablet.get_bundle().status_code == 401
    assert new.get_bundle().status_code == 200


def test_console_api_starts_enrolment(fortress):
    with TestClient(create_app(fortress, agent_port=47999), base_url="http://127.0.0.1") as c:
        tok = c.post("/api/v1/unlock", json={"password": PASSWORD}).json()["token"]
        h = {"Authorization": "Bearer " + tok}
        c.post("/api/v1/devices", json={"id": "tablet", "name": "Idea Tab", "platform": "android"}, headers=h)
        assert c.post("/api/v1/devices/tablet/enrolment").status_code == 423      # needs the token
        r = c.post("/api/v1/devices/tablet/enrolment", headers=h).json()
        assert len(r["code"]) == 11 and r["port"] == 47999 and r["device_id"] == "tablet"
        assert r["key_id"] == crypto.key_id(fortress.public_key)
        assert c.post("/api/v1/devices/pixel/enrolment", headers=h).status_code == 400
        dev = c.get("/api/v1/status").json()["devices"][0]
        assert dev["enrolled"] is False and dev["version_held"] is None


def test_old_database_is_migrated(tmp_path, clock):
    import sqlite3
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT NOT NULL, platform TEXT NOT NULL,
            added_at TEXT NOT NULL, last_seen TEXT, released INTEGER NOT NULL DEFAULT 0);
        INSERT INTO devices(id, name, platform, added_at) VALUES ('pc', 'PC', 'windows', 'x');
    """)
    db.close()
    from fortress_core.store import Store
    s = Store(path)
    assert s.device("pc")["public_key"] is None
    assert s.get("schema_version") == 2
    s.close()


def test_database_from_a_newer_core_is_refused(tmp_path):
    from fortress_core.store import SCHEMA_VERSION, NewerSchema, Store
    s = Store(tmp_path / "x.db")
    s.set("schema_version", SCHEMA_VERSION + 1)
    s.close()
    with pytest.raises(NewerSchema):
        Store(tmp_path / "x.db")
    import sqlite3  # the refusal must not have rewritten the marker
    db = sqlite3.connect(tmp_path / "x.db")
    assert db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0] == str(SCHEMA_VERSION + 1)
    db.close()


def test_lan_addresses_never_loopback():
    assert all(not a.startswith("127.") for a in agents.lan_addresses())


def test_real_clock_time_header_is_accepted(fortress, agent_client):
    """Unix seconds from the real clock against Core's real clock (no fake time)."""
    from fortress_core.core import _utcnow
    fortress.clock = _utcnow
    fortress.unlock(PASSWORD)
    fortress.add_device("pc", "PC", "windows")
    code, _ = fortress.start_enrolment("pc")
    fortress.lock()

    class Now:
        @property
        def now(self):
            return _utcnow()

    a = SoftAgent(agent_client, "pc", Now())
    assert a.enrol(code).status_code == 200
    assert abs(int(a.headers("GET", "/")["X-Fortress-Time"]) - time.time()) < 5
    assert a.get_bundle().status_code == 200
