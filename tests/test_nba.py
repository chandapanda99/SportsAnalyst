from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient
from sportsdataverse.errors import SeasonNotFoundError

from sports_analyst.api import create_app
from sports_analyst.config import Settings
from sports_analyst.models import AnalysisRequest, AnalysisScope, AnalysisSubject, AnalysisWindow
from sports_analyst.nba_data import NBA_DEFAULT_DATASETS, SportsDataverseNBAConnector
from sports_analyst.plugins.nba import NBAPlugin
from sports_analyst.service import AnalystApplication


def _nba_frames(season: int, points: int) -> dict[str, pl.DataFrame]:
    game_id = f"{season}-BOS-LAL"
    return {
        "play_by_play": pl.DataFrame(
            {
                "game_id": [game_id, game_id],
                "sequence_number": [1, 2],
                "text": ["Jayson Tatum makes 26-foot 3-pt jump shot (Derrick White assists)", "Jayson Tatum misses layup"],
                "period_number": [1, 4],
                "clock_display_value": ["11:42", "00:08"],
                "team_id": ["2", "2"],
                "home_team_id": ["2", "2"],
                "away_team_id": ["13", "13"],
                "home_team_abbrev": ["BOS", "BOS"],
                "away_team_abbrev": ["LAL", "LAL"],
                "home_team_name": ["Celtics", "Celtics"],
                "away_team_name": ["Lakers", "Lakers"],
                "athlete_id_1": ["4065648", "4065648"],
                "athlete_name_1": ["Jayson Tatum", "Jayson Tatum"],
                "athlete_id_2": ["4433134", None],
                "athlete_name_2": ["Derrick White", None],
                "home_score": [3, points],
                "away_score": [0, points - 4],
                "score_value": [3, 0],
                "scoring_play": [True, False],
                "shooting_play": [True, True],
                "coordinate_x_raw": [8.0, 1.0],
                "coordinate_y_raw": [23.0, 4.0],
                "game_date": [f"{season - 1}-11-01", f"{season - 1}-11-01"],
                "start_quarter_seconds_remaining": [702.0, 8.0],
                "start_game_seconds_remaining": [2862.0, 8.0],
            }
        ),
        "schedules": pl.DataFrame(
            {
                "game_id": [game_id],
                "date": [f"{season - 1}-11-01T19:30:00Z"],
                "season_type": [2],
                "notes_headline": [""],
                "home_abbreviation": ["BOS"],
                "away_abbreviation": ["LAL"],
            }
        ),
        "team_boxscores": pl.DataFrame(
            {
                "game_id": [game_id],
                "team_id": ["2"],
                "team_abbreviation": ["BOS"],
                "game_date": [date(season - 1, 11, 1)],
                "team_score": [points],
                "opponent_team_score": [points - 4],
                "team_winner": [True],
                "field_goals_made": [42],
                "field_goals_attempted": [86],
                "three_point_field_goals_made": [15],
                "three_point_field_goals_attempted": [38],
                "free_throws_attempted": [20],
                "offensive_rebounds": [10],
                "total_rebounds": [46],
                "assists": [27],
                "turnovers": [12],
            }
        ),
        "player_boxscores": pl.DataFrame(
            {
                "game_id": [game_id],
                "player_id": ["4065648"],
                "player_name": ["Jayson Tatum"],
                "team_abbreviation": ["BOS"],
                "points": [points // 3],
                "minutes": [36.0],
                "field_goals_made": [12],
                "field_goals_attempted": [22],
                "three_point_field_goals_made": [4],
                "three_point_field_goals_attempted": [9],
                "free_throws_attempted": [6],
                "rebounds": [8],
                "offensive_rebounds": [1],
                "assists": [5],
                "turnovers": [3],
                "plus_minus": [7],
            }
        ),
        "lineups": pl.DataFrame(
            {
                "team_abbreviation": ["BOS"] * 6,
                "group_id": ["4065648-4433134-1628369-1628401-201143"] * 3 + ["4065648-4433134-1628369-201143-1630202"] * 3,
                "group_name": ["J. Tatum - D. White - J. Brown - A. Horford - J. Holiday"] * 3
                + ["J. Tatum - D. White - J. Brown - J. Holiday - K. Porzingis"] * 3,
                "group_set": ["Lineups"] * 6,
                "measure_type": ["Advanced", "Advanced", "Base", "Advanced", "Advanced", "Base"],
                "per_mode": ["Totals", "PerGame", "Totals", "Totals", "PerGame", "Totals"],
                "season_type": ["Regular Season"] * 6,
                "min": [18.0, 18.0, 18.0, 12.0, 12.0, 12.0],
                "poss": [38.0, 38.0, 38.0, 24.0, 24.0, 24.0],
                "off_rating": [114.0 + season - 2024, 114.0 + season - 2024, None, 109.0 + season - 2024, 109.0 + season - 2024, None],
                "def_rating": [108.0, 108.0, None, 111.0, 111.0, None],
                "net_rating": [6.0 + season - 2024, 6.0 + season - 2024, None, -2.0 + season - 2024, -2.0 + season - 2024, None],
            }
        ),
        "lineups_v3": pl.DataFrame(
            {
                "game_id": [game_id],
                "action_number": [1],
                "period": [1],
                "home_player_1": ["4065648"],
                "home_player_2": ["4433134"],
                "home_player_3": ["1628369"],
                "home_player_4": ["1628401"],
                "home_player_5": ["201143"],
                "away_player_1": ["2544"],
                "away_player_2": ["1641709"],
                "away_player_3": ["203076"],
                "away_player_4": ["1630559"],
                "away_player_5": ["1629060"],
            }
        ),
        "possessions_v3": pl.DataFrame(
            {
                "game_id": [game_id],
                "period": [1],
                "possession_number": [1],
                "start_order_index": [1],
                "end_order_index": [1],
                **{f"off_player_{index}": [value] for index, value in enumerate(["4065648", "4433134", "1628369", "1628401", "201143"], 1)},
                **{f"def_player_{index}": [value] for index, value in enumerate(["2544", "1641709", "203076", "1630559", "1629060"], 1)},
            }
        ),
        "game_rosters": pl.DataFrame(
            {
                "game_id": [game_id] * 10,
                "athlete_id": ["4065648", "4433134", "1628369", "1628401", "201143", "2544", "1641709", "203076", "1630559", "1629060"],
                "athlete_display_name": [
                    "Jayson Tatum",
                    "Derrick White",
                    "Jaylen Brown",
                    "Al Horford",
                    "Jrue Holiday",
                    "LeBron James",
                    "Austin Reaves",
                    "Anthony Davis",
                    "Max Christie",
                    "Rui Hachimura",
                ],
                "athlete_position": ["SF", "SG", "SG", "C", "PG", "SF", "SG", "PF", "SG", "PF"],
                "team_abbreviation": ["BOS"] * 5 + ["LAL"] * 5,
                "starter": [True] * 10,
            }
        ),
    }


def test_nba_connector_translates_seasons_normalizes_and_partitions(tmp_path: Path, monkeypatch) -> None:
    connector = SportsDataverseNBAConnector(Settings(data_dir=tmp_path))
    calls: list[tuple[str, list[int], bool]] = []
    progress: list[tuple[str, str, int, int, int]] = []

    def loader(dataset: str):
        def load(seasons: list[int], return_as_pandas: bool) -> pl.DataFrame:
            calls.append((dataset, seasons, return_as_pandas))
            return _nba_frames(seasons[0], 108)[dataset]

        return load

    monkeypatch.setattr(
        connector,
        "_loader_registry",
        lambda: {dataset: loader(dataset) for dataset in NBA_DEFAULT_DATASETS},
    )
    manifests = connector.sync([2025], NBA_DEFAULT_DATASETS, progress_callback=lambda *event: progress.append(event))

    assert {item.dataset for item in manifests} == set(NBA_DEFAULT_DATASETS)
    assert all(item.sport == "nba" and item.season == 2025 and item.sha256 for item in manifests)
    assert all(call[1:] == ([2025], False) for call in calls)
    assert progress[0] == ("downloading", "play_by_play", 2025, 0, 4)
    assert progress[-1] == ("downloaded", "player_boxscores", 2025, 4, 4)
    assert {event[0] for event in progress} == {"downloading", "processing", "downloaded"}
    pbp = connector.load(next(item for item in manifests if item.dataset == "play_by_play"))
    assert {"season", "play_id", "description", "period", "clock", "team_abbreviation"} <= set(pbp.columns)
    with pytest.raises(ValueError, match="cannot load nfl"):
        connector.load(manifests[0].model_copy(update={"sport": "nfl"}))


def test_nba_connector_keeps_core_data_when_optional_release_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    connector = SportsDataverseNBAConnector(Settings(data_dir=tmp_path))

    def unavailable(_seasons: list[int], return_as_pandas: bool) -> pl.DataFrame:
        assert return_as_pandas is False
        raise SeasonNotFoundError("season is not published")

    monkeypatch.setattr(
        connector,
        "_loader_registry",
        lambda: {
            "play_by_play": lambda seasons, return_as_pandas: _nba_frames(seasons[0], 108)["play_by_play"],
            "player_crosswalk": unavailable,
        },
    )

    manifests = connector.sync([2026], ["play_by_play", "player_crosswalk"])

    assert [(item.dataset, item.season) for item in manifests] == [("play_by_play", 2026)]


def test_nba_subject_options_are_limited_to_franchises_and_their_players() -> None:
    plugin = NBAPlugin()
    options = plugin.analysis_options(
        [],
        {
            "teams": pl.DataFrame(
                {
                    "team_abbreviation": ["BOS", "EAST", "RISING"],
                    "team_name": ["Boston Celtics", "Eastern Conference All-Stars", "Rising Stars"],
                }
            )
        },
    )
    players = plugin.resolve_players(
        "",
        [
            (
                2025,
                pl.DataFrame(
                    {
                        "player_id": ["4065648", "4065648", "exhibition-only"],
                        "player_name": ["Jayson Tatum", "Jayson Tatum", "Exhibition Player"],
                        "team_abbreviation": ["BOS", "EAST", "RISING"],
                    }
                ),
            )
        ],
    )

    assert len(options.teams) == 30
    assert {team.value for team in options.teams} >= {"BOS", "LAL", "OKC"}
    assert not {"EAST", "WEST", "RISING"} & {team.value for team in options.teams}
    assert [(player.name, player.teams) for player in players] == [("Jayson Tatum", ["BOS"])]


def test_team_and_player_nba_investigations_share_the_nfl_flow(tmp_path: Path, monkeypatch) -> None:
    application = AnalystApplication(Settings(data_dir=tmp_path, foundry_endpoint=""))
    connector = application.connectors["nba"]
    for season, points in ((2024, 105), (2025, 114)):
        for dataset, frame in _nba_frames(season, points).items():
            source = tmp_path / f"{dataset}-{season}.parquet"
            frame.write_parquet(source)
            application.store.save_manifest(connector.register_local(source, season, dataset))

    scope = AnalysisScope(
        team="BOS",
        baseline=AnalysisWindow(season=2024, segment="regular_season"),
        comparison=AnalysisWindow(season=2025, segment="regular_season"),
        season_type="ALL",
        comparison_design="season_segments",
    )
    team = application.investigate(
        AnalysisRequest(
            sport="nba",
            subject=AnalysisSubject(type="team", id="BOS"),
            question="How did Boston's scoring change?",
            scope=scope,
            analysis_domain="offense",
            metrics=["points_per_game", "effective_fg_pct"],
        )
    )
    player = application.investigate(
        AnalysisRequest(
            sport="nba",
            subject=AnalysisSubject(type="player", id="4065648", team_id="BOS", display_name="Jayson Tatum"),
            question="How did Tatum's scoring change?",
            scope=scope,
            analysis_domain="scoring",
            metrics=["points_per_game", "true_shooting_pct"],
        )
    )
    shooting = application.investigate(
        AnalysisRequest(
            sport="nba",
            subject=AnalysisSubject(type="team", id="BOS"),
            question="How did Boston's shot profile change?",
            scope=scope,
            analysis_domain="shooting",
            metrics=["effective_fg_pct", "three_point_rate"],
        )
    )
    assert player.run.subject and player.run.subject.display_name == "Jayson Tatum"
    lineup = application.investigate(
        AnalysisRequest(
            sport="nba",
            subject=AnalysisSubject(type="team", id="BOS"),
            question="How did Boston's lineup performance change across seasons?",
            scope=AnalysisScope(
                team="BOS",
                baseline=AnalysisWindow(season=2024, segment="full_season"),
                comparison=AnalysisWindow(season=2025, segment="full_season"),
                season_type="ALL",
                comparison_design="full_seasons",
            ),
            analysis_domain="lineups",
            metrics=["lineup_net_rating", "lineup_off_rating", "lineup_def_rating"],
        )
    )

    assert team.run.sport == player.run.sport == "nba"
    assert team.aggregate_evidence and player.aggregate_evidence
    assert {item.tool for item in team.executions} >= {"analyze_game_trends", "rank_game_outliers", "benchmark_against_league"}
    assert any(item.tool == "compare_player_usage" for item in player.executions)
    assert any(item.tool == "compare_shot_profiles" for item in shooting.executions)
    assert any(item.metric == "shot_zone_share" for item in shooting.aggregate_evidence)
    assert team.charts[0].specification["usermeta"]["chartKind"] == "metric-rows"
    assert {item.window for item in team.play_evidence} == {"baseline", "comparison"}
    assert all(item.selection_reason and item.selector_version == "diverse-v1" for item in team.play_evidence)
    assert {item.evidence_role for item in team.play_evidence} <= {"typical", "metric_example", "supports_change", "counterexample"}
    representative_tool = next(item for item in team.executions if item.tool == "find_representative_possessions")
    assert [window["season"] for window in representative_tool.parameters["windows"]] == [2024, 2025]
    assert representative_tool.parameters["selector_version"] == "diverse-v1"
    assert [chart.title for chart in lineup.charts] == [
        "NBA range endpoints",
        "Season-by-season Lineup net rating",
        "Five-player lineup performance",
    ]
    assert all(chart.specification["data"]["values"] for chart in lineup.charts)
    assert {row["season"] for row in lineup.charts[1].specification["data"]["values"]} == {2024, 2025}
    assert lineup.charts[1].specification["encoding"]["tooltip"] == [
        {"field": "season", "type": "ordinal", "title": "Season"},
        {"field": "series", "type": "nominal", "title": "Metric"},
        {"field": "value", "type": "quantitative", "title": "Lineup net rating"},
    ]
    lineup_tool = next(item for item in lineup.executions if item.tool == "analyze_lineup_performance")
    assert lineup_tool.parameters["canonicalization"] == "advanced/preferred-per-mode/unique-group-v1"
    units = [item for item in lineup.aggregate_evidence if item.metric == "lineup_unit"]
    assert units and all(item.context["players"] and item.context["possessions"] for item in units)
    assert any("J. Tatum" in claim.statement for claim in lineup.claims)
    net_rating = next(item for item in lineup.aggregate_evidence if item.metric == "lineup_net_rating")
    assert net_rating.sample_size == 62
    assert net_rating.unit == "per 100 possessions"
    assert team.play_evidence[0].visualization.sport == "nba"
    assert team.play_evidence[0].visualization.shot_x is not None
    made_shot = next(item for item in team.play_evidence if "makes 26-foot" in item.description)
    assert made_shot.visualization.shot_result == "Made"
    assert made_shot.visualization.shot_distance == 26
    assert (made_shot.visualization.shot_x, made_shot.visualization.shot_y) == (8.0, 23.0)
    assert made_shot.visualization.shot_coordinate_system == "court_feet"
    assert made_shot.visualization.secondary_player_name == "Derrick White"
    assert made_shot.visualization.secondary_player_role == "assist"
    assert made_shot.visualization.game_seconds_remaining == 2862.0
    assert made_shot.visualization.quarter_seconds_remaining == 702.0
    assert made_shot.visualization.game_date and made_shot.visualization.game_date.endswith("-11-01")
    assert made_shot.visualization.home_team_name == "Celtics"
    assert made_shot.visualization.away_team_name == "Lakers"
    enriched = next(item for item in team.play_evidence if item.visualization.possession_number == 1)
    assert len(enriched.visualization.offense_player_ids) == 5
    assert enriched.visualization.offense_names == ["Jayson Tatum", "Derrick White", "Jaylen Brown", "Al Horford", "Jrue Holiday"]
    assert enriched.visualization.offense_positions[0] == "SF"
    assert enriched.visualization.defense_names[0] == "LeBron James"
    assert "game_rosters" in enriched.visualization.source_packages
    assert {item.sport for item in team.dataset_manifests} == {"nba"}
    assert {item.run.subject.type for item in application.store.list_investigation_summaries(sport="nba")} == {
        "team",
        "player",
    }
    report = (tmp_path / "investigations" / team.run.investigation_id / "report.html").read_text(encoding="utf-8")
    assert "--team-primary:#007A33" in report
    assert "--team-secondary:#BA9653" in report
    with pytest.raises(KeyError):
        application.store.manifest_for_season(2025, sport="nfl")

    client = TestClient(create_app(application))
    assert {item["value"] for item in client.get("/api/sports").json()} == {"nfl", "nba"}
    options = client.get("/api/sports/nba/options").json()
    assert options["available_seasons"] == [2024, 2025]
    assert {item["value"] for item in options["subject_types"]} == {"team", "player"}
    assert "regular_season" in options["segment_availability"]["2025"]
    assert options["dataset_min_seasons"]["rosters"] == 2025
    assert options["dataset_min_seasons"]["lineups"] == 2008
    assert options["dataset_min_seasons"]["stats_rosters"] == 1997
    assert options["dataset_min_seasons"]["player_crosswalk"] == 2026
    assert options["dataset_available_seasons"]["stats_rosters"] == list(range(1997, 2027))
    assert options["syncable_seasons"][0] == 2027
    assert options["syncable_seasons"][-1] == 1996
    assert "stats_game_rosters" in options["syncable_datasets"]
    assert "lineups_v3" not in options["syncable_datasets"]
    assert "possessions_v3" not in options["syncable_datasets"]
    progress_manifests = application.store.manifests(sport="nba")[:2]

    def progress_sync(_seasons, _datasets, progress_callback):
        progress_callback("downloading", "play_by_play", 2024, 0, 2)
        progress_callback("processing", "play_by_play", 2024, 0, 2)
        progress_callback("downloaded", "play_by_play", 2024, 1, 2)
        progress_callback("downloading", "schedules", 2024, 1, 2)
        progress_callback("processing", "schedules", 2024, 1, 2)
        progress_callback("downloaded", "schedules", 2024, 2, 2)
        return progress_manifests

    monkeypatch.setattr(connector, "sync", progress_sync)
    application.sync([2024], "nba-progress", ["play_by_play", "schedules"], "nba")
    sync_events = application.events.events("nba-progress")
    sync_progress = [float(event["progress"]) for event in sync_events]
    assert sync_progress == sorted(sync_progress)
    assert {event["stage"] for event in sync_events} >= {"downloading", "processing", "downloaded", "registering", "complete"}
    assert any("Play By Play" in str(event["message"]) and "1 of 2" in str(event["message"]) for event in sync_events)
    synced: dict[str, object] = {}

    def capture_sync(seasons, _job_id, datasets, sport):
        synced.update(seasons=seasons, datasets=datasets, sport=sport)
        return []

    monkeypatch.setattr(application, "sync", capture_sync)
    full_sync = client.post(
        "/api/datasets/nba/sync",
        json={"seasons": options["syncable_seasons"], "datasets": options["syncable_datasets"]},
    )
    assert full_sync.status_code == 202
    assert full_sync.json()["timeout_seconds"] > application.settings.event_stream_timeout_seconds
    assert synced == {
        "seasons": options["syncable_seasons"],
        "datasets": options["syncable_datasets"],
        "sport": "nba",
    }
    assert client.get("/api/investigations", params={"sport": "nfl"}).json() == []
    assert application.query_sql("SELECT count(*) AS plays FROM pbp", sport="nba") == [{"plays": 4}]
    with pytest.raises(ValueError, match="no datasets"):
        application.query_sql("SELECT count(*) FROM pbp", sport="nfl")
