"""The rules document: block lists, schedules and the always-allowed list.

Format reference: docs/rules_format.md. Everything here is plain JSON-able data so the
same document can be signed, sent to an Agent, and read by Kotlin.
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ITEM_KINDS = ("domains", "android_packages", "windows_programs")
PLATFORMS = ("android", "windows")

# Spec 01 §10 starter list. Editable; these are never blocked by any schedule.
STARTER_ALLOW = {
    "domains": [
        "github.com",
        "pub.dev",
        "pypi.org",
        "developer.android.com",
        "silabs.com",
        "seeedstudio.com",
    ],
    "android_packages": ["com.shotput.app"],
    "windows_programs": [],
}

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
_PROGRAM = re.compile(r"^[^\\/:*?\"<>|]+\.exe$", re.IGNORECASE)
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_LIST_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class RuleError(ValueError):
    """A rule, list or schedule is malformed."""


def empty_rules() -> dict:
    return {
        "lists": {},
        "schedules": [],
        "allow": {k: list(v) for k, v in STARTER_ALLOW.items()},
    }


def normalize_item(kind: str, item: str) -> str:
    item = item.strip()
    if kind == "domains":
        return normalize_domain(item)
    if kind == "android_packages":
        if not _PACKAGE.match(item):
            raise RuleError(f"not an Android package name: {item!r}")
        return item
    if kind == "windows_programs":
        if not _PROGRAM.match(item):
            raise RuleError(f"not a Windows program file name (e.g. steam.exe): {item!r}")
        return item.lower()
    raise RuleError(f"unknown item kind: {kind!r}")


def normalize_domain(domain: str) -> str:
    """Lower-case a domain; accept one leading '*.' wildcard. Reject URLs."""
    d = domain.strip().lower().rstrip(".")
    if "://" in d or "/" in d:
        raise RuleError(f"give a domain, not a URL: {domain!r}")
    labels = d[2:].split(".") if d.startswith("*.") else d.split(".")
    if len(labels) < 2 or not all(_LABEL.match(lab) for lab in labels):
        raise RuleError(f"not a domain: {domain!r}")
    return d


def validate_list_name(name: str) -> str:
    if not _LIST_NAME.match(name):
        raise RuleError("list names are lower-case letters, digits, '-' or '_', up to 40 characters")
    return name


def _text(s: dict, key: str) -> str:
    """A schedule field that must be a string. JSON from the Console or a hand-edited
    bundle can hold anything, and every refusal here must be a RuleError."""
    v = s.get(key, "")
    if not isinstance(v, str):
        raise RuleError(f"'{key}' must be text, not {type(v).__name__}")
    return v


def validate_schedule(s: dict, rules: dict) -> None:
    """Every Agent evaluates schedules with no error handling to fall back on, so anything
    that could make schedule.py raise is refused here, before it is ever signed."""
    if not isinstance(s.get("id", ""), str):
        raise RuleError("schedule id must be text")
    if _text(s, "list") not in rules["lists"]:
        raise RuleError(f"schedule names an unknown list: {s.get('list')!r}")
    devices = s.get("devices")
    if not isinstance(devices, list) or not devices:
        raise RuleError("schedule needs at least one device, or 'all'")
    if not all(isinstance(d, str) and d for d in devices):
        raise RuleError("device ids must be text")
    kind = s.get("kind")
    if kind == "weekly":
        days = s.get("days")
        if not isinstance(days, list) or not days or any(d not in DAYS for d in days):
            raise RuleError(f"days must be from {', '.join(DAYS)}")
        for f in ("from", "to"):
            if not _HHMM.match(_text(s, f)):
                raise RuleError(f"'{f}' must be HH:MM, 24-hour")
        try:
            ZoneInfo(_text(s, "tz"))
        except (ZoneInfoNotFoundError, ValueError):
            raise RuleError(f"unknown time zone: {s.get('tz')!r}") from None
    elif kind == "once":
        start, end = parse_utc(_text(s, "start")), parse_utc(_text(s, "end"))
        if end <= start:
            raise RuleError("a one-off block must end after it starts")
    else:
        raise RuleError(f"unknown schedule kind: {kind!r}")


def parse_utc(text: str) -> datetime:
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise RuleError(f"not an ISO date-time: {text!r}") from None
    if dt.tzinfo is None:
        raise RuleError(f"date-time needs a time zone: {text!r}")
    return dt


def format_utc(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
