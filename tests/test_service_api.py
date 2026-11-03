import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

from sports_analyst.api import _event_stream, create_app
from sports_analyst.application.service import AnalystApplication
from sports_analyst.config import Settings
from sports_analyst.models import AnalysisRequest, AnalysisScope


class RecordingTelemetry:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, Any]]] = []

    @contextmanager
    def span(self, name: str, **kwargs: Any):
        self.spans.append((name, kwargs.get("metadata") or {}))
        yield object()

    @staticmethod
    def add_outputs(_run: object, _outputs: dict[str, Any]) -> None:
        return


def test_clear_downloaded_data_requires_confirmation_and_admin_token(tmp_path: Path) -> None:
    application = AnalystApplication(Settings(data_dir=tmp_path, foundry_endpoint="", _env_file=None,
                                               SPORTS_ANALYST_DATA_ADMIN_TOKEN="test-admin"))
    client = TestClient(create_app(application))
    payload = {"confirmation": "CLEAR DOWNLOADED DATA"}
    assert client.request("DELETE", "/api/datasets/nfl", json=payload).status_code == 403
    headers = {"X-Data-Admin-Token": "test-admin"}
    assert client.request("DELETE", "/api/datasets/nfl", json={"confirmation": "no"}, headers=headers).status_code == 422
    assert client.request("DELETE", "/api/datasets/soccer", json=payload, headers=headers).status_code == 422
    response = client.request("DELETE", "/api/datasets/nfl", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"deleted_packages": 0}
    application.events.emit("active-sync", "downloading", "Downloading", 0.1)
    assert client.request("DELETE", "/api/datasets/nfl", json=payload, headers=headers).status_code == 409


def test_dataset_sync_stream_keeps_work_and_progress_in_one_request(tmp_path: Path, monkeypatch) -> None:
    application = AnalystApplication(Settings(data_dir=tmp_path, foundry_endpoint=""))
    captured: dict[str, object] = {}

    def sync(seasons, job_id, datasets, sport, competition=None):
        captured.update(seasons=seasons, datasets=datasets, sport=sport)
        application.events.emit(job_id, "downloading", "Downloading selected datasets", 0.5)
        application.events.emit(job_id, "complete", "Dataset sync complete", 1.0, manifest_ids=[])
        return []

    monkeypatch.setattr(application, "sync", sync)
    response = TestClient(create_app(application)).post(
        "/api/datasets/nfl/sync-stream",
        json={"seasons": [2024, 2025], "datasets": ["play_by_play"]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"stage": "downloading"' in response.text
    assert '"stage": "complete"' in response.text
    assert captured == {"seasons": [2024, 2025], "datasets": ["play_by_play"], "sport": "nfl"}


def test_investigation_streams_keep_model_work_and_progress_in_one_request(tmp_path: Path, monkeypatch) -> None:
    application = AnalystApplication(Settings(data_dir=tmp_path, foundry_endpoint=""))
    captured: dict[str, object] = {}
    request = AnalysisRequest(
        question="Why did KC passing efficiency decline?",
        scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025),
        metrics=["epa_per_dropback"],
    )

    def investigate(received, investigation_id):
        captured.update(request=received, investigation_id=investigation_id)
        application.events.emit(investigation_id, "planning", "Planning analysis", 0.1)
        application.events.emit(investigation_id, "complete", "Investigation ready", 1.0, investigation_id=investigation_id)

    monkeypatch.setattr(application, "investigate", investigate)
    client = TestClient(create_app(application))
    response = client.post("/api/investigations/stream", json=request.model_dump(mode="json"))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-investigation-id"] == captured["investigation_id"]
    assert '"stage": "planning"' in response.text
    assert '"stage": "complete"' in response.text
    assert captured["request"] == request

    parent_id = "investigation-parent"
    monkeypatch.setattr(application.store, "get_investigation", lambda _identifier: object())

    def follow_up(received_parent_id, question, child_id):
        captured.update(parent_id=received_parent_id, question=question, child_id=child_id)
        application.events.emit(child_id, "synthesizing", "Answering follow-up", 0.75)
        application.events.emit(child_id, "complete", "Follow-up ready", 1.0, investigation_id=child_id)

    monkeypatch.setattr(application, "follow_up", follow_up)
    response = client.post(
        f"/api/investigations/{parent_id}/follow-ups/stream",
        json={"question": "Was the change consistent across the sample?"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-investigation-id"] == captured["child_id"]
    assert '"stage": "synthesizing"' in response.text
    assert '"stage": "complete"' in response.text
    assert captured["parent_id"] == parent_id
    assert captured["question"] == "Was the change consistent across the sample?"


def test_full_deterministic_investigation(tmp_path: Path, pbp_pair, monkeypatch) -> None:
    settings = Settings(data_dir=tmp_path, foundry_endpoint="")
    application = AnalystApplication(settings)
    telemetry = RecordingTelemetry()
    application.telemetry = telemetry
    synthesis_metadata: list[dict[str, Any]] = []
    original_synthesize = application.agent.synthesize

    def capture_synthesis(*args: Any, **kwargs: Any):
        synthesis_metadata.append(kwargs["trace_metadata"])
        return original_synthesize(*args, **kwargs)

    monkeypatch.setattr(application.agent, "synthesize", capture_synthesis)
    for season, frame in pbp_pair.items():
        if season == 2025:
            context = frame.head(1).with_columns(
                pl.lit(101).alias("play_id"), pl.lit("BUF").alias("posteam"), pl.lit("KC").alias("defteam"),
                pl.lit(None, dtype=pl.Float64).alias("epa"), pl.lit(0).alias("qb_dropback"),
                pl.lit("kickoff").alias("play_type"), pl.lit("Opponent kickoff game context").alias("desc"))
            frame = pl.concat([frame, context], how="vertical_relaxed")
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
    assert {name for name, _metadata in telemetry.spans} >= {
        "sports-analyst.investigation",
        "sports-analyst.plan-analysis",
        "sports-analyst.load-datasets",
        "sports-analyst.execute-deterministic-analysis",
        "sports-analyst.synthesize-report",
        "sports-analyst.validate-and-persist",
    }
    assert synthesis_metadata[0]["investigation_id"] == bundle.run.investigation_id
    assert synthesis_metadata[0]["thread_id"] == bundle.run.investigation_id

    client = TestClient(create_app(application))
    assert client.get("/api/health").json() == {"status": "ready"}
    assert client.get("/api/capabilities").json()["custom_analysis"] is False
    options = client.get("/api/sports/nfl/options").json()
    assert options["data_setup"]["required_datasets"] == ["play_by_play"]
    assert {"schedules", "rosters", "player_stats"} <= set(options["data_setup"]["recommended_datasets"])
    from sports_analyst.models import AnalysisOptions

    legacy_options = {key: value for key, value in options.items() if key != "data_setup"}
    assert AnalysisOptions.model_validate(legacy_options).data_setup.required_datasets == []
    assert options["available_seasons"] == [2024, 2025]
    assert {item["value"] for item in options["teams"]} >= {"KC", "BUF"}
    assert {item["value"] for item in options["metrics"]} >= {"epa_per_dropback", "sack_rate"}
    assert {item["value"] for item in options["analysis_domains"]} == {
        "passing",
        "rushing",
        "offense",
        "quarterback",
        "receiving",
        "running",
    }
    assert {item["value"] for item in options["subject_types"]} == {"team", "player"}
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
    assert f'filename="{bundle.run.investigation_id}_analysis_report.html"' in exported.headers["content-disposition"]
    evidence_id = bundle.claims[0].evidence_ids[0]
    assert client.get(f"/api/investigations/{bundle.run.investigation_id}/evidence/{evidence_id}").status_code == 200
    cited = next(play for play in bundle.play_evidence if play.game_id == "2025_01_KC_BUF")
    game_url = f"/api/investigations/{bundle.run.investigation_id}/evidence/{cited.evidence_id}/plays"
    browsed = client.post(game_url)
    assert browsed.status_code == 200
    game_plays = browsed.json()["plays"]
    assert len(game_plays) == 41
    assert {play["game_id"] for play in game_plays} == {cited.game_id}
    kickoff = next(play for play in game_plays if play["play_id"] == 101)
    assert kickoff["epa"] is None and kickoff["visualization"]["possession_team"] == "BUF"
    assert kickoff["evidence_role"] is None
    assert next(play for play in game_plays if play["play_id"] == cited.play_id) == cited.model_dump(mode="json")
    assert len(application.store.get_investigation(bundle.run.investigation_id).play_evidence) == len(bundle.play_evidence)
    def removed_snapshot(*args, **kwargs):
        raise FileNotFoundError("Removed snapshot")

    with monkeypatch.context() as missing_data:
        missing_data.setattr(application, "_load_dataset", removed_snapshot)
        unavailable = client.post(game_url)
        assert unavailable.status_code == 200 and unavailable.json()["retryable"]
        assert unavailable.json()["plays"] == [cited.model_dump(mode="json")]
    assert client.post(f"/api/investigations/{bundle.run.investigation_id}/evidence/not-a-saved-play/plays").status_code == 404
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
    assert synthesis_metadata[1]["investigation_id"] == child.run.investigation_id
    assert synthesis_metadata[1]["thread_id"] == bundle.run.investigation_id
    assert {name for name, _metadata in telemetry.spans} >= {
        "sports-analyst.follow-up",
        "sports-analyst.reuse-parent-evidence",
        "sports-analyst.synthesize-follow-up",
        "sports-analyst.persist-follow-up",
    }
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

    async def trimmed_history() -> list[str]:
        application.events.emit("long-download", "downloading", "Starting", 0.1)
        stream = _event_stream(application, "long-download", timeout_seconds=0.05, poll_interval=0.001)
        updates = [await anext(stream)]
        for index in range(450):
            application.events.emit("long-download", "downloading", f"School {index}", 0.8)
        application.events.emit("long-download", "complete", "Saved", 1)
        updates.extend([event async for event in stream])
        return updates

    updates = asyncio.run(trimmed_history())
    assert '"stage": "complete"' in updates[-1]
    assert updates[-1].startswith("id: 452\n")
    assert len(application.events.events("long-download")) == 200
    assert len(application.events.events("long-download", after=450)) == 2

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
    assert "available games from every selected season, 2022 through 2025" in bundle.summary


def head_to_head_request(**overrides: Any) -> AnalysisRequest:
    season = {"season": 2025, "weeks": [1, 22]}
    payload = {
        "sport": "nfl", "question": "Which offense passed more efficiently?", "analysis_domain": "passing",
        "subject": {"type": "team", "id": "KC"}, "comparison_subject": {"type": "team", "id": "BUF"},
        "scope": {"team": "KC", "baseline": season, "comparison": season, "comparison_design": "head_to_head"},
        "metrics": ["epa_per_dropback", "success_rate"],
    }
    return AnalysisRequest.model_validate({**payload, **overrides})


def test_head_to_head_request_rules() -> None:
    assert head_to_head_request().comparison_subject.id == "BUF"
    with pytest.raises(ValueError, match="two teams or two players"):
        head_to_head_request(comparison_subject={"type": "player", "id": "00-0033873"})
    with pytest.raises(ValueError, match="two different subjects"):
        head_to_head_request(comparison_subject={"type": "team", "id": "KC"})
    season_range = head_to_head_request(scope={"team": "KC", "baseline": {"season": 2023}, "comparison": {"season": 2025},
                                               "comparison_design": "head_to_head"})
    assert season_range.scope.season_range and season_range.scope.included_seasons == [2023, 2024, 2025]
    with pytest.raises(ValueError, match="complete seasons"):
        head_to_head_request(scope={"team": "KC", "baseline": {"season": 2024, "weeks": [1, 9]}, "comparison": {"season": 2025},
                                    "comparison_design": "head_to_head"})
    with pytest.raises(ValueError, match="not be earlier"):
        head_to_head_request(scope={"team": "KC", "baseline": {"season": 2025}, "comparison": {"season": 2024},
                                    "comparison_design": "head_to_head"})
    with pytest.raises(ValueError, match="at most 6 seasons"):
        head_to_head_request(scope={"team": "KC", "baseline": {"season": 2018}, "comparison": {"season": 2025},
                                    "comparison_design": "head_to_head"})
    with pytest.raises(ValueError, match="requires a head-to-head"):
        head_to_head_request(scope={"team": "KC", "baseline": {"season": 2024}, "comparison": {"season": 2025},
                                    "comparison_design": "full_seasons"})


def test_head_to_head_pairs_each_subjects_own_measurements(tmp_path: Path, pbp_pair) -> None:
    application = AnalystApplication(Settings(data_dir=tmp_path, foundry_endpoint=""))
    kansas_city = pbp_pair[2025]
    buffalo = kansas_city.with_columns(
        pl.lit("BUF").alias("posteam"), pl.lit("KC").alias("defteam"), (pl.col("epa") - 0.2).alias("epa"),
        pl.col("game_id").str.replace("KC_BUF", "BUF_KC"), pl.lit("Josh Allen").alias("passer_player_name"),
        pl.lit("00-0034857").alias("passer_player_id"))
    source = tmp_path / "source-2025.parquet"
    pl.concat([kansas_city, buffalo.with_columns(pl.col("success").cast(kansas_city["success"].dtype))]).write_parquet(source)
    application.store.save_manifest(application.connector.register_local(source, 2025))

    bundle = application.investigate(head_to_head_request())

    assert bundle.run.comparison_subject.id == "BUF" and bundle.run.scope.comparison_design == "head_to_head"
    epa = next(item for item in bundle.aggregate_evidence if item.metric == "epa_per_dropback")
    assert epa.baseline_value > epa.comparison_value
    assert epa.value == pytest.approx(epa.comparison_value - epa.baseline_value, abs=1e-6)
    assert epa.context["subjects"] == ["Kansas City Chiefs", "Buffalo Bills"]
    assert epa.context["difference_definition"] == "Buffalo Bills minus Kansas City Chiefs"
    assert {item.metric for item in bundle.aggregate_evidence} == {"epa_per_dropback", "success_rate"}
    assert {play.window for play in bundle.play_evidence} == {"baseline", "comparison"}
    assert {play.team for play in bundle.play_evidence if play.window == "comparison"} == {"BUF"}
    assert [chart.specification["usermeta"]["comparisonKind"] for chart in bundle.charts] == ["subject-comparison"]
    assert bundle.summary.startswith("Kansas City Chiefs led on EPA/dropback (Kansas City Chiefs 0.058")
    assert "not changes over time" in bundle.methodological_caveats[0]
    assert any(item.tool == "compare_subjects" for item in bundle.executions)

    follow_up = application.follow_up(bundle.run.investigation_id, "Which offense had the better success rate?")
    assert follow_up.run.comparison_subject.id == "BUF"
    assert not any(item.tool.startswith("complete_calculations") for item in follow_up.executions)


def test_head_to_head_season_range_pairs_each_season(tmp_path: Path, pbp_pair) -> None:
    application = AnalystApplication(Settings(data_dir=tmp_path, foundry_endpoint=""))
    for season, kansas_city in pbp_pair.items():
        buffalo = kansas_city.with_columns(
            pl.lit("BUF").alias("posteam"), pl.lit("KC").alias("defteam"), (pl.col("epa") + 0.3).alias("epa"),
            pl.col("game_id").str.replace("KC_BUF", "BUF_KC"))
        source = tmp_path / f"source-{season}.parquet"
        pl.concat([kansas_city, buffalo.with_columns(pl.col("success").cast(kansas_city["success"].dtype))]).write_parquet(source)
        application.store.save_manifest(application.connector.register_local(source, season))

    bundle = application.investigate(head_to_head_request(
        scope={"team": "KC", "baseline": {"season": 2024}, "comparison": {"season": 2025}, "comparison_design": "head_to_head"}))

    epa = sorted((item for item in bundle.aggregate_evidence if item.metric == "epa_per_dropback"), key=lambda item: item.context["season"])
    assert [item.context["season"] for item in epa] == [2024, 2025]
    assert [item.label for item in epa] == ["EPA/dropback · 2024", "EPA/dropback · 2025"]
    assert all(item.value == pytest.approx(0.3, abs=1e-6) for item in epa)
    assert epa[0].baseline_value > epa[1].baseline_value  # The fixture's 2025 offense is weaker in both subjects.
    assert {(play.window, play.season) for play in bundle.play_evidence} == {
        ("baseline", 2024), ("baseline", 2025), ("comparison", 2024), ("comparison", 2025)}
    assert any("compared one at a time" in caveat for caveat in bundle.methodological_caveats)
    chart = bundle.charts[0].specification
    assert chart["usermeta"]["comparisonKind"] == "subject-comparison"
    assert [plot["title"]["text"] for plot in chart["vconcat"]][:2] == ["EPA/dropback · 2024", "EPA/dropback · 2025"]
    # The deterministic report leads with the latest season.
    assert "EPA/dropback · 2025" in bundle.summary and bundle.summary.startswith("Buffalo Bills led")
