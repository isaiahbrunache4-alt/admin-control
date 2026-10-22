"""Reference cases for schedule evaluation. Every Agent (Kotlin, Windows) must give the
same answers for these; see the note in fortress_core/schedule.py."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from fortress_core import rules
from fortress_core.schedule import (
    active_blocks,
    domain_matches,
    is_app_blocked,
    is_domain_blocked,
    schedule_active,
)

NY = ZoneInfo("America/New_York")


def ny(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=NY)


def weekly(days, start, end, tz="America/New_York"):
    return {"kind": "weekly", "days": days, "from": start, "to": end, "tz": tz}


# 2026-10-19 is a Monday.
@pytest.mark.parametrize("when,expected", [
    (ny(2026, 10, 19, 7, 59), False),
    (ny(2026, 10, 19, 8, 0), True),     # start is inclusive
    (ny(2026, 10, 19, 14, 59), True),
    (ny(2026, 10, 19, 15, 0), False),   # end is exclusive
    (ny(2026, 10, 20, 9, 0), False),    # Tuesday is not listed
])
def test_same_day_window(when, expected):
    assert schedule_active(weekly(["mon"], "08:00", "15:00"), when) is expected


@pytest.mark.parametrize("when,expected", [
    (ny(2026, 10, 18, 23, 0), False),   # Sunday night: Sunday not listed
    (ny(2026, 10, 19, 21, 59), False),
    (ny(2026, 10, 19, 22, 0), True),    # Monday night
    (ny(2026, 10, 20, 5, 59), True),    # ...runs into Tuesday morning
    (ny(2026, 10, 20, 6, 0), False),
    (ny(2026, 10, 20, 22, 30), False),  # Tuesday night: Tuesday not listed
])
def test_overnight_window_belongs_to_its_start_day(when, expected):
    assert schedule_active(weekly(["mon"], "22:00", "06:00"), when) is expected


def test_equal_from_and_to_means_whole_day():
    s = weekly(["sat"], "00:00", "00:00")
    assert schedule_active(s, ny(2026, 10, 24, 0, 0))
    assert schedule_active(s, ny(2026, 10, 24, 23, 59))
    assert not schedule_active(s, ny(2026, 10, 25, 0, 0))


def test_window_is_in_the_schedules_own_zone():
    s = weekly(["mon"], "08:00", "15:00")
    # 12:30 UTC on Monday is 08:30 in New York (EDT, UTC-4).
    assert schedule_active(s, datetime(2026, 10, 19, 12, 30, tzinfo=timezone.utc))
    assert not schedule_active(s, datetime(2026, 10, 19, 11, 30, tzinfo=timezone.utc))


def test_dst_change_keeps_local_time():
    s = weekly(["sun", "mon"], "08:00", "09:00")
    # US clocks go back on 2026-11-01. 08:30 local is 12:30 UTC before, 13:30 UTC after.
    assert schedule_active(s, datetime(2026, 10, 26, 12, 30, tzinfo=timezone.utc))
    assert schedule_active(s, datetime(2026, 11, 2, 13, 30, tzinfo=timezone.utc))
    assert not schedule_active(s, datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc))


def test_once():
    s = {"kind": "once", "start": "2026-10-19T12:00:00Z", "end": "2026-10-19T14:00:00Z"}
    utc = timezone.utc
    assert not schedule_active(s, datetime(2026, 10, 19, 11, 59, tzinfo=utc))
    assert schedule_active(s, datetime(2026, 10, 19, 12, 0, tzinfo=utc))
    assert not schedule_active(s, datetime(2026, 10, 19, 14, 0, tzinfo=utc))


@pytest.mark.parametrize("host,pattern,expected", [
    ("tiktok.com", "tiktok.com", True),
    ("www.tiktok.com", "tiktok.com", True),
    ("WWW.TikTok.com.", "tiktok.com", True),
    ("nottiktok.com", "tiktok.com", False),
    ("tiktok.com.evil.net", "tiktok.com", False),
    ("reddit.com", "*.reddit.com", True),
    ("old.reddit.com", "*.reddit.com", True),
])
def test_domain_matching(host, pattern, expected):
    assert domain_matches(host, pattern) is expected


def _rules():
    r = rules.empty_rules()
    r["lists"]["social"] = {
        "domains": ["tiktok.com", "*.reddit.com", "github.com"],
        "android_packages": ["com.zhiliaoapp.musically", "com.shotput.app"],
        "windows_programs": ["steam.exe"],
    }
    r["schedules"] = [
        {"id": "s1", "list": "social", "devices": ["tablet"], **weekly(["mon"], "08:00", "15:00")},
        {"id": "s2", "list": "social", "devices": ["all"], **weekly(["sat"], "00:00", "00:00")},
    ]
    return r


def test_device_targeting():
    monday = ny(2026, 10, 19, 9)
    assert active_blocks(_rules(), "tablet", monday).schedule_ids == ["s1"]
    assert active_blocks(_rules(), "pixel", monday).schedule_ids == []
    assert active_blocks(_rules(), "pixel", ny(2026, 10, 24, 9)).schedule_ids == ["s2"]


def test_blocking_and_always_allowed_wins():
    r, monday = _rules(), ny(2026, 10, 19, 9)
    assert is_domain_blocked(r, "tablet", "m.tiktok.com", monday)
    assert not is_domain_blocked(r, "tablet", "m.tiktok.com", ny(2026, 10, 19, 16))
    assert not is_domain_blocked(r, "tablet", "github.com", monday)          # allowed wins
    assert not is_domain_blocked(r, "tablet", "gist.github.com", monday)
    assert is_app_blocked(r, "tablet", "android_packages", "com.zhiliaoapp.musically", monday)
    assert not is_app_blocked(r, "tablet", "android_packages", "com.shotput.app", monday)
    assert is_app_blocked(r, "tablet", "windows_programs", "Steam.exe", monday)


def test_time_without_zone_is_refused():
    """A naive time would silently use the machine's zone for weekly blocks."""
    s = weekly(["mon"], "09:00", "10:00")
    with pytest.raises(ValueError):
        schedule_active(s, datetime(2026, 10, 19, 9, 30))
