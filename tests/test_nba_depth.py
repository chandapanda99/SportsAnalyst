"""NBA depth: rebuilt lineups, true usage and per-100 rates, game-trend patterns, official shot distances, season labels."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
from test_nba_analysis import SHOOTER, _data, _manifest, _request

from sports_analyst.application.preparation import reusable
from sports_analyst.config import Settings
from sports_analyst.datasets.nba import SEASON_LABEL_MARKER, SportsDataverseNBAConnector, loader_season
from sports_analyst.models import AnalysisSubject
from sports_analyst.plugins.nba import NBAPlugin, _metric
from sports_analyst.plugins.nba_context import change_point, rolling_mean, trend_pattern
from sports_analyst.plugins.nba_lineups import reconstruct_lineups

GS = [f"g{index}" for index in range(1, 7)]
BOS = [f"b{index}" for index in range(1, 7)]


def _lineup_box() -> pl.DataFrame:
    return pl.DataFrame({
        "game_id": ["L1"] * 12, "player_id": GS + BOS, "player_name": [name.upper() for name in GS + BOS],
        "team_abbreviation": ["GS"] * 6 + ["BOS"] * 6, "starter": [True] * 5 + [False] + [True] * 5 + [False],
        "minutes": [30.0] * 12,
    })


def _lineup_pbp() -> pl.DataFrame:
    events = [
        # period, clock, team, type, text, athlete 1, athlete 2, home score, away score, shooting
        (1, "11:00", "GS", "Jump Shot", "g1 makes 10-foot jumper", "g1", None, 2, 0, True),
        (1, "10:00", "BOS", "Jump Shot", "b1 misses 12-foot jumper", "b1", None, 2, 0, True),
        (1, "10:00", "GS", "Defensive Rebound", "g2 defensive rebound", "g2", None, 2, 0, False),
        (1, "9:00", "GS", "Substitution", "g6 enters the game for g5", "g6", "g5", 2, 0, False),
        (1, "8:00", "GS", "Jump Shot", "g6 makes 25-foot three point jumper", "g6", None, 5, 0, True),
        (1, "7:00", "BOS", "Bad Pass Turnover", "b2 bad pass turnover", "b2", None, 5, 0, False),
        # Period 2 opens with g5 back on: credited before any substitution brings him in.
        (2, "11:30", "GS", "Layup Shot", "g5 makes layup", "g5", None, 7, 0, True),
        (2, "11:00", "GS", "Substitution", "g6 enters the game for g3", "g6", "g3", 7, 0, False),
        (2, "10:00", "BOS", "Jump Shot", "b3 makes 8-foot jumper", "b3", None, 7, 2, True),
        # Period 3 credits six different Golden State players before any substitution: unresolvable.
        *[(3, "11:00", "GS", "Defensive Rebound", f"{player} defensive rebound", player, None, 7, 2, False) for player in GS],
        (3, "10:00", "BOS", "Jump Shot", "b1 makes 9-foot jumper", "b1", None, 7, 4, True),
    ]
    return pl.DataFrame([
        {"game_id": "L1", "play_id": str(number), "period": period, "clock": clock, "team_abbreviation": team, "type_text": kind,
         "description": text, "athlete_id_1": first, "athlete_id_2": second, "home_score": home, "away_score": away,
         "shooting_play": shooting, "home_team_abbrev": "GS", "away_team_abbrev": "BOS"}
        for number, (period, clock, team, kind, text, first, second, home, away, shooting) in enumerate(events, 1)
    ])


def test_lineups_are_rebuilt_from_substitutions_and_unresolved_periods_are_excluded():
    units, coverage = reconstruct_lineups(_lineup_pbp(), _lineup_box())
    assert coverage["periods"] == 3 and coverage["resolved_periods"] == 2 and coverage["resolved_share"] == pytest.approx(2 / 3, abs=1e-4)
    rows = {row["group_id"]: row for row in units.iter_rows(named=True)}
    starters = rows["g1-g2-g3-g4-g5"]
    # Period 1 until the 9:00 substitution plus period 2 until 11:00: 4 points on 2 possessions; 1 opponent possession, 0 allowed.
    assert starters["min"] == pytest.approx(4.0)
    assert (starters["points_for"], starters["points_against"], starters["off_rating"], starters["def_rating"]) == (4, 0, 200, 0)
    assert starters["group_name"] == "G1 - G2 - G3 - G4 - G5"
    bench = rows["g1-g2-g3-g4-g6"]
    assert (bench["points_for"], bench["off_rating"], bench["min"]) == (3, 300, pytest.approx(2.0))
    assert "g1-g2-g4-g5-g6" not in rows  # no offensive possession recorded for that five
    boston = rows["b1-b2-b3-b4-b5"]
    assert boston["points_against"] == 7 and boston["points_for"] == 2  # period-3 basket is excluded with its period
    assert boston["off_rating"] == pytest.approx(100 * 2 / 3) and boston["def_rating"] == pytest.approx(100 * 7 / 3)


def test_date_segments_fall_back_from_the_aggregate_package_to_rebuilt_lineups():
    plugin = NBAPlugin()
    request = _request(AnalysisSubject(type="team", id="GSW"), "lineups", metrics=["lineup_net_rating"])
    supplemental = {
        "player_boxscores": {2025: _lineup_box()},
        "schedules": {2025: pl.DataFrame({"game_id": ["L1"], "game_date": [date(2024, 10, 25)], "season_type": [2],
                                          "notes_headline": [""]})},
        "lineups": {2025: pl.DataFrame({"team_abbreviation": ["GSW"], "group_id": ["x"], "group_name": ["X"], "min": [1.0],
                                        "poss": [2.0], "net_rating": [1.0], "season_type": ["Regular Season"]})},
    }
    frames, source = plugin._lineup_windows(request, {2025: _lineup_pbp()}, supplemental, [(2025, "opening_month")])
    assert source["source"] == "play_by_play_reconstruction_v1" and source["coverage"]["resolved_periods"] == 2
    assert set(frames[0]["team_abbreviation"]) == {"GSW"}
    player = _request(AnalysisSubject(type="player", id="g6", team_id="GSW"), "lineups", metrics=["lineup_net_rating"])
    frames, _source = plugin._lineup_windows(player, {2025: _lineup_pbp()}, supplemental, [(2025, "opening_month")])
    assert frames[0]["group_id"].to_list() == ["g1-g2-g3-g4-g6"]
    frames, source = plugin._lineup_windows(request, {2025: _lineup_pbp()}, supplemental, [(2025, "regular_season")])
    assert source == {"source": "nba_stats_lineups"} and frames[0]["group_id"].to_list() == ["x"]


def test_usage_rate_and_per_100_rates_use_the_team_same_game_row():
    box = {"game_id": ["G1", "G1"], "team_abbreviation": ["GS", "BOS"], "team_id": ["9", "2"], "opponent_team_id": ["2", "9"],
           "field_goals_attempted": [80, 85], "free_throws_attempted": [20, 15], "offensive_rebounds": [10, 9],
           "turnovers": [13, 11], "total_turnovers": [14, 12], "team_score": [110, 100], "opponent_team_score": [100, 110]}
    players = pl.DataFrame({"game_id": ["G1", "G1"], "player_id": [SHOOTER, "201"], "team_abbreviation": ["GS", "GS"],
                            "minutes": [36.0, 204.0], "field_goals_attempted": [20, 60], "free_throws_attempted": [10, 10],
                            "turnovers": [4, 9], "points": [30, 80], "assists": [5, 20], "rebounds": [8, 30],
                            "three_point_field_goals_made": [3, 9], "field_goals_made": [10, 31], "offensive_rebounds": [1, 9]})
    supplemental = {"team_boxscores": {2025: pl.DataFrame(box)}, "player_boxscores": {2025: players},
                    "schedules": {2025: pl.DataFrame({"game_id": ["G1"], "game_date": [date(2024, 11, 1)], "season_type": [2],
                                                      "notes_headline": [""]})}}
    request = _request(AnalysisSubject(type="player", id=SHOOTER, team_id="GSW"), "usage")
    frame = NBAPlugin._window_frame(request, 2025, "full_season", supplemental)
    assert frame["tm_minutes"].to_list() == [240.0]
    usage = 100 * (20 + 0.44 * 10 + 4) * (240 / 5) / (36 * (80 + 0.44 * 20 + 14))
    assert _metric(frame, "usage_rate", "player") == pytest.approx(usage)
    possessions = ((80 - 10 + 14 + 0.44 * 20) + (85 - 9 + 12 + 0.44 * 15)) / 2
    on_court = possessions * 36 / 48
    assert _metric(frame, "points_per_100", "player") == pytest.approx(100 * 30 / on_court)
    assert _metric(frame, "assists_per_100", "player") == pytest.approx(100 * 5 / on_court)
    assert _metric(frame.drop("tm_possessions"), "rebounds_per_100", "player") is None  # missing context is not zero
    definition = NBAPlugin().explain_metric("usage_rate")
    assert "team minutes" in definition.formula


def test_game_trend_helpers_and_report_evidence():
    assert rolling_mean([1, 2, 3, 4, 5, 6]) == [None, None, None, None, 3, 4]
    assert trend_pattern([0.0] * 10, [1.0] * 10)["classification"] == "sustained"
    mixed = trend_pattern([0.0] * 20, [2.0] * 5 + [-1.0] * 5 + [1.0] * 5 + [-1.0] * 5)  # half the blocks follow the rise
    assert mixed["blocks"] == 4 and mixed["classification"] == "mixed"
    assert trend_pattern([0.0] * 8, [1.0] * 8) is None  # fewer than two blocks
    point = change_point([0.0] * 6 + [10.0] * 6)
    assert (point["index"], point["before"], point["after"]) == (6, 0.0, 10.0)
    datasets, manifests, supplemental = _data()
    result = NBAPlugin().analyze(_request(AnalysisSubject(type="team", id="GSW"), "defense"), datasets, manifests, supplemental, {})
    metrics = {item.metric for item in result.aggregate_evidence}
    assert "defensive_rating_rolling_average" in metrics
    assert "defensive_rating_change_point" not in metrics  # eight games cannot leave five on each side
    assert change_point([1.0] * 12) is None
    chart = next(chart for chart in result.charts if chart.title.startswith("Game-by-game"))
    kinds = {row["kind"] for row in chart.specification["data"]["values"]}
    assert kinds == {"Game", "5-game average"} and chart.specification["encoding"]["strokeDash"]["field"] == "kind"


def test_official_shot_distances_are_used_only_with_complete_coverage():
    datasets, manifests, supplemental = _data()
    games = [f"S{index}" for index in range(8)]
    stats_schedule = pl.DataFrame({"game_id": games, "game_date": supplemental["schedules"][2025]["game_date"],
                                   "season_type": [2] * 8, "notes_headline": [""] * 8})
    shots = pl.DataFrame({
        "game_id": [game for game in games for _ in range(3)], "team_abbreviation": ["GSW"] * 24,
        "player_id": ["1630000"] * 24, "shot_value": [3, 2, 2] * 8, "shot_distance": [25, 2, 9] * 8,
        "shot_result": ["Made", "Missed", "Made"] * 8,
    })
    supplemental = {**supplemental, "stats_shots": {2025: shots, 2026: shots}, "stats_schedules": {2025: stats_schedule, 2026: stats_schedule}}
    request = _request(AnalysisSubject(type="team", id="GSW"), "shooting")
    result = NBAPlugin().analyze(request, datasets, manifests, supplemental, {})
    profile_tool = next(item for item in result.executions if item.tool == "compare_shot_profiles")
    assert profile_tool.parameters["source"] == "nba_stats_shots"
    shares = {item.label: item.comparison_value for item in result.aggregate_evidence if item.metric == "shot_zone_share"}
    assert shares == {"Rim attempt share": pytest.approx(1 / 3, abs=1e-4), "Short midrange attempt share": pytest.approx(1 / 3, abs=1e-4),
                      "Three attempt share": pytest.approx(1 / 3, abs=1e-4)}
    partial = {**supplemental, "stats_shots": {2025: shots.filter(pl.col("game_id") != "S7"), 2026: shots}}
    result = NBAPlugin().analyze(request, datasets, manifests, partial, {})
    assert next(item for item in result.executions if item.tool == "compare_shot_profiles").parameters["source"] == "play_by_play"


def test_nba_stats_loaders_receive_start_years_and_old_packages_are_excluded(tmp_path: Path, monkeypatch):
    assert loader_season("stats_shots", 2025) == 2024 and loader_season("lineups", 2025) == 2024
    assert loader_season("play_by_play", 2025) == 2025
    connector = SportsDataverseNBAConnector(Settings(_env_file=None, data_dir=tmp_path))
    calls = []

    stamp_offset = {"value": 1}

    def load(seasons, return_as_pandas):
        calls.append(seasons)
        # Published NBA Stats assets stamp the season's END year.
        return pl.DataFrame({"game_id": ["0022400001"], "team_abbreviation": ["GSW"], "shot_value": [3],
                             "season": [seasons[0] + stamp_offset["value"]]})

    monkeypatch.setattr(connector, "_loader_registry", lambda: {"stats_shots": load})
    manifest = connector.sync([2025], ["stats_shots"])[0]
    assert calls == [[2024]] and manifest.coverage[SEASON_LABEL_MARKER] == 1 and manifest.season == 2025
    assert "source_season" in manifest.columns  # lets research reuse the package instead of downloading it again
    assert connector.load(manifest)["source_season"].to_list() == [2025]
    stamp_offset["value"] = 2  # an asset stamped with another season is never relabelled
    mismatched = connector.sync([2025], ["stats_shots"])[0]
    # The refresh is refused and the last good download is kept, still stamped 2025.
    assert mismatched.availability == "partial" and mismatched.coverage["retained_previous_data"] == 1
    assert connector.load(mismatched)["source_season"].to_list() == [2025]
    stale = manifest.model_copy(update={"coverage": {}})
    assert reusable(manifest, 2027) and not reusable(stale, 2027)
    datasets, manifests, supplemental = _data()
    supplemental = {**supplemental, "stats_shots": {2025: pl.DataFrame({"game_id": ["x"]})}}
    result = NBAPlugin().analyze(_request(AnalysisSubject(type="team", id="GSW"), "shooting"), datasets, manifests, supplemental,
                                 {"stats_shots": {2025: _manifest("stats_shots", 2025)}})
    assert any("stats_shots" in caveat and "Download them again" in caveat for caveat in result.caveats)
