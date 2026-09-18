"""Major desktop SQLite and cloud object-job workflows."""
import asyncio
import json
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from sports_analyst.api import _event_stream, create_app
from sports_analyst.config import Settings
from sports_analyst.jobs import LeaseLost, SQLiteJobStore
from sports_analyst.models import AnalysisRequest, AnalysisScope
from sports_analyst.object_jobs import ObjectJobStore
from sports_analyst.service import AnalystApplication
from sports_analyst.worker import execute_job


class MemoryPersistence:
    durable = True

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))

    def read_bytes(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def write_bytes(self, key: str, payload: bytes, content_type: str = "application/octet-stream") -> None:
        del content_type
        self.objects[key] = payload

    def download_file(self, key: str, destination: Path) -> bool:
        payload = self.objects.get(key)
        if payload is None:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return True

    def upload_file(self, key: str, source: Path) -> None:
        self.objects[key] = source.read_bytes()

    def delete_prefix(self, prefix: str) -> None:
        for key in [key for key in self.objects if key.startswith(prefix)]:
            del self.objects[key]


def test_object_job_ledger_preserves_requests_progress_and_dispatch_recovery():
    persistence = MemoryPersistence()
    store = ObjectJobStore(persistence)
    store.enqueue("sync-one", "sync", {"sport": "nba", "seasons": [2025]}, max_active=1)
    assert store.request("sync-one")["payload"]["sport"] == "nba"
    attempt = store.reserve_dispatch("sync-one", startup_seconds=900)
    assert attempt == 1 and store.reserve_dispatch("sync-one", startup_seconds=900) is None
    store.complete_dispatch("sync-one", attempt, True, startup_seconds=900)
    assert store.reserve_dispatch("sync-one", startup_seconds=0) is None
    store.emit("sync-one", "downloading", "Downloading Play By Play", 0.4, dataset="play_by_play")
    status = store.status("sync-one")
    assert status["stage"] == "downloading" and status["dataset"] == "play_by_play"
    events = store.events("sync-one")
    assert [event["stage"] for event in events] == ["queued", "dispatching", "provisioning", "downloading"]
    assert json.loads(persistence.objects["jobs/sync-one/request.json"])["kind"] == "sync"


def test_object_cloud_dispatch_routes_syncs_and_analyses_separately(tmp_path, monkeypatch):
    from sports_analyst import cloud_dispatch

    settings = Settings(_env_file=None, data_dir=tmp_path).model_copy(update={"job_backend": "object"})
    sync = MagicMock()
    analysis = MagicMock()
    monkeypatch.setattr(cloud_dispatch, "launch_sync", sync)
    monkeypatch.setattr(cloud_dispatch, "launch_analysis", analysis)

    cloud_dispatch.launch(settings, "sync-job", "sync")
    cloud_dispatch.launch(settings, "analysis-job", "investigation")

    sync.assert_called_once_with(settings, "sync-job")
    analysis.assert_called_once_with(settings, "analysis-job")


def test_dispatch_recovery_and_queue_admission(tmp_path, monkeypatch):
    from sports_analyst import cloud_dispatch
    from sports_analyst.jobs import QueueFull

    settings = Settings(_env_file=None, data_dir=tmp_path)
    settings = settings.model_copy(update={"job_dispatch_backend": "cloud_run", "max_active_jobs": 3,
                                           "job_progress_transport": "poll"})
    application = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path))
    application.settings = settings
    queue = application.jobs = MagicMock()
    queue.reserve_dispatch.side_effect = [1, None, 2]
    queue.status.return_value = {"stage": "queued", "progress": 0, "message": "Queued"}
    launch = MagicMock(side_effect=[TimeoutError("private"), None])
    monkeypatch.setattr(cloud_dispatch, "launch", launch)
    client = TestClient(create_app(application))
    result = client.post("/api/datasets/nba/sync", json={"seasons": [2025]})
    assert result.status_code == 202
    key = result.json()["job_id"]
    queue.complete_dispatch.assert_called_with(
        key, 1, False, retry_seconds=settings.job_dispatch_retry_seconds,
        startup_seconds=settings.job_dispatch_startup_seconds,
    )
    client.get(f"/api/dataset-jobs/{key}/status")
    assert launch.call_count == 1
    client.get(f"/api/dataset-jobs/{key}/status")
    queue.complete_dispatch.assert_called_with(
        key, 2, True, retry_seconds=settings.job_dispatch_retry_seconds,
        startup_seconds=settings.job_dispatch_startup_seconds,
    )
    assert client.get("/api/capabilities").json()["job_progress_transport"] == "poll"
    queue.enqueue.side_effect = QueueFull("Queue full")
    assert client.post("/api/datasets/nba/sync", json={"seasons": [2025]}).status_code == 429


def test_drain_waits_for_retries_and_releases_interrupted_attempts(tmp_path, monkeypatch):
    from sports_analyst import worker

    settings = Settings(_env_file=None, data_dir=tmp_path, job_backend="sqlite")
    queue = MagicMock()
    job = {"job_id": "job", "lease_token": "token"}
    queue.claim.side_effect = [None, job, None, job, None]
    queue.has_active_work.side_effect = [True, True, False]
    monkeypatch.setattr("sports_analyst.jobs.SQLiteJobStore", lambda _: queue)
    monkeypatch.setattr(worker.signal, "signal", lambda *_: None)
    process = MagicMock()
    process.is_alive.return_value = False
    context = MagicMock()
    context.Process.return_value = process
    monkeypatch.setattr(worker.multiprocessing, "get_context", lambda _: context)
    stop = MagicMock()
    stop.is_set.return_value = False
    worker.run_worker(settings, drain=True, stop_event=stop)
    assert process.start.call_count == 2
    assert stop.wait.call_count == 2
    assert queue.release.call_count == 2


def test_cloud_api_enqueues_all_operations_and_replays_progress_after_restart(tmp_path, monkeypatch):
    application = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, job_backend="local"))
    queue = MagicMock()
    application.jobs = queue
    application.events = queue
    monkeypatch.setattr(application.store, "get_investigation", lambda _: object())
    monkeypatch.setattr(application.store, "_restore_durable_index", lambda: None)
    application.investigate = MagicMock(side_effect=AssertionError("API must not execute jobs"))
    application.follow_up = MagicMock(side_effect=AssertionError("API must not execute jobs"))
    application.sync = MagicMock(side_effect=AssertionError("API must not execute jobs"))
    request = AnalysisRequest(question="What changed in passing efficiency?", scope=AnalysisScope(
        team="KC", baseline_season=2024, comparison_season=2025))
    client = TestClient(create_app(application))
    responses = [
        client.post("/api/investigations", json=request.model_dump(mode="json")),
        client.post("/api/investigations/parent/follow-ups", json={"question": "Which games explain this?"}),
        client.post("/api/datasets/nba/sync", json={"seasons": [2025], "datasets": ["play_by_play"]}),
    ]
    assert all(response.status_code == 202 for response in responses)
    assert [call.args[1] for call in queue.enqueue.call_args_list] == ["investigation", "follow_up", "sync"]
    assert queue.enqueue.call_args_list[2].args[2]["sport"] == "nba"
    queue.events.return_value = [{"sequence": 42, "stage": "complete", "message": "Ready", "progress": 1}]
    # A fresh API object reconnects to the shared ledger, including SSE cursor support.
    restarted = TestClient(create_app(application))
    response = restarted.get("/api/investigations/example/events", headers={"Last-Event-ID": "41"})
    assert 'id: 42' in response.text
    queue.events.assert_called_with("example", 41)
    queue.status.return_value = queue.events.return_value[0]
    assert restarted.get("/api/dataset-jobs/example/status").json()["stage"] == "complete"
    assert restarted.get("/api/investigations/example/status").json()["stage"] == "complete"
    # The streaming POST variants enqueue too; they only observe progress.
    for url, payload in [
        ("/api/investigations/stream", request.model_dump(mode="json")),
        ("/api/investigations/parent/follow-ups/stream", {"question": "Which games explain this?"}),
        ("/api/datasets/nba/sync-stream", {"seasons": [2025], "datasets": ["play_by_play"]}),
    ]:
        assert client.post(url, json=payload).status_code == 200
    assert queue.enqueue.call_count == 6
    queue.enqueue.side_effect = ConnectionError("private connection details")
    failure = client.post("/api/investigations", json=request.model_dump(mode="json"))
    assert failure.status_code == 503 and "private" not in failure.text


def test_worker_dispatch_reuses_saved_results_and_handles_failures(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, data_dir=tmp_path, job_backend="sqlite")
    queue = MagicMock()
    queue.publication.return_value = nullcontext()
    monkeypatch.setattr("sports_analyst.jobs.SQLiteJobStore", lambda _: queue)
    application = MagicMock()
    application.store.get_investigation.side_effect = KeyError("missing")
    monkeypatch.setattr("sports_analyst.service.AnalystApplication", lambda _: application)

    def complete(*_):
        application.events.emit("job", "complete", "Ready", 1, investigation_id="job")

    application.investigate.side_effect = complete
    application.sync.side_effect = complete
    application.follow_up.side_effect = complete
    payload = AnalysisRequest(question="What changed?", scope=AnalysisScope(
        team="KC", baseline_season=2024, comparison_season=2025)).model_dump(mode="json")
    job = {"job_id": "job", "lease_token": "attempt", "kind": "investigation", "payload": payload}
    execute_job(settings, job)
    execute_job(settings, {**job, "kind": "sync", "payload": {"seasons": [2025], "sport": "nba"}})
    execute_job(settings, {**job, "kind": "follow_up", "payload": {"parent_id": "parent", "question": "Why?"}})
    assert queue.finish.call_count == 3
    application.sync.assert_called_once_with([2025], "job", None, "nba")
    application.store.get_investigation.side_effect = None
    execute_job(settings, job)
    assert application.investigate.call_count == 1  # Saved R2 result avoids a repeated AI call.
    application.store.get_investigation.side_effect = KeyError("missing")
    application.investigate.side_effect = TimeoutError("secret")
    execute_job(settings, job)
    queue.fail.assert_called_with("job", "attempt", True)
    application.investigate.side_effect = ValueError("bad request")
    execute_job(settings, job)
    queue.fail.assert_called_with("job", "attempt", False)


def test_sqlite_queue_survives_restart_recovers_leases_and_replays_progress(tmp_path):
    from sports_analyst.jobs import QueueFull

    path = tmp_path / "jobs.sqlite3"
    store = SQLiteJobStore(path)
    store.enqueue("job", "investigation", {"sport": "nba"}, max_attempts=2)
    with pytest.raises(QueueFull):
        store.enqueue("excess", "sync", {}, max_active=1)

    first = store.claim(300)
    assert first["attempts"] == 1 and store.claim(300) is None
    assert store.heartbeat("job", first["lease_token"], 300)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE jobs SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE job_id = 'job'")

    restarted = SQLiteJobStore(path)
    second = restarted.claim(300)
    assert second["lease_token"] != first["lease_token"] and second["attempts"] == 2
    with pytest.raises(LeaseLost):
        restarted.emit_owned("job", first["lease_token"], "complete", "Stale result", 1)
    restarted.finish("job", second["lease_token"], dict(stage="complete", message="Ready", progress=1))

    events = SQLiteJobStore(path).events("job")
    assert events[-1]["stage"] == "complete"
    assert SQLiteJobStore(path).events("job", events[-2]["sequence"]) == [events[-1]]

    async def replay():
        application = MagicMock(jobs=SQLiteJobStore(path))
        application.settings.event_stream_timeout_seconds = 30
        return [event async for event in _event_stream(application, "job", after=events[-2]["sequence"])]

    assert '"stage": "complete"' in "".join(asyncio.run(replay()))
