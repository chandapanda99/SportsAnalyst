"""Durable queue and progress ledger. Each mutation is a short PostgreSQL transaction."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    job_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    kind: Mapped[str] = mapped_column(sa.Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(sa.Text, server_default="queued")
    progress: Mapped[float] = mapped_column(sa.Float, server_default="0")
    message: Mapped[str] = mapped_column(sa.Text, server_default="Queued")
    attempts: Mapped[int] = mapped_column(server_default="0")
    max_attempts: Mapped[int] = mapped_column(server_default="3")
    available_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    lease_owner: Mapped[str | None] = mapped_column(sa.Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    result_id: Mapped[str | None] = mapped_column(sa.Text)
    error: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    __table_args__ = (
        sa.Index("jobs_claimable_idx", "status", "available_at", "lease_expires_at"),
    )


class JobEvent(Base):
    __tablename__ = "job_events"
    sequence: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(sa.ForeignKey("jobs.job_id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(sa.Text)
    message: Mapped[str] = mapped_column(sa.Text)
    progress: Mapped[float] = mapped_column(sa.Float)
    details: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    __table_args__ = (sa.Index("job_events_stream_idx", "job_id", "sequence"),)


def database_engine(url: str) -> sa.Engine:
    parsed = sa.engine.make_url(url)
    if parsed.get_backend_name() not in {"postgres", "postgresql"}:
        raise ValueError("The job database must be PostgreSQL")
    return sa.create_engine(parsed.set(drivername="postgresql+psycopg"), poolclass=NullPool,
                            connect_args={"connect_timeout": 10}, hide_parameters=True)


class LeaseLost(RuntimeError):
    pass


class PostgresJobStore:
    durable = True

    def __init__(self, url: str):
        self.engine = database_engine(url)

    def enqueue(self, key: str, kind: str, payload: dict, max_attempts: int = 3) -> None:
        with self.engine.begin() as db:
            db.execute(sa.insert(Job).values(job_id=key, kind=kind, payload=payload, max_attempts=max_attempts))
            self._event(db, key, "queued", "Queued for an available worker", 0,
                        job_id=key, **({"investigation_id": key} if kind != "sync" else {}))

    @staticmethod
    def _event(db, key: str, stage: str, message: str, progress: float, **extra) -> dict:
        created_at = datetime.now(UTC)
        event = {**extra, "timestamp": created_at.isoformat(), "stage": stage, "message": message, "progress": progress}
        sequence = db.execute(sa.insert(JobEvent).values(
            job_id=key, stage=stage, message=message, progress=progress, details=extra, created_at=created_at
        ).returning(JobEvent.sequence)).scalar_one()
        event["sequence"] = sequence
        db.execute(sa.update(Job).where(Job.job_id == key).values(
            progress=progress, message=message, updated_at=sa.func.now()))
        return event

    def status(self, key: str) -> dict | None:
        with self.engine.connect() as db:
            event = db.execute(sa.select(
                JobEvent.sequence, JobEvent.stage, JobEvent.message, JobEvent.progress,
                JobEvent.details, JobEvent.created_at,
            ).where(JobEvent.job_id == key).order_by(JobEvent.sequence.desc()).limit(1)).mappings().first()
            if event is not None:
                return {**(event["details"] or {}), "timestamp": event["created_at"].isoformat(),
                        "sequence": event["sequence"], "stage": event["stage"],
                        "message": event["message"], "progress": event["progress"]}
            row = db.execute(sa.select(Job.status, Job.message, Job.progress).where(Job.job_id == key)).first()
            return None if row is None else {"stage": row.status, "message": row.message, "progress": row.progress}

    def catalog_version(self) -> datetime | None:
        with self.engine.connect() as db:
            return db.execute(sa.select(sa.func.max(Job.updated_at)).where(Job.status == "complete")).scalar_one()

    def events(self, key: str, after: int = 0) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(sa.select(
                JobEvent.sequence, JobEvent.stage, JobEvent.message, JobEvent.progress,
                JobEvent.details, JobEvent.created_at,
            ).where(
                JobEvent.job_id == key, JobEvent.sequence > after).order_by(JobEvent.sequence).limit(200))
            return [{**(row.details or {}), "timestamp": row.created_at.isoformat(), "sequence": row.sequence,
                     "stage": row.stage, "message": row.message, "progress": row.progress} for row in rows]

    def claim(self, lease_seconds: int) -> dict | None:
        with self.engine.begin() as db:
            eligible = sa.or_(Job.status == "queued", sa.and_(
                Job.status == "running", Job.lease_expires_at < sa.func.now()))
            row = db.execute(sa.select(Job.__table__).where(eligible, Job.available_at <= sa.func.now())
                             .order_by(Job.created_at).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if row is None:
                return None
            if row["attempts"] >= row["max_attempts"]:
                db.execute(sa.update(Job).where(Job.job_id == row["job_id"]).values(status="failed", lease_owner=None))
                self._event(db, row["job_id"], "failed", "Worker stopped repeatedly; please start a new analysis.", 1)
                return None
            token = uuid4().hex
            attempts = row["attempts"] + 1
            db.execute(sa.update(Job).where(Job.job_id == row["job_id"]).values(
                status="running", lease_owner=token, attempts=attempts,
                lease_expires_at=sa.func.now() + timedelta(seconds=lease_seconds)))
            self._event(db, row["job_id"], "starting", f"Worker started attempt {attempts}", 0.03)
            return {**row, "lease_token": token, "attempts": attempts}

    @contextmanager
    def publication(self, key: str, token: str, lease_seconds: int | None = None):
        """Fence progress and artifact publication against a replacement attempt."""
        with self.engine.begin() as db:
            owned = db.execute(sa.select(Job.job_id).where(
                Job.job_id == key, Job.lease_owner == token, Job.status == "running",
                Job.lease_expires_at > sa.func.now()).with_for_update()).first()
            if not owned:
                raise LeaseLost("The job lease belongs to another worker or has expired")
            yield db
            if lease_seconds is not None:
                # Long uploads keep this row locked, so no replacement can
                # claim it. Extend the lease before releasing that lock.
                db.execute(sa.update(Job).where(Job.job_id == key).values(
                    lease_expires_at=sa.func.clock_timestamp() + timedelta(seconds=lease_seconds)))

    def heartbeat(self, key: str, token: str, lease_seconds: int) -> bool:
        with self.engine.begin() as db:
            owned = db.execute(sa.select(Job.job_id).where(
                Job.job_id == key, Job.lease_owner == token, Job.status == "running")
                .with_for_update(skip_locked=True)).first()
            if not owned:
                # A publication may hold the row. Read the committed token
                # without blocking the supervisor; check again next heartbeat.
                return db.execute(sa.select(Job.job_id).where(
                    Job.job_id == key, Job.lease_owner == token, Job.status == "running")).first() is not None
            result = db.execute(sa.update(Job).where(
                Job.job_id == key, Job.lease_owner == token, Job.status == "running",
                Job.lease_expires_at > sa.func.now()).values(
                lease_expires_at=sa.func.now() + timedelta(seconds=lease_seconds)))
            return result.rowcount == 1

    def emit_owned(self, key: str, token: str, stage: str, message: str, progress: float, **extra) -> None:
        with self.publication(key, token) as db:
            self._event(db, key, stage, message, progress, **extra)

    def finish(self, key: str, token: str, event: dict) -> None:
        with self.publication(key, token) as db:
            self._event(db, key, **event)
            db.execute(sa.update(Job).where(Job.job_id == key).values(
                status="complete", lease_owner=None, lease_expires_at=None,
                result_id=event.get("investigation_id") or key, error=None))

    def fail(self, key: str, token: str, retryable: bool) -> None:
        with self.publication(key, token) as db:
            row = db.execute(sa.select(Job.attempts, Job.max_attempts).where(Job.job_id == key)).one()
            retry = retryable and row.attempts < row.max_attempts
            db.execute(sa.update(Job).where(Job.job_id == key).values(
                status="queued" if retry else "failed", lease_owner=None, lease_expires_at=None,
                error=None if retry else "Job failed. Check worker logs, then try again.",
                available_at=sa.func.now() + timedelta(seconds=min(300, 10 * 2 ** row.attempts))))
            self._event(db, key, "retrying" if retry else "failed",
                        "Temporary failure; waiting to retry." if retry else "Job failed. Check worker logs, then try again.",
                        0 if retry else 1)


class WorkerEvents:
    def __init__(self, jobs: PostgresJobStore, key: str, token: str):
        self.jobs, self.key, self.token = jobs, key, token
        self.completion: dict[str, Any] | None = None

    def emit(self, key: str, stage: str, message: str, progress: float, **extra) -> None:
        if key != self.key:
            raise ValueError("Worker attempted to write another job's progress")
        if stage == "complete":
            self.completion = dict(stage=stage, message=message, progress=progress, **extra)
        else:
            self.jobs.emit_owned(key, self.token, stage, message, progress, **extra)
