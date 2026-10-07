"""Local SQLite store for the publishing queue, the engagement inbox and insight snapshots.

Default path: DATA_DIR/personalab.db (DATA_DIR defaults to PROJECT_DIR/.local) (override with PERSONALAB_DB).
Publishing is idempotent: a row is atomically claimed as 'publishing' before any API call, the container id is
saved before media_publish, and rows left in 'publishing' are inspected (not blindly retried) on the next run.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config

SCHEDULE_STATUSES = ("queued", "publishing", "published", "failed", "dry_run")
INBOX_STATUSES = ("pending", "approved", "sent", "escalated")

SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT,
    persona TEXT,
    publish_at_utc TEXT NOT NULL,
    media_type TEXT NOT NULL,
    media_url TEXT,
    caption TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','publishing','published','failed','dry_run')),
    ig_container_id TEXT,
    ig_media_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    claimed_at TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS schedules_due ON schedules(status, publish_at_utc);
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT,
    kind TEXT NOT NULL,             -- comment | dm | pasted
    external_id TEXT,               -- comment id or message id
    target_id TEXT,                 -- media id (comment) or IGSID (dm)
    author TEXT,
    text TEXT,
    draft TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','sent','escalated')),
    received_at TEXT,
    sent_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (kind, external_id)
);
CREATE TABLE IF NOT EXISTS insights_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    dry_run INTEGER NOT NULL DEFAULT 0,
    metrics_json TEXT NOT NULL
);
"""


def now_iso(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat()


def default_path() -> Path:
    override = config.get("PERSONALAB_DB")
    return Path(override) if override else config.data_dir() / "personalab.db"


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def _exec(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, tuple(args))

    def _rows(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        return [dict(r) for r in self._exec(sql, args).fetchall()]

    # ---- schedules --------------------------------------------------------------------------------------
    def add_schedule(self, *, publish_at_utc: str, media_type: str, caption: str | None, media_url: str | None = None,
                     persona: str | None = None, status: str = "queued", thread_id: str | None = None,
                     note: str | None = None) -> int:
        if status not in SCHEDULE_STATUSES:
            raise ValueError(f"bad status {status}")
        cur = self._exec(
            "INSERT INTO schedules (thread_id, persona, publish_at_utc, media_type, media_url, caption, status, last_error, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (thread_id, persona, publish_at_utc, media_type, media_url, caption, status, note, now_iso()),
        )
        return int(cur.lastrowid)

    def get_schedule(self, schedule_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM schedules WHERE id=?", (schedule_id,))
        return rows[0] if rows else None

    def schedules(self, status: str | None = None) -> list[dict]:
        if status:
            return self._rows("SELECT * FROM schedules WHERE status=? ORDER BY publish_at_utc, id", (status,))
        return self._rows("SELECT * FROM schedules ORDER BY publish_at_utc, id")

    def due(self, now: datetime) -> list[dict]:
        return self._rows("SELECT * FROM schedules WHERE status='queued' AND publish_at_utc<=? ORDER BY publish_at_utc, id",
                          (now_iso(now),))

    def set_media_url(self, schedule_id: int, url: str) -> None:
        self._exec("UPDATE schedules SET media_url=?, last_error=NULL WHERE id=?", (url, schedule_id))

    def claim(self, schedule_id: int, now: datetime | None = None) -> bool:
        """Atomically move queued -> publishing. Returns False if another worker already claimed it."""
        cur = self._exec(
            "UPDATE schedules SET status='publishing', attempts=attempts+1, claimed_at=? WHERE id=? AND status='queued'",
            (now_iso(now), schedule_id),
        )
        return cur.rowcount == 1

    def set_container(self, schedule_id: int, container_id: str) -> None:
        self._exec("UPDATE schedules SET ig_container_id=? WHERE id=?", (container_id, schedule_id))

    def mark_published(self, schedule_id: int, media_id: str | None, now: datetime | None = None) -> None:
        self._exec("UPDATE schedules SET status='published', ig_media_id=?, published_at=?, last_error=NULL WHERE id=?",
                   (media_id, now_iso(now), schedule_id))

    def mark_failed(self, schedule_id: int, error: str) -> None:
        self._exec("UPDATE schedules SET status='failed', last_error=? WHERE id=?", (error[:500], schedule_id))

    def requeue(self, schedule_id: int, error: str | None = None) -> None:
        self._exec("UPDATE schedules SET status='queued', claimed_at=NULL, last_error=? WHERE id=?",
                   (error[:500] if error else None, schedule_id))

    def note(self, schedule_id: int, message: str) -> None:
        self._exec("UPDATE schedules SET last_error=? WHERE id=?", (message[:500], schedule_id))

    def stale_publishing(self, older_than: datetime) -> list[dict]:
        return self._rows("SELECT * FROM schedules WHERE status='publishing' AND (claimed_at IS NULL OR claimed_at<=?)",
                          (now_iso(older_than),))

    def published_since(self, since: datetime) -> int:
        row = self._exec("SELECT COUNT(*) FROM schedules WHERE status='published' AND published_at>=?",
                         (now_iso(since),)).fetchone()
        return int(row[0])

    # ---- inbox ------------------------------------------------------------------------------------------
    def upsert_inbox(self, *, kind: str, external_id: str | None, author: str | None, text: str | None,
                     target_id: str | None = None, received_at: str | None = None, thread_id: str | None = None,
                     draft: str | None = None, status: str = "pending") -> int:
        if status not in INBOX_STATUSES:
            raise ValueError(f"bad status {status}")
        if external_id:
            existing = self._rows("SELECT id FROM inbox WHERE kind=? AND external_id=?", (kind, external_id))
            if existing:
                self._exec("UPDATE inbox SET thread_id=COALESCE(?, thread_id) WHERE id=?", (thread_id, existing[0]["id"]))
                return int(existing[0]["id"])
        cur = self._exec(
            "INSERT INTO inbox (thread_id, kind, external_id, target_id, author, text, draft, status, received_at, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (thread_id, kind, external_id, target_id, author, text, draft, status, received_at, now_iso()),
        )
        return int(cur.lastrowid)

    def get_inbox(self, item_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM inbox WHERE id=?", (item_id,))
        return rows[0] if rows else None

    def inbox(self, thread_id: str | None = None, status: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM inbox WHERE 1=1", []
        if thread_id is not None:
            sql += " AND thread_id=?"
            args.append(thread_id)
        if status:
            sql += " AND status=?"
            args.append(status)
        return self._rows(sql + " ORDER BY id", args)

    def set_draft(self, item_id: int, draft: str | None, status: str = "pending") -> None:
        self._exec("UPDATE inbox SET draft=?, status=? WHERE id=? AND status IN ('pending','escalated')",
                   (draft, status, item_id))

    def set_inbox_status(self, item_id: int, status: str, error: str | None = None, sent_at: str | None = None) -> None:
        if status not in INBOX_STATUSES:
            raise ValueError(f"bad status {status}")
        self._exec("UPDATE inbox SET status=?, last_error=?, sent_at=COALESCE(?, sent_at) WHERE id=?",
                   (status, error, sent_at, item_id))

    def has_sent_dm(self, recipient_id: str) -> bool:
        row = self._exec("SELECT 1 FROM inbox WHERE kind='dm' AND target_id=? AND status='sent' LIMIT 1", (recipient_id,)).fetchone()
        return row is not None

    def last_inbound_dm(self, recipient_id: str) -> str | None:
        row = self._exec("SELECT MAX(received_at) FROM inbox WHERE kind='dm' AND target_id=?", (recipient_id,)).fetchone()
        return row[0] if row else None

    # ---- insights ---------------------------------------------------------------------------------------
    def add_snapshot(self, media_id: str, metrics: dict, dry_run: bool = False) -> int:
        cur = self._exec("INSERT INTO insights_snapshots (media_id, captured_at, dry_run, metrics_json) VALUES (?,?,?,?)",
                         (media_id, now_iso(), int(dry_run), json.dumps(metrics, sort_keys=True)))
        return int(cur.lastrowid)

    def snapshots(self, media_id: str | None = None) -> list[dict]:
        rows = self._rows("SELECT * FROM insights_snapshots" + (" WHERE media_id=?" if media_id else "") + " ORDER BY id",
                          (media_id,) if media_id else ())
        for row in rows:
            row["metrics"] = json.loads(row.pop("metrics_json"))
        return rows


_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    """Process-wide store; reopened if PERSONALAB_DB changes (tests point it at a temp file)."""
    global _store
    with _store_lock:
        if _store is None or _store.path != default_path():
            if _store is not None:
                _store.close()
            _store = Store()
        return _store
