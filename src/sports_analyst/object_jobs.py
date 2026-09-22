"""Small R2-backed job ledger for serverless Cloud Run execution."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from sports_analyst.job_common import QueueFull
from sports_analyst.persistence import PersistenceBackend, normalize_object_key


class ObjectJobStore:
    """Persist requests and progress alongside datasets and reports."""

    durable = True

    def __init__(
        self,
        persistence: PersistenceBackend,
        *,
        record_events: bool = True,
        status_min_interval: float = 0.0,
    ) -> None:
        if not persistence.durable:
            raise ValueError("Object jobs require durable object storage")
        self.persistence = persistence
        self.record_events = record_events
        self.status_min_interval = max(0.0, status_min_interval)
        self._last_status: dict[str, tuple[float, float]] = {}
        self._status_lock = Lock()

    @staticmethod
    def _request_key(key: str) -> str:
        return normalize_object_key(f"jobs/{key}/request.json")

    @staticmethod
    def _status_key(key: str) -> str:
        return normalize_object_key(f"jobs/{key}/status.json")

    @staticmethod
    def _event_key(key: str, sequence: int) -> str:
        return normalize_object_key(f"jobs/{key}/events/{sequence:020d}.json")

    @staticmethod
    def _active_key() -> str:
        return "jobs/active.json"

    def _read_json(self, key: str) -> dict[str, Any] | None:
        payload = self.persistence.read_bytes(key)
        return None if payload is None else json.loads(payload)

    def _write_json(self, key: str, payload: dict[str, Any]) -> None:
        self.persistence.write_bytes(
            key,
            json.dumps(payload, separators=(",", ":"), default=str).encode(),
            "application/json",
        )

    def _mutate_active(self, key: str, *, add: bool, limit: int = 0) -> None:
        reader = getattr(self.persistence, "read_versioned_bytes", None)
        conditional_write = getattr(self.persistence, "write_bytes_if_version", None)
        active_key = self._active_key()
        for attempt in range(8):
            if reader is None:
                payload, version = self.persistence.read_bytes(active_key), None
            else:
                payload, version = reader(active_key)
            candidates = set(json.loads(payload).get("jobs", [])) if payload else set()
            # The compact registry stays bounded by the admission limit. Clean
            # interrupted or completed entries with at most a handful of GETs.
            active = {
                candidate
                for candidate in candidates
                if (status := self.status(candidate)) is not None and status.get("stage") not in {"complete", "failed"}
            }
            if add:
                if limit and key not in active and len(active) >= limit:
                    raise QueueFull("The analysis queue is full. Wait for an active job to finish and try again.")
                active.add(key)
            else:
                active.discard(key)
            document = json.dumps({"jobs": sorted(active)}, separators=(",", ":")).encode()
            if conditional_write is None:
                self.persistence.write_bytes(active_key, document, "application/json")
                return
            if conditional_write(active_key, document, version, "application/json"):
                return
            time.sleep(0.025 * (attempt + 1))
        raise RuntimeError("active job admission contention did not settle")

    def enqueue(self, key: str, kind: str, payload: dict, max_attempts: int = 2, *, max_active: int = 0) -> None:
        if self.request(key) is not None:
            return
        self._mutate_active(key, add=True, limit=max_active)
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
        if not self.record_events:
            status = self.status(key)
            return [status] if status is not None and int(status.get("sequence", 0)) > after else []
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
        now = time.monotonic()
        force = stage in {"queued", "dispatching", "provisioning", "retrying", "complete", "failed"}
        with self._status_lock:
            previous_time, previous_progress = self._last_status.get(key, (float("-inf"), -1.0))
            if (
                not self.record_events
                and not force
                and now - previous_time < self.status_min_interval
                and progress < previous_progress + 0.01
            ):
                return
            self._last_status[key] = now, progress
        sequence = time.time_ns()
        event = {
            **extra,
            "timestamp": datetime.now(UTC).isoformat(),
            "sequence": sequence,
            "stage": stage,
            "message": message,
            "progress": progress,
        }
        if self.record_events:
            self._write_json(self._event_key(key, sequence), event)
        self._write_json(self._status_key(key), event)
        if stage in {"complete", "failed"}:
            self._mutate_active(key, add=False)

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
        kind = (self.request(key) or {}).get("kind", "investigation")
        subject = "data download" if kind == "sync" else "analysis"
        self.emit(
            key,
            "dispatching",
            f"Getting your {subject} ready",
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
        # The task may have started before the enqueue API receives the Cloud
        # Tasks acknowledgement. Never replace worker progress with "waiting".
        current = self.status(key)
        if current is None or current.get("stage") not in {"queued", "dispatching"}:
            return
        if int(current.get("dispatch_attempt", 0)) != attempt:
            return
        now = datetime.now(UTC)
        kind = (self.request(key) or {}).get("kind", "investigation")
        subject = "data download" if kind == "sync" else "analysis"
        message = (
            f"Waiting for the {subject} service to start"
            if success
            else f"Your {subject} is taking a little longer to start · trying again shortly"
        )
        self.emit(
            key,
            "provisioning" if success else "queued",
            message,
            0.02 if success else 0.01,
            dispatch_attempt=attempt,
            dispatch_lease_expires_at=(now + timedelta(
                seconds=startup_seconds if success else retry_seconds
            )).isoformat(),
        )

    def catalog_version(self) -> str | None:
        payload = self.persistence.read_bytes("metadata/catalog/version.json")
        return payload.decode() if payload is not None else None

    def delete(self, key: str) -> None:
        self._mutate_active(key, add=False)
        self.persistence.delete_prefix(f"jobs/{key}/")
