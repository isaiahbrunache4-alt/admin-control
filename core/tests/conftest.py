from datetime import datetime, timedelta, timezone

import pytest

from fortress_core import crypto
from fortress_core.core import Fortress

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def fast_argon2(monkeypatch):
    """Real Argon2id, but cheap, so the suite runs in seconds. Sealed blobs record their
    own cost, so nothing else changes."""
    monkeypatch.setattr(crypto, "ARGON2_TIME_COST", 1)
    monkeypatch.setattr(crypto, "ARGON2_MEMORY_KIB", 8)
    monkeypatch.setattr(crypto, "ARGON2_PARALLELISM", 1)


class Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock(datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc))   # a Monday


@pytest.fixture
def fortress(tmp_path, clock):
    f = Fortress(tmp_path / "fortress.db", clock=clock)
    f.recovery_code = f.setup(PASSWORD)
    yield f
    f.close()
