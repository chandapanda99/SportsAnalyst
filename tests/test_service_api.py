import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from sports_analyst.api import _event_stream, create_app
from sports_analyst.config import Settings
from sports_analyst.models import AnalysisRequest, AnalysisScope
from sports_analyst.service import AnalystApplication


def test_full_deterministic_investigation(tmp_path: Path, pbp_pair) -> None:
    settings = Settings(data_dir=tmp_path, foundry_endpoint="")
    application = AnalystApplication(settings)
    for season, frame in pbp_pair.items():
        source = tmp_path / f"source-{season}.parquet"
        frame.write_parquet(source)
        application.store.save_manifest(application.connector.register_local(source, season))
    request = AnalysisRequest(
        question="Why did KC passing efficiency decline?",
        scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025),
    )
    bundle = application.investigate(request)
    assert bundle.fallback_used
    assert bundle.claims
    assert (tmp_path / "investigations" / bundle.run.investigation_id / "report.html").exists()
    assert all(claim.evidence_ids for claim in bundle.claims)

    client = TestClient(create_app(application))
    assert client.get("/api/capabilities").json()["custom_analysis"] is False
    options = client.get("/api/sports/nfl/options").json()
    assert options["available_seasons"] == [2024, 2025]
    assert {item["value"] for item in options["teams"]} >= {"KC", "BUF"}
    assert {item["value"] for item in options["metrics"]} >= {"epa_per_dropback", "sack_rate"}
    assert {"play_by_play", "rosters", "injuries", "nextgen_passing"} <= set(options["syncable_datasets"])
    metric = client.get("/api/sports/nfl/metrics/epa_per_dropback")
    assert metric.status_code == 200
    assert "mean(epa)" in metric.json()["formula"]
    tools = client.get("/api/sports/nfl/tools")
    assert tools.status_code == 200
    assert {item["name"] for item in tools.json()} >= {
        "compare_time_windows",
        "decompose_metric_change",
        "compare_player_usage",
        "analyze_starter_availability",
    }
    players = client.get("/api/sports/nfl/players", params={"query": "kelce"})
    assert players.status_code == 200
    assert players.json()[0]["name"] == "Travis Kelce"
    assert client.get(f"/api/investigations/{bundle.run.investigation_id}").status_code == 200
    evidence_id = bundle.claims[0].evidence_ids[0]
    assert client.get(f"/api/investigations/{bundle.run.investigation_id}/evidence/{evidence_id}").status_code == 200


def test_event_stream_timeout_is_recoverable(tmp_path: Path) -> None:
    application = AnalystApplication(Settings(data_dir=tmp_path, foundry_endpoint=""))
    assert application.settings.event_stream_timeout_seconds == 120

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
