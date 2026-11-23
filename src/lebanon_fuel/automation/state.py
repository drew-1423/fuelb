"""Local operations journal, atomic reports and a cross-process refresh lock."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import json
import os
import sqlite3
import tempfile


def now():
    return datetime.now(timezone.utc)


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def write_json(path, payload):
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def refresh_lock(root):
    path = Path(root) / "data/operations/refresh.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning("A refresh is already running. No overlapping collection started.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Journal:
    def __init__(self, root):
        path = Path(root) / "data/operations.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, run_id TEXT NOT NULL,
                kind TEXT NOT NULL, subject TEXT NOT NULL, payload_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_kind_subject ON events(kind, subject, id);
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'Operations events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'Operations events are immutable'); END;
        """)

    def close(self):
        self.db.close()

    def append(self, run_id, kind, subject, payload):
        with self.db:
            self.db.execute("INSERT INTO events(recorded_at,run_id,kind,subject,payload_json) VALUES(?,?,?,?,?)",
                            (now().isoformat(), run_id, kind, subject,
                             json.dumps(payload, ensure_ascii=False, allow_nan=False)))

    def latest(self, kind, subject):
        row = self.db.execute("SELECT * FROM events WHERE kind=? AND subject=? ORDER BY id DESC LIMIT 1",
                              (kind, subject)).fetchone()
        return dict(row, payload=json.loads(row["payload_json"])) if row else None
