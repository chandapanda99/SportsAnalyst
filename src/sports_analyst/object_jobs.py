"""Small R2-backed job ledger for serverless Cloud Run execution."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sports_analyst.job_common import QueueFull
from sports_analyst.persistence import PersistenceBackend, normalize_object_key


class ObjectJobStore:
    """Persist requests and progress alongside datasets and reports."""

    durable = True

    def __init__(self, persistence: PersistenceBackend) -> None:
        if not persistence.durable:
            raise ValueError("Object jobs require durable object storage")
        self.persistence = persistence

    @staticmethod
    def _request_key(key: str) -> str:
        return normalize_object_key(f"jobs/{key}/request.json")

    @staticmethod
    def _status_key(key: str) -> str:
        return normalize_object_key(f"jobs/{key}/status.json")

    @staticmethod
    def _event_key(key: str, sequence: int) -> str:
        return normalize_object_key(f"jobs/{key}/events/{sequence:020d}.json")

    def _read_json(self, key: str) -> dict[str, Any] | None:
        payload = self.persistence.read_bytes(key)
        return None if payload is None else json.loads(payload)

    def _write_json(self, key: str, payload: dict[str, Any]) -> None:
        self.persistence.write_bytes(
            key,
            json.dumps(payload, separators=(",", ":"), default=str).encode(),
            "application/json",
        )

    def enqueue(self, key: str, kind: str, payload: dict, max_attempts: int = 2, *, max_active: int = 0) -> None:
        if self.request(key) is not None:
            return
        if max_active:
            active = 0
            for status_key in self.persistence.list_keys("jobs/"):
                if not status_key.endswith("/status.json"):
                    continue
                status = self._read_json(status_key)
                if status and status.get("stage") not in {"complete", "failed"}:
                    active += 1
            if active >= max_active:
                raise QueueFull("The analysis queue is full. Wait for an active job to finish and try again.")
        self._write_json(
            self._request_key(key),
            {
                "job_id": key,
                "kind": kind,
                "payload": payload,
                "max_attempts": max_attempts,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        subject = "data download" if kind == "sync" else "analysis"
        self.emit(key, "queued", f"Waiting to begin your {subject}", 0)

    def request(self, key: str) -> dict[str, Any] | None:
        return self._read_json(self._request_key(key))

    def status(self, key: str) -> dict[str, Any] | None:
        return self._read_json(self._status_key(key))

    def events(self, key: str, after: int = 0) -> list[dict[str, Any]]:
        events = []
        for event_key in self.persistence.list_keys(f"jobs/{key}/events/"):
            try:
                sequence = int(event_key.rsplit("/", 1)[-1].removesuffix(".json"))
            except ValueError:
                continue
            if sequence <= after:
                continue
            event = self._read_json(event_key)
            if event is not None:
                events.append(event)
        return sorted(events, key=lambda event: int(event["sequence"]))[:200]

    def emit(self, key: str, stage: str, message: str, progress: float, **extra: object) -> None:
        sequence = time.time_ns()
        event = {
            **extra,
            "timestamp": datetime.now(UTC).isoformat(),
            "sequence": sequence,
            "stage": stage,
            "message": message,
            "progress": progress,
        }
        self._write_json(self._event_key(key, sequence), event)
        self._write_json(self._status_key(key), event)

    def reserve_dispatch(self, key: str, startup_seconds: int = 900) -> int | None:
        status = self.status(key)
        if status is None or status.get("stage") in {"complete", "failed"}:
            return None
        # Once a worker has begun, Cloud Run or Cloud Tasks owns retries. Only
        # the pre-start stages are eligible for dispatch recovery.
        # An accepted Cloud Run execution or Cloud Task is already durable in
        # Google Cloud. Re-dispatching a provisioning job after an arbitrary
        # browser polling timeout can create a duplicate execution.
        if status.get("stage") == "provisioning":
            return None
        if status.get("stage") not in {"queued", "dispatching"}:
            return None
        now = datetime.now(UTC)
        lease = status.get("dispatch_lease_expires_at")
        if lease:
            try:
                if datetime.fromisoformat(str(lease)) > now:
                    return None
            except ValueError:
                pass
        attempt = int(status.get("dispatch_attempt", 0)) + 1
        self.emit(
            key,
            "dispatching",
            "Requesting analysis capacity",
            max(0.01, float(status.get("progress", 0))),
            dispatch_attempt=attempt,
            dispatch_lease_expires_at=(now + timedelta(seconds=startup_seconds)).isoformat(),
        )
        return attempt

    def complete_dispatch(
        self,
        key: str,
        attempt: int,
        success: bool,
        *,
        retry_seconds: int = 30,
        startup_seconds: int = 900,
    ) -> None:
        now = datetime.now(UTC)
        self.emit(
            key,
            "provisioning" if success else "queued",
            "Worker requested · waiting for capacity" if success else "Worker launch delayed · retrying shortly",
            0.02 if success else 0.01,
            dispatch_attempt=attempt,
            dispatch_lease_expires_at=(now + timedelta(
                seconds=startup_seconds if success else retry_seconds
            )).isoformat(),
        )

    def catalog_version(self) -> None:
        return None

    def delete(self, key: str) -> None:
        self.persistence.delete_prefix(f"jobs/{key}/")
