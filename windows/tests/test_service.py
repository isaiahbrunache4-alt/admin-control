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
