import subprocess
import sys
from pathlib import Path

from fortress_agent import cli

CORE = Path(__file__).resolve().parents[2] / "core"


def run(argv, capsys):
    code = cli.main(argv)
    return code, capsys.readouterr()


def test_status_before_enrol(tmp_path, capsys):
    code, out = run(["--data-dir", str(tmp_path), "status"], capsys)
    assert code == 0 and "Not enrolled" in out.out


def test_run_without_enrol_refused(tmp_path, capsys):
    code, out = run(["--data-dir", str(tmp_path), "run"], capsys)
    assert code == 2 and "not enrolled" in out.err


def test_enrol_bad_address(tmp_path, capsys):
    code, out = run(["--data-dir", str(tmp_path), "enrol", "http://", "pc", "ABCDE-FGHJK"], capsys)
    assert code == 2 and "not an address" in out.err


def test_enrol_unreachable(tmp_path, capsys):
    code, out = run(["--data-dir", str(tmp_path), "enrol", "127.0.0.1:1", "pc", "ABCDE-FGHJK"], capsys)
    assert code == 2 and "cannot reach" in out.err


def test_enrol_and_status_against_live_core(tmp_path, capsys):
    """End to end: enrol the PC with a real code, then status shows what it holds."""
    import socket
    import time

    db = tmp_path / "core.db"
    pw = "cli test password\n"

    def fortress(*args, **kw):
        return subprocess.run([sys.executable, "-m", "fortress_core.cli", "--db", str(db), "--password-stdin", *args],
                              cwd=CORE, input=kw.get("stdin", ""), capture_output=True, text=True)

    assert fortress("init", stdin=pw).returncode == 0
    fortress("device", "add", "pc", "windows", "This PC", stdin=pw)
    fortress("list", "add", "games", stdin=pw)
    fortress("item", "add", "games", "program", "steam.exe", stdin=pw)
    fortress("block-now", "games", "2", "--devices", "pc", stdin=pw)
    out = fortress("device", "enrol", "pc", stdin=pw).stdout
    code = next(w for w in out.replace(":", " ").split() if "-" in w and w.replace("-", "").isalnum())

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        agent_port = s.getsockname()[1]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        console_port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "fortress_core.cli", "--db", str(db), "serve",
                             "--port", str(console_port), "--agent-port", str(agent_port)],
                            cwd=CORE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", agent_port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        rc, res = run(["--data-dir", str(tmp_path), "enrol", f"127.0.0.1:{agent_port}", "pc", code], capsys)
        assert rc == 0 and "Enrolled as pc" in res.out
        rc, res = run(["--data-dir", str(tmp_path), "status"], capsys)
        assert rc == 0 and "Device:        pc" in res.out and "steam.exe" in res.out
    finally:
        proc.terminate()
        proc.wait(timeout=5)
