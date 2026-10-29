"""Major download contracts: historical groups, isolated snapshots, and analysis reuse."""
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest
from fastapi.testclient import TestClient

from sports_analyst.api import create_app
from sports_analyst.application.preparation import prepare_investigation
from sports_analyst.application.service import AnalystApplication
from sports_analyst.config import Settings
from sports_analyst.datasets import download_scope
from sports_analyst.models import AnalysisRequest, DatasetManifest


@pytest.mark.parametrize("sport", ["nfl", "nba"])
def test_scoped_bulk_sync_preserves_games_reuses_sources_and_prepares_analysis(tmp_path, monkeypatch, sport):
    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path), analysis_runtime=False)
    connector = app.connectors[sport]
    calls = []
    before = "GB" if sport == "nfl" else "BOS"
    fields = {"home_team" if sport == "nfl" else "home_team_abbrev": ["CHI", "CHI", "DEN", "DEN"],
              "away_team" if sport == "nfl" else "away_team_abbrev": [before, before, *( ["KC"] * 2 if sport == "nfl" else ["LAL"] * 2)],
              "posteam" if sport == "nfl" else "team_abbreviation": ["CHI", before, "DEN", "KC" if sport == "nfl" else "LAL"]}
    data = pl.DataFrame({"game_id": ["g1", "g1", "g2", "g2"], "play_id": [1, 2, 3, 4], **fields})

    def acquire(seasons, datasets, progress_callback=None, **kwargs):
        calls.append((seasons[0], datasets[0]))
        path = (app.settings.raw_dir if sport == "nfl" else connector.data_dir) / f"{datasets[0]}_{seasons[0]}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        data.write_parquet(path)
        return [connector.manifest_for(path, seasons[0], data, datasets[0])]

    monkeypatch.setattr(connector, "sync", acquire)
    sources = ["play_by_play"] if sport == "nfl" else ["play_by_play", "team_boxscores"]
    snapshots = app.sync([2024, 2025], datasets=sources, sport=sport, team_ids=["CHI"])
    assert snapshots and all(item.partition_key == "team:CHI" for item in snapshots)
    assert all(set(connector.load(item)["game_id"]) == {"g1"} and item.row_count == 2 for item in snapshots)
    assert all(item.source_scope == "league" and item.download_scope == "team" for item in snapshots)
    assert all(item.coverage["league_benchmarks_available"] == 0 for item in snapshots)
    with pytest.raises(KeyError):
        app.store.manifest_for_season(2024, sport=sport)
    count = len(calls)
    again = app.sync([2024, 2025], datasets=sources, sport=sport, team_ids=["DEN"])
    assert len(calls) == count  # A second team reuses cached full-source files.
    assert all(set(connector.load(item)["game_id"]) == {"g2"} for item in again)
    request = AnalysisRequest(sport=sport, question="Compare this team's seasons", subject={"type": "team", "id": "CHI"},
        scope={"team": "CHI", "baseline_season": 2024, "comparison_season": 2025})
    partition, years = prepare_investigation(app, request, "prepare-test")
    assert partition == "team:CHI" and years == [2024, 2025]
    assert len(calls) == count
    app.sync([2024], datasets=sources, sport=sport)
    assert app.store.manifest_for_season(2024, sport=sport).partition_key is None
    assert len(calls) > count  # Partial snapshots must never satisfy full-league coverage.


def test_groups_are_resolved_per_season_and_api_rejects_ambiguous_scope(tmp_path, monkeypatch):
    def catalog(sport, season, competition=None):
        return {"teams": [{"value": "CHI" if season == 2024 else "DEN", "label": "Recorded Team",
                            "conference_id": "group-x", "division_id": "division-x"}],
                "conferences": [{"value": "group-x", "label": "Recorded Conference"}], "divisions": []}

    monkeypatch.setattr(download_scope, "download_catalog", catalog)
    assert download_scope.resolve_download_teams("nfl", [2024, 2025], conference_id="group-x") == {2024: ["CHI"], 2025: ["DEN"]}
    assert download_scope.resolve_download_teams("nba", [2024, 2025], division_id="division-x") == {2024: ["CHI"], 2025: ["DEN"]}
    with pytest.raises(ValueError, match="no verified members"):
        download_scope.resolve_download_teams("soccer", [2024], "eng.1", conference_id="unknown")
    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path), analysis_runtime=False)
    client = TestClient(create_app(app))
    response = client.post("/api/datasets/nfl/sync", json={"seasons": [2024], "team_ids": ["CHI"], "conference_id": "group-x"})
    assert response.status_code == 422
    assert client.get("/api/sports/nfl/download-catalog?season=2024").json()["teams"][0]["value"] == "CHI"
    calls = []

    def sync(seasons, key, datasets, sport, competition, **scope):
        calls.append(scope)
        app.events.emit(key, "complete", "Selected group ready", 1)

    monkeypatch.setattr(app, "sync", sync)
    response = client.post("/api/datasets/nfl/sync-stream", json={"seasons": [2024], "conference_id": "group-x"})
    assert response.status_code == 200 and "Selected group ready" in response.text
    assert calls == [{"conference_id": "group-x"}]


def test_soccer_team_sync_fetches_only_selected_teams_and_preserves_partition(tmp_path, monkeypatch):
    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path), analysis_runtime=False)
    calls = []

    def acquire(seasons, datasets, **kwargs):
        team = kwargs["team_id"]
        calls.append((team, seasons))
        data = pl.DataFrame({"event_id": ["match-1"], "home_team_id": [team], "away_team_id": ["20"]})
        path = tmp_path / "raw" / f"soccer-{team}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        data.write_parquet(path)
        item = app.connectors["soccer"].manifest_for(path, "eng.1", seasons[0], "play_by_play", data, 1, 1, 1, f"team:{team}")
        kwargs["manifest_callback"](item)
        return [item]

    monkeypatch.setattr(app.connectors["soccer"], "sync", acquire)
    items = app.sync([2024], datasets=["play_by_play"], sport="soccer", competition="eng.1", team_ids=["10", "30"])
    assert calls == [("10", [2024]), ("30", [2024])]
    assert {item.partition_key for item in items} == {"team:10", "team:30"}
    assert all(Path(item.local_path).exists() for item in items)


def test_team_scoped_analysis_does_not_publish_league_ranks_or_opponent_adjustments(pbp_pair):
    from sports_analyst.plugins.nfl import NFLPlugin

    manifests = {season: DatasetManifest(manifest_id=f"scoped-{season}", dataset="play_by_play", season=season,
        partition_key="team:KC", source_url="synthetic-test", sha256="a" * 64, row_count=frame.height,
        columns=frame.columns, package_version="test", local_path=f"C:/test/{season}.parquet")
        for season, frame in pbp_pair.items()}
    request = AnalysisRequest(question="Compare passing efficiency", scope={"team":"KC", "baseline_season":2024, "comparison_season":2025})
    result = NFLPlugin().analyze(request, pbp_pair, manifests)
    assert any(item.metric == "epa_per_dropback" for item in result.aggregate_evidence)
    assert not any("league_rank" in item.metric or "percentile" in item.metric or "opponent_adjusted" in item.metric
                   for item in result.aggregate_evidence)
    assert any("full-league data" in caveat for caveat in result.caveats)


def test_soccer_catalog_matches_app_season_and_does_not_invent_single_table_groups(monkeypatch):
    calls = []

    def standings(**kwargs):
        calls.append(kwargs)
        return {"season": {"year": 2024}, "children": [{"id": "1", "name": "Premier League",
            "standings": {"entries": [{"team": {"id": "10", "displayName": "Recorded Club"}}]}}]}

    monkeypatch.setattr(download_scope, "load_optional_module", lambda *args: SimpleNamespace(espn_soccer_standings=standings))
    catalog = download_scope._catalog("soccer", 2025, "eng.1", 0)
    assert calls[0]["season"] == 2024  # The app's 2024-25 season is ESPN season 2024.
    assert catalog["teams"][0]["value"] == "10"
    assert catalog["conferences"] == [] and catalog["divisions"] == []
