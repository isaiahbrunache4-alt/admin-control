"""SQLite storage for Fortress Core.

Settings are small JSON values in a key/value table. The draft rules are one JSON
document. Every published bundle is kept, so the Activity screen can show history and
an Agent can always fetch the latest.
"""

import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bundles (
    version   INTEGER PRIMARY KEY,
    issued_at TEXT NOT NULL,
    envelope  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    platform  TEXT NOT NULL,
    added_at  TEXT NOT NULL,
    last_seen TEXT,
    released  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS activity (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    kind   TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # The API serialises every request behind one lock, so sharing across threads is safe.
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        if self.get("schema_version") is None:
            self.set("schema_version", SCHEMA_VERSION)

    def close(self) -> None:
        self.db.close()

    # settings
    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def set(self, key: str, value) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    # bundles
    def add_bundle(self, version: int, issued_at: str, envelope: dict) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO bundles(version, issued_at, envelope) VALUES(?, ?, ?)",
                (version, issued_at, json.dumps(envelope)),
            )

    def latest_bundle(self) -> dict | None:
        row = self.db.execute(
            "SELECT envelope FROM bundles ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return None if row is None else json.loads(row["envelope"])

    # devices
    def add_device(self, device_id: str, name: str, platform: str, added_at: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO devices(id, name, platform, added_at) VALUES(?, ?, ?, ?)",
                (device_id, name, platform, added_at),
            )

    def devices(self, include_released: bool = False) -> list[dict]:
        sql = "SELECT * FROM devices"
        if not include_released:
            sql += " WHERE released = 0"
        return [dict(r) for r in self.db.execute(sql + " ORDER BY added_at")]

    def release_device(self, device_id: str) -> bool:
        with self.db:
            cur = self.db.execute(
                "UPDATE devices SET released = 1 WHERE id = ? AND released = 0", (device_id,)
            )
        return cur.rowcount == 1

    def touch_device(self, device_id: str, seen_at: str) -> bool:
        with self.db:
            cur = self.db.execute(
                "UPDATE devices SET last_seen = ? WHERE id = ? AND released = 0",
                (seen_at, device_id),
            )
        return cur.rowcount == 1

    # activity
    def log(self, at: str, kind: str, detail: str = "") -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO activity(at, kind, detail) VALUES(?, ?, ?)", (at, kind, detail)
            )

    def activity(self, limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            "SELECT at, kind, detail FROM activity ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]
