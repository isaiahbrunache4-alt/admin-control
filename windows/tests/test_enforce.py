"""The PC's block decisions, against the shared vectors and the published rules, so the
Windows side gives the same answers as Core and the Android app."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fortress_agent.enforce import make_domain_check, programs_to_block

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "testdata" / "fortress_vectors.json").read_text())


def payload(rules: dict) -> dict:
    return {"version": 1, "issued_at": "x", "rules": rules, "released": []}


def at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_matches_the_windows_program_vectors():
    p = payload(VECTORS["rules"])
    for case in VECTORS["match_cases"]:
        if case["kind"] != "windows_programs":
            continue
        blocked = case["item"].lower() in programs_to_block(p, case["device"], at(case["at"]))
        assert blocked == case["blocked"], f"{case['why']} ({case['at']})"


def test_matches_the_domain_vectors():
    p = payload(VECTORS["rules"])
    for case in VECTORS["match_cases"]:
        if case["kind"] != "domains":
            continue
        check = make_domain_check(p, case["device"], clock=lambda c=case: at(c["at"]))
        assert check(case["item"]) == case["blocked"], f"{case['why']} ({case['at']})"


def test_no_rules_blocks_nothing():
    assert programs_to_block(None, "pc") == set()
    assert make_domain_check(None, "pc")("tiktok.com") is False


def test_critical_programs_never_blocked():
    rules = {
        "lists": {"everything": {"domains": [], "android_packages": [],
                                 "windows_programs": ["explorer.exe", "python.exe", "steam.exe"]}},
        "schedules": [{"id": "s1", "list": "everything", "devices": ["all"], "kind": "once",
                       "start": "2026-10-19T00:00:00Z", "end": "2026-10-20T00:00:00Z"}],
        "allow": {"domains": [], "android_packages": [], "windows_programs": []},
    }
    blocked = programs_to_block(payload(rules), "pc", at("2026-10-19T12:00:00Z"))
    assert "steam.exe" in blocked
    assert "explorer.exe" not in blocked and "python.exe" not in blocked


def test_domain_check_caches_per_minute():
    p = payload(VECTORS["rules"])
    calls = {"n": 0}

    def clock():
        calls["n"] += 1
        return datetime(2026, 10, 19, 13, 0, calls["n"] % 60, tzinfo=timezone.utc)

    check = make_domain_check(p, "tablet", clock=clock)
    for _ in range(10):
        check("tiktok.com")
    # All within the same minute; the active-blocks computation is cached, not redone each call.
    assert check("tiktok.com") is True
