"""High-level optional spatial enrichment; synthetic fixtures do not prove live coverage."""
import json

import pandas as pd
import polars as pl

from sports_analyst.analysis.research.state import ResearchState
from sports_analyst.config import Settings
from sports_analyst.datasets.soccer.connector import SportsDataverseSoccerConnector
from sports_analyst.datasets.soccer.whoscored import WhoScoredSource, cached_recap
from sports_analyst.models import PlayVisualization


def test_whoscored_parser_worker_cache_and_exact_event_enrichment(tmp_path, monkeypatch):
    connector = SportsDataverseSoccerConnector(Settings(data_dir=tmp_path, _env_file=None))
    assert connector.settings.soccer_whoscored_enabled is True
    fixture = {"event_id": "123", "date": "2023-09-01", "home_team": "Home", "away_team": "Away",
        "home_team_id": "1", "away_team_id": "2", "home_score": 1, "away_score": 0}
    fixtures = pl.DataFrame([fixture])
    goal = {"id": 987, "teamId": 11, "playerId": 33, "type": {"displayName": "Goal"},
        "period": {"value": 1}, "minute": 33, "second": 12, "x": 90, "y": 40,
        "isGoal": True, "outcomeType": {"displayName": "Successful"}, "qualifiers": []}
    payload = {"home": {"teamId": 11, "name": "Home"}, "away": {"teamId": 22, "name": "Away"},
        "playerIdNameDictionary": {"33": "Alex Forward"}, "events": [goal,
            {**goal, "id": 988, "isGoal": False, "type": {"displayName": "Pass"}, "x": 0, "y": 0,
             "qualifiers": [{"type": {"value": 140}, "value": "50"}, {"type": {"value": 141}, "value": "25"}]}]}
    requests = []
    def fetch(self, url, **kwargs):
        requests.append(url)
        assert url == "https://www.whoscored.com/Matches/456/Live"
        return ("<script>matchCentreData: " + json.dumps(payload) + ", other: null</script>").encode()
    monkeypatch.setattr(ResearchState, "fetch", fetch)
    # Exercise the installed SoccerData event parser, with no browser startup.
    source = WhoScoredSource(connector)
    client = source.client("eng.1", 2024, False)
    client.read_schedule = lambda *args, **kwargs: pd.DataFrame([{**fixture, "game_id": 456,
        "league": "ENG-Premier League", "season": "2324", "game": "match"}]).set_index(["league", "season", "game"])
    monkeypatch.setattr(source, "client", lambda *args: client)
    manifest = source.publish("eng.1", 2024, fixtures)
    assert manifest.availability == "available"
    assert manifest.provider_id == "whoscored"
    events = pl.read_parquet(manifest.local_path).to_dicts()
    assert events[0]["start_x"] == 94.5 and events[0]["end_x"] is None
    assert events[1]["start_x"] == 0 and events[1]["end_x"] == 52.5
    assert json.loads(events[0]["raw_event_json"])["id"] == 987
    source.publish("eng.1", 2024, fixtures)
    assert len(requests) == 1  # Durable/local normalized cache reused.
    event = {"id": "espn-1", "clock": "33'", "type": "Goal - Volley", "team_id": "1", "side": "home",
        "scoring_play": True, "athlete_id": "espn-33", "athlete_name": "Alex Forward", "period": 1}
    visual = PlayVisualization(sport="soccer", home_team_name="Home", away_team_name="Away", home_score=1,
        away_score=0, game_date="2023-09-01", soccer_timeline=[event])
    enriched = cached_recap(connector, "eng.1", 2024, "123", visual)
    assert enriched.soccer_timeline[0]["spatial_event_id"] == "987"
    assert enriched.soccer_timeline[0]["spatial_context"]["start_x"] == 94.5
    assert visual.soccer_timeline == [event]
    for timeline in ([{**event, "athlete_name": "A. Forward"}], [{**event, "period": None}], [event, event]):
        result = cached_recap(connector, "eng.1", 2024, "123", visual.model_copy(update={"soccer_timeline": timeline}))
        assert all("spatial_context" not in row for row in result.soccer_timeline)
    conflict = visual.model_copy(update={"home_score": 2})
    assert cached_recap(connector, "eng.1", 2024, "123", conflict) is conflict
    # Source failure never removes previously verified event observations.
    monkeypatch.setattr(source, "client", lambda *args: (_ for _ in ()).throw(ConnectionError("blocked")))
    failed = source.publish("eng.1", 2024, fixtures, refresh=True)
    assert failed.availability == "partial" and failed.row_count == 2


def test_optional_whoscored_scope_and_disabled_states_do_not_fetch(tmp_path, monkeypatch):
    connector = SportsDataverseSoccerConnector(Settings(data_dir=tmp_path, soccer_whoscored_enabled=False, _env_file=None))
    source = WhoScoredSource(connector)
    monkeypatch.setattr(source, "client", lambda *args: (_ for _ in ()).throw(AssertionError("Must not fetch")))
    fixture = pl.DataFrame([{"event_id": "123", "date": "2023-09-01", "home_team_id": "1", "away_team_id": "2"}])
    disabled = source.publish("eng.1", 2024, fixture)
    assert disabled.availability == "source_unavailable" and "disabled" in disabled.availability_message
    connector.settings.soccer_whoscored_enabled = True
    unsupported = source.publish("usa.1", 2024, fixture)
    assert unsupported.availability == "source_unavailable" and "five European" in unsupported.availability_message
