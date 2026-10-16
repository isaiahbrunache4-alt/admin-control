"""Signed rule bundles, and the reference check every Agent performs on them.

Envelope (what travels to an Agent):

    {"format": 1, "key_id": "<16 hex>", "payload": "<base64>", "sig": "<base64>"}

The signature covers the exact payload bytes. An Agent verifies those bytes first and
only then parses them as JSON, so Python and Kotlin never have to agree on how JSON is
re-serialised.
"""

import json

from . import crypto

FORMAT = 1


class BundleRejected(Exception):
    """An Agent must refuse this bundle. The message says why."""


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_bundle(payload: dict, priv_raw: bytes, pub_raw: bytes) -> dict:
    data = canonical(payload)
    return {
        "format": FORMAT,
        "key_id": crypto.key_id(pub_raw),
        "payload": crypto.b64e(data),
        "sig": crypto.b64e(crypto.sign(priv_raw, data)),
    }


class BundleVerifier:
    """What an Agent does with an incoming bundle (Agent contract A2).

    Pinned to Core's public key at enrolment. Accepts only a valid signature and a
    version strictly higher than the one it already holds.
    """

    def __init__(self, pub_raw: bytes, highest_version: int = 0):
        self.pub_raw = pub_raw
        self.highest_version = highest_version

    def accept(self, envelope: dict) -> dict:
        if envelope.get("format") != FORMAT:
            raise BundleRejected(f"unknown bundle format {envelope.get('format')!r}")
        if envelope.get("key_id") != crypto.key_id(self.pub_raw):
            raise BundleRejected("signed by a different Fortress")
        try:
            data = crypto.b64d(envelope["payload"])
            sig = crypto.b64d(envelope["sig"])
        except (KeyError, ValueError):
            raise BundleRejected("malformed envelope") from None
        if not crypto.verify(self.pub_raw, data, sig):
            raise BundleRejected("bad signature")
        payload = json.loads(data)
        if payload["version"] <= self.highest_version:
            raise BundleRejected(
                f"version {payload['version']} is not newer than {self.highest_version}"
            )
        self.highest_version = payload["version"]
        return payload
