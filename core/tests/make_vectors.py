"""Builds testdata/fortress_vectors.json: the cases every Agent's own tests must pass.

The answers come from the Python reference code, so an Agent that passes them agrees
with Core on signatures, versions, schedules, matching and the Agent protocol.
Everything is deterministic; test_vectors.py fails if the file is out of date.

    python -m tests.make_vectors      (from core/)
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from fortress_core import agents, bundle, crypto, rules
from fortress_core.bundle import BundleRejected, BundleVerifier
from fortress_core.schedule import domain_matches, is_app_blocked, is_domain_blocked

PATH = Path(__file__).resolve().parents[2] / "testdata" / "fortress_vectors.json"


def _ed25519(label: str) -> tuple[bytes, bytes]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(label.encode()).digest())
    return (priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()),
            priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


RULES = {
    "lists": {
        "social": {
            "domains": ["*.reddit.com", "tiktok.com"],
            "android_packages": ["com.shotput.app", "com.zhiliaoapp.musically"],
            "windows_programs": [],
        },
        "games": {
            "domains": [],
            "android_packages": ["com.supercell.clashroyale"],
            "windows_programs": ["steam.exe"],
        },
        "video": {"domains": ["github.com", "youtube.com"], "android_packages": [], "windows_programs": []},
    },
    "schedules": [
        {"id": "s1", "list": "social", "devices": ["tablet"], "kind": "weekly",
         "days": ["mon", "tue", "wed", "thu", "fri"], "from": "08:00", "to": "15:00", "tz": "America/New_York"},
        {"id": "s2", "list": "games", "devices": ["all"], "kind": "weekly",
         "days": ["sun", "mon", "tue", "wed", "thu"], "from": "22:00", "to": "06:00", "tz": "America/New_York"},
        {"id": "s3", "list": "video", "devices": ["pixel", "tablet"], "kind": "once",
         "start": "2026-10-24T14:00:00Z", "end": "2026-10-24T16:00:00Z"},
        {"id": "s4", "list": "video", "devices": ["pc"], "kind": "weekly",
         "days": ["sat"], "from": "00:00", "to": "00:00", "tz": "Europe/London"},
    ],
    "allow": {
        "domains": ["github.com", "pypi.org"],
        "android_packages": ["com.shotput.app"],
        "windows_programs": ["code.exe"],
    },
}

# (device, UTC time, kind, item, why). The expected answer is computed, not typed.
CASES = [
    ("tablet", "2026-10-19T12:00:00Z", "domains", "tiktok.com", "Mon 08:00 New York: start is inclusive"),
    ("tablet", "2026-10-19T11:59:00Z", "domains", "tiktok.com", "Mon 07:59 New York: before the window"),
    ("tablet", "2026-10-19T18:59:00Z", "domains", "www.tiktok.com", "Mon 14:59: subdomain of a plain name"),
    ("tablet", "2026-10-19T19:00:00Z", "domains", "tiktok.com", "Mon 15:00: end is exclusive"),
    ("tablet", "2026-10-24T13:00:00Z", "domains", "tiktok.com", "Saturday is not listed"),
    ("pixel", "2026-10-19T13:00:00Z", "domains", "tiktok.com", "s1 targets the tablet only"),
    ("tablet", "2026-10-19T13:00:00Z", "domains", "reddit.com", "*.reddit.com matches the bare name"),
    ("tablet", "2026-10-19T13:00:00Z", "domains", "old.reddit.com", "*.reddit.com matches subdomains"),
    ("tablet", "2026-10-19T13:00:00Z", "domains", "notreddit.com", "suffix without a dot is not a match"),
    ("tablet", "2026-10-19T13:00:00Z", "domains", "TikTok.COM.", "case and trailing dot are ignored"),
    ("tablet", "2026-10-19T13:00:00Z", "android_packages", "com.zhiliaoapp.musically", "app in an active list"),
    ("tablet", "2026-10-19T13:00:00Z", "android_packages", "com.shotput.app", "always-allowed beats a block"),
    ("tablet", "2026-10-19T13:00:00Z", "android_packages", "com.zhiliaoapp.musically.lite", "packages match exactly"),
    ("pixel", "2026-10-20T02:30:00Z", "android_packages", "com.supercell.clashroyale", "Mon 22:30 New York: overnight starts"),
    ("pixel", "2026-10-20T09:59:00Z", "android_packages", "com.supercell.clashroyale", "Tue 05:59: overnight runs into next day"),
    ("pixel", "2026-10-20T10:00:00Z", "android_packages", "com.supercell.clashroyale", "Tue 06:00: overnight ends"),
    ("pixel", "2026-10-24T02:30:00Z", "android_packages", "com.supercell.clashroyale", "Fri 22:30: Friday night not listed"),
    ("pixel", "2026-10-24T09:00:00Z", "android_packages", "com.supercell.clashroyale", "Sat 05:00: part of Friday night, which is not listed"),
    ("pixel", "2026-10-25T09:00:00Z", "android_packages", "com.supercell.clashroyale", "Sun 05:00: Saturday night not listed"),
    ("pixel", "2026-10-26T09:00:00Z", "android_packages", "com.supercell.clashroyale", "Mon 05:00: Sunday night listed"),
    ("pixel", "2026-11-02T10:30:00Z", "android_packages", "com.supercell.clashroyale", "Mon 05:30 EST, after the DST change"),
    ("pixel", "2026-11-02T11:30:00Z", "android_packages", "com.supercell.clashroyale", "Mon 06:30 EST: ended"),
    ("pc", "2026-10-20T03:00:00Z", "windows_programs", "Steam.EXE", "programs compare case-insensitively; s2 is 'all'"),
    ("pc", "2026-10-20T03:00:00Z", "windows_programs", "code.exe", "not in a list"),
    ("pixel", "2026-10-24T14:00:00Z", "domains", "youtube.com", "one-off block: start inclusive"),
    ("pixel", "2026-10-24T15:59:59Z", "domains", "m.youtube.com", "one-off block: still on"),
    ("pixel", "2026-10-24T16:00:00Z", "domains", "youtube.com", "one-off block: end exclusive"),
    ("pc", "2026-10-24T14:30:00Z", "domains", "youtube.com", "s3 is not for the PC, but s4 (all Saturday, London) is"),
    ("pc", "2026-10-23T23:30:00Z", "domains", "youtube.com", "Sat 00:30 London (BST): all-day starts at midnight"),
    ("pc", "2026-10-24T22:59:00Z", "domains", "youtube.com", "Sat 23:59 London"),
    ("pc", "2026-10-24T23:00:00Z", "domains", "youtube.com", "Sun 00:00 London: over"),
    ("pixel", "2026-10-24T15:00:00Z", "domains", "github.com", "allowed domain in an active list stays allowed"),
    ("pixel", "2026-10-24T15:00:00Z", "domains", "gist.github.com", "allowed domains cover subdomains"),
    ("laptop", "2026-10-20T03:00:00Z", "windows_programs", "steam.exe", "'all' covers devices not named anywhere"),
]

DOMAIN_CASES = [
    ("tiktok.com", "tiktok.com"), ("www.tiktok.com", "tiktok.com"), ("WWW.TikTok.com.", "tiktok.com"),
    ("nottiktok.com", "tiktok.com"), ("tiktok.com.evil.net", "tiktok.com"), ("reddit.com", "*.reddit.com"),
    ("a.b.reddit.com", "*.reddit.com"), ("com", "tiktok.com"),
]


def _bundle_cases(core_priv, core_pub, other_priv, other_pub):
    def sign(version, priv=core_priv, pub=core_pub, **extra):
        payload = {"version": version, "issued_at": "2026-10-19T12:00:00Z", "rules": RULES,
                   "released": [], **extra}
        return bundle.sign_bundle(payload, priv, pub)

    v3 = sign(3)
    tampered = dict(v3)
    tampered["payload"] = crypto.b64e(bundle.canonical(
        {**json.loads(crypto.b64d(v3["payload"])), "rules": rules.empty_rules()}))
    forged_id = dict(sign(4, other_priv, other_pub))
    forged_id["key_id"] = crypto.key_id(core_pub)
    no_version_data = b'{"rules":{}}'
    cases = [
        ("valid", v3, 0),
        ("valid, newer than held", v3, 2),
        ("same version again (replay)", v3, 3),
        ("older version (replay of laxer rules)", sign(2), 3),
        ("released list is signed too", sign(5, released=["tablet"]), 3),
        ("payload changed after signing", tampered, 0),
        ("signed by another Fortress", sign(4, other_priv, other_pub), 0),
        ("another key claiming our key id", forged_id, 0),
        ("unknown format", {**v3, "format": 2}, 0),
        ("payload is not base64", {**v3, "payload": "not base64!"}, 0),
        ("signature missing", {k: v for k, v in v3.items() if k != "sig"}, 0),
        ("signed payload without a version", {
            "format": 1, "key_id": crypto.key_id(core_pub), "payload": crypto.b64e(no_version_data),
            "sig": crypto.b64e(crypto.sign(core_priv, no_version_data))}, 0),
    ]
    out = []
    for name, env, held in cases:
        try:
            p = BundleVerifier(core_pub, held).accept(env)
            result = {"accept": True, "version": p["version"]}
        except BundleRejected:
            result = {"accept": False}
        out.append({"name": name, "highest_held": held, "envelope": env, **result})
    return out


def build() -> dict:
    core_priv, core_pub = _ed25519("fortress test vectors: core key")
    other_priv, other_pub = _ed25519("fortress test vectors: some other fortress")

    match = []
    for device, at, kind, item, why in CASES:
        now = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if kind == "domains":
            blocked = is_domain_blocked(RULES, device, item, now)
        else:
            blocked = is_app_blocked(RULES, device, kind, item, now)
        match.append({"device": device, "at": at, "kind": kind, "item": item, "blocked": blocked, "why": why})

    # Agent protocol (docs/agent_protocol.md)
    device_key = ec.derive_private_key(
        int.from_bytes(hashlib.sha256(b"fortress test vectors: device key").digest(), "big") % (2**255),
        ec.SECP256R1())
    device_pub = crypto.b64e(device_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo))
    code, device_id = "MFA4D-52ANU", "tablet"
    nonce = crypto.b64e(hashlib.sha256(b"fortress test vectors: nonce").digest()[:16])
    k = agents.enrol_key(code)
    core_pub_b64 = crypto.b64e(core_pub)

    body = b'{"version":3,"agent_version":"0.1.0","enforcing":true,"events":[]}'
    req_nonce = crypto.b64e(hashlib.sha256(b"fortress test vectors: request nonce").digest()[:16])
    msg = agents.request_message("POST", "/agent/v1/checkin", device_id, "1792411200", req_nonce, body)
    sig = device_key.sign(msg, ec.ECDSA(hashes.SHA256(), deterministic_signing=True))
    assert agents.verify_device_signature(device_pub, msg, crypto.b64e(sig))

    return {
        "about": "Fortress Agent test vectors. Generated by core/tests/make_vectors.py from the "
                 "Python reference code; do not edit by hand. Every key here is a TEST key, "
                 "published on purpose; never use one for a real Fortress.",
        "format": 1,
        "core_key": {"public_key": core_pub_b64, "key_id": crypto.key_id(core_pub)},
        "bundle_cases": _bundle_cases(core_priv, core_pub, other_priv, other_pub),
        "rules": RULES,
        "match_cases": match,
        "domain_cases": [{"host": h, "pattern": p, "match": domain_matches(h, p)} for h, p in DOMAIN_CASES],
        "enrolment": {
            "code": code,
            "normalized_code": crypto.normalize_recovery_code(code),
            "key_hex": k.hex(),
            "device_id": device_id,
            "public_key": device_pub,
            "nonce": nonce,
            "agent_proof": agents.agent_proof(k, device_id, device_pub, nonce),
            "core_public_key": core_pub_b64,
            "core_proof": agents.core_proof(k, device_id, device_pub, nonce, core_pub_b64),
        },
        "signed_request": {
            "method": "POST",
            "path": "/agent/v1/checkin",
            "device_id": device_id,
            "time": "1792411200",
            "nonce": req_nonce,
            "body": body.decode(),
            "message": msg.decode(),
            "device_public_key": device_pub,
            "device_private_key_pkcs8": crypto.b64e(device_key.private_bytes(
                Encoding.DER, PrivateFormat.PKCS8, NoEncryption())),
            "signature": crypto.b64e(sig),
        },
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(render(), encoding="utf-8")
    print(f"wrote {PATH}")
