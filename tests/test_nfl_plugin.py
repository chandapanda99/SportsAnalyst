from datetime import UTC, datetime

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
    assert first.play_evidence[0].visualization is not None
    assert first.play_evidence[0].visualization.down is not None
    assert first.play_evidence[0].visualization.yards_gained is not None
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


def test_rushing_and_overall_offense_domains_scope_the_correct_plays(pbp_pair) -> None:
    plugin = NFLPlugin()
    frames: dict[int, pl.DataFrame] = {}
    for season, rush_epa in ((2024, 0.05), (2025, 0.15)):
        passing = pbp_pair[season].with_columns(pl.lit(0).alias("rush_attempt"))
        rushing = pl.DataFrame(
            [
                {
                    "season": season,
                    "season_type": "REG",
                    "week": game,
                    "game_id": f"{season}_0{game}_KC_BUF",
                    "play_id": 1000 + game * 100 + play,
                    "posteam": "KC",
                    "defteam": "BUF",
                    "qb_dropback": 0,
                    "rush_attempt": 1,
                    "play_type": "run",
                    "epa": rush_epa + (play % 5) * 0.01,
                    "success": 1,
                    "yards_gained": 12 if play % 5 == 0 else 4,
                    "ydstogo": 5,
                    "interception": 0,
                    "fumble_lost": int(play == 20),
                    "down": 1 + play % 3,
                    "yardline_100": 25 + play,
                    "score_differential": 0,
                    "desc": f"Synthetic rush play {play} in game {game}",
                }
                for game in range(1, 5)
                for play in range(1, 21)
            ]
        )
        frames[season] = pl.concat([passing, rushing], how="diagonal_relaxed")
    manifests = {season: manifest(season, frame.columns) for season, frame in frames.items()}
    scope = AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025)

    rushing_result = plugin.analyze(
        AnalysisRequest(question="How did the run game change?", scope=scope, analysis_domain="rushing"), frames, manifests
    )
    rush_epa = next(item for item in rushing_result.aggregate_evidence if item.metric == "epa_per_rush")
    assert rush_epa.sample_size == 80
    assert rush_epa.value == 0.1
    assert all("rush play" in play.description for play in rushing_result.play_evidence)

    offense_result = plugin.analyze(
        AnalysisRequest(question="How did the full offense change?", scope=scope, analysis_domain="offense"), frames, manifests
    )
    overall_epa = next(item for item in offense_result.aggregate_evidence if item.metric == "epa_per_play")
    assert overall_epa.sample_size == 240
    assert {item.metric for item in offense_result.aggregate_evidence} >= {
        "overall_success_rate",
        "overall_yards_per_play",
        "turnover_rate",
    }


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
    analysis_pbp = {
        2024: pbp_pair[2024],
        2025: pbp_pair[2025].with_columns(
            pl.when(pl.col("receiver_player_name") == "Rashee Rice")
            .then(pl.lit("Xavier Worthy"))
            .otherwise(pl.col("receiver_player_name"))
            .alias("receiver_player_name"),
            pl.when(pl.col("receiver_player_id") == "00-0039064")
            .then(pl.lit("00-0039912"))
            .otherwise(pl.col("receiver_player_id"))
            .alias("receiver_player_id"),
        ),
    }
    rosters = {
        2024: pl.DataFrame(
            {
                "team": ["KC", "KC", "KC"],
                "position": ["QB", "WR", "TE"],
                "gsis_id": ["00-0033873", "00-0039064", "00-0030506"],
                "full_name": ["Patrick Mahomes", "Rashee Rice", "Travis Kelce"],
            }
        ),
        2025: pl.DataFrame(
            {
                "team": ["KC", "KC", "KC", "KC"],
                "position": ["QB", "WR", "WR", "TE"],
                "gsis_id": ["00-0033873", "00-0039064", "00-0039912", "00-0030506"],
                "full_name": ["Patrick Mahomes", "Rashee Rice", "Xavier Worthy", "Travis Kelce"],
            }
        ),
    }
    injuries = {
        2024: pl.DataFrame(
            {
                "team": ["KC"],
                "week": [2],
                "full_name": ["Rashee Rice"],
                "position": ["WR"],
                "report_status": ["Questionable"],
                "last_modified": [datetime(2024, 9, 1, tzinfo=UTC)],
            }
        ),
        2025: pl.DataFrame(
            {
                "team": ["KC", "KC"],
                "week": [2, 3],
                "full_name": ["Rashee Rice", "Rashee Rice"],
                "position": ["WR", "WR"],
                "report_status": ["Out", "Out"],
                "last_modified": [datetime(2025, 9, 1, tzinfo=UTC), datetime(2025, 9, 8, tzinfo=UTC)],
            }
        ),
    }
    snap_counts = {}
    for season in (2024, 2025):
        players = (
            [("Patrick Mahomes", "QB", 60), ("Rashee Rice", "WR", 50), ("Travis Kelce", "TE", 40)]
            if season == 2024
            else [("Patrick Mahomes", "QB", 60), ("Xavier Worthy", "WR", 48), ("Travis Kelce", "TE", 40)]
        )
        snap_counts[season] = pl.DataFrame(
            [
                {"team": "KC", "week": week, "player": player, "position": position, "offense_snaps": snaps}
                for week in range(1, 5)
                for player, position, snaps in players
            ]
        )
    nextgen = {
        2024: pl.DataFrame({"team_abbr": ["KC"], "week": [1], "avg_time_to_throw": [2.8]}),
        2025: pl.DataFrame({"team_abbr": ["KC"], "week": [1], "avg_time_to_throw": [3.0]}),
    }
    schedules = {
        2024: pl.DataFrame({"week": [1], "home_team": ["KC"], "away_team": ["BUF"], "home_score": [27], "away_score": [20]}),
        2025: pl.DataFrame({"week": [1], "home_team": ["BUF"], "away_team": ["KC"], "home_score": [24], "away_score": [20]}),
    }
    participation = {}
    ftn_charting = {}
    weekly_rosters = {}
    depth_charts = {}
    nextgen_receiving = {}
    nextgen_rushing = {}
    pfr_passing = {}
    for season in (2024, 2025):
        receiver_id = "00-0039064" if season == 2024 else "00-0039912"
        receiver_name = "Rashee Rice" if season == 2024 else "Xavier Worthy"
        play_rows = analysis_pbp[season].select("game_id", "play_id", "week").iter_rows(named=True)
        participation[season] = pl.DataFrame(
            [
                {
                    "nflverse_game_id": row["game_id"],
                    "play_id": row["play_id"],
                    "week": row["week"],
                    "possession_team": "KC",
                    "offense_players": f"00-0033873;{receiver_id};00-0030506",
                    "offense_names": f"Patrick Mahomes;{receiver_name};Travis Kelce",
                    "offense_positions": "QB;WR;TE",
                    "defense_names": "T.J. Watt;Minkah Fitzpatrick",
                    "defense_positions": "EDGE;S",
                    "defense_personnel": "2 DL, 4 LB, 5 DB",
                    "defenders_in_box": 6 if season == 2024 else 7,
                    "number_of_pass_rushers": 4 if season == 2024 else 5,
                    "was_pressure": season == 2025,
                    "route": "SLANT",
                    "defense_man_zone_type": "MAN" if season == 2025 else "ZONE",
                    "defense_coverage_type": "COVER_1" if season == 2025 else "COVER_3",
                }
                for row in play_rows
            ]
        )
        ftn_charting[season] = participation[season].select(
            pl.col("nflverse_game_id"),
            pl.col("play_id").alias("nflverse_play_id"),
        ).with_columns(
            pl.lit(season == 2025).alias("is_motion"),
            pl.lit(False).alias("is_no_huddle"),
            pl.lit(season == 2025).alias("is_play_action"),
            pl.lit(False).alias("is_rpo"),
            pl.lit(False).alias("is_screen_pass"),
            pl.lit(4 if season == 2024 else 5).alias("n_pass_rushers"),
            pl.lit("R").alias("starting_hash"),
            pl.lit("SHOTGUN").alias("qb_location"),
            pl.lit(1).alias("n_offense_backfield"),
            pl.lit(7).alias("n_defense_box"),
            pl.lit(1 if season == 2024 else 2).alias("n_blitzers"),
            pl.lit(False).alias("is_trick_play"),
            pl.lit(season == 2025).alias("is_qb_out_of_pocket"),
            pl.lit(False).alias("is_interception_worthy"),
            pl.lit(False).alias("is_throw_away"),
            pl.lit("FIRST").alias("read_thrown"),
            pl.lit(False).alias("is_contested_ball"),
            pl.lit(False).alias("is_created_reception"),
            pl.lit(False).alias("is_qb_sneak"),
            pl.lit(False).alias("is_qb_fault_sack"),
            pl.datetime(season, 1, 1, time_zone="UTC").alias("loaded_at"),
        )
        weekly_rosters[season] = pl.DataFrame(
            [
                {
                    "team": "KC",
                    "week": week,
                    "gsis_id": receiver_id,
                    "full_name": receiver_name,
                    "position": "WR",
                    "status": "ACT",
                }
                for week in range(1, 5)
            ]
        )
        depth_charts[season] = pl.DataFrame(
            [
                {
                    "team": "KC",
                    "week": week,
                    "gsis_id": receiver_id,
                    "player_name": receiver_name,
                    "pos_abb": "WR",
                    "pos_rank": 1,
                }
                for week in range(1, 5)
            ]
        )
        nextgen_receiving[season] = pl.DataFrame(
            {"team_abbr": ["KC"], "week": [1], "avg_separation": [2.5 if season == 2024 else 3.0]}
        )
        nextgen_rushing[season] = pl.DataFrame(
            {"team_abbr": ["KC"], "week": [1], "rush_yards_over_expected_per_att": [0.1 if season == 2024 else 0.4]}
        )
        pfr_passing[season] = pl.DataFrame(
            {"team": ["KC"], "week": [1], "times_pressured_pct": [20.0 if season == 2024 else 25.0]}
        )
    supplemental = {
        "rosters": rosters,
        "injuries": injuries,
        "snap_counts": snap_counts,
        "nextgen_passing": nextgen,
        "schedules": schedules,
        "participation": participation,
        "weekly_rosters": weekly_rosters,
        "depth_charts": depth_charts,
        "nextgen_receiving": nextgen_receiving,
        "nextgen_rushing": nextgen_rushing,
        "ftn_charting": ftn_charting,
        "pfr_passing": pfr_passing,
    }
    supplemental_manifests = {
        dataset: {season: manifest(season, frame.columns, dataset) for season, frame in frames.items()}
        for dataset, frames in supplemental.items()
    }
    manifests = {season: manifest(season, frame.columns) for season, frame in analysis_pbp.items()}

    result = plugin.analyze(request, analysis_pbp, manifests, supplemental, supplemental_manifests)
    executed = {item.tool for item in result.executions}
    assert {
        "compare_player_usage",
        "build_player_week_dataset",
        "analyze_position_group_availability",
        "analyze_lineup_continuity",
        "decompose_lineup_continuity",
        "analyze_qb_receiver_pairs",
        "get_roster_context",
        "analyze_starter_availability",
        "summarize_injured_or_inactive_players",
        "join_nextgen_passing_metrics",
        "join_schedule_context",
        "join_participation_context",
        "join_depth_chart_context",
        "join_nextgen_receiving_metrics",
        "join_nextgen_rushing_metrics",
        "join_ftn_charting",
        "join_pfr_advanced_stats",
    } <= executed
    metrics = {item.metric for item in result.aggregate_evidence}
    assert {
        "receiver_target_share",
        "player_opportunity_share",
        "position_group_availability_rate",
        "lineup_returning_snap_share",
        "lineup_turnover_position_contribution",
        "qb_receiver_epa_per_target",
        "unavailable_player_reports",
    } <= metrics
    overall_continuity = next(
        item for item in result.aggregate_evidence if item.metric == "lineup_returning_snap_share" and item.label.startswith("Overall")
    )
    assert 0 < float(overall_continuity.comparison_value) < 1
    wr_availability = next(
        item
        for item in result.aggregate_evidence
        if item.metric == "position_group_availability_rate" and item.label.startswith("WR")
    )
    assert float(wr_availability.comparison_value) < float(wr_availability.baseline_value)
    worthy_targets = next(
        item for item in result.aggregate_evidence if item.metric == "receiver_target_share" and "Xavier Worthy" in item.label
    )
    rice_targets = next(
        item for item in result.aggregate_evidence if item.metric == "receiver_target_share" and "Rashee Rice" in item.label
    )
    assert worthy_targets.baseline_value == 0
    assert rice_targets.comparison_value == 0
    assert "nextgen_avg_time_to_throw" in metrics
    assert "schedule_average_scoring_margin" in metrics
    assert {
        "participation_pressure_rate",
        "depth_chart_starter_continuity",
        "nextgen_receiving_avg_separation",
        "nextgen_rushing_rush_yards_over_expected_per_att",
        "ftn_is_motion",
        "pfr_passing_times_pressured_pct",
    } <= metrics
    assert result.play_evidence[0].visualization is not None
    assert result.play_evidence[0].visualization.coverage_type in {"COVER_1", "COVER_3"}
    assert result.play_evidence[0].visualization.starting_hash == "R"
    assert result.play_evidence[0].visualization.qb_location == "SHOTGUN"
    assert result.play_evidence[0].visualization.offense_names
    assert result.play_evidence[0].visualization.defense_names == ["T.J. Watt", "Minkah Fitzpatrick"]
    assert result.play_evidence[0].visualization.source_packages == ["play_by_play", "participation", "ftn_charting"]


def test_metric_explanation_and_player_resolution(pbp_pair) -> None:
    plugin = NFLPlugin()
    definition = plugin.explain_metric("epa_per_dropback")
    assert "mean(epa)" in definition.formula
    assert definition.higher_is_better is True
    assert "higher is generally better" in definition.interpretation
    players = plugin.resolve_players("kelce", [(2025, pbp_pair[2025])])
    assert players[0].name == "Travis Kelce"
