"""Major secondary-source acquisition, comparison and provenance contracts."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from sports_analyst.analysis.research.contracts import contract
from sports_analyst.config import Settings
from sports_analyst.datasets.soccer.connector import SportsDataverseSoccerConnector
from sports_analyst.datasets.soccer.enrichment import SoccerEnrichment, normalize_fotmob
from sports_analyst.datasets.soccer.open_events import OpenEvents
from sports_analyst.datasets.soccer.statistics import measured_value
from sports_analyst.models import AnalysisRequest
from sports_analyst.plugins.soccer import SoccerPlugin


@pytest.fixture
def source():
    return json.loads((Path(__file__).parent / "fixtures/soccer/fotmob_match.json").read_text(encoding="utf-8"))


def fixture(source):
    home, away = source["header"]["teams"]
    return {"event_id": "espn1", "date": source["general"]["matchTimeUTCDate"], "status": "STATUS_FINAL",
            "home_team": home["name"], "away_team": away["name"], "home_team_id": "1", "away_team_id": "2",
            "home_score": home["score"], "away_score": away["score"], "season": 2026, "competition": "eng.1"}


def test_fotmob_shots_match_exact_timeline_and_hydrate_old_report(source, tmp_path):
    from sports_analyst.datasets.soccer.shot_recap import hydrate_shots, match_shots
    from sports_analyst.models import PlayVisualization
    from sports_analyst.storage.local import LocalStore
    settings = Settings(data_dir=tmp_path, _env_file=None)
    connector = SportsDataverseSoccerConnector(settings)
    store = LocalStore(settings)
    rows = normalize_fotmob(source, fixture(source), "eng.1")
    frame = pl.from_dicts(rows, infer_schema_length=None)
    path = tmp_path / "analytics.parquet"
    frame.write_parquet(path)
    manifest = connector.manifest_for(path, "eng.1", 2026, "match_analytics", frame, 1, 1, 1)
    store.save_manifest(manifest)
    goal = source["content"]["shotmap"]["shots"][2]
    event = {"id":"native", "type":"Goal - Volley", "clock":"6'", "team_id":"1", "athlete_id":"native-player",
        "athlete_name":goal["playerName"], "period":1, "scoring_play":True}
    visual = PlayVisualization(sport="soccer", soccer_timeline=[event])
    hydrated = hydrate_shots(store, SimpleNamespace(season=2026, game_id="espn1"), "eng.1", visual)
    matched = match_shots(hydrated, "espn1")
    context = matched.soccer_timeline[0]
    assert context["spatial_provider"] == "fotmob"
    assert context["spatial_context"]["shot"]["goalCrossedZ"] == goal["goalCrossedZ"]
    assert context["spatial_event_id"] == str(goal["id"])
    assert not visual.soccer_analytics and "spatial_context" not in event
    # Same-minute ambiguity, wrong outcome, wrong game or initials cannot produce a link.
    duplicate = [{**row, "shots_json":json.dumps([s for s in json.loads(row["shots_json"]) for _ in (1,2)])} for row in rows]
    cases = [hydrated.model_copy(update={"soccer_analytics":duplicate}),
        hydrated.model_copy(update={"soccer_timeline":[{**event, "type":"Attempt Saved", "scoring_play":False}]}),
        hydrated.model_copy(update={"soccer_timeline":[{**event, "athlete_name":"D. Gomez"}]}),
        hydrated.model_copy(update={"soccer_timeline":[event, event]})]
    assert all("spatial_context" not in match_shots(case, "espn1").soccer_timeline[0] for case in cases)
    assert "spatial_context" not in match_shots(hydrated, "other-game").soccer_timeline[0]


def test_source_backed_match_preserves_broad_counters_and_native_player_identity(source):
    rows = normalize_fotmob(source, fixture(source), "eng.1")
    assert rows[0]["expected_goals"] == 1.32 and rows[0]["expected_goals_on_target"] == 1.18
    assert rows[0]["accurate_passes"] == 453 and rows[0]["total_passes"] == 522
    assert rows[0]["defensive_shot_blocks"] == 6 and rows[0]["blocked_shots"] == 2
    assert rows[0]["physical_metrics_distance_covered"] == 119127
    assert len(rows[0]["source_sha256"]) == 64
    shots = [shot for row in rows for shot in json.loads(row["shots_json"])]
    assert len(shots) == 3 and all("expectedGoalsOnTarget" in shot for shot in shots)
    people = [p for row in rows for p in json.loads(row["players_json"])]
    assert len(people) == 2 and all("provider_player_id" in p and "athlete_id" not in p for p in people)
    for field, value in [("home_score", 99), ("date", "2020-01-01"), ("home_team", "Unrelated school")]:
        with pytest.raises(ValueError, match="corroborate"):
            normalize_fotmob(source, {**fixture(source), field: value}, "eng.1")
    future = deepcopy(source)
    future["general"]["finished"] = False
    with pytest.raises(ValueError, match="Uncompleted"):
        normalize_fotmob(future, fixture(source), "eng.1")


def test_recorded_rates_use_paired_sums_and_do_not_zero_fill_missing_matches():
    rows = [{"game_id": "a"}, {"game_id": "b"}, {"game_id": "c"}]
    data = pl.DataFrame({"game_id": ["a", "b", "c"], "team_id": ["1"] * 3,
                         "accurate_passes": [1., 90., None], "total_passes": [2., 100., 20.]})
    assert measured_value("pass_completion_rate", rows, data, "1") == (91 / 102, 2)
    missing = data.with_columns(pl.lit(None).alias("accurate_passes"))
    assert measured_value("pass_completion_rate", rows, missing, "1") == (None, 0)
    with pytest.raises(ValueError, match="Duplicate"):
        measured_value("pass_completion_rate", rows, pl.concat([data, data]), "1")


def test_scoped_sync_reuses_raw_payloads_retains_last_good_and_discloses_failed_asa(tmp_path, monkeypatch, source):
    connector = SportsDataverseSoccerConnector(Settings(_env_file=None, data_dir=tmp_path))
    game = fixture(source)
    connector._scoreboard = lambda *a: pl.DataFrame([game, {**game, "event_id": "future", "status": "STATUS_SCHEDULED"}])
    calls = []

    def request(**kwargs):
        calls.append(kwargs)
        return {"leagues": [{"id": 47, "matches": [{"id": "4813647", "home": source["header"]["teams"][0],
            "away": source["header"]["teams"][1], "status": {"finished": True, "utcTime": game["date"]}}]}]}

    provider = SimpleNamespace(fotmob_matches=request, fotmob_match_details=lambda **k: deepcopy(source))
    monkeypatch.setattr("sports_analyst.datasets.soccer.enrichment.load_optional_module", lambda *a: provider)
    manifests = connector.sync([2026], ["match_analytics"], competition="eng.1", team_id="1")
    manifest = manifests[0]
    assert manifest.coverage["expected_matches"] == 1 and manifest.coverage["recorded_matches"] == 1
    assert manifest.coverage["expected_goals_rows"] == 2 and manifest.partition_key == "team:1"
    assert manifest.availability == "available" and "FOTMOB" in manifest.attribution
    assert connector.load(manifest).height == 2
    connector.sync([2026], ["match_analytics"], competition="eng.1", team_id="1")
    assert len(calls) == 1  # Successful historical/raw reads do not re-download.
    people = connector.sync([2026], ["match_players"], competition="eng.1", team_id="1")[0]
    assert people.row_count == 2 and contract(people).player_namespace == "fotmob"
    assert "athlete_id" not in people.columns
    monkeypatch.setattr(SoccerEnrichment, "match", lambda *a, **k: (_ for _ in ()).throw(OSError("source down")))
    retry = connector.sync([2026], ["match_analytics"], competition="eng.1", team_id="1")[0]
    assert retry.availability == "partial" and connector.load(retry).height == 2
    monkeypatch.setattr(SoccerEnrichment, "fetch", lambda *a, **k: (_ for _ in ()).throw(OSError("HTTP 500")))
    unavailable, counts = SoccerEnrichment(connector).asa_matches("usa.1", 2026, pl.DataFrame([game]))
    assert unavailable.is_empty() and counts["failed_requests"] == 1
    failed = connector.sync([2026], ["asa_analytics"], competition="usa.1", team_id="1")[0]
    assert failed.row_count == 0 and failed.availability == "source_unavailable"


def test_new_measurements_are_registered_cited_and_available_in_match_evidence(tmp_path, source):
    connector = SportsDataverseSoccerConnector(Settings(_env_file=None, data_dir=tmp_path))
    schedules, manifests, stats, analytics, source_manifests = {}, {}, {}, {}, {}
    for year, xgot in ((2025, .59), (2026, 1.18)):
        game = {**fixture(source), "date": f"{year}-03-01", "season": year}
        schedules[year] = pl.DataFrame([game])
        normalized = normalize_fotmob(source, fixture(source), "eng.1")
        normalized[0]["expected_goals_on_target"] = xgot
        analytics[year] = pl.from_dicts(normalized, infer_schema_length=None)
        stats[year] = pl.DataFrame({"game_id": ["espn1"], "team_id": ["1"],
                                   "accurate_passes": [9.], "total_passes": [10.]})
        path = tmp_path / f"schedule-{year}.parquet"
        schedules[year].write_parquet(path)
        manifests[year] = connector.manifest_for(path, "eng.1", year, "play_by_play", schedules[year])
        path = tmp_path / f"analytics-{year}.parquet"
        analytics[year].write_parquet(path)
        source_manifests[year] = connector.manifest_for(path, "eng.1", year, "match_analytics", analytics[year])
    request = AnalysisRequest(sport="soccer", question="Did possession control and shot execution improve?",
        subject={"type": "team", "id": "1"}, analysis_domain="control",
        scope={"team": "1", "competition": "eng.1", "season_type": "ALL", "comparison_design": "full_seasons",
               "baseline": {"season": 2025}, "comparison": {"season": 2026}},
        metrics=["pass_completion_rate", "fotmob_expected_goals_on_target_per_match"])
    result = SoccerPlugin().analyze(request, schedules, manifests,
        {"team_stats": stats, "match_analytics": analytics}, {"match_analytics": source_manifests})
    evidence = {item.metric: item for item in result.aggregate_evidence}
    assert evidence["pass_completion_rate"].comparison_value == .9
    assert evidence["fotmob_expected_goals_on_target_per_match"].value == .59
    assert evidence["fotmob_expected_goals_on_target_per_match"].context["provider"] == "fotmob"
    assert source_manifests[2026].manifest_id in evidence["fotmob_expected_goals_on_target_per_match"].dataset_manifest_ids
    assert result.play_evidence[0].visualization.soccer_analytics
    assert result.charts[0].evidence_ids
    monthly = [item for item in result.aggregate_evidence if item.metric == "soccer_monthly"]
    assert {item.context["group"]["month"] for item in monthly} == {"2025-03", "2026-03"}
    passing = [item for item in monthly if item.context["measure"]["field"] == "pass_completion_rate"]
    assert len(passing) == 2 and all(item.value == .9 and item.sample_size == 1 for item in passing)
    assert all(item.tool_execution_id == result.executions[0].execution_id for item in monthly)
    from sports_analyst.analysis.research.presentation import add_research_charts

    add_research_charts(result)
    assert any(chart.specification["usermeta"].get("comparisonKind") == "monthly-trend" for chart in result.charts)


def test_open_event_pipeline_preserves_native_events_and_versions_real_spadl_xt(tmp_path, monkeypatch):
    pytest.importorskip("kloppy")
    capture = json.loads((Path(__file__).parent / "fixtures/soccer/statsbomb_actions.json").read_text(encoding="utf-8"))
    game = capture["game"]
    connector = SportsDataverseSoccerConnector(Settings(_env_file=None, data_dir=tmp_path))
    source = OpenEvents(connector)
    primary = {"event_id": "espn-open", "date": game["match_date"],
        **{f"{side}_team": game[f"{side}_team"][f"{side}_team_name"] for side in ("home", "away")},
        "home_team_id": "1", "away_team_id": "2", "home_score": game["home_score"], "away_score": game["away_score"]}
    payloads = {"competitions.json": [{"competition_name": "Premier League", "season_name": "2015/2016",
                    "competition_gender": "male", "competition_id": 2, "season_id": 27}],
                "matches/2/27.json": [game], f"events/{game['match_id']}.json": capture["events"],
                f"lineups/{game['match_id']}.json": capture["lineups"]}
    monkeypatch.setattr(source.source, "fetch", lambda comp, year, function, params, refresh: payloads[params["resource"]])
    frame, counts = source.prepare("eng.1", 2016, pl.DataFrame([primary]))
    assert counts["recorded_matches"] == 1 and counts["failed_requests"] == 0
    assert frame.height == len(capture["events"]) and frame["xt"].is_not_null().sum() > 0
    assert len(frame["xt_model_sha256"][0]) == 64 and "athlete_id" not in frame.columns
    assert frame["source_json"].str.contains('"id"').all()
    # Ambiguity is not resolved by taking the first or joining by event ordinal.
    payloads["matches/2/27.json"] = [game, game]
    rejected, coverage = source.prepare("eng.1", 2016, pl.DataFrame([primary]))
    assert rejected.is_empty() and coverage["unmapped_matches"] == 1
