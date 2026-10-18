"""testdata/fortress_vectors.json must match what the reference code produces now."""

import json

from fortress_core import crypto

from .make_vectors import PATH, build, render


def test_vectors_file_is_current():
    assert PATH.read_text(encoding="utf-8") == render(), (
        "testdata/fortress_vectors.json is stale: run `python -m tests.make_vectors` in core/")


def test_vectors_cover_both_answers():
    v = build()
    assert {c["blocked"] for c in v["match_cases"]} == {True, False}
    assert {c["accept"] for c in v["bundle_cases"]} == {True, False}
    assert {c["match"] for c in v["domain_cases"]} == {True, False}


def test_vector_keys_are_marked_as_test_keys():
    v = json.loads(PATH.read_text(encoding="utf-8"))
    assert "TEST key" in v["about"]
    assert crypto.key_id(crypto.b64d(v["core_key"]["public_key"])) == v["core_key"]["key_id"]
