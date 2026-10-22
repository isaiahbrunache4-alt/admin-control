import pytest

from fortress_core import rules
from fortress_core.rules import RuleError


@pytest.mark.parametrize("given,expected", [
    ("TikTok.com", "tiktok.com"),
    ("*.Reddit.com.", "*.reddit.com"),
    ("  youtube.com ", "youtube.com"),
])
def test_domains_normalised(given, expected):
    assert rules.normalize_domain(given) == expected


@pytest.mark.parametrize("bad", [
    "https://tiktok.com", "tiktok.com/foryou", "localhost", "-bad.com", "a..b", "*.com", "**.x.com",
])
def test_bad_domains_rejected(bad):
    with pytest.raises(RuleError):
        rules.normalize_domain(bad)


def test_items():
    assert rules.normalize_item("android_packages", "com.zhiliaoapp.musically") == "com.zhiliaoapp.musically"
    assert rules.normalize_item("windows_programs", "Steam.EXE") == "steam.exe"
    for kind, bad in [("android_packages", "tiktok"), ("windows_programs", r"C:\x\steam.exe"),
                      ("windows_programs", "steam"), ("nope", "x")]:
        with pytest.raises(RuleError):
            rules.normalize_item(kind, bad)


def test_starter_allow_list_is_a_copy():
    r = rules.empty_rules()
    r["allow"]["domains"].append("example.com")
    assert "example.com" not in rules.STARTER_ALLOW["domains"]
    assert "github.com" in rules.empty_rules()["allow"]["domains"]


def _rules_with_list():
    r = rules.empty_rules()
    r["lists"]["social"] = {k: [] for k in rules.ITEM_KINDS}
    return r


def test_schedule_validation():
    r = _rules_with_list()
    good = {"kind": "weekly", "list": "social", "devices": ["all"], "days": ["mon"],
            "from": "22:00", "to": "06:00", "tz": "America/New_York"}
    rules.validate_schedule(good, r)
    for change in [{"list": "nope"}, {"devices": []}, {"days": ["monday"]}, {"from": "24:00"},
                   {"to": "6:00"}, {"tz": "Mars/Base"}, {"kind": "daily"}]:
        with pytest.raises(RuleError):
            rules.validate_schedule({**good, **change}, r)


def test_once_schedule_must_end_after_start():
    r = _rules_with_list()
    s = {"kind": "once", "list": "social", "devices": ["all"],
         "start": "2026-10-19T12:00:00Z", "end": "2026-10-19T12:00:00Z"}
    with pytest.raises(RuleError):
        rules.validate_schedule(s, r)
    with pytest.raises(RuleError):
        rules.validate_schedule({**s, "end": "2026-10-19T13:00:00"}, r)   # no zone


def _rules_with_list():
    r = rules.empty_rules()
    r["lists"]["social"] = {k: [] for k in rules.ITEM_KINDS}
    return r


@pytest.mark.parametrize("change", [
    {"from": None}, {"to": 900}, {"tz": None}, {"tz": ["UTC"]}, {"days": "mon"},
    {"devices": [1]}, {"devices": [None]}, {"devices": [""]}, {"list": ["social"]}, {"id": 7},
])
def test_wrong_types_are_rule_errors(change):
    """Anything from JSON must be refused as a RuleError, never crash with TypeError."""
    s = {"id": "s1", "list": "social", "devices": ["all"], "kind": "weekly",
         "days": ["mon"], "from": "09:00", "to": "10:00", "tz": "UTC", **change}
    with pytest.raises(RuleError):
        rules.validate_schedule(s, _rules_with_list())


@pytest.mark.parametrize("start,end", [(5, "2026-01-01T00:00:00Z"), ("2026-01-01T00:00:00Z", None)])
def test_one_off_with_wrong_types(start, end):
    s = {"list": "social", "devices": ["all"], "kind": "once", "start": start, "end": end}
    with pytest.raises(RuleError):
        rules.validate_schedule(s, _rules_with_list())
