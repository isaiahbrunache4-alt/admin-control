"""The PC's website filter (Spec 01 §8.1): a local DNS server on 127.0.0.1.

It answers blocked names with "no such domain" and forwards everything else to the real
upstream resolver, handing the answer back unchanged. The Agent points the PC's network
adapters at 127.0.0.1 (done in the Windows layer), so every lookup passes through here.
It is a local filter, not a remote VPN; web traffic itself never passes through it.

The message parsing is plain bytes and is tested on any OS with real UDP packets.
"""

import socket
import struct
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

MAX_NAME = 253


def question_name(message: bytes) -> str | None:
    """The first question's name, lower case, no trailing dot, if this is a standard query."""
    if len(message) < 12:
        return None
    flags = struct.unpack_from("!H", message, 2)[0]
    if flags & 0x8000:
        return None  # a response
    if (flags >> 11) & 0xF != 0:
        return None  # only standard queries
    qdcount = struct.unpack_from("!H", message, 4)[0]
    if qdcount < 1:
        return None
    labels = []
    i = 12
    total = 0
    while True:
        if i >= len(message):
            return None
        length = message[i]
        if length == 0:
            break
        if length & 0xC0:
            return None  # compression in a question: not from a real client
        if i + 1 + length > len(message):
            return None
        total += length + 1
        if total > MAX_NAME + 1:
            return None
        labels.append(message[i + 1:i + 1 + length].decode("latin-1"))
        i += 1 + length
    if i + 5 > len(message):
        return None  # QTYPE and QCLASS must follow
    return ".".join(labels).lower()


def nxdomain(query: bytes) -> bytes:
    """A 'no such domain' answer to the first question in `query`."""
    i = 12
    while query[i] != 0:
        i += 1 + query[i]
    end = i + 1 + 4  # name terminator + QTYPE + QCLASS
    out = bytearray(query[:end])
    flags = struct.unpack_from("!H", query, 2)[0]
    # QR=1, same opcode, copy RD, RA=1, RCODE=3 (NXDOMAIN).
    answer = 0x8000 | (flags & 0x7900) | 0x0080 | 3
    struct.pack_into("!HHHHH", out, 2, answer, 1, 0, 0, 0)
    return bytes(out)


class DnsFilter:
    """Serves DNS on 127.0.0.1. `is_blocked(host)` decides; it may change at any time."""

    def __init__(self, is_blocked, upstreams: list[str], host: str = "127.0.0.1", port: int = 53):
        self.is_blocked = is_blocked
        self.upstreams = upstreams
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        # Forwarding goes to a pool so one slow upstream never stalls other lookups,
        # above all the fast "blocked -> NXDOMAIN" path.
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="fortress-dns-up")

    @property
    def bound_port(self) -> int:
        return self._sock.getsockname()[1] if self._sock else self.port

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._serve, name="fortress-dns", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._pool.shutdown(wait=False, cancel_futures=True)
        if self._sock:
            self._sock.close()
            self._sock = None

    def take_counts(self) -> str | None:
        """Blocked lookups since the last call, 'tiktok.com 12, youtube.com 3'; None if none."""
        with self._lock:
            counts = self._counts
            self._counts = Counter()
        if not counts:
            return None
        return ", ".join(f"{host} {n}" for host, n in counts.most_common())

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(data, addr)
            except Exception:
                pass  # one bad packet must never stop the filter

    def _handle(self, data: bytes, addr) -> None:
        name = question_name(data)
        if name is not None and self.is_blocked(name):
            with self._lock:
                self._counts[name] += 1
            self._sock.sendto(nxdomain(data), addr)
            return
        self._pool.submit(self._forward_and_reply, data, addr)

    def _forward_and_reply(self, query: bytes, addr) -> None:
        try:
            reply = self._forward(query)
            if reply is not None and self._sock is not None:
                self._sock.sendto(reply, addr)
        except OSError:
            pass

    def _forward(self, query: bytes) -> bytes | None:
        for server in self.upstreams:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as up:
                    up.settimeout(4)
                    up.sendto(query, (server, 53))
                    return up.recv(65535)
            except OSError:
                continue
        return None  # the asker will retry
