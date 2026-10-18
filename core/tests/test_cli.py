import io
import json
import re
import time

import pytest

from fortress_core import cli

PW = "correct horse battery"


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    db = tmp_path / "f.db"

    def run(*argv, stdin=""):
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        code = cli.main(["--db", str(db), "--password-stdin", *argv])
        out = capsys.readouterr()
        return code, out.out, out.err
    return run


def test_cli_flow(run, tmp_path):
    code, out, _ = run("status")
    assert code == 2

    code, out, _ = run("init", stdin=PW + "\n")
    assert code == 0
    recovery = re.search(r"([A-Z2-9]{4}(?:-[A-Z2-9]{4}){5})", out).group(1)

    assert run("list", "add", "social", stdin=PW + "\n")[0] == 0
    code, out, _ = run("item", "add", "social", "site", "tiktok.com", "*.reddit.com", stdin=PW + "\n")
    assert code == 0 and "version 3" in out
    code, out, _ = run("device", "add", "tablet", "android", "Idea Tab", stdin=PW + "\n")
    assert code == 0 and "unchanged" in out              # devices alone don't need a new bundle
    code, out, _ = run("schedule", "add", "social", "--devices", "tablet", "--days", "mon",
                       "--from", "08:00", "--to", "15:00", "--tz", "America/New_York",
                       stdin=PW + "\n")
    assert code == 0 and "s1" in out

    # 2026-10-19 13:00 UTC is Monday 09:00 in New York.
    code, out, _ = run("check", "tablet", "site", "www.tiktok.com", "--at", "2026-10-19T13:00:00Z")
    assert code == 3 and "BLOCKED" in out
    code, out, _ = run("check", "tablet", "site", "github.com", "--at", "2026-10-19T13:00:00Z")
    assert code == 0 and "allowed" in out

    # A bad item in a batch changes nothing.
    code, _, err = run("item", "add", "social", "site", "youtube.com", "http://x.com", stdin=PW + "\n")
    assert code == 2 and "URL" in err
    _, out, _ = run("show")
    assert "youtube.com" not in out

    # Wrong password: refused, nothing published.
    code, _, err = run("list", "add", "games", stdin="wrong password\n")
    assert code == 2 and "wrong password" in err

    out_file = tmp_path / "bundle.json"
    assert run("bundle", "--out", str(out_file))[0] == 0
    code, out, _ = run("verify", str(out_file))
    assert code == 0 and "version 4" in out
    code, _, err = run("verify", str(out_file), "--newer-than", "4")
    assert code == 2 and "not newer" in err

    time.sleep(1.1)                                      # the 1 s delay after one wrong attempt
    assert run("recover", stdin=recovery.lower() + "\nanother password\n")[0] == 0
    assert run("list", "add", "games", stdin="another password\n")[0] == 0

    _, out, _ = run("activity")
    assert "wrong_password" in out and "password_reset" in out
    pub = run("pubkey")[1].strip()
    env = json.loads(out_file.read_text())
    assert run("verify", str(out_file), "--pubkey", pub)[0] == 0
    assert env["format"] == 1


def test_fortress_db_env_and_default(tmp_path, monkeypatch):
    monkeypatch.setenv("FORTRESS_DB", str(tmp_path / "x" / "f.db"))
    assert cli.default_db() == tmp_path / "x" / "f.db"
    monkeypatch.delenv("FORTRESS_DB")
    monkeypatch.setenv("LOCALAPPDATA", "/users/someone/AppData/Local")
    assert cli.default_db(windows=True).as_posix() == "/users/someone/AppData/Local/Fortress/fortress.db"
    assert cli.default_db(windows=False).name == "fortress.db"


def test_unopenable_database_is_a_clear_error(tmp_path, capsys):
    # A directory where the database file should be: SQLite cannot open it.
    code = cli.main(["--db", str(tmp_path), "status"])
    err = capsys.readouterr().err
    assert code == 2
    assert "cannot open the database" in err and "FORTRESS_DB" in err
    assert "Traceback" not in err
