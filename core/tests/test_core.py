"""Lock, unlock, editing and publishing (Spec 01 §6, §7.4). The end-to-end test at the
bottom is Phase 1's "done when": a signed bundle produced and verified."""

import json
from datetime import timedelta

import pytest

from fortress_core import crypto
from fortress_core.bundle import BundleVerifier
from fortress_core.core import Fortress, FortressError, Locked, TooSoon, WrongPassword, failure_delay
from fortress_core.rules import RuleError
from fortress_core.schedule import is_domain_blocked

from .conftest import PASSWORD


def payload_of(env):
    return json.loads(crypto.b64d(env["payload"]))


def test_setup_publishes_version_1_and_starts_locked(fortress):
    assert fortress.state() == "locked"
    assert fortress.store.get("version") == 1
    env = fortress.latest_bundle()
    p = BundleVerifier(fortress.public_key).accept(env)
    assert p["version"] == 1 and p["released"] == []
    assert "github.com" in p["rules"]["allow"]["domains"]


def test_setup_twice_refused(fortress):
    with pytest.raises(FortressError):
        fortress.setup("another password")


def test_short_password_refused(tmp_path, clock):
    f = Fortress(tmp_path / "f.db", clock=clock)
    with pytest.raises(FortressError):
        f.setup("short")
    assert not f.is_set_up


def test_signing_key_never_stored_in_clear(fortress):
    raw = (fortress.store.db.execute("SELECT group_concat(value, '') FROM settings").fetchone()[0])
    fortress.unlock(PASSWORD)
    priv_b64 = crypto.b64e(fortress._priv)
    assert priv_b64 not in raw


def test_every_edit_needs_unlock(fortress):
    edits = [
        lambda f: f.add_list("social"),
        lambda f: f.add_item("social", "domains", "tiktok.com"),
        lambda f: f.allow("domains", "example.com"),
        lambda f: f.add_device("tablet", "Idea Tab", "android"),
        lambda f: f.publish(),
        lambda f: f.set_unlock_delay(5),
        lambda f: f.change_password(PASSWORD, "new password 1"),
    ]
    for edit in edits:
        with pytest.raises(Locked):
            edit(fortress)
    assert fortress.store.get("version") == 1


def test_unlock_edit_lock_publishes(fortress):
    assert fortress.unlock(PASSWORD) == "unlocked"
    fortress.add_list("social")
    fortress.add_item("social", "domains", "TikTok.com")
    assert fortress.store.get("version") == 1          # not published until lock/publish
    fortress.lock()
    assert fortress.state() == "locked"
    p = payload_of(fortress.latest_bundle())
    assert p["version"] == 2
    assert p["rules"]["lists"]["social"]["domains"] == ["tiktok.com"]


def test_lock_without_changes_does_not_publish(fortress):
    fortress.unlock(PASSWORD)
    fortress.lock()
    assert fortress.store.get("version") == 1


def test_wrong_password_and_growing_delay(fortress, clock):
    with pytest.raises(WrongPassword):
        fortress.unlock("wrong password")
    with pytest.raises(TooSoon):                        # 1 s delay after the first
        fortress.unlock(PASSWORD)
    clock.advance(seconds=1)
    with pytest.raises(WrongPassword):
        fortress.unlock("wrong again")
    clock.advance(seconds=1)
    with pytest.raises(TooSoon):                        # 2 s after the second
        fortress.unlock(PASSWORD)
    clock.advance(seconds=1)
    assert fortress.unlock(PASSWORD) == "unlocked"
    assert fortress.store.get("failures") == 0
    kinds = [a["kind"] for a in fortress.store.activity()]
    assert kinds.count("wrong_password") == 2


def test_failure_delay_caps_at_15_minutes():
    assert [failure_delay(n) for n in range(5)] == [0, 1, 2, 4, 8]
    assert failure_delay(11) == 900 and failure_delay(50) == 900


def test_delay_survives_restart(tmp_path, clock):
    path = tmp_path / "f.db"
    f = Fortress(path, clock=clock)
    f.setup(PASSWORD)
    for _ in range(4):
        with pytest.raises(WrongPassword):
            f.unlock("nope nope")
        clock.advance(seconds=failure_delay(f.store.get("failures")))
    with pytest.raises(WrongPassword):
        f.unlock("nope nope")
    f.close()
    g = Fortress(path, clock=clock)
    with pytest.raises(TooSoon):
        g.unlock(PASSWORD)
    g.close()


def test_auto_relock_publishes_pending_edits(fortress, clock):
    fortress.unlock(PASSWORD)
    fortress.add_list("games")
    clock.advance(minutes=14)
    assert fortress.state() == "unlocked"
    fortress.add_item("games", "windows_programs", "steam.exe")   # resets the idle clock
    clock.advance(minutes=15)
    assert fortress.state() == "locked"
    p = payload_of(fortress.latest_bundle())
    assert p["version"] == 2 and p["rules"]["lists"]["games"]["windows_programs"] == ["steam.exe"]
    with pytest.raises(Locked):
        fortress.add_list("more")


def test_unlock_delay(fortress, clock):
    fortress.unlock(PASSWORD)
    fortress.set_unlock_delay(30)
    fortress.lock()
    assert fortress.unlock(PASSWORD) == "pending"
    with pytest.raises(Locked, match="delay"):
        fortress.add_list("social")
    clock.advance(minutes=29)
    assert fortress.state() == "pending"
    clock.advance(minutes=1)
    assert fortress.state() == "unlocked"               # idle clock starts after the delay
    fortress.add_list("social")


def test_unlock_delay_can_be_cancelled(fortress, clock):
    fortress.unlock(PASSWORD)
    fortress.set_unlock_delay(10)
    fortress.lock()
    fortress.unlock(PASSWORD)
    fortress.lock()
    clock.advance(minutes=10)
    assert fortress.state() == "locked"


def test_locked_until_ignores_password_but_not_recovery(fortress, clock):
    fortress.unlock(PASSWORD)
    fortress.lock_until(clock.now + timedelta(days=2))
    assert fortress.state() == "locked"
    with pytest.raises(TooSoon):
        fortress.unlock(PASSWORD)
    fortress.recover(fortress.recovery_code, "brand new password")
    assert fortress.unlock("brand new password") == "unlocked"


def test_locked_until_expires(fortress, clock):
    fortress.unlock(PASSWORD)
    fortress.lock_until(clock.now + timedelta(hours=1))
    clock.advance(hours=1)
    assert fortress.unlock(PASSWORD) == "unlocked"


def test_change_password(fortress, clock):
    fortress.unlock(PASSWORD)
    with pytest.raises(WrongPassword):
        fortress.change_password("not it at all", "new password 1")
    with pytest.raises(TooSoon):
        fortress.change_password(PASSWORD, "new password 1")
    clock.advance(seconds=1)
    fortress.change_password(PASSWORD, "new password 1")
    assert fortress.store.get("failures") == 0
    fortress.lock()
    with pytest.raises(WrongPassword):
        fortress.unlock(PASSWORD)


def test_recovery_with_wrong_code(fortress):
    with pytest.raises(WrongPassword):
        fortress.recover("AAAA-AAAA-AAAA-AAAA-AAAA-AAAA", "brand new password")
    assert fortress.store.get("failures") == 1


def test_recovery_code_is_forgiving_about_format(fortress, clock):
    fortress.recover(fortress.recovery_code.lower().replace("-", " "), "brand new password")
    assert fortress.unlock("brand new password") == "unlocked"


def test_same_key_after_password_reset(fortress):
    """Agents pin the public key, so a password change must not change it."""
    pub = fortress.public_key
    fortress.recover(fortress.recovery_code, "brand new password")
    fortress.unlock("brand new password")
    fortress.add_list("social")
    fortress.lock()
    assert fortress.public_key == pub
    BundleVerifier(pub, 1).accept(fortress.latest_bundle())


def test_editing_rules_validated(fortress):
    fortress.unlock(PASSWORD)
    fortress.add_list("social")
    with pytest.raises(RuleError):
        fortress.add_list("social")
    with pytest.raises(RuleError):
        fortress.add_item("social", "domains", "https://tiktok.com/")
    with pytest.raises(RuleError):
        fortress.add_item("nope", "domains", "tiktok.com")
    with pytest.raises(RuleError):
        fortress.add_schedule({"kind": "weekly", "list": "social", "devices": ["pixel"],
                               "days": ["mon"], "from": "08:00", "to": "15:00", "tz": "UTC"})
    fortress.add_item("social", "domains", "tiktok.com")
    fortress.add_item("social", "domains", "tiktok.com")          # idempotent
    assert fortress.draft["lists"]["social"]["domains"] == ["tiktok.com"]


def test_list_in_use_cannot_be_removed(fortress):
    fortress.unlock(PASSWORD)
    fortress.add_list("social")
    sid = fortress.block_now("social", 2, ["all"])
    with pytest.raises(RuleError, match=sid):
        fortress.remove_list("social")
    fortress.remove_schedule(sid)
    fortress.remove_list("social")


def test_schedule_ids_are_never_reused(fortress):
    fortress.unlock(PASSWORD)
    fortress.add_list("social")
    a = fortress.block_now("social", 1, ["all"])
    fortress.remove_schedule(a)
    b = fortress.block_now("social", 1, ["all"])
    assert a != b


def test_block_now(fortress, clock):
    fortress.unlock(PASSWORD)
    fortress.add_list("social")
    fortress.add_item("social", "domains", "tiktok.com")
    fortress.block_now("social", 2, ["all"])
    fortress.lock()
    r = payload_of(fortress.latest_bundle())["rules"]
    assert is_domain_blocked(r, "pixel", "tiktok.com", clock.now)
    assert is_domain_blocked(r, "pixel", "tiktok.com", clock.now + timedelta(minutes=119))
    assert not is_domain_blocked(r, "pixel", "tiktok.com", clock.now + timedelta(hours=2))


def test_devices_and_release(fortress, clock):
    fortress.unlock(PASSWORD)
    fortress.add_device("tablet", "Lenovo Idea Tab", "android")
    fortress.add_device("pixel", "Pixel 8a", "android")
    with pytest.raises(RuleError):
        fortress.add_device("tablet", "again", "android")
    with pytest.raises(RuleError):
        fortress.add_device("all", "x", "android")
    with pytest.raises(RuleError):
        fortress.add_device("ipad", "x", "ios")
    fortress.add_list("social")
    only_tablet = fortress.block_now("social", 1, ["tablet"])
    both = fortress.block_now("social", 1, ["tablet", "pixel"])
    fortress.remove_device("tablet")
    p = payload_of(fortress.latest_bundle())
    assert p["released"] == ["tablet"]
    ids = {s["id"]: s["devices"] for s in p["rules"]["schedules"]}
    assert only_tablet not in ids and ids[both] == ["pixel"]
    with pytest.raises(RuleError):
        fortress.add_device("tablet", "re-used id", "android")
    assert [d["id"] for d in fortress.store.devices()] == ["pixel"]


def test_check_in_and_status(fortress, clock):
    fortress.unlock(PASSWORD)
    fortress.add_device("tablet", "Idea Tab", "android")
    fortress.lock()
    dev = lambda: fortress.store.devices()[0]
    assert fortress.device_status(dev()) == "never"
    fortress.check_in("tablet")                          # no unlock needed
    assert fortress.device_status(dev()) == "ok"
    clock.advance(hours=24)
    assert fortress.device_status(dev()) == "amber"
    clock.advance(hours=48)
    assert fortress.device_status(dev()) == "red"
    with pytest.raises(FortressError):
        fortress.check_in("nobody")


def test_agent_end_to_end(fortress, clock):
    """Phase 1 'done when': Core produces a signed bundle; an Agent pinned to Core's key
    verifies it, rejects a replay of an older one, and evaluates blocks from it."""
    agent = BundleVerifier(fortress.public_key)
    agent.accept(fortress.latest_bundle())               # enrol on version 1

    fortress.unlock(PASSWORD)
    fortress.add_device("tablet", "Idea Tab", "android")
    fortress.add_list("social")
    fortress.add_item("social", "domains", "tiktok.com")
    fortress.add_item("social", "android_packages", "com.zhiliaoapp.musically")
    fortress.add_schedule({"kind": "weekly", "list": "social", "devices": ["tablet"],
                           "days": ["mon", "tue", "wed", "thu", "fri"],
                           "from": "08:00", "to": "15:00", "tz": "America/New_York"})
    fortress.lock()
    lax = fortress.latest_bundle()

    fortress.unlock(PASSWORD)
    fortress.add_item("social", "domains", "youtube.com")
    fortress.lock()
    strict = fortress.latest_bundle()

    p = agent.accept(strict)
    assert p["version"] == 3
    with pytest.raises(Exception, match="not newer"):
        agent.accept(lax)                                # old, laxer rules cannot be replayed
    # 12:00 UTC Monday is 08:00 in New York.
    assert is_domain_blocked(p["rules"], "tablet", "www.youtube.com", clock.now)
    assert not is_domain_blocked(p["rules"], "pixel", "youtube.com", clock.now)
