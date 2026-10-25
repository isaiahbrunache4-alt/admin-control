from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from fortress_core.api import create_app
from fortress_core.bundle import BundleVerifier
from fortress_core.core import Fortress

from .conftest import PASSWORD

API = "/api/v1"


@pytest.fixture
def client(fortress):
    with TestClient(create_app(fortress), base_url="http://127.0.0.1") as c:
        yield c


def unlock(client, password=PASSWORD):
    r = client.post(API + "/unlock", json={"password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_reports_need_no_unlock_and_skip_removed_devices(fortress, client):
    fortress.unlock(PASSWORD)
    fortress.add_device("pixel", "Pixel", "android")
    fortress.add_device("old", "Old phone", "android")
    fortress.lock()
    report = {"at": "2026-10-19T11:58:00Z", "data": {"v": 1}}
    fortress.store.put_report("pixel", "block_trainer", "2026-10-19T12:00:00Z", report)
    fortress.store.put_report("old", "block_trainer", "2026-10-19T12:00:00Z", report)
    fortress.store.release_device("old")
    r = client.get(API + "/reports")
    assert r.status_code == 200
    assert r.json() == {"pixel": {"block_trainer": {"received_at": "2026-10-19T12:00:00Z", "report": report}}}


def test_reading_needs_no_unlock(client):
    s = client.get(API + "/status").json()
    assert s["set_up"] and s["state"] == "locked" and s["version"] == 1
    assert "github.com" in client.get(API + "/rules").json()["allow"]["domains"]
    assert client.get(API + "/bundle").json()["format"] == 1
    assert client.get(API + "/activity").json()[0]["kind"] == "publish"


def test_other_hosts_refused(client):
    assert client.get(API + "/status", headers={"Host": "evil.example"}).status_code == 400


def test_setup_through_api(tmp_path, clock):
    f = Fortress(tmp_path / "new.db", clock=clock)
    with TestClient(create_app(f), base_url="http://127.0.0.1") as c:
        assert c.get(API + "/status").json() == {"set_up": False, "state": "locked"}
        assert c.get(API + "/rules").status_code == 409
        assert c.post(API + "/setup", json={"password": "short"}).status_code == 400
        r = c.post(API + "/setup", json={"password": PASSWORD})
        assert len(r.json()["recovery_code"]) == 29
        assert c.post(API + "/setup", json={"password": PASSWORD}).status_code == 400
    f.close()


def test_edits_need_the_session_token(client):
    assert client.post(API + "/lists", json={"name": "social"}).status_code == 423
    headers = unlock(client)
    assert client.post(API + "/lists", json={"name": "social"}).status_code == 423
    bad = {"Authorization": "Bearer not-the-token"}
    assert client.post(API + "/lists", json={"name": "social"}, headers=bad).status_code == 423
    r = client.post(API + "/lists", json={"name": "social"}, headers=headers)
    assert r.status_code == 200 and "social" in r.json()["rules"]["lists"]
    assert r.json()["unpublished_changes"] is True


def test_token_dies_with_the_lock(client):
    headers = unlock(client)
    assert client.post(API + "/lock", headers=headers).json()["state"] == "locked"
    assert client.post(API + "/lists", json={"name": "x"}, headers=headers).status_code == 423
    # A second unlock replaces the first session's token.
    first = unlock(client)
    second = unlock(client)
    assert client.post(API + "/lists", json={"name": "x"}, headers=first).status_code == 423
    assert client.post(API + "/lists", json={"name": "x"}, headers=second).status_code == 200


def test_token_dies_with_auto_relock(client, clock):
    headers = unlock(client)
    clock.advance(minutes=15)
    assert client.get(API + "/status").json()["state"] == "locked"
    assert client.post(API + "/lists", json={"name": "x"}, headers=headers).status_code == 423


def test_wrong_password_then_too_soon(client):
    r = client.post(API + "/unlock", json={"password": "nope nope"})
    assert r.status_code == 401 and r.json()["error"] == "wrong_password"
    r = client.post(API + "/unlock", json={"password": PASSWORD})
    assert r.status_code == 429 and r.headers["Retry-After"] == "1"
    assert r.json()["retry_after"].endswith("Z")


def test_full_edit_flow_and_publish(client, fortress, clock):
    h = unlock(client)

    def ok(method, path, **kw):
        r = client.request(method, API + path, headers=h, **kw)
        assert r.status_code == 200, r.text
        return r.json()

    ok("POST", "/devices", json={"id": "tablet", "name": "Idea Tab", "platform": "android"})
    ok("POST", "/lists", json={"name": "social"})
    ok("POST", "/lists/social/items", json={"kind": "domains", "item": "TikTok.com"})
    ok("POST", "/lists/social/items", json={"kind": "domains", "item": "*.reddit.com"})
    ok("POST", "/lists/social/items/remove", json={"kind": "domains", "item": "*.reddit.com"})
    sid = ok("POST", "/schedules", json={
        "list": "social", "devices": ["tablet"], "days": ["mon"],
        "from": "08:00", "to": "15:00", "tz": "America/New_York"})["id"]
    once = ok("POST", "/block-now", json={"list": "social", "hours": 1})["id"]
    ok("DELETE", f"/schedules/{once}")
    ok("POST", "/allow", json={"kind": "domains", "item": "example.org"})
    s = ok("POST", "/publish")
    assert s["version"] == 2 and not s["unpublished_changes"]

    # 12:00 UTC Monday = 08:00 New York: the weekly schedule is in force on the tablet.
    status = client.get(API + "/status").json()
    assert status["devices"][0]["active_schedules"] == [sid]
    assert status["active_schedules"] == [sid]

    p = BundleVerifier(fortress.public_key, 1).accept(client.get(API + "/bundle").json())
    assert p["rules"]["lists"]["social"]["domains"] == ["tiktok.com"]
    assert "example.org" in p["rules"]["allow"]["domains"]


def test_dashboard_shows_published_not_draft(client, clock):
    h = unlock(client)
    client.post(API + "/lists", json={"name": "social"}, headers=h)
    client.post(API + "/block-now", json={"list": "social", "hours": 1}, headers=h)
    assert client.get(API + "/status").json()["active_schedules"] == []    # not published yet
    client.post(API + "/lock", headers=h)
    assert client.get(API + "/status").json()["active_schedules"] == ["s1"]


def test_rule_errors_are_400(client):
    h = unlock(client)
    r = client.post(API + "/lists/nope/items", json={"kind": "domains", "item": "x.com"}, headers=h)
    assert r.status_code == 400 and r.json()["error"] == "invalid"
    r = client.post(API + "/lists", json={"name": "Has Spaces"}, headers=h)
    assert r.status_code == 400
    r = client.post(API + "/lists/x/items", json={"kind": "tweets", "item": "x"}, headers=h)
    assert r.status_code == 422                                     # schema, from FastAPI


def test_unlock_delay_through_api(client, clock):
    h = unlock(client)
    client.post(API + "/settings", json={"unlock_delay_minutes": 10}, headers=h)
    client.post(API + "/lock", headers=h)
    r = client.post(API + "/unlock", json={"password": PASSWORD}).json()
    assert r["state"] == "pending" and r["unlocks_at"] == "2026-10-19T12:10:00Z"
    h = {"Authorization": "Bearer " + r["token"]}
    assert client.post(API + "/lists", json={"name": "x"}, headers=h).status_code == 423
    clock.advance(minutes=10)
    assert client.post(API + "/lists", json={"name": "x"}, headers=h).status_code == 200


def test_lock_until_and_recover(client, fortress, clock):
    h = unlock(client)
    until = (clock.now + timedelta(days=1)).isoformat()
    assert client.post(API + "/lock-until", json={"until": until}, headers=h).json()["state"] == "locked"
    assert client.post(API + "/unlock", json={"password": PASSWORD}).status_code == 429
    r = client.post(API + "/recover", json={"code": fortress.recovery_code, "new_password": "fresh password"})
    assert r.status_code == 200
    unlock(client, "fresh password")


def test_wrong_recovery_code_keeps_the_unlock(client):
    h = unlock(client)
    r = client.post(API + "/recover", json={"code": "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA", "new_password": "fresh password"})
    assert r.status_code == 401
    assert client.post(API + "/lists", json={"name": "still-unlocked"}, headers=h).status_code == 200


def test_change_password_through_api(client):
    h = unlock(client)
    r = client.post(API + "/password", json={"current": PASSWORD, "new": "another password"}, headers=h)
    assert r.status_code == 200
    client.post(API + "/lock", headers=h)
    unlock(client, "another password")
