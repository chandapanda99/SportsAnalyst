"""Order-sensitive feature contracts: evidence, game context and normalized snapshots."""

from dataclasses import replace
from io import BytesIO

import polars as pl
import pytest
from test_nba import _nba_frames
from test_nfl_plugin import manifest
from test_soccer import _summary

from sports_analyst.analysis.evidence import EvidenceCandidate, select_diverse_evidence
from sports_analyst.datasets.nba import SportsDataverseNBAConnector
from sports_analyst.datasets.soccer.connector import SOCCER_COMPETITIONS, SportsDataverseSoccerConnector, _snapshot_order
from sports_analyst.models import AnalysisRequest, AnalysisSubject
from sports_analyst.plugins.nba import NBAPlugin, _metric_game_rows
from sports_analyst.plugins.soccer import SoccerPlugin


def test_shared_evidence_selection_is_permutation_invariant_and_rejects_conflicts():
    candidates = [EvidenceCandidate(key=str(i), window=window, game_id=str(i), event_type="pass", payload={"id": i},
        outcome_value=float(i % 4), relevance=float(i % 2))
        for window in ("baseline", "comparison") for i in range(12)]
    expected = select_diverse_evidence(candidates)
    assert len(expected) == 8 and {item.candidate.window for item in expected} == {"baseline", "comparison"}
    assert select_diverse_evidence(list(reversed(candidates))) == expected
    assert select_diverse_evidence([*candidates, candidates[0]]) == expected
    with pytest.raises(ValueError, match="Conflicting evidence"):
        select_diverse_evidence([*candidates, replace(candidates[0], outcome_value=100.)])


def test_nba_reports_and_latest_lineup_context_do_not_depend_on_file_order():
    plugin = NBAPlugin()
    request = AnalysisRequest(sport="nba", question="Compare Boston's lineups", subject={"type": "team", "id": "BOS"},
        analysis_domain="lineups", metrics=["lineup_net_rating"],
        scope={"team": "BOS", "baseline_season": 2024, "comparison_season": 2025})
    normalized = {year: {name: SportsDataverseNBAConnector.normalize(frame, year, name)
                        for name, frame in _nba_frames(year, points).items()}
                  for year, points in ((2024, 105), (2025, 114))}
    datasets = {year: frames["play_by_play"] for year, frames in normalized.items()}
    manifests = {year: manifest(year, frame.columns).model_copy(update={"sport": "nba"}) for year, frame in datasets.items()}
    supplemental = {name: {year: frames[name] for year, frames in normalized.items()}
                    for name in normalized[2024] if name != "play_by_play"}
    expected = plugin.analyze(request, datasets, manifests, supplemental)
    shuffled = plugin.analyze(request, {year: frame.reverse() for year, frame in datasets.items()}, manifests,
        {name: {year: frame.reverse() for year, frame in frames.items()} for name, frames in supplemental.items()})
    assert [item.model_dump() for item in shuffled.aggregate_evidence] == [item.model_dump() for item in expected.aggregate_evidence]
    assert [item.model_dump() for item in shuffled.play_evidence] == [item.model_dump() for item in expected.play_evidence]
    ties = {**supplemental, "team_boxscores": {**supplemental["team_boxscores"],
        2025: supplemental["team_boxscores"][2025].with_columns(pl.lit(114).alias("team_score")).reverse()}}
    tied_report = plugin.analyze(request.model_copy(update={"analysis_domain": "offense", "metrics": ["points_per_game"]}),
                                datasets, manifests, ties)
    assert next(item.value for item in tied_report.aggregate_evidence if item.metric == "points_per_game_league_rank") == 1
    rows = pl.DataFrame({"game_id": ["b", "a"], "team_score": [20, 10], "game_date": ["2025-02-01", "2025-01-01"]})
    assert [row["game_id"] for row in _metric_game_rows(rows, "points_per_game", "team")] == ["a", "b"]
    # A shuffled prior snapshot must not win over the latest eligible action.
    lineup = pl.concat([supplemental["lineups_v3"][2025].with_columns(
        pl.lit(action).alias("action_number"), pl.lit(4).alias("period"),
        pl.lit(player).alias("home_player_1")) for action, player in ((2, "latest"), (9, "future"), (1, "old"))])
    plays = plugin._representative_plays(request, datasets[2025], {"lineups_v3": {2025: lineup}}, manifests[2025])
    play = next(item for item in plays if item.play_id == 2)
    assert play.visualization.offense_player_ids[0] == "latest"
    ambiguous = pl.concat([lineup, lineup.head(1).with_columns(pl.lit("conflicting").alias("home_player_1"))])
    plays = plugin._representative_plays(request, datasets[2025], {"lineups_v3": {2025: ambiguous}}, manifests[2025])
    assert not next(item for item in plays if item.play_id == 2).visualization.offense_player_ids
    canonical = supplemental["lineups"][2025]
    bad = pl.concat([canonical, canonical.head(1).with_columns((pl.col("net_rating") + 1).alias("net_rating"))])
    with pytest.raises(ValueError, match="Conflicting NBA lineup"):
        plugin._scope_lineups(bad, AnalysisSubject(type="team", id="BOS"))


@pytest.mark.parametrize("competition", list(SOCCER_COMPETITIONS))
def test_soccer_snapshot_hashes_and_example_order_are_stable_across_leagues(competition):
    summary = _summary("match")
    summary["keyEvents"] = [
        {"id": "2", "type": {"text": "Goal"}, "text": "First recorded event", "clock": {"displayValue": "45+2'"}},
        {"id": "1", "type": {"text": "Goal"}, "text": "Second recorded event", "clock": {"displayValue": "45+2'"}},
    ]
    events = SportsDataverseSoccerConnector._parse_summary(summary, "key_events")
    events = events.with_columns(pl.lit("match").alias("game_id"))
    ordered = _snapshot_order(events, "key_events")
    shuffled = _snapshot_order(events.reverse().select(list(reversed(events.columns))), "key_events")
    before, after = BytesIO(), BytesIO()
    ordered.write_parquet(before)
    shuffled.write_parquet(after)
    assert before.getvalue() == after.getvalue()
    assert ordered["text"].to_list() == ["First recorded event", "Second recorded event"]
    schedule = pl.DataFrame({"event_id": ["b", "a"], "date": ["2025-02-01", "2025-01-01"],
        "home_team_id": ["1", "1"], "away_team_id": ["2", "2"], "status": ["STATUS_FINAL"] * 2,
        "home_score": [2, 1], "away_score": [0, 0], "competition": [competition] * 2})
    assert [row["game_id"] for row in SoccerPlugin._team_rows(schedule, "1")] == ["a", "b"]
    assert SoccerPlugin._team_rows(schedule, "1") == SoccerPlugin._team_rows(schedule.reverse(), "1")
