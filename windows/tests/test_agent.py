"""The Windows Agent against a real, running Fortress Core (both Python). This is the
cross-check that the PC side speaks the protocol the same way the Android side does."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fortress_agent.agent import Agent, AgentState
from fortress_agent.client import CoreClient, CoreError, normalize_base_url
from fortress_agent.signer import DeviceSigner

CORE = Path(__file__).resolve().parents[2] / "core"
PASSWORD = "windows agent test password"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _fortress(db: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "fortress_core.cli", "--db", str(db), "--password-stdin", *args],
        cwd=CORE, input=stdin, capture_output=True, text=True, check=False)


@pytest.fixture
def core(tmp_path):
    """A running Core with one device ('pc') and an enrolment code waiting."""
    db = tmp_path / "core.db"
    pw = PASSWORD + "\n"
    assert _fortress(db, "init", stdin=pw).returncode == 0
    _fortress(db, "device", "add", "pc", "windows", "This PC", stdin=pw)
    _fortress(db, "list", "add", "social", stdin=pw)
    _fortress(db, "item", "add", "social", "site", "tiktok.com", stdin=pw)
    _fortress(db, "item", "add", "social", "program", "steam.exe", stdin=pw)
    out = _fortress(db, "device", "enrol", "pc", stdin=pw).stdout
    code = next(w for w in out.replace(":", " ").split() if "-" in w and w.replace("-", "").isalnum())

    agent_port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "fortress_core.cli", "--db", str(db), "serve",
         "--port", str(_free_port()), "--agent-port", str(agent_port)],
        cwd=CORE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{agent_port}"
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", agent_port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    try:
        yield {"url": url, "code": code, "db": db, "pw": pw}
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def make_agent(tmp_path, name="pc"):
    signer = DeviceSigner(tmp_path / f"{name}.key")
    state = AgentState(tmp_path / f"{name}.json")
    return Agent(state, signer)


def test_normalize_base_url():
    assert normalize_base_url("192.168.1.20") == "http://192.168.1.20:47801"
    assert normalize_base_url(" http://10.0.0.5/ ") == "http://10.0.0.5:47801"
    assert normalize_base_url("fortress-pc:9000") == "http://fortress-pc:9000"
    with pytest.raises(ValueError):
        normalize_base_url("http://")


def test_enrol_sync_and_fetch(core, tmp_path):
    agent = make_agent(tmp_path)

    # A wrong code is refused and nothing is pinned.
    with pytest.raises(CoreError) as e:
        agent.enrol(core["url"], "pc", "AAAAA-AAAAA")
    assert e.value.kind == "bad_proof"
    assert not agent.state.enrolled

    agent.enrol(core["url"], "pc", core["code"])
    assert agent.state.enrolled
    held = agent.state.highest_version
    assert held >= 1
    payload = agent.current_payload()
    assert "social" in payload["rules"]["lists"]

    # A check-in uploads events; nothing newer to fetch.
    agent.log("test", "hello from Windows agent")
    changed, err = agent.sync(enforcing=True)
    assert err is None and changed is False
    assert agent.state.events == []

    # Pretend to hold an older version: the agent fetches, verifies and keeps it.
    agent.state.set(highest_version=held - 1)
    changed, err = agent.sync(enforcing=True)
    assert err is None and changed is True
    assert agent.state.highest_version == held

    # The code was single-use.
    other = make_agent(tmp_path, "pc2")
    with pytest.raises(CoreError) as e:
        other.enrol(core["url"], "pc", core["code"])
    assert e.value.kind == "no_enrolment"


def test_fake_core_is_refused(tmp_path):
    """A server that answers but cannot prove the code must not get pinned."""
    import http.server
    import json
    import threading

    from fortress_core import crypto

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.dumps({
                "core_public_key": crypto.b64e(b"\x00" * 32), "key_id": "0" * 16,
                "proof": crypto.b64e(b"\x00" * 32), "bundle": {},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        agent = make_agent(tmp_path)
        with pytest.raises(CoreError) as e:
            agent.enrol(f"http://127.0.0.1:{srv.server_port}", "pc", "MFA4D-52ANU")
        assert e.value.kind == "bad_core_proof"
        assert not agent.state.enrolled
    finally:
        srv.shutdown()


def test_unreachable_core_is_reported(tmp_path):
    agent = make_agent(tmp_path)
    agent.state.set(device_id="pc", core_url="http://127.0.0.1:1", core_public_key="x", highest_version=3)
    changed, err = agent.sync(enforcing=True)
    assert changed is False and "cannot reach" in err
    assert agent.state.highest_version == 3


def test_released_device_stands_down(core, tmp_path):
    agent = make_agent(tmp_path)
    agent.enrol(core["url"], "pc", core["code"])
    _fortress(core["db"], "device", "remove", "pc", stdin=core["pw"])
    changed, err = agent.sync(enforcing=True)
    assert err is None and agent.state.released is True


def test_signer_key_is_stable_and_private(tmp_path):
    s1 = DeviceSigner(tmp_path / "k.key")
    pub1 = s1.public_key_der
    s2 = DeviceSigner(tmp_path / "k.key")        # reloaded
    assert s2.public_key_der == pub1
    # The signature verifies against the public key.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    msg = b"fortress"
    load_der_public_key(pub1).verify(s1.sign(msg), msg, ec.ECDSA(hashes.SHA256()))
    s1.reset()
    assert s1.public_key_der != pub1
