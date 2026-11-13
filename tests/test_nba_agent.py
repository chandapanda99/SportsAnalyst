"""The analysis agent's own NBA data access: franchise spellings, named segments, appearances and guidance."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import polars as pl
import pytest
from test_nba_analysis import _manifest

from sports_analyst.analysis.agents import _fallback_synthesis
from sports_analyst.analysis.evaluation import evaluation_cases
from sports_analyst.analysis.instructions import analysis_guidance, domain_guidance
from sports_analyst.analysis.research import dictionary, semantics
from sports_analyst.analysis.research.contracts import contract
from sports_analyst.analysis.scoped_data import ScopedData
from sports_analyst.config import Settings
from sports_analyst.datasets.snapshots import sha256_file
from sports_analyst.models import AggregateEvidence, AnalysisRequest, AnalysisWindow
from sports_analyst.plugins.nba import NBAPlugin

GAMES = {"S1": (date(2024, 10, 25), 2, True), "S2": (date(2024, 12, 20), 2, True), "S3": (date(2025, 4, 25), 3, True),
         "S4": (date(2025, 1, 5), 2, False)}


def _write(tmp_path, dataset, frame):
    path = tmp_path / f"{dataset}.parquet"
    frame.write_parquet(path)
    return _manifest(dataset, 2025).model_copy(update={"manifest_id": f"{dataset}-2025", "local_path": str(path),
                                                        "sha256": sha256_file(path), "columns": frame.columns})


@pytest.fixture
def catalog(tmp_path):
    schedule = pl.DataFrame({"game_id": list(GAMES), "game_date": [value[0] for value in GAMES.values()],
                             "season_type": [value[1] for value in GAMES.values()],
                             "status_type_completed": [value[2] for value in GAMES.values()],
                             "home_team_abbrev": ["GS"] * 4, "away_team_abbrev": ["BOS"] * 4})
    team_box = pl.DataFrame({"game_id": [game for game in GAMES for _ in range(2)], "team_abbreviation": ["GS", "BOS"] * 4,
                             "team_score": [110, 100] * 4, "season_type": [GAMES[game][1] for game in GAMES for _ in range(2)]})
    player_box = pl.DataFrame({"game_id": ["S1", "S2"], "player_id": ["100", "100"], "team_abbreviation": ["GS", "GS"],
                               "points": [20, None], "minutes": [30.0, None], "did_not_play": [False, True]})
    return [_write(tmp_path, "schedules", schedule), _write(tmp_path, "team_boxscores", team_box),
            _write(tmp_path, "player_boxscores", player_box)], tmp_path


def _scoped(catalog, subject, season_type="ALL", segment="regular_season"):
    manifests, tmp_path = catalog
    from sports_analyst.storage.persistence import LocalPersistenceBackend

    app = SimpleNamespace(settings=Settings(_env_file=None, data_dir=tmp_path),
                          store=SimpleNamespace(manifests=lambda **kwargs: manifests, materialize_manifest=lambda item: item,
                                                persistence=LocalPersistenceBackend()))
    request = AnalysisRequest(
        sport="nba", subject=subject, question="How did the regular season compare with the opening month?",
        analysis_domain="scoring" if subject["type"] == "player" else "offense",
        scope={"team": "GSW", "comparison_design": "season_segments", "season_type": season_type,
               "baseline": AnalysisWindow(season=2025, segment="opening_month").model_dump(),
               "comparison": AnalysisWindow(season=2025, segment=segment).model_dump()})
    return ScopedData(app, request, None)


def _count(scoped, dataset, window):
    result = scoped.aggregate(f"{dataset}-2025", window, [], [{"op": "count"}], [])
    return result["rows"][0]["m0"]


def test_agent_scoped_data_matches_espn_team_codes_and_named_segments(catalog):
    scoped = _scoped(catalog, {"type": "team", "id": "GSW"})
    # Opening month holds only S1; the regular season holds S1 and S2 but not the playoff game or unfinished S4.
    assert _count(scoped, "team_boxscores", "baseline") == 1
    assert _count(scoped, "team_boxscores", "comparison") == 2
    extract = scoped.extract("team_boxscores-2025", "comparison", ["game_id", "team_score"], [])
    assert sorted(row["game_id"] for row in extract["rows"]) == ["S1", "S2"]
    base = scoped.executor.base(scoped.manifests["team_boxscores-2025"], {"team_score"}, "comparison").collect()
    assert base.height == 2
    # A full season under POST is the playoffs only, matching the NBA plugin.
    assert _count(_scoped(catalog, {"type": "team", "id": "GSW"}, "POST", "full_season"), "team_boxscores", "comparison") == 1
    assert _count(_scoped(catalog, {"type": "team", "id": "GSW"}, "ALL", "full_season"), "team_boxscores", "comparison") == 3


def test_agent_scoped_data_excludes_did_not_play_rows(catalog):
    scoped = _scoped(catalog, {"type": "player", "id": "100", "team_id": "GSW"})
    result = scoped.aggregate("player_boxscores-2025", "comparison", [], [{"op": "count"}, {"op": "mean", "field": "points"}], [])
    assert result["rows"][0]["m0"] == 1 and result["rows"][0]["m1"] == 20
    base = scoped.executor.base(scoped.manifests["player_boxscores-2025"], {"points"}, "comparison").collect()
    assert base.height == 1


def test_rate_names_do_not_collide_with_nba_metrics_and_shots_flag_free_throws():
    names = {name for name, _unit in semantics.RATE_PAIRS.values()}
    assert {"three_point_pct", "free_throw_pct", "field_goal_pct"} <= names
    assert not names & {"three_point_rate", "free_throw_rate"}  # NBA metrics: attempt share and FTA/FGA
    shots = _manifest("shots", 2025).model_copy(update={"columns": ["game_id", "play_id", "type_text"]})
    assert any("free throw" in note.lower() for note in contract(shots).restrictions)
    assert "free throw" in dictionary.describe("nba", "shots", "type_text")["description"].lower()


def test_nba_guidance_covers_data_use_and_every_domain():
    text = analysis_guidance("nba", "offense")
    for phrase in ("run_sport_analysis", "clutch", "did-not-play", "UTAH", "crosswalk", "free throws", "nba cup"):
        assert phrase.lower() in text.lower(), phrase
    for domain in ("shooting", "lineups", "usage", "rebounding", "playmaking", "turnovers", "impact", "scoring"):
        assert domain_guidance("nba", domain), domain
    assert "tackle" not in domain_guidance("nba", "usage")


def test_planner_sees_current_nba_analyses_and_fallback_reports_them():
    tools = {tool.name: tool.description for tool in NBAPlugin().tools()}
    assert "clutch" in tools["analyze_situational_split"] and "shot mix" in tools["decompose_metric_change"]
    assert "usage rate" in tools["compare_player_usage"] and "rebuilt" in tools["analyze_lineup_performance"]

    def item(metric, value, label=None, context=None):
        return AggregateEvidence(evidence_id=metric, metric=metric, label=label or metric, value=value, baseline_value=0.0,
                                 comparison_value=value, unit="points per field-goal attempt", sample_size=400,
                                 row_set_sha256="x", dataset_manifest_ids=["m"], tool_execution_id="e", context=context or {})

    aggregate = [item("effective_fg_pct", 0.03, "Effective field-goal percentage"),
                 item("shot_mix_effect", 0.01, "Shot-mix effect on points per shot"),
                 item("shot_conversion_effect", 0.05, "Shot-making effect on points per shot"),
                 item("effective_fg_pct_trend_pattern", 0.8, "Game-block change pattern: sustained", {"classification": "sustained"})]
    draft = _fallback_synthesis("Did shot making or shot selection drive it?", "GSW", AnalysisWindow(season=2025, segment="regular_season"),
                                AnalysisWindow(season=2026, segment="regular_season"), aggregate, analysis_domain="shooting", sport="nba")
    assert "shot-making" in draft.summary.lower() and "sustained" in draft.summary
    assert any("shot_conversion_effect" in claim.evidence_ids for claim in draft.claims)


def test_nba_evaluation_cases_cover_new_analyses():
    cases = [case for case in evaluation_cases() if case.sport == "nba"]
    tools = {tool for case in cases for tool in case.expected_tools}
    assert {"analyze_situational_split", "decompose_metric_change", "compare_player_usage", "analyze_lineup_performance"} <= tools
    assert any("clutch" in case.question.lower() for case in cases)
