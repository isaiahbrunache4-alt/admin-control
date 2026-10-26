"""The running PC-layer lock: enforce the rules, keep the DNS filter current, stop blocked
programs, and check in. Platform calls are guarded so the loop can be exercised off-Windows
with a stub platform; on Windows it uses windows_platform.
"""

import os
import threading
import time
from datetime import datetime, timezone

from . import AGENT_VERSION
from .agent import Agent
from .dnsfilter import DnsFilter
from .enforce import list_running_programs, make_domain_check, programs_to_block, terminate

SYNC_EVERY = 15 * 60
PROGRAM_SCAN_EVERY = 2
DNS_CHECK_EVERY = 30
DEFAULT_UPSTREAMS = ["1.1.1.1", "9.9.9.9"]


class Platform:
    """The Windows-specific actions, behind an interface so the loop is testable."""

    def set_browser_dns_policy(self, enabled: bool) -> None: ...
    def point_dns_at_filter(self) -> list[str]: ...
    def restore_dns(self) -> None: ...
    def dns_drifted(self) -> bool:
        """True if a connected adapter no longer sends lookups to the filter first."""
        return False
    def list_programs(self) -> dict[str, list[int]]:
        return list_running_programs()
    def terminate(self, pid: int) -> bool:
        return terminate(pid)
    def upstreams(self) -> list[str]:
        """The network's own DNS servers, as seen before pointing the adapters at the
        filter; empty if not known."""
        return []


class WindowsPlatform(Platform):  # pragma: no cover - Windows only
    def __init__(self):
        from . import windows_platform as w
        self._w = w
        self._adapters: list[str] = []
        self._saved_upstreams: list[str] = []

    def set_browser_dns_policy(self, enabled: bool) -> None:
        self._w.set_browser_dns_policy(enabled)

    def upstreams(self) -> list[str]:
        return list(self._saved_upstreams)

    def point_dns_at_filter(self) -> list[str]:
        self._adapters = self._w.list_adapters()
        servers = []
        for a in self._adapters:
            servers += [s for s in self._w.current_dns_servers(a) if s != "127.0.0.1"]
        if servers:
            self._saved_upstreams = list(dict.fromkeys(servers))
        for a in self._adapters:
            self._w.point_dns_at_filter(a)
        self._w.flush_dns()
        return self._adapters

    def dns_drifted(self) -> bool:
        return any(self._w.current_dns_servers(a)[:1] != ["127.0.0.1"] for a in self._w.list_adapters())

    def restore_dns(self) -> None:
        for a in self._adapters or self._w.list_adapters():
            self._w.restore_dns_dhcp(a)
        self._w.flush_dns()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentService:
    def __init__(self, agent: Agent, platform: Platform, *, clock=_utcnow, dns_port: int = 53):
        self.agent = agent
        self.platform = platform
        self.clock = clock
        self.dns_port = dns_port
        self.filter: DnsFilter | None = None
        self._stop = threading.Event()
        self._enforcing = False

    # ---- enforcement -----------------------------------------------------------------

    def apply(self) -> None:
        """Make the PC match the current rules. Safe to call repeatedly."""
        state = self.agent.state
        payload = None if state.released else self.agent.current_payload()
        device_id = state.device_id or "pc"

        if state.released:
            self._stand_down()
            return

        self._ensure_filter(payload, device_id)
        self._enforce_programs(payload, device_id)
        try:
            self.platform.set_browser_dns_policy(True)
        except Exception:
            pass
        self._enforcing = True

    def _ensure_filter(self, payload, device_id) -> None:
        check = make_domain_check(payload, device_id, clock=self.clock)
        if self.filter is None:
            self.filter = DnsFilter(check, self._upstreams(), port=self.dns_port)
            try:
                self.filter.start()
                self._adapters = self.platform.point_dns_at_filter()
                # Only now has the platform read the network's own DNS servers.
                self.filter.upstreams = self._upstreams()
                self.agent.log("filter_started", "forwarding to " + ", ".join(self.filter.upstreams))
            except OSError as e:
                self.agent.log("filter_error", str(e))
                self.filter = None
        else:
            self.filter.is_blocked = check

    def _upstreams(self) -> list[str]:
        """Where allowed lookups go. Once the adapters point at 127.0.0.1 (which survives a
        reboot) Windows no longer shows the network's DNS servers, so remember them."""
        found = self.platform.upstreams()
        if found:
            if found != self.agent.state.upstreams:
                self.agent.state.set(upstreams=found)
                self.agent.state.save()
            return found
        return self.agent.state.upstreams or DEFAULT_UPSTREAMS

    def _enforce_programs(self, payload, device_id) -> int:
        want = programs_to_block(payload, device_id, self.clock())
        if not want:
            return 0
        killed = 0
        running = self.platform.list_programs()
        for name in want:
            for pid in running.get(name, []):
                if self.platform.terminate(pid):
                    killed += 1
        if killed:
            self.agent.log("programs_blocked", f"{killed} stopped: {', '.join(sorted(want))}")
        return killed

    def _stand_down(self) -> None:
        if self.filter:
            self.filter.stop()
            self.filter = None
        try:
            self.platform.restore_dns()
            self.platform.set_browser_dns_policy(False)
        except Exception:
            pass
        self.agent.log("released", "website filter off, DNS restored; PC no longer enforced")
        self._enforcing = False

    # ---- the loop --------------------------------------------------------------------

    def sync(self) -> None:
        if self.filter:
            counts = self.filter.take_counts()
            if counts:
                self.agent.log("sites_blocked", counts)
        changed, _ = self.agent.sync(enforcing=self._enforcing)
        if changed or self.agent.state.released:
            self.apply()

    def run(self) -> None:
        """Enforce now, then loop: scan programs often, sync every 15 minutes."""
        self.apply()
        self.sync()
        last_sync = last_dns = time.monotonic()
        while not self._stop.wait(PROGRAM_SCAN_EVERY):
            payload = None if self.agent.state.released else self.agent.current_payload()
            self._enforce_programs(payload, self.agent.state.device_id or "pc")
            if time.monotonic() - last_dns >= DNS_CHECK_EVERY:
                self._keep_dns()
                last_dns = time.monotonic()
            if time.monotonic() - last_sync >= SYNC_EVERY:
                self.sync()
                last_sync = time.monotonic()
            if self.agent.state.released:
                break

    def _keep_dns(self) -> None:
        """A network change or another tool (e.g. one setting 1.1.1.3) can point the adapters
        away from the filter, and then nothing is blocked. Point them back. What they were
        set to becomes the filter's upstream, so that tool's own filtering still applies."""
        if not self.filter or not self._enforcing:
            return
        try:
            if not self.platform.dns_drifted():
                return
            self._adapters = self.platform.point_dns_at_filter()
            self.filter.upstreams = self._upstreams()
            self.agent.log("dns_reset", "adapters pointed back at the filter; forwarding to "
                           + ", ".join(self.filter.upstreams))
        except Exception as e:
            self.agent.log("filter_error", f"DNS check: {e}")

    def stop(self) -> None:
        self._stop.set()
        if self.filter:
            self.filter.stop()
