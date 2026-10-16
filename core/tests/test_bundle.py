import json

import pytest

from fortress_core import bundle, crypto
from fortress_core.bundle import BundleRejected, BundleVerifier


@pytest.fixture
def keys():
    return crypto.new_signing_key()


def _signed(keys, version, **extra):
    priv, pub = keys
    return bundle.sign_bundle({"version": version, **extra}, priv, pub)


def test_accepts_newer_and_rejects_replay(keys):
    v = BundleVerifier(keys[1])
    assert v.accept(_signed(keys, 1))["version"] == 1
    assert v.accept(_signed(keys, 3))["version"] == 3
    for old in (3, 2):
        with pytest.raises(BundleRejected, match="not newer"):
            v.accept(_signed(keys, old))
    assert v.highest_version == 3


def test_rejects_other_fortress(keys):
    other = crypto.new_signing_key()
    with pytest.raises(BundleRejected, match="different Fortress"):
        BundleVerifier(keys[1]).accept(_signed(other, 1))


def test_rejects_forged_key_id(keys):
    other = crypto.new_signing_key()
    env = _signed(other, 1)
    env["key_id"] = crypto.key_id(keys[1])
    with pytest.raises(BundleRejected, match="bad signature"):
        BundleVerifier(keys[1]).accept(env)


def test_rejects_tampered_payload(keys):
    env = _signed(keys, 1, rules={"lists": {}})
    payload = json.loads(crypto.b64d(env["payload"]))
    payload["version"] = 99
    env["payload"] = crypto.b64e(bundle.canonical(payload))
    with pytest.raises(BundleRejected, match="bad signature"):
        BundleVerifier(keys[1]).accept(env)


@pytest.mark.parametrize("mangle", [
    lambda e: e.update(format=2),
    lambda e: e.pop("sig"),
    lambda e: e.update(payload="not base64!"),
])
def test_rejects_malformed(keys, mangle):
    env = _signed(keys, 1)
    mangle(env)
    with pytest.raises(BundleRejected):
        BundleVerifier(keys[1]).accept(env)


def test_rejects_signed_payload_without_version(keys):
    priv, pub = keys
    data = b'{"rules":{}}'
    env = {"format": 1, "key_id": crypto.key_id(pub),
           "payload": crypto.b64e(data), "sig": crypto.b64e(crypto.sign(priv, data))}
    with pytest.raises(BundleRejected, match="no version"):
        BundleVerifier(pub).accept(env)
