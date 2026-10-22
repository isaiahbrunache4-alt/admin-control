import pytest

from fortress_core import crypto


def test_seal_round_trip():
    sealed = crypto.seal(b"secret key bytes", "pw-123456")
    assert crypto.unseal(sealed, "pw-123456") == b"secret key bytes"


def test_wrong_secret_fails_to_unseal():
    sealed = crypto.seal(b"x", "pw-123456")
    with pytest.raises(crypto.InvalidSecret):
        crypto.unseal(sealed, "pw-1234567")


def test_seal_is_salted():
    assert crypto.seal(b"x", "pw")["ct"] != crypto.seal(b"x", "pw")["ct"]


def test_sign_and_verify():
    priv, pub = crypto.new_signing_key()
    sig = crypto.sign(priv, b"data")
    assert crypto.verify(pub, b"data", sig)
    assert not crypto.verify(pub, b"datA", sig)
    _, other_pub = crypto.new_signing_key()
    assert not crypto.verify(other_pub, b"data", sig)


def test_recovery_code_format_and_normalisation():
    code = crypto.new_recovery_code()
    groups = code.split("-")
    assert len(groups) == 6 and all(len(g) == 4 for g in groups)
    assert not set(code) & set("01ILO")
    assert crypto.normalize_recovery_code(code.lower().replace("-", " ")) == code.replace("-", "")


def test_unseal_refuses_unknown_kdf():
    sealed = dict(crypto.seal(b"x", "pw-123456"), kdf="scrypt")
    with pytest.raises(ValueError):
        crypto.unseal(sealed, "pw-123456")
