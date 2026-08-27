import asyncio
from pathlib import Path

import polars as pl
from fastapi.testclient import TestClient

from sports_analyst.api import _event_stream, create_app
from sports_analyst.config import Settings
from sports_analyst.models import AnalysisRequest, AnalysisScope
from sports_analyst.service import AnalystApplication


def test_full_deterministic_investigation(tmp_path: Path, pbp_pair, monkeypatch) -> None:
    settings = Settings(data_dir=tmp_path, foundry_endpoint="")
    application = AnalystApplication(settings)
    for season, frame in pbp_pair.items():
        source = tmp_path / f"source-{season}.parquet"
        frame.write_parquet(source)
        application.store.save_manifest(application.connector.register_local(source, season))
    request = AnalysisRequest(
        question="Why did KC passing efficiency decline?",
        scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025),
        metrics=["epa_per_dropback", "success_rate"],
    )
    bundle = application.investigate(request)
    assert bundle.fallback_used
    assert bundle.claims
    synthesis_events = [
        event for event in application.events.events(bundle.run.investigation_id) if event["stage"] == "synthesizing"
    ]
    assert [event["message"] for event in synthesis_events] == [
        "Reviewing evidence and drafting findings",
        "Organizing the validated evidence",
        "Writing the deterministic evidence report",
    ]
    assert [event["progress"] for event in synthesis_events] == [0.75, 0.76, 0.94]
    assert (tmp_path / "investigations" / bundle.run.investigation_id / "report.html").exists()
    assert all(claim.evidence_ids for claim in bundle.claims)

    client = TestClient(create_app(application))
    assert client.get("/api/capabilities").json()["custom_analysis"] is False
    options = client.get("/api/sports/nfl/options").json()
    assert options["available_seasons"] == [2024, 2025]
    assert {item["value"] for item in options["teams"]} >= {"KC", "BUF"}
    assert {item["value"] for item in options["metrics"]} >= {"epa_per_dropback", "sack_rate"}
    assert {item["value"] for item in options["analysis_domains"]} == {"passing", "rushing", "offense"}
    assert options["default_metrics_by_domain"]["rushing"][0] == "epa_per_rush"
    assert {"play_by_play", "rosters", "injuries", "nextgen_passing"} <= set(options["syncable_datasets"])
    metric = client.get("/api/sports/nfl/metrics/epa_per_dropback")
    assert metric.status_code == 200
    assert "mean(epa)" in metric.json()["formula"]
    assert metric.json()["interpretation"]
    tools = client.get("/api/sports/nfl/tools")
    assert tools.status_code == 200
    assert {item["name"] for item in tools.json()} >= {
        "compare_time_windows",
        "decompose_metric_change",
        "compare_player_usage",
        "analyze_starter_availability",
        "build_player_week_dataset",
        "analyze_position_group_availability",
        "analyze_lineup_continuity",
        "decompose_lineup_continuity",
    }
    assert all(
        item["input_schema"].get("type") == "object"
        for item in tools.json()
        if item["name"]
        in {
            "get_analysis_options",
            "compare_time_windows",
            "analyze_weekly_trends",
            "rank_game_outliers",
            "benchmark_against_league",
            "analyze_situational_split",
            "find_representative_plays",
            "explain_metric",
        }
    )
    players = client.get("/api/sports/nfl/players", params={"query": "kelce"})
    assert players.status_code == 200
    assert players.json()[0]["name"] == "Travis Kelce"
    assert client.get(f"/api/investigations/{bundle.run.investigation_id}").status_code == 200
    history = client.get("/api/investigations").json()
    assert history[0]["run"]["investigation_id"] == bundle.run.investigation_id
    assert "claims" not in history[0]
    exported = client.get(f"/api/investigations/{bundle.run.investigation_id}/export", params={"format": "html"})
    assert exported.status_code == 200
    assert "--team-primary:#E31837" in exported.text
    assert "--team-secondary:#FFB81C" in exported.text
    assert 'filename="report.html"' in exported.headers["content-disposition"]
    evidence_id = bundle.claims[0].evidence_ids[0]
    assert client.get(f"/api/investigations/{bundle.run.investigation_id}/evidence/{evidence_id}").status_code == 200
    batch = client.post(
        f"/api/investigations/{bundle.run.investigation_id}/evidence/batch",
        json={"evidence_ids": bundle.claims[0].evidence_ids},
    )
    assert batch.status_code == 200
    assert [item["evidence_id"] for item in batch.json()] == bundle.claims[0].evidence_ids
    monkeypatch.setattr(
        application.plugin,
        "analyze",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("follow-ups must reuse parent evidence")),
    )
    follow_up = client.post(
        f"/api/investigations/{bundle.run.investigation_id}/follow-ups",
        json={"question": "Was the change consistent across the full sample?"},
    )
    assert follow_up.status_code == 202
    child = application.store.get_investigation(follow_up.json()["investigation_id"])
    assert child.run.parent_investigation_id == bundle.run.investigation_id
    assert child.run.scope == bundle.run.scope
    assert child.run.metrics == bundle.run.metrics
    assert child.summary.startswith("Follow-up:")
    assert child.plan.calls[0].tool == "reuse_parent_evidence"
    assert [item.execution_id for item in child.executions] == [item.execution_id for item in bundle.executions]
    thread = client.get(f"/api/investigations/{child.run.investigation_id}/thread")
    assert thread.status_code == 200
    assert [item["run"]["investigation_id"] for item in thread.json()] == [
        bundle.run.investigation_id,
        child.run.investigation_id,
    ]
    investigation_directory = tmp_path / "investigations" / bundle.run.investigation_id
    child_directory = tmp_path / "investigations" / child.run.investigation_id
    assert client.delete(f"/api/investigations/{bundle.run.investigation_id}").status_code == 204
    assert client.get(f"/api/investigations/{bundle.run.investigation_id}").status_code == 404
    assert not investigation_directory.exists()
    assert not child_directory.exists()


def test_event_stream_timeout_is_recoverable(tmp_path: Path) -> None:
    application = AnalystApplication(Settings(data_dir=tmp_path, foundry_endpoint=""))
    assert application.settings.event_stream_timeout_seconds >= 120

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in _event_stream(
                application,
                "pending-investigation",
                timeout_seconds=0.005,
                poll_interval=0.001,
                heartbeat_interval=1.0,
            )
        ]

    chunks = asyncio.run(collect())
    assert any('"stage": "timeout"' in chunk for chunk in chunks)
    assert not any('"stage": "failed"' in chunk for chunk in chunks)

    client = TestClient(create_app(application))
    pending = client.get("/api/investigations/pending-investigation/status")
    assert pending.json()["stage"] == "pending"
    application.events.emit("failed-investigation", "failed", "Analysis could not be saved", 1.0)
    failed = client.get("/api/investigations/failed-investigation/status")
    assert failed.status_code == 200
    assert failed.json()["stage"] == "failed"
    assert failed.json()["message"] == "Analysis could not be saved"
    assert failed.json()["progress"] == 1.0


def test_service_loads_every_season_in_a_full_season_range(tmp_path: Path, pbp_pair) -> None:
    application = AnalystApplication(Settings(data_dir=tmp_path, foundry_endpoint=""))
    frames = {
        2022: pbp_pair[2024].with_columns(pl.lit(2022).alias("season")),
        2023: pbp_pair[2024].with_columns(pl.lit(2023).alias("season")),
        2024: pbp_pair[2024],
        2025: pbp_pair[2025],
    }
    for season, frame in frames.items():
        source = tmp_path / f"range-{season}.parquet"
        frame.write_parquet(source)
        application.store.save_manifest(application.connector.register_local(source, season))

    bundle = application.investigate(
        AnalysisRequest(
            question="How did KC perform from 2022 through 2025?",
            scope=AnalysisScope(
                team="KC",
                baseline_season=2022,
                comparison_season=2025,
                comparison_design="full_seasons",
            ),
            metrics=["epa_per_dropback"],
        )
    )

    assert {manifest.season for manifest in bundle.dataset_manifests if manifest.dataset == "play_by_play"} == {
        2022,
        2023,
        2024,
        2025,
    }
    assert "every full season from 2022 through 2025" in bundle.summary
