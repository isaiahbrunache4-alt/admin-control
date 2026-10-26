"""The PC's DNS filter, exercised with real UDP packets and a stub upstream resolver."""

import socket
import struct
import threading
import time

import pytest

from fortress_agent.dnsfilter import DnsFilter, nxdomain, question_name


def build_query(name: str, qid: int = 0x1234, flags: int = 0x0100, qtype: int = 1) -> bytes:
    msg = struct.pack("!HHHHHH", qid, flags, 1, 0, 0, 0)
    for label in name.split("."):
        msg += bytes([len(label)]) + label.encode()
    msg += b"\x00" + struct.pack("!HH", qtype, 1)
    return msg


def test_question_name_parsing():
    assert question_name(build_query("WWW.YouTube.com")) == "www.youtube.com"
    assert question_name(build_query("tiktok.com", qtype=28)) == "tiktok.com"
    assert question_name(build_query("a.com", flags=0x8180)) is None    # a response
    assert question_name(build_query("a.com", flags=0x2900)) is None    # an UPDATE, not a query
    assert question_name(b"") is None
    assert question_name(build_query("a.com")[:-2]) is None             # cut short
    compressed = bytearray(build_query("a.com"))
    compressed[12] = 0xC0
    assert question_name(bytes(compressed)) is None


def test_nxdomain_answers_the_same_question():
    q = build_query("tiktok.com", qid=0xBEEF)
    r = nxdomain(q)
    qid, flags, qd, an, ns, ar = struct.unpack_from("!HHHHHH", r, 0)
    assert qid == 0xBEEF
    assert flags & 0x8000 and flags & 0x0080 and flags & 0xF == 3
    assert flags & 0x0100  # RD copied
    assert (qd, an, ns, ar) == (1, 0, 0, 0)
    assert r[12:] == q[12:12 + len(r) - 12]  # the question is unchanged
    assert len(r) == 12 + len("\x06tiktok\x03com\x00") + 4


@pytest.fixture
def upstream():
    """A stub resolver that always answers 1.2.3.4, so forwarding can be observed."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    stop = threading.Event()

    def serve():
        sock.settimeout(0.5)
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            # Echo the query as a response with one A record, 1.2.3.4. Ignore junk.
            if question_name(data) is None:
                continue
            name_end = 12
            while data[name_end] != 0:
                name_end += 1 + data[name_end]
            question = data[12:name_end + 5]
            header = struct.pack("!HHHHHH", struct.unpack_from("!H", data)[0], 0x8180, 1, 1, 0, 0)
            answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + bytes([1, 2, 3, 4])
            sock.sendto(header + question + answer, addr)

    threading.Thread(target=serve, daemon=True).start()
    yield sock.getsockname()[1]
    stop.set()
    sock.close()


@pytest.fixture
def running_filter(upstream):
    blocked = {"tiktok.com", "www.tiktok.com"}
    f = DnsFilter(is_blocked=lambda h: h in blocked, upstreams=["127.0.0.1"], port=0)
    # Point the filter's upstream at the stub (same host, chosen port).
    f._forward = lambda q, _p=upstream: _forward_to(q, _p)
    f.start()
    for _ in range(50):
        if f.bound_port:
            break
        time.sleep(0.02)
    yield f, blocked
    f.stop()


def _forward_to(query: bytes, port: int) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as up:
        up.settimeout(2)
        up.sendto(query, ("127.0.0.1", port))
        return up.recv(65535)


def ask(port: int, name: str) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as c:
        c.settimeout(2)
        c.sendto(build_query(name), ("127.0.0.1", port))
        return c.recv(65535)


def test_blocked_names_get_nxdomain_and_others_are_forwarded(running_filter):
    f, _ = running_filter
    port = f.bound_port

    blocked = ask(port, "www.tiktok.com")
    assert struct.unpack_from("!H", blocked, 2)[0] & 0xF == 3       # NXDOMAIN

    allowed = ask(port, "example.com")
    flags = struct.unpack_from("!H", allowed, 2)[0]
    assert flags & 0xF == 0 and flags & 0x8000                      # a normal answer
    assert allowed.endswith(bytes([1, 2, 3, 4]))                    # from the stub upstream

    assert f.take_counts() == "www.tiktok.com 1"
    assert f.take_counts() is None


def test_filter_survives_junk(running_filter):
    import os

    f, _ = running_filter
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as c:
        for _ in range(200):
            c.sendto(os.urandom(40), ("127.0.0.1", f.bound_port))
    # Still answering afterwards.
    assert struct.unpack_from("!H", ask(f.bound_port, "www.tiktok.com"), 2)[0] & 0xF == 3


def test_filter_survives_a_connection_reset():
    """On Windows, an ICMP "port unreachable" left by a reply to a client that had given up
    surfaces as ConnectionResetError on the next receive. That used to end the serving
    thread, leaving the PC with no working DNS at all."""
    f = DnsFilter(lambda host: True, [], port=0)
    f.start()
    try:
        real = f._sock
        resets = {"left": 2}

        class Flaky:
            def __getattr__(self, name):
                return getattr(real, name)

            def recvfrom(self, n):
                if resets["left"]:
                    resets["left"] -= 1
                    raise ConnectionResetError(10054, "connection reset by peer")
                return real.recvfrom(n)

        f._sock = Flaky()
        time.sleep(0.2)
        assert f.alive
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as c:
            c.settimeout(3)
            c.sendto(build_query("tiktok.com"), ("127.0.0.1", real.getsockname()[1]))
            reply = c.recv(4096)
        assert struct.unpack_from("!H", reply, 2)[0] & 0xF == 3
        assert resets["left"] == 0 and f.alive
    finally:
        f._sock = real
        f.stop()
    assert not f.alive
