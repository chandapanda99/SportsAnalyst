import polars as pl

from sports_analyst.models import AnalysisRequest, AnalysisScope, AnalysisWindow, DatasetManifest
from sports_analyst.plugins.nfl import NFLPlugin


def manifest(season: int, columns: list[str], dataset: str = "play_by_play") -> DatasetManifest:
    return DatasetManifest(
        manifest_id=f"dataset-{dataset}-{season}",
        dataset=dataset,
        season=season,
        source_url="https://example.test",
        sha256="a" * 64,
        row_count=160,
        columns=columns,
        package_version="test",
        local_path=f"C:/data/{dataset}-{season}.parquet",
    )


def test_efficiency_diagnosis_is_deterministic_and_evidence_bound(pbp_pair) -> None:
    plugin = NFLPlugin()
    request = AnalysisRequest(
        question="Why did passing efficiency decline?",
        scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025),
    )
    manifests = {season: manifest(season, frame.columns) for season, frame in pbp_pair.items()}
    first = plugin.analyze(request, pbp_pair, manifests)
    second = plugin.analyze(request, pbp_pair, manifests)
    epa = next(item for item in first.aggregate_evidence if item.metric == "epa_per_dropback")
    assert epa.value == -0.1
    assert epa.sample_size == 160
    assert [item.evidence_id for item in first.aggregate_evidence] == [item.evidence_id for item in second.aggregate_evidence]
    assert len(first.play_evidence) == 5
    assert first.charts
    weekly = [item for item in first.aggregate_evidence if item.metric == "weekly_epa_per_dropback"]
    assert weekly and all(item.confidence_low is not None and item.confidence_high is not None for item in weekly)
    assert any(item.metric == "weekly_moving_average_epa_per_dropback" for item in first.aggregate_evidence)
    trend = next(item for item in first.aggregate_evidence if item.metric == "weekly_trend_classification_epa_per_dropback")
    assert trend.label in {
        "Weekly change pattern: sustained",
        "Weekly change pattern: mixed",
        "Weekly change pattern: outlier-concentrated",
    }
    benchmark_metrics = {item.metric for item in first.aggregate_evidence}
    assert {
        "league_percentile_epa_per_dropback",
        "league_rank_epa_per_dropback",
        "conference_rank_epa_per_dropback",
        "league_average_delta_epa_per_dropback",
    } <= benchmark_metrics
    assert "analyze_situational_split" in {item.tool for item in first.executions}


def test_full_season_range_analyzes_every_included_season(pbp_pair) -> None:
    plugin = NFLPlugin()
    frames: dict[int, pl.DataFrame] = {}
    for season, shift in ((2022, 0.0), (2023, 0.04), (2024, -0.02), (2025, 0.08)):
        frames[season] = pbp_pair[2024].with_columns(
            pl.lit(season).alias("season"),
            (pl.col("epa") + shift).alias("epa"),
            pl.col("game_id").str.replace("2024", str(season)).alias("game_id"),
        )
    manifests = {season: manifest(season, frame.columns) for season, frame in frames.items()}
    request = AnalysisRequest(
        question="How did CHI perform from 2022 through 2025?",
        scope=AnalysisScope(
            team="KC",
            baseline_season=2022,
            comparison_season=2025,
            comparison_design="full_seasons",
        ),
        metrics=["epa_per_dropback"],
    )

    result = plugin.analyze(request, frames, manifests)

    seasonal = [item for item in result.aggregate_evidence if item.metric == "seasonal_epa_per_dropback"]
    assert [int(item.label.split(" ·", 1)[0]) for item in seasonal] == [2022, 2023, 2024, 2025]
    assert {item.tool for item in result.executions} >= {"analyze_season_trends", "compare_time_windows"}
    assert {manifest_id for item in seasonal for manifest_id in item.dataset_manifest_ids} == {
        "dataset-play_by_play-2022",
        "dataset-play_by_play-2023",
        "dataset-play_by_play-2024",
        "dataset-play_by_play-2025",
    }
    assert any(chart.title == "Season-by-season EPA/dropback" for chart in result.charts)
    comparison_chart = next(chart for chart in result.charts if chart.title == "All seasons · Passing efficiency comparison")
    assert {row["season"] for row in comparison_chart.specification["data"]["values"]} == {2022, 2023, 2024, 2025}
    assert comparison_chart.specification["encoding"]["color"]["field"] == "season"


def test_plan_uses_only_registered_tools() -> None:
    plugin = NFLPlugin()
    request = AnalysisRequest(question="Why?", scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025))
    plan = plugin.default_plan(request)
    registered = {tool.name for tool in plugin.tools()}
    assert {call.tool for call in plan.calls} <= registered
    priority_tools = {
        tool.name: tool
        for tool in plugin.tools()
        if tool.name
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
    }
    assert len(priority_tools) == 8
    assert all(tool.input_schema.get("type") == "object" for tool in priority_tools.values())


def test_selected_metrics_and_week_windows_constrain_analysis(pbp_pair) -> None:
    plugin = NFLPlugin()
    request = AnalysisRequest(
        question="Did sack rate change in the first half?",
        scope=AnalysisScope(
            team="KC",
            baseline=AnalysisWindow(season=2024, weeks=(1, 2)),
            comparison=AnalysisWindow(season=2025, weeks=(1, 2)),
        ),
        metrics=["sack_rate"],
    )
    manifests = {season: manifest(season, frame.columns) for season, frame in pbp_pair.items()}
    result = plugin.analyze(request, pbp_pair, manifests)
    requested = [item for item in result.aggregate_evidence if item.metric == "sack_rate"]
    assert len(requested) == 1
    assert requested[0].sample_size == 80
    assert {item.tool for item in result.executions} >= {
        "compare_time_windows",
        "analyze_weekly_trends",
        "rank_game_outliers",
        "benchmark_against_league",
        "decompose_metric_change",
        "compare_play_mix",
        "identify_change_points",
        "find_representative_plays",
    }
    comparison_execution = next(item for item in result.executions if item.tool == "compare_time_windows")
    assert comparison_execution.parameters["baseline"]["weeks"] == (1, 2)


def test_options_report_season_specific_field_availability(pbp_pair) -> None:
    plugin = NFLPlugin()
    manifests = [manifest(season, frame.columns) for season, frame in pbp_pair.items()]
    options = plugin.analysis_options(manifests)
    formation = next(item for item in options.split_dimensions if item.value == "formation")
    no_huddle = next(item for item in options.split_dimensions if item.value == "no_huddle")
    assert formation.available_seasons == [2024, 2025]
    assert no_huddle.available_seasons == []
    assert options.syncable_seasons[0] == 2025


def test_selected_split_limits_decomposition_dimensions(pbp_pair) -> None:
    plugin = NFLPlugin()
    request = AnalysisRequest(
        question="Which downs drove the change?",
        scope=AnalysisScope(
            team="KC",
            baseline=AnalysisWindow(season=2024, weeks=(1, 2)),
            comparison=AnalysisWindow(season=2025, weeks=(1, 2)),
        ),
        metrics=["epa_per_dropback"],
        splits=["down"],
    )
    manifests = {season: manifest(season, frame.columns) for season, frame in pbp_pair.items()}
    result = plugin.analyze(request, pbp_pair, manifests)
    decompositions = [item.metric for item in result.aggregate_evidence if item.metric.endswith("_decomposition")]
    assert decompositions
    assert set(decompositions) == {"epa_per_dropback__down_decomposition"}


def test_player_and_supplemental_context_tools(pbp_pair) -> None:
    plugin = NFLPlugin()
    request = AnalysisRequest(
        question="Did personnel and availability contribute to the decline?",
        scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025),
    )
    rosters = {
        season: pl.DataFrame(
            {
                "team": ["KC", "KC", "KC"],
                "position": ["QB", "WR", "TE"],
                "gsis_id": ["00-0033873", "00-0039064", "00-0030506"],
                "full_name": ["Patrick Mahomes", "Rashee Rice", "Travis Kelce"],
            }
        )
        for season in (2024, 2025)
    }
    injuries = {
        2024: pl.DataFrame({"team": ["KC"], "week": [2], "full_name": ["Rashee Rice"], "report_status": ["Questionable"]}),
        2025: pl.DataFrame(
            {
                "team": ["KC", "KC"],
                "week": [2, 3],
                "full_name": ["Rashee Rice", "Rashee Rice"],
                "report_status": ["Out", "Out"],
            }
        ),
    }
    nextgen = {
        2024: pl.DataFrame({"team_abbr": ["KC"], "week": [1], "avg_time_to_throw": [2.8]}),
        2025: pl.DataFrame({"team_abbr": ["KC"], "week": [1], "avg_time_to_throw": [3.0]}),
    }
    schedules = {
        2024: pl.DataFrame({"week": [1], "home_team": ["KC"], "away_team": ["BUF"], "home_score": [27], "away_score": [20]}),
        2025: pl.DataFrame({"week": [1], "home_team": ["BUF"], "away_team": ["KC"], "home_score": [24], "away_score": [20]}),
    }
    supplemental = {"rosters": rosters, "injuries": injuries, "nextgen_passing": nextgen, "schedules": schedules}
    supplemental_manifests = {
        dataset: {season: manifest(season, frame.columns, dataset) for season, frame in frames.items()}
        for dataset, frames in supplemental.items()
    }
    manifests = {season: manifest(season, frame.columns) for season, frame in pbp_pair.items()}

    result = plugin.analyze(request, pbp_pair, manifests, supplemental, supplemental_manifests)
    executed = {item.tool for item in result.executions}
    assert {
        "compare_player_usage",
        "analyze_qb_receiver_pairs",
        "get_roster_context",
        "analyze_starter_availability",
        "summarize_injured_or_inactive_players",
        "join_nextgen_passing_metrics",
        "join_schedule_context",
    } <= executed
    metrics = {item.metric for item in result.aggregate_evidence}
    assert {"receiver_target_share", "qb_receiver_epa_per_target", "unavailable_player_reports"} <= metrics
    assert "nextgen_avg_time_to_throw" in metrics
    assert "schedule_average_scoring_margin" in metrics


def test_metric_explanation_and_player_resolution(pbp_pair) -> None:
    plugin = NFLPlugin()
    definition = plugin.explain_metric("epa_per_dropback")
    assert "mean(epa)" in definition.formula
    assert definition.higher_is_better is True
    assert "higher is generally better" in definition.interpretation
    players = plugin.resolve_players("kelce", [(2025, pbp_pair[2025])])
    assert players[0].name == "Travis Kelce"
