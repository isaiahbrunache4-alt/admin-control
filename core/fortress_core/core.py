"""Lock, unlock, editing and publishing: the part of Core the Console talks to.

Spec 01 §6. One lock for the whole system. A fresh `Fortress` is always locked; the
signing key exists unsealed only in memory, only while unlocked. Every edit changes the
draft rules; `publish()` (and `lock()`, which publishes anything pending) signs the
draft as a new, higher-numbered bundle for the Agents.

The bundle payload is:

    {"version": n, "issued_at": "...Z", "rules": {...}, "released": ["device-id", ...]}

`released` is how a device is removed (Agent contract A6): an Agent that finds its
own id there stands down.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import bundle, crypto, rules
from .rules import RuleError
from .schedule import block_now_window
from .store import Store

MAX_DELAY_SECONDS = 15 * 60
DEFAULT_RELOCK_MINUTES = 15          # Spec 01 §6.1, assumed
MIN_PASSWORD_LENGTH = 8

_DEVICE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class FortressError(Exception):
    """Base for refusals the Console should show to the user."""


class Locked(FortressError):
    """The change needs an unlock first."""


class NotSetUp(FortressError):
    pass


class WrongPassword(FortressError):
    pass


class TooSoon(FortressError):
    """Wrong attempts are delayed (Spec 01 §6.2), or 'locked until' is in force."""

    def __init__(self, message: str, retry_after: datetime):
        super().__init__(message)
        self.retry_after = retry_after


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def failure_delay(failures: int) -> int:
    """Seconds to wait after the nth wrong attempt in a row: 1, 2, 4 … up to 15 min."""
    if failures <= 0:
        return 0
    return min(2 ** (failures - 1), MAX_DELAY_SECONDS)


class Fortress:
    def __init__(self, path: str | Path, clock: Callable[[], datetime] = _utcnow):
        self.store = Store(path)
        self.clock = clock
        self._priv: bytes | None = None
        self._unlock_at: datetime | None = None
        self._last_used: datetime | None = None

    def close(self) -> None:
        self._forget_key()
        self.store.close()

    def _now(self) -> datetime:
        return self.clock()

    def _ts(self) -> str:
        return rules.format_utc(self._now())

    def _log(self, kind: str, detail: str = "") -> None:
        self.store.log(self._ts(), kind, detail)

    # ---- setup ------------------------------------------------------------------

    @property
    def is_set_up(self) -> bool:
        return self.store.get("public_key") is not None

    def setup(self, password: str) -> str:
        """First run. Returns the recovery code, which is shown once and never stored."""
        if self.is_set_up:
            raise FortressError("Fortress is already set up")
        _check_password(password)
        priv, pub = crypto.new_signing_key()
        code = crypto.new_recovery_code()
        s = self.store
        s.set("public_key", crypto.b64e(pub))
        s.set("key_by_password", crypto.seal(priv, password))
        s.set("key_by_recovery", crypto.seal(priv, crypto.normalize_recovery_code(code)))
        s.set("draft", rules.empty_rules())
        s.set("version", 0)
        s.set("dirty", True)
        s.set("next_schedule", 1)
        s.set("failures", 0)
        s.set("relock_minutes", DEFAULT_RELOCK_MINUTES)
        s.set("unlock_delay_minutes", 0)
        s.set("locked_until", None)
        self._log("setup", f"key {crypto.key_id(pub)}")
        # Publish version 1 straight away so Agents have something to enrol against.
        self._priv = priv
        self.publish()
        self._forget_key()
        return code

    def _require_set_up(self) -> None:
        if not self.is_set_up:
            raise NotSetUp("run setup first")

    @property
    def public_key(self) -> bytes:
        self._require_set_up()
        return crypto.b64d(self.store.get("public_key"))

    # ---- lock state -------------------------------------------------------------

    def state(self) -> str:
        """'locked', 'pending' (right password, waiting out the unlock delay) or 'unlocked'."""
        self._expire_idle()
        if self._priv is None:
            return "locked"
        if self._unlock_at is not None and self._now() < self._unlock_at:
            return "pending"
        return "unlocked"

    @property
    def unlocks_at(self) -> datetime | None:
        return self._unlock_at if self.state() == "pending" else None

    def unlock(self, password: str) -> str:
        """Check the password. Returns the new state ('unlocked' or 'pending')."""
        self._require_set_up()
        now = self._now()
        locked_until = self.store.get("locked_until")
        if locked_until and now < rules.parse_utc(locked_until):
            raise TooSoon(f"locked until {locked_until}", rules.parse_utc(locked_until))
        self._wait_out_failures(now)
        try:
            priv = crypto.unseal(self.store.get("key_by_password"), password)
        except crypto.InvalidSecret:
            self._record_failure("unlock")
            raise WrongPassword("wrong password") from None
        self.store.set("failures", 0)
        self._priv = priv
        self._last_used = now
        delay = self.store.get("unlock_delay_minutes", 0)
        self._unlock_at = now + timedelta(minutes=delay) if delay else None
        self._log("unlock", f"after {delay} min delay" if delay else "")
        return self.state()

    def lock(self) -> None:
        """Lock, publishing any edits first so nothing is left half-done."""
        st = self.state()
        if st == "locked":
            return
        if st == "unlocked" and self.store.get("dirty"):
            self.publish()
        self._forget_key()
        self._log("lock")

    def _forget_key(self) -> None:
        self._priv = None
        self._unlock_at = None
        self._last_used = None

    def _expire_idle(self) -> None:
        if self._priv is None or self._last_used is None:
            return
        idle = timedelta(minutes=self.store.get("relock_minutes", DEFAULT_RELOCK_MINUTES))
        # The idle clock starts once the unlock delay is over, not while it runs.
        since = max(self._last_used, self._unlock_at or self._last_used)
        if self._now() - since >= idle:
            if self.store.get("dirty"):
                self.publish(_touch=False)
            self._forget_key()
            self._log("lock", "auto-relock after idle")

    def _require_unlocked(self) -> bytes:
        self._require_set_up()
        st = self.state()
        if st == "pending":
            raise Locked(f"unlock delay running until {rules.format_utc(self._unlock_at)}")
        if st != "unlocked":
            raise Locked("unlock first")
        self._last_used = self._now()
        return self._priv

    def _wait_out_failures(self, now: datetime) -> None:
        failures = self.store.get("failures", 0)
        last = self.store.get("last_failure")
        if failures and last:
            retry = rules.parse_utc(last) + timedelta(seconds=failure_delay(failures))
            if now < retry:
                raise TooSoon(f"too many wrong attempts; try again at {rules.format_utc(retry)}", retry)

    def _record_failure(self, what: str) -> None:
        n = self.store.get("failures", 0) + 1
        self.store.set("failures", n)
        self.store.set("last_failure", self._ts())
        self._log("wrong_password", f"{what}, attempt {n}")

    # ---- password and recovery ----------------------------------------------------

    def change_password(self, current: str, new: str) -> None:
        priv = self._require_unlocked()
        self._wait_out_failures(self._now())
        try:
            crypto.unseal(self.store.get("key_by_password"), current)
        except crypto.InvalidSecret:
            self._record_failure("change password")
            raise WrongPassword("current password is wrong") from None
        self.store.set("failures", 0)
        _check_password(new)
        self.store.set("key_by_password", crypto.seal(priv, new))
        self._log("password_changed")

    def recover(self, code: str, new_password: str) -> None:
        """Reset the password with the recovery code. Works even under 'locked until'
        (Spec 01 §6.3); the wrong-attempt delay still applies. Leaves Fortress locked."""
        self._require_set_up()
        self._wait_out_failures(self._now())
        _check_password(new_password)
        try:
            priv = crypto.unseal(
                self.store.get("key_by_recovery"), crypto.normalize_recovery_code(code)
            )
        except crypto.InvalidSecret:
            self._record_failure("recovery code")
            raise WrongPassword("wrong recovery code") from None
        self.store.set("failures", 0)
        self.store.set("key_by_password", crypto.seal(priv, new_password))
        self.store.set("locked_until", None)
        self._log("password_reset", "with recovery code")

    # ---- self-control options (Spec 01 §6.3) -------------------------------------

    def set_unlock_delay(self, minutes: int) -> None:
        self._require_unlocked()
        if not 0 <= minutes <= 24 * 60:
            raise FortressError("unlock delay is 0 to 1440 minutes")
        self.store.set("unlock_delay_minutes", minutes)
        self._log("setting", f"unlock delay {minutes} min")

    def set_relock_minutes(self, minutes: int) -> None:
        self._require_unlocked()
        if not 1 <= minutes <= 24 * 60:
            raise FortressError("auto-relock is 1 to 1440 minutes")
        self.store.set("relock_minutes", minutes)
        self._log("setting", f"auto-relock {minutes} min")

    def lock_until(self, until: datetime) -> None:
        """Ignore the password until `until`, then lock now."""
        self._require_unlocked()
        if until <= self._now():
            raise FortressError("'locked until' must be in the future")
        self.store.set("locked_until", rules.format_utc(until))
        self._log("setting", f"locked until {rules.format_utc(until)}")
        self.lock()

    # ---- editing the draft --------------------------------------------------------

    @property
    def draft(self) -> dict:
        self._require_set_up()
        return self.store.get("draft")

    def _edit(self, change: Callable[[dict], str]) -> None:
        self._require_unlocked()
        d = self.store.get("draft")
        detail = change(d)
        self.store.set("draft", d)
        self.store.set("dirty", True)
        self._log("edit", detail)

    def add_list(self, name: str) -> None:
        def change(d):
            rules.validate_list_name(name)
            if name in d["lists"]:
                raise RuleError(f"list {name!r} already exists")
            d["lists"][name] = {k: [] for k in rules.ITEM_KINDS}
            return f"add list {name}"
        self._edit(change)

    def remove_list(self, name: str) -> None:
        def change(d):
            if name not in d["lists"]:
                raise RuleError(f"no list {name!r}")
            used = [s["id"] for s in d["schedules"] if s["list"] == name]
            if used:
                raise RuleError(f"list {name!r} is used by schedules {', '.join(used)}")
            del d["lists"][name]
            return f"remove list {name}"
        self._edit(change)

    def add_item(self, list_name: str, kind: str, item: str) -> None:
        def change(d):
            if list_name not in d["lists"]:
                raise RuleError(f"no list {list_name!r}")
            v = rules.normalize_item(kind, item)
            items = d["lists"][list_name][kind]
            if v not in items:
                items.append(v)
                items.sort()
            return f"{list_name}: add {kind} {v}"
        self._edit(change)

    def remove_item(self, list_name: str, kind: str, item: str) -> None:
        def change(d):
            if list_name not in d["lists"]:
                raise RuleError(f"no list {list_name!r}")
            v = rules.normalize_item(kind, item)
            if v not in d["lists"][list_name][kind]:
                raise RuleError(f"{v!r} is not in {list_name}")
            d["lists"][list_name][kind].remove(v)
            return f"{list_name}: remove {kind} {v}"
        self._edit(change)

    def allow(self, kind: str, item: str) -> None:
        def change(d):
            v = rules.normalize_item(kind, item)
            if v not in d["allow"][kind]:
                d["allow"][kind].append(v)
                d["allow"][kind].sort()
            return f"allow {kind} {v}"
        self._edit(change)

    def disallow(self, kind: str, item: str) -> None:
        def change(d):
            v = rules.normalize_item(kind, item)
            if v not in d["allow"][kind]:
                raise RuleError(f"{v!r} is not on the allowed list")
            d["allow"][kind].remove(v)
            return f"un-allow {kind} {v}"
        self._edit(change)

    def add_schedule(self, schedule: dict) -> str:
        """Add a weekly or one-off schedule. Returns its id."""
        new_id = f"s{self.store.get('next_schedule', 1)}"

        def change(d):
            s = dict(schedule, id=new_id)
            rules.validate_schedule(s, d)
            self._check_devices(s["devices"])
            d["schedules"].append(s)
            return f"add schedule {new_id} ({s['kind']}, list {s['list']})"
        self._edit(change)
        self.store.set("next_schedule", int(new_id[1:]) + 1)
        return new_id

    def block_now(self, list_name: str, hours: float, devices: list[str]) -> str:
        """'Block now for N hours' (Spec 01 §8.3): a one-off schedule starting now."""
        if not 0 < hours <= 24 * 7:
            raise RuleError("block for between 0 and 168 hours")
        start, end = block_now_window(self._now(), hours)
        return self.add_schedule({
            "kind": "once", "list": list_name, "devices": devices,
            "start": rules.format_utc(start), "end": rules.format_utc(end),
        })

    def remove_schedule(self, schedule_id: str) -> None:
        def change(d):
            before = len(d["schedules"])
            d["schedules"] = [s for s in d["schedules"] if s["id"] != schedule_id]
            if len(d["schedules"]) == before:
                raise RuleError(f"no schedule {schedule_id!r}")
            return f"remove schedule {schedule_id}"
        self._edit(change)

    # ---- devices -----------------------------------------------------------------

    def _check_devices(self, devices: list[str]) -> None:
        known = {d["id"] for d in self.store.devices()}
        unknown = [d for d in devices if d != "all" and d not in known]
        if unknown:
            raise RuleError(f"unknown device(s): {', '.join(unknown)}")

    def add_device(self, device_id: str, name: str, platform: str) -> None:
        self._require_unlocked()
        if not _DEVICE_ID.match(device_id) or device_id == "all":
            raise RuleError("device ids are lower-case letters, digits and '-', up to 32")
        if platform not in rules.PLATFORMS:
            raise RuleError(f"platform must be one of {', '.join(rules.PLATFORMS)}")
        if any(d["id"] == device_id for d in self.store.devices(include_released=True)):
            raise RuleError(f"device id {device_id!r} has been used before")
        self.store.add_device(device_id, name, platform, self._ts())
        self._log("device_added", f"{device_id} ({platform})")

    def remove_device(self, device_id: str) -> None:
        """Devices → Remove (Spec 01 §7.4): mark released; the next bundle tells the
        Agent to stand down. Schedules naming only this device are dropped."""
        self._require_unlocked()
        if not self.store.release_device(device_id):
            raise RuleError(f"no enrolled device {device_id!r}")

        def change(d):
            for s in d["schedules"]:
                s["devices"] = [x for x in s["devices"] if x != device_id]
            d["schedules"] = [s for s in d["schedules"] if s["devices"]]
            return f"release device {device_id}"
        self._edit(change)
        self.publish()

    def check_in(self, device_id: str) -> None:
        """Record that a device reached Core (Spec 01 §7.4). Needs no unlock."""
        if not self.store.touch_device(device_id, self._ts()):
            raise FortressError(f"no enrolled device {device_id!r}")

    def device_status(self, device: dict, amber_hours: int = 24, red_hours: int = 72) -> str:
        if not device["last_seen"]:
            return "never"
        age = self._now() - rules.parse_utc(device["last_seen"])
        if age >= timedelta(hours=red_hours):
            return "red"
        if age >= timedelta(hours=amber_hours):
            return "amber"
        return "ok"

    # ---- publishing ---------------------------------------------------------------

    def publish(self, _touch: bool = True) -> int:
        """Sign the draft as the next bundle. Returns its version."""
        priv = self._require_unlocked() if _touch else self._priv
        version = self.store.get("version", 0) + 1
        payload = {
            "version": version,
            "issued_at": self._ts(),
            "rules": self.store.get("draft"),
            "released": sorted(
                d["id"] for d in self.store.devices(include_released=True) if d["released"]
            ),
        }
        envelope = bundle.sign_bundle(payload, priv, self.public_key)
        self.store.add_bundle(version, payload["issued_at"], envelope)
        self.store.set("version", version)
        self.store.set("dirty", False)
        self._log("publish", f"version {version}")
        return version

    def latest_bundle(self) -> dict:
        self._require_set_up()
        return self.store.latest_bundle()


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise FortressError(f"passwords are at least {MIN_PASSWORD_LENGTH} characters")
