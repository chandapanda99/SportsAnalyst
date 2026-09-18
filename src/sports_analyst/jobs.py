"""Durable single-machine job queue stored in the user's AppData directory."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sports_analyst.job_common import QueueFull


class LeaseLost(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def user_job_message(kind: str, stage: str) -> str:
    subject = "data download" if kind == "sync" else "analysis"
    return f"Waiting to begin your {subject}" if stage == "queued" else f"Starting your {subject}"


class SQLiteJobStore:
    """Transactional queue for one desktop installation and its sibling worker."""

    durable = True

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT 'Queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    available_at TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    result_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_claimable_idx
                    ON jobs(status, available_at, lease_expires_at);
                CREATE TABLE IF NOT EXISTS job_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    message TEXT NOT NULL,
                    progress REAL NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS job_events_stream_idx
                    ON job_events(job_id, sequence);
                """
            )

    @contextmanager
    def _transaction(self):
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db: sqlite3.Connection, key: str, stage: str, message: str, progress: float, **extra: object) -> dict:
        created_at = _timestamp()
        cursor = db.execute(
            "INSERT INTO job_events(job_id, stage, message, progress, details, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (key, stage, message, progress, json.dumps(extra, separators=(",", ":"), default=str), created_at),
        )
        db.execute(
            "UPDATE jobs SET progress = ?, message = ?, updated_at = ? WHERE job_id = ?",
            (progress, message, created_at, key),
        )
        return {
            **extra,
            "timestamp": created_at,
            "sequence": cursor.lastrowid,
            "stage": stage,
            "message": message,
            "progress": progress,
        }

    def enqueue(self, key: str, kind: str, payload: dict, max_attempts: int = 3, *, max_active: int = 0) -> None:
        now = _timestamp()
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM jobs WHERE job_id = ?", (key,)).fetchone():
                return
            if max_active:
                active = db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
                ).fetchone()[0]
                if active >= max_active:
                    raise QueueFull("The analysis queue is full. Wait for an active job to finish and try again.")
            db.execute(
                """INSERT INTO jobs
                   (job_id, kind, payload, max_attempts, available_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (key, kind, json.dumps(payload, separators=(",", ":"), default=str), max_attempts, now, now, now),
            )
            self._event(
                db,
                key,
                "queued",
                user_job_message(kind, "queued"),
                0,
                job_id=key,
                **({"investigation_id": key} if kind != "sync" else {}),
            )

    def has_active_work(self) -> bool:
        with self._connect() as db:
            return bool(db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()[0])

    def status(self, key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT sequence, stage, message, progress, details, created_at
                   FROM job_events WHERE job_id = ? ORDER BY sequence DESC LIMIT 1""",
                (key,),
            ).fetchone()
            if row is None:
                return None
            return {
                **json.loads(row["details"]),
                "timestamp": row["created_at"],
                "sequence": row["sequence"],
                "stage": row["stage"],
                "message": row["message"],
                "progress": row["progress"],
            }

    def catalog_version(self) -> str | None:
        with self._connect() as db:
            return db.execute("SELECT MAX(updated_at) FROM jobs WHERE status = 'complete'").fetchone()[0]

    def events(self, key: str, after: int = 0) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT sequence, stage, message, progress, details, created_at
                   FROM job_events WHERE job_id = ? AND sequence > ? ORDER BY sequence LIMIT 200""",
                (key, after),
            ).fetchall()
        return [
            {
                **json.loads(row["details"]),
                "timestamp": row["created_at"],
                "sequence": row["sequence"],
                "stage": row["stage"],
                "message": row["message"],
                "progress": row["progress"],
            }
            for row in rows
        ]

    def claim(self, lease_seconds: int) -> dict | None:
        now = _now()
        now_text = _timestamp(now)
        with self._transaction() as db:
            row = db.execute(
                """SELECT * FROM jobs
                   WHERE available_at <= ?
                     AND (status = 'queued' OR (status = 'running' AND lease_expires_at < ?))
                   ORDER BY created_at LIMIT 1""",
                (now_text, now_text),
            ).fetchone()
            if row is None:
                return None
            if row["attempts"] >= row["max_attempts"]:
                db.execute(
                    "UPDATE jobs SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL WHERE job_id = ?",
                    (row["job_id"],),
                )
                self._event(db, row["job_id"], "failed", "Worker stopped repeatedly; please start a new analysis.", 1)
                return None
            token = uuid4().hex
            attempts = row["attempts"] + 1
            db.execute(
                """UPDATE jobs SET status = 'running', lease_owner = ?, attempts = ?, lease_expires_at = ?, updated_at = ?
                   WHERE job_id = ?""",
                (token, attempts, _timestamp(now + timedelta(seconds=lease_seconds)), now_text, row["job_id"]),
            )
            self._event(
                db,
                row["job_id"],
                "starting",
                user_job_message(row["kind"], "starting"),
                0.03,
                worker_attempt=attempts,
            )
            return {
                **dict(row),
                "payload": json.loads(row["payload"]),
                "lease_token": token,
                "attempts": attempts,
            }

    def _require_lease(self, db: sqlite3.Connection, key: str, token: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM jobs WHERE job_id = ? AND lease_owner = ? AND status = 'running'",
            (key, token),
        ).fetchone()
        if row is None or not row["lease_expires_at"] or row["lease_expires_at"] <= _timestamp():
            raise LeaseLost("The job lease belongs to another worker or has expired")
        return row

    @contextmanager
    def publication(self, key: str, token: str, lease_seconds: int | None = None):
        # Validate without holding SQLite's single writer lock while a large
        # Parquet/report file is written. The sibling supervisor keeps the
        # lease alive, and finish() fences the final state transition.
        with self._transaction() as db:
            self._require_lease(db, key, token)
            if lease_seconds is not None:
                db.execute(
                    "UPDATE jobs SET lease_expires_at = ? WHERE job_id = ?",
                    (_timestamp(_now() + timedelta(seconds=lease_seconds)), key),
                )
        yield None

    def heartbeat(self, key: str, token: str, lease_seconds: int) -> bool:
        with self._transaction() as db:
            now = _timestamp()
            result = db.execute(
                """UPDATE jobs SET lease_expires_at = ?, updated_at = ?
                   WHERE job_id = ? AND lease_owner = ? AND status = 'running' AND lease_expires_at > ?""",
                (_timestamp(_now() + timedelta(seconds=lease_seconds)), now, key, token, now),
            )
            return result.rowcount == 1

    def emit_owned(self, key: str, token: str, stage: str, message: str, progress: float, **extra: object) -> None:
        with self._transaction() as db:
            self._require_lease(db, key, token)
            self._event(db, key, stage, message, progress, **extra)

    def finish(self, key: str, token: str, event: dict) -> None:
        with self._transaction() as db:
            self._require_lease(db, key, token)
            self._event(db, key, **event)
            db.execute(
                """UPDATE jobs SET status = 'complete', lease_owner = NULL, lease_expires_at = NULL,
                   result_id = ?, error = NULL, updated_at = ? WHERE job_id = ?""",
                (event.get("investigation_id") or key, _timestamp(), key),
            )

    def fail(self, key: str, token: str, retryable: bool) -> None:
        with self._transaction() as db:
            row = self._require_lease(db, key, token)
            retry = retryable and row["attempts"] < row["max_attempts"]
            db.execute(
                """UPDATE jobs SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                   error = ?, available_at = ?, updated_at = ? WHERE job_id = ?""",
                (
                    "queued" if retry else "failed",
                    None if retry else "Job failed. Check worker logs, then try again.",
                    _timestamp(_now() + timedelta(seconds=min(300, 10 * 2 ** row["attempts"]))),
                    _timestamp(),
                    key,
                ),
            )
            self._event(
                db,
                key,
                "retrying" if retry else "failed",
                "Temporary failure; waiting to retry." if retry else "Job failed. Check worker logs, then try again.",
                0 if retry else 1,
            )

    def release(self, key: str, token: str) -> bool:
        """Immediately recover a child that exited before publishing a terminal state."""
        with self._transaction() as db:
            result = db.execute(
                """UPDATE jobs SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL,
                   available_at = ?, updated_at = ?
                   WHERE job_id = ? AND lease_owner = ? AND status = 'running'""",
                (_timestamp(), _timestamp(), key, token),
            )
            if not result.rowcount:
                return False
            self._event(db, key, "queued", "The interrupted job will resume automatically.", 0)
            return True


class WorkerEvents:
    def __init__(self, jobs: SQLiteJobStore, key: str, token: str):
        self.jobs, self.key, self.token = jobs, key, token
        self.completion: dict[str, Any] | None = None

    def emit(self, key: str, stage: str, message: str, progress: float, **extra: object) -> None:
        if key != self.key:
            raise ValueError("Worker attempted to write another job's progress")
        if stage == "complete":
            self.completion = dict(stage=stage, message=message, progress=progress, **extra)
        else:
            self.jobs.emit_owned(key, self.token, stage, message, progress, **extra)
