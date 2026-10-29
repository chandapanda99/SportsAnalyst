"""High-level provider/identity/measurement checks using synthetic API failure fixtures.

Payload structure follows the pinned upstream Understat parser. These offline
fixtures verify integration behavior, not live source availability.
"""
import json
from types import SimpleNamespace

import polars as pl
import pytest

from sports_analyst.analysis.research.state import ResearchState
from sports_analyst.config import Settings
from sports_analyst.datasets.cfb_source import CFBSource
from sports_analyst.datasets.soccer.connector import SportsDataverseSoccerConnector
from sports_analyst.datasets.soccer.statistics import measured_value
from sports_analyst.datasets.soccer.understat import DATASETS, UnderstatSource, tablet_rows
from sports_analyst.models import AnalysisRequest
from sports_analyst.plugins.soccer import SoccerPlugin
from sports_analyst.storage.local import LocalStore
from sports_analyst.storage.persistence import LocalPersistenceBackend


def payloads():
    date = "2023-08-12 15:00:00"
    game = {"id": "99", "datetime": date, "h": {"id": "1", "title": "Home", "short_title": "HOM"},
            "a": {"id": "2", "title": "Away", "short_title": "AWY"}, "goals": {"h": "1", "a": "0"},
            "xG": {"h": "0.5", "a": "0"}, "isResult": True}
    teams = {side: {"id": str(i), "title": name, "history": [{"date": date, "h_a": side,
        "pts": 3 if side == "h" else 0, "xpts": .5, "scored": 1 if side == "h" else 0,
        "xG": .5 if side == "h" else 0., "npxG": .5 if side == "h" else 0., "npxGD": .5,
        "ppda": {"att": 20, "def": 2}, "deep": 4}]} for side, i, name in (("h", 1, "Home"), ("a", 2, "Away"))}
    rosters = {side: {str(i): {"team_id": str(i), "player_id": str(i + 6), "id": str(i + 6),
        "player": name, "position": "FW", "positionOrder": "1", "time": "90", "goals": "1" if side == "h" else "0",
        "own_goals": "0", "shots": "2" if side == "h" else "0", "xG": "0.5" if side == "h" else "0",
        "xGChain": "0.5", "xGBuildup": "0.1", "assists": "0", "xA": "0", "key_passes": "0",
        "yellow_card": "0", "red_card": "0"}} for side, i, name in (("h", 1, "Forward"), ("a", 2, "Opponent"))}
    shots = [{"id": str(i), "h_a": "h", "h_team": "Home", "a_team": "Away", "date": date,
        "player_id": "7", "player": "Forward", "player_assisted": "", "xG": "0.25", "X": ".9", "Y": ".5",
        "minute": str(i), "shotType": "RightFoot", "situation": "OpenPlay", "result": "Goal" if i == 1 else "MissedShots"}
        for i in (1, 2)]
    return {"/": {}, "/getStatData": {"stat": [{"league_id": 1, "league": "EPL", "year": 2023, "month": 8}]},
        "/getLeagueData/EPL/2023": {"dates": [game], "teams": teams, "players": []},
        "/getMatchData/99": {"tmpl": {"home": '<h3><a>Home</a></h3>', "away": '<h3><a>Away</a></h3>'},
                                 "rosters": rosters, "shots": {"h": shots, "a": []}}}


@pytest.mark.parametrize("durable", [False, True])
def test_understat_real_parser_scoped_sync_cache_analysis_and_tablet(tmp_path, monkeypatch, durable):
    from test_data_catalog import MemoryPersistence

    monkeypatch.setenv("SOCCERDATA_DIR", str(tmp_path / "soccerdata"))
    connector = SportsDataverseSoccerConnector(Settings(_env_file=None, data_dir=tmp_path, dataset_sync_concurrency=2))
    persistence = MemoryPersistence() if durable else LocalPersistenceBackend()
    connector.source_cache = CFBSource(connector.data_dir, persistence, namespace="soccer")
    fixtures = pl.DataFrame({"event_id": ["101"], "home_team_id": ["10"], "away_team_id": ["20"],
        "home_team": ["Home"], "away_team": ["Away"], "home_score": [1], "away_score": [0],
        "date": ["2023-08-12T15:00:00Z"], "status": ["STATUS_FINAL"]})
    data, fetched = payloads(), []

    def fetch(state, url, **kwargs):
        from urllib.parse import urlparse

        fetched.append(url)
        state.consume(requests=1)
        assert kwargs["headers"] == {"X-Requested-With": "XMLHttpRequest"}
        return json.dumps(data[urlparse(url).path]).encode()

    monkeypatch.setattr(ResearchState, "fetch", fetch)
    schedule = pl.concat([fixtures, fixtures.with_columns(pl.lit("scheduled").alias("event_id"),
        pl.lit("STATUS_SCHEDULED").alias("status"))])
    monkeypatch.setattr(connector, "_scoreboard", lambda *a, **k: schedule)
    manifests = connector.sync([2024], list(DATASETS), competition="eng.1", team_id="10")
    assert len(manifests) == 3 and len(fetched) == 4
    assert all(m.provider_id == "understat" and m.partition_key == "team:10" for m in manifests)
    assert all(m.availability == "available" for m in manifests)
    frames = {m.dataset: pl.read_parquet(m.local_path) for m in manifests}
    assert frames["understat_shots"]["x"].to_list() == [94.5, 94.5]
    assert frames["understat_player_matches"]["provider_player_id"].to_list() == ["7", "8"]
    assert "athlete_id" not in frames["understat_player_matches"].columns
    assert measured_value("understat_expected_goals_per_match", [{"game_id": "101"}], frames["understat_team_matches"], "10") == (.5, 1)
    assert measured_value("understat_expected_goals_per_match", [{"game_id": "101"}], frames["understat_team_matches"], "20") == (0., 1)
    view = tablet_rows("101", frames)
    assert len(json.loads(view[0]["shots_json"])) == 2
    assert "expectedGoalsOnTarget" not in json.loads(view[0]["shots_json"])[0]
    calendars = {year: fixtures.with_columns(pl.lit(str(year)).alias("event_id"),
        pl.lit(f"{year - 1}-08-12T15:00:00Z").alias("date"), pl.lit(year).alias("season"),
        pl.lit("eng.1").alias("competition")) for year in (2024, 2025)}
    sources = {year: manifests[0].model_copy(update={"dataset": "play_by_play", "season": year,
        "manifest_id": f"calendar-{year}"}) for year in calendars}
    extras = {key: {year: frame.with_columns(pl.lit(str(year)).alias("game_id"),
        (pl.col("expected_goals") * (year - 2023)).alias("expected_goals"))
        for year in calendars} for key, frame in frames.items()}
    extras["open_events"] = {year: pl.DataFrame({"game_id": [str(year)], "team_id": ["10"], "id": ["pass-1"],
        "provider": ["statsbomb"], "sequence": [42], "period": [1], "minute": [23], "second": [12],
        "event_type": ["Pass"], "start_x": [28.], "start_y": [44.], "end_x": [69.], "end_y": [25.],
        "coordinate_system": ["StatsBomb 120x80 scaled to 105x68; executing-team orientation"]}) for year in calendars}
    request = AnalysisRequest(sport="soccer", question="How did Understat xG change?", analysis_domain="attack",
        subject={"type": "team", "id": "10"}, metrics=["understat_expected_goals_per_match"],
        scope={"team": "10", "competition": "eng.1", "baseline": {"season": 2024}, "comparison": {"season": 2025}})
    result = SoccerPlugin().analyze(request, calendars, sources, extras)
    measurement = next(e for e in result.aggregate_evidence if e.metric == "understat_expected_goals_per_match")
    assert (measurement.baseline_value, measurement.comparison_value) == (.5, 1.)
    assert measurement.context["provider"] == "understat" and measurement.context["comparison_sample"] == 1
    assert any(p.visualization.soccer_analytics for p in result.play_evidence)
    action = result.play_evidence[0].visualization.soccer_actions[0]
    assert action["sequence"] == 42 and action["provider"] == "statsbomb" and action["team_name"] == "Home"
    assert "executing-team orientation" in action["coordinate_system"]
    # Historical cache hits do not issue any source requests in a new adapter.
    connector.sync([2024], list(DATASETS), competition="eng.1", team_id="10")
    assert len(fetched) == 4
    store = LocalStore(connector.settings, persistence)
    for manifest in manifests:
        store.save_manifest(manifest)
    assert len(store.manifests(sport="soccer", provider_id="understat", processing_version=None)) == 3
    # A failed refresh retains checked observations and reports a failed request.
    monkeypatch.setattr(connector.source_cache, "_cached", lambda *args: None)
    monkeypatch.setattr(ResearchState, "fetch", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("source timeout")))
    retained = UnderstatSource(connector).publish("eng.1", 2024, fixtures, list(DATASETS), team_id="10", refresh=True)
    assert [m.sha256 for m in retained] == [m.sha256 for m in manifests]
    assert all(m.availability == "partial" and m.coverage["failed_requests"] == 1 for m in retained)


@pytest.mark.parametrize("ambiguous", [False, True])
def test_understat_missing_or_ambiguous_fixture_never_becomes_xg_zero(tmp_path, monkeypatch, ambiguous):
    monkeypatch.setenv("SOCCERDATA_DIR", str(tmp_path / "soccerdata"))
    connector = SportsDataverseSoccerConnector(Settings(_env_file=None, data_dir=tmp_path))
    data = payloads()
    if ambiguous:
        data["/getLeagueData/EPL/2023"]["dates"] *= 2
    monkeypatch.setattr(ResearchState, "fetch", lambda self, url, **kwargs: json.dumps(
        data[url.removeprefix("https://understat.com")]).encode())
    fixtures = pl.DataFrame({"event_id": ["101"], "home_team_id": ["10"], "away_team_id": ["20"],
        "home_team": ["Home"], "away_team": ["Away"], "home_score": [1 if ambiguous else 9], "away_score": [0],
        "date": ["2023-08-12T15:00:00Z"]})
    result = UnderstatSource(connector).publish("eng.1", 2024, fixtures, [DATASETS[0]])[0]
    assert result.row_count == 0 and result.availability == "source_unavailable"
    assert result.coverage["ambiguous_matches" if ambiguous else "unmatched_matches"] == 1


def test_understat_join_preserves_observations_and_native_player_identity(tmp_path):
    from test_research import setup_access

    access, _ = setup_access(tmp_path, "soccer", [("understat_team_matches", {
        "game_id": ["1"], "team_id": ["A"], "expected_goals": [.5]}), ("understat_shots", {
        "game_id": ["1", "1"], "team_id": ["A", "A"], "id": ["s1", "s2"],
        "provider_player_id": ["7", "7"], "expected_goals": [.2, .3]})])
    relation = next(r for r in access.executor.discover()["relationships"] if r["left_dataset_id"] == "m0")
    plan = {"objective": "Shot xG reconciliation", "dataset_id": "m0", "window": "comparison", "grain": "team_game",
        "steps": [{"relationship_id": relation["relationship_id"], "alias": "shots", "mode": "exists"}],
        "measures": [{"op": "sum", "field": "expected_goals", "name": "xg"}]}
    result = access.executor.execute(access.executor.validate(plan)["plan_id"])
    assert result["rows"][0]["xg"] == .5 and result["qualifying_rows"] == 1
    access.request = access.request.model_copy(update={"subject": SimpleNamespace(type="player", id="7")})
    with pytest.raises(ValueError, match="crosswalk"):
        access.executor.base(access.manifests["m1"], {"expected_goals"}, "comparison")
