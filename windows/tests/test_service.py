"""The enforcement loop, with a stub platform so it runs on any OS. The real Windows
calls (netsh, registry, process kill) are in windows_platform and only run on Windows."""

import socket
import struct
from datetime import datetime, timezone

from fortress_agent.agent import Agent, AgentState
from fortress_agent.service import AgentService, Platform
from fortress_agent.signer import DeviceSigner


class StubPlatform(Platform):
    def __init__(self):
        self.running = {"steam.exe": [101, 102], "explorer.exe": [10]}
        self.killed: list[int] = []
        self.dns_pointed = False
        self.browser_policy = None

    def set_browser_dns_policy(self, enabled):
        self.browser_policy = enabled

    def point_dns_at_filter(self):
        self.dns_pointed = True
        return ["Wi-Fi"]

    def restore_dns(self):
        self.dns_pointed = False

    def list_programs(self):
        return {k: list(v) for k, v in self.running.items()}

    def terminate(self, pid):
        self.killed.append(pid)
        for name, pids in self.running.items():
            if pid in pids:
                pids.remove(pid)
        return True

    def upstreams(self):
        return ["127.0.0.1"]  # not used; no lookups are forwarded in these tests


def make(tmp_path, clock):
    signer = DeviceSigner(tmp_path / "pc.key")
    state = AgentState(tmp_path / "pc.json")
    # Enrol offline by writing a self-consistent signed bundle the agent will accept.
    from fortress_core import bundle, crypto

    priv, pub = crypto.new_signing_key()
    rules = {
        "lists": {"games": {"domains": ["tiktok.com"], "android_packages": [], "windows_programs": ["steam.exe"]}},
        "schedules": [{"id": "s1", "list": "games", "devices": ["pc"], "kind": "once",
                       "start": "2026-10-19T00:00:00Z", "end": "2026-10-20T00:00:00Z"}],
        "allow": {"domains": ["github.com"], "android_packages": [], "windows_programs": []},
    }
    env = bundle.sign_bundle({"version": 5, "issued_at": "2026-10-19T00:00:00Z", "rules": rules, "released": []}, priv, pub)
    state.set(device_id="pc", core_url="http://127.0.0.1:1", core_public_key=crypto.b64e(pub),
              envelope=env, highest_version=5, released=False)
    agent = Agent(state, signer, clock=clock)
    return agent, AgentService(agent, StubPlatform(), clock=clock, dns_port=0)


NOON = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def test_apply_blocks_programs_and_sites(tmp_path):
    agent, svc = make(tmp_path, clock=lambda: NOON)
    try:
        svc.apply()
        plat = svc.platform
        # The filter is up and DNS is pointed at it.
        assert svc.filter is not None and plat.dns_pointed and plat.browser_policy is True
        # steam.exe was running; both PIDs were killed. explorer.exe (critical) was not.
        assert sorted(plat.killed) == [101, 102]
        assert "explorer.exe" not in [k for k in plat.running if not plat.running[k]] or plat.running["explorer.exe"] == [10]
        # The filter blocks the scheduled domain and its subdomains over real UDP…
        assert _nxdomain(svc.filter.bound_port, "www.tiktok.com")
        # …and leaves the allowed domain to be forwarded (checked directly, no upstream here).
        assert svc.filter.is_blocked("github.com") is False
        assert svc.filter.is_blocked("tiktok.com") is True
    finally:
        svc.stop()


def test_release_stands_down(tmp_path):
    agent, svc = make(tmp_path, clock=lambda: NOON)
    try:
        svc.apply()
        assert svc.filter is not None
        agent.state.set(released=True)
        svc.apply()
        assert svc.filter is None
        assert svc.platform.dns_pointed is False and svc.platform.browser_policy is False
        assert any(e["kind"] == "released" for e in agent.state.events)
    finally:
        svc.stop()


def test_newly_started_blocked_program_is_caught(tmp_path):
    agent, svc = make(tmp_path, clock=lambda: NOON)
    try:
        svc.apply()
        svc.platform.killed.clear()
        svc.platform.running["steam.exe"] = [201]   # relaunched
        svc._enforce_programs(agent.current_payload(), "pc")
        assert svc.platform.killed == [201]
    finally:
        svc.stop()


def _nxdomain(port: int, name: str) -> bool:
    msg = struct.pack("!HHHHHH", 1, 0x0100, 1, 0, 0, 0)
    for label in name.split("."):
        msg += bytes([len(label)]) + label.encode()
    msg += b"\x00" + struct.pack("!HH", 1, 1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as c:
        c.settimeout(2)
        c.sendto(msg, ("127.0.0.1", port))
        reply = c.recv(4096)
    return struct.unpack_from("!H", reply, 2)[0] & 0xF == 3


class RouterDnsPlatform(StubPlatform):
    """Like Windows: the network's DNS servers are only read while pointing the adapters
    at the filter, and after a reboot the adapters already say 127.0.0.1."""

    def __init__(self, network_dns):
        super().__init__()
        self.network_dns = network_dns
        self.seen: list[str] = []

    def point_dns_at_filter(self):
        self.seen = list(self.network_dns)
        return super().point_dns_at_filter()

    def upstreams(self):
        return self.seen


def test_filter_forwards_to_the_networks_own_dns(tmp_path):
    from fortress_agent.service import DEFAULT_UPSTREAMS

    agent, svc = make(tmp_path, clock=lambda: NOON)
    svc.platform = RouterDnsPlatform(["192.168.1.1"])
    try:
        svc.apply()
        assert svc.filter.upstreams == ["192.168.1.1"]
    finally:
        svc.stop()

    # After a reboot Windows shows only 127.0.0.1; the remembered servers are used.
    agent2 = Agent(AgentState(tmp_path / "pc.json"), agent.signer, clock=lambda: NOON)
    svc2 = AgentService(agent2, RouterDnsPlatform([]), clock=lambda: NOON, dns_port=0)
    try:
        svc2.apply()
        assert svc2.filter.upstreams == ["192.168.1.1"]
        assert svc2.filter.upstreams != DEFAULT_UPSTREAMS
    finally:
        svc2.stop()


def test_domain_check_matches_core_and_follows_the_clock():
    from fortress_agent.enforce import make_domain_check
    from fortress_core.schedule import is_domain_blocked

    rules = {
        "lists": {"social": {"domains": ["tiktok.com", "*.reddit.com"], "android_packages": [], "windows_programs": []}},
        "schedules": [{"id": "s1", "list": "social", "devices": ["pc"], "kind": "once",
                       "start": "2026-10-19T12:00:00Z", "end": "2026-10-19T13:00:00Z"}],
        "allow": {"domains": ["docs.reddit.com"], "android_packages": [], "windows_programs": []},
    }
    now = {"t": NOON}
    check = make_domain_check({"rules": rules}, "pc", clock=lambda: now["t"])
    hosts = ["tiktok.com", "www.tiktok.com", "reddit.com", "docs.reddit.com", "github.com"]
    for t in (NOON, NOON.replace(hour=13, minute=1)):
        now["t"] = t
        for h in hosts:
            assert check(h) == is_domain_blocked(rules, "pc", h, t), (h, t)


class DriftingPlatform(StubPlatform):
    """Something else on the PC (a network change, another DNS tool) can repoint the
    adapters away from the filter after it started."""

    def __init__(self):
        super().__init__()
        self.points = 0
        self.drifted = False

    def point_dns_at_filter(self):
        self.points += 1
        self.drifted = False
        return super().point_dns_at_filter()

    def dns_drifted(self):
        return self.drifted


def test_dns_is_pointed_back_when_something_changes_it(tmp_path):
    agent, svc = make(tmp_path, clock=lambda: NOON)
    svc.platform = DriftingPlatform()
    try:
        svc.apply()
        assert svc.platform.points == 1
        svc._keep_dns()
        assert svc.platform.points == 1                     # still pointed: left alone
        svc.platform.drifted = True                         # e.g. set to 1.1.1.3
        svc._keep_dns()
        assert svc.platform.points == 2 and not svc.platform.drifted
        assert [e["kind"] for e in agent.state.events].count("dns_reset") == 1
    finally:
        svc.stop()


def test_dns_is_left_alone_once_released(tmp_path):
    agent, svc = make(tmp_path, clock=lambda: NOON)
    svc.platform = DriftingPlatform()
    try:
        svc.apply()
        agent.state.set(released=True)
        svc.apply()                                         # stands down, restores DNS
        svc.platform.drifted = True
        svc._keep_dns()
        assert svc.platform.points == 1
    finally:
        svc.stop()


def test_a_dead_filter_is_restarted(tmp_path):
    agent, svc = make(tmp_path, clock=lambda: NOON)
    try:
        svc.apply()
        old = svc.filter
        old._stop.set()                                     # the serving thread ends
        old._thread.join(timeout=2)
        assert not old.alive
        svc._keep_dns()
        assert svc.filter is not None and svc.filter is not old and svc.filter.alive
        assert _nxdomain(svc.filter.bound_port, "tiktok.com")
        assert any(e["kind"] == "filter_error" for e in agent.state.events)
    finally:
        svc.stop()
