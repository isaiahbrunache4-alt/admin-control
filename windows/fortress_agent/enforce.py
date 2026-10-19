"""What to block on the PC right now, and the Windows calls that do it.

The decision part (which programs, which domains, when) reuses fortress_core.schedule, so
it matches Core and the phones and is covered by testdata/fortress_vectors.json. The
Windows calls (listing and killing programs, writing browser policy, pointing the
adapters at the filter) are isolated below and imported lazily, so this module loads for
tests on any OS.
"""

from datetime import datetime, timezone

from fortress_core.schedule import active_blocks, is_domain_blocked

# Fortress never blocks the tools needed to unlock or recover (Spec 01 §9, §10), nor the
# programs that would stop blocking from working. These are always allowed on the PC on
# top of the editable allow-list.
ALWAYS_ALLOWED_PROGRAMS = frozenset({
    "explorer.exe", "python.exe", "pythonw.exe", "fortress-agent.exe",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def programs_to_block(payload: dict | None, device_id: str, now: datetime | None = None) -> set[str]:
    """Lower-case program file names to stop from launching right now."""
    if payload is None:
        return set()
    now = now or _now()
    blocked = set(active_blocks(payload["rules"], device_id, now).windows_programs)
    allowed = {p.lower() for p in payload["rules"]["allow"]["windows_programs"]}
    return {p for p in blocked if p not in allowed and p not in ALWAYS_ALLOWED_PROGRAMS}


def make_domain_check(payload: dict | None, device_id: str, clock=_now):
    """A fast is_blocked(host) for the DNS filter, re-reading the schedule each minute."""
    cache: dict[str, object] = {"minute": None, "active": None}

    def is_blocked(host: str) -> bool:
        if payload is None:
            return False
        now = clock()
        minute = int(now.timestamp()) // 60
        if cache["minute"] != minute:
            cache["active"] = active_blocks(payload["rules"], device_id, now)
            cache["minute"] = minute
        # is_domain_blocked honours the allow-list; evaluate against the cached window by
        # reusing the published matching rules directly.
        return is_domain_blocked(payload["rules"], device_id, host, now)

    return is_blocked


def active_schedule_ids(payload: dict | None, device_id: str, now: datetime | None = None) -> list[str]:
    if payload is None:
        return []
    return active_blocks(payload["rules"], device_id, now or _now()).schedule_ids


# --- Windows calls (imported lazily) -----------------------------------------------------

def list_running_programs():  # pragma: no cover - Windows only
    """Lower-case exe name -> list of PIDs, for programs currently running."""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x2
    kernel32 = ctypes.windll.kernel32

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260),
        ]

    out: dict[str, list[int]] = {}
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return out
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = kernel32.Process32First(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.decode("latin-1", "replace").lower()
            out.setdefault(name, []).append(entry.th32ProcessID)
            ok = kernel32.Process32Next(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return out


def terminate(pid: int) -> bool:  # pragma: no cover - Windows only
    import ctypes

    PROCESS_TERMINATE = 0x1
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)
