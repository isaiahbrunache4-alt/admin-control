"""Which blocks are in force on a device at a given moment.

This is the reference implementation of what every Agent evaluates locally (Spec 01
§8.3). The Android and Windows Agents must give the same answers; the tests in
tests/test_schedule.py are the cases they should be checked against.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .rules import DAYS, parse_utc


@dataclass
class ActiveBlocks:
    domains: set[str] = field(default_factory=set)
    android_packages: set[str] = field(default_factory=set)
    windows_programs: set[str] = field(default_factory=set)
    schedule_ids: list[str] = field(default_factory=list)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def schedule_active(s: dict, now: datetime) -> bool:
    if now.tzinfo is None:
        # A naive time would be read as the machine's local time for weekly blocks and
        # fail to compare for one-off blocks. Always pass an aware time (UTC is simplest).
        raise ValueError("schedule checks need a time with a time zone")
    if s["kind"] == "once":
        return parse_utc(s["start"]) <= now < parse_utc(s["end"])

    local = now.astimezone(ZoneInfo(s["tz"]))
    t = local.hour * 60 + local.minute
    today = DAYS[local.weekday()]
    yesterday = DAYS[(local.weekday() - 1) % 7]
    start, end = _minutes(s["from"]), _minutes(s["to"])

    if start == end:                      # the whole of each listed day
        return today in s["days"]
    if start < end:                       # same-day window, e.g. 08:00-15:00
        return today in s["days"] and start <= t < end
    # Overnight window, e.g. 22:00-06:00. It belongs to the day it starts on.
    return (today in s["days"] and t >= start) or (yesterday in s["days"] and t < end)


def applies_to(s: dict, device_id: str) -> bool:
    return "all" in s["devices"] or device_id in s["devices"]


def active_blocks(rules: dict, device_id: str, now: datetime) -> ActiveBlocks:
    out = ActiveBlocks()
    for s in rules["schedules"]:
        if applies_to(s, device_id) and schedule_active(s, now):
            lst = rules["lists"][s["list"]]
            out.domains.update(lst.get("domains", []))
            out.android_packages.update(lst.get("android_packages", []))
            out.windows_programs.update(lst.get("windows_programs", []))
            out.schedule_ids.append(s["id"])
    return out


def domain_matches(host: str, pattern: str) -> bool:
    """'*.example.com' matches example.com and every subdomain; a plain name matches
    itself and its subdomains too (blocking tiktok.com should block www.tiktok.com)."""
    host = host.lower().rstrip(".")
    base = pattern[2:] if pattern.startswith("*.") else pattern
    return host == base or host.endswith("." + base)


def is_domain_blocked(rules: dict, device_id: str, host: str, now: datetime) -> bool:
    """The always-allowed list wins over every block (Spec 01 §8.3, §10)."""
    if any(domain_matches(host, p) for p in rules["allow"]["domains"]):
        return False
    blocks = active_blocks(rules, device_id, now)
    return any(domain_matches(host, p) for p in blocks.domains)


def is_app_blocked(rules: dict, device_id: str, kind: str, name: str, now: datetime) -> bool:
    if kind == "windows_programs":
        name = name.lower()
    if name in rules["allow"][kind]:
        return False
    return name in getattr(active_blocks(rules, device_id, now), kind)


def block_now_window(now: datetime, hours: float) -> tuple[datetime, datetime]:
    return now, now + timedelta(hours=hours)
