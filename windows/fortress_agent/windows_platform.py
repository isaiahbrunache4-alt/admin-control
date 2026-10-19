"""The Windows-only glue: browser policy in the registry, and pointing the network
adapters at the local DNS filter. All lazily imported; never loaded on other OSes.

On Windows Home there is no Group Policy editor, but Chrome, Edge and Firefox read their
policies from the registry directly (Spec 01 §13), so Fortress writes them there.
"""

import subprocess


def set_browser_dns_policy(enabled: bool) -> None:  # pragma: no cover - Windows only
    """Turn browsers' own secure DNS (DNS-over-HTTPS) off, so they cannot look names up
    past the filter. Undone (enabled=False clears the keys) on release."""
    import winreg

    chromium = {"DnsOverHttpsMode": "off"}
    policies = {
        r"SOFTWARE\Policies\Google\Chrome": chromium,
        r"SOFTWARE\Policies\Microsoft\Edge": chromium,
        # Firefox: 0 = off, 5 = disabled.
        r"SOFTWARE\Policies\Mozilla\Firefox\DNSOverHTTPS": {"Enabled": 0, "Locked": 1},
    }
    for path, values in policies.items():
        if not enabled:
            _delete_key(winreg, path)
            continue
        key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE)
        try:
            for name, value in values.items():
                if isinstance(value, int):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        finally:
            winreg.CloseKey(key)


def _delete_key(winreg, path: str) -> None:  # pragma: no cover - Windows only
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, path)
    except OSError:
        pass


def list_adapters() -> list[str]:  # pragma: no cover - Windows only
    """Names of connected IPv4 adapters (for `netsh`)."""
    out = subprocess.run(["netsh", "interface", "show", "interface"],
                         capture_output=True, text=True).stdout
    names = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1].lower() == "connected" and parts[0].lower() == "enabled":
            names.append(line.split(None, 3)[3].strip())
    return names


def current_dns_servers(adapter: str) -> list[str]:  # pragma: no cover - Windows only
    out = subprocess.run(["netsh", "interface", "ipv4", "show", "dnsservers", f'name={adapter}'],
                         capture_output=True, text=True).stdout
    servers = []
    for line in out.splitlines():
        token = line.strip().split()
        for t in token:
            if t.count(".") == 3 and all(p.isdigit() for p in t.split(".")):
                servers.append(t)
    return servers


def point_dns_at_filter(adapter: str) -> None:  # pragma: no cover - Windows only
    subprocess.run(["netsh", "interface", "ipv4", "set", "dnsservers",
                    f'name={adapter}', "static", "127.0.0.1", "primary", "no"], check=False)


def restore_dns_dhcp(adapter: str) -> None:  # pragma: no cover - Windows only
    subprocess.run(["netsh", "interface", "ipv4", "set", "dnsservers",
                    f'name={adapter}', "dhcp"], check=False)


def flush_dns() -> None:  # pragma: no cover - Windows only
    subprocess.run(["ipconfig", "/flushdns"], check=False, capture_output=True)
