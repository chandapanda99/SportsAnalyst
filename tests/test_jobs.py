"""Major durable-job workflows, including real Postgres lease recovery when configured."""
import asyncio
import os
from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr

from sports_analyst.api import _event_stream, create_app
from sports_analyst.config import Settings
from sports_analyst.jobs import Base, Job, LeaseLost, PostgresJobStore
from sports_analyst.models import AnalysisRequest, AnalysisScope
from sports_analyst.service import AnalystApplication
from sports_analyst.worker import execute_job


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
    settings = Settings(_env_file=None, data_dir=tmp_path, job_backend="local", database_url=SecretStr("postgresql://unused/db"))
    queue = MagicMock()
    queue.publication.return_value = nullcontext()
    monkeypatch.setattr("sports_analyst.worker.PostgresJobStore", lambda _: queue)
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


@pytest.mark.postgres
def test_postgres_migration_claim_recovery_fencing_and_event_replay(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable local or development PostgreSQL database")
    from sports_analyst.jobs import database_engine
    admin = database_engine(url)
    schema = "test_jobs_" + uuid4().hex
    with admin.begin() as db:
        db.execute(sa.schema.CreateSchema(schema))
    scoped_url = sa.engine.make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    store = PostgresJobStore(scoped_url.render_as_string(hide_password=False))
    try:
        # Reproduce the documented pre-Alembic setup: the normalized job tables
        # already exist, while alembic_version does not.
        with store.engine.begin() as db:
            Base.metadata.create_all(db)
        config = Config("alembic.ini")
        with store.engine.begin() as db:
            config.attributes["connection"] = db
            command.upgrade(config, "head")
        store.enqueue("job", "investigation", {"sport": "nba"}, max_attempts=2)
        first = store.claim(300)
        assert first["attempts"] == 1
        assert store.claim(300) is None  # Another worker cannot claim a live lease.
        assert store.heartbeat("job", first["lease_token"], 300)
        with store.engine.begin() as db:
            db.execute(sa.update(Job).values(lease_expires_at=sa.func.now() - timedelta(seconds=1)))
        second = store.claim(300)
        assert second["lease_token"] != first["lease_token"] and second["attempts"] == 2
        with pytest.raises(LeaseLost):
            store.emit_owned("job", first["lease_token"], "complete", "Stale result", 1)
        # A publication lock must not block another claim or kill the publishing child.
        with store.publication("job", second["lease_token"], 300):
            assert store.claim(300) is None
            assert store.heartbeat("job", second["lease_token"], 300)
        store.finish("job", second["lease_token"], dict(stage="complete", message="Ready", progress=1))
        restarted = PostgresJobStore(scoped_url.render_as_string(hide_password=False))
        events = restarted.events("job")
        assert events[-1]["stage"] == "complete"
        assert restarted.events("job", events[-2]["sequence"]) == [events[-1]]
        with pytest.raises(LeaseLost):
            store.fail("job", second["lease_token"], True)
        store.enqueue("retry", "sync", {}, max_attempts=1)
        retry = store.claim(300)
        store.fail("retry", retry["lease_token"], True)
        assert store.status("retry")["stage"] == "failed"

        async def replay():
            application = MagicMock(jobs=restarted)
            application.settings.event_stream_timeout_seconds = 30
            return [event async for event in _event_stream(application, "job", after=events[-2]["sequence"])]
        assert '"stage": "complete"' in "".join(asyncio.run(replay()))
    finally:
        store.engine.dispose()
        with admin.begin() as db:
            db.execute(sa.schema.DropSchema(schema, cascade=True))
        admin.dispose()
