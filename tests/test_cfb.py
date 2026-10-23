"""Major conference, scoped preparation, transfer, and evidence workflows."""

import threading
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import polars as pl
import pytest
from fastapi.testclient import TestClient

from sports_analyst.api import create_app
from sports_analyst.application.service import AnalystApplication
from sports_analyst.config import Settings
from sports_analyst.datasets.cfb import SportsDataverseCFBConnector
from sports_analyst.datasets.cfb_source import CORE, CFBSource
from sports_analyst.models import AnalysisRequest, DatasetManifest
from sports_analyst.plugins.cfb import CFBPlugin
from sports_analyst.storage.local import LocalStore


class DurableMemory:
    durable = True

    def __init__(self):
        self.objects, self.versions, self.lock = {}, {}, threading.Lock()

    def read_bytes(self, key):
        return self.objects.get(key)

    def read_versioned_bytes(self, key):
        return self.objects.get(key), str(self.versions[key]) if key in self.versions else None

    def write_bytes(self, key, payload, content_type=None):
        with self.lock:
            self.objects[key] = payload
            self.versions[key] = self.versions.get(key, 0) + 1

    def write_bytes_if_version(self, key, payload, version, content_type=None):
        with self.lock:
            current = str(self.versions[key]) if key in self.versions else None
            if current != version:
                return False
            self.objects[key] = payload
            self.versions[key] = self.versions.get(key, 0) + 1
            return True

    def upload_file(self, key, path):
        self.write_bytes(key, path.read_bytes())

    def download_file(self, key, path):
        if key not in self.objects:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.objects[key])
        return True

    def delete_prefix(self, prefix):
        for key in list(self.objects):
            if key.startswith(prefix):
                self.objects.pop(key)

    def list_keys(self, prefix):
        return [key for key in self.objects if key.startswith(prefix)]


def event(game, season):
    return {
        "id": game,
        "date": f"{season}-09-0{game[-1]}T19:00Z",
        "season": {"year": season},
        "seasonType": {"type": 2},
        "week": {"number": int(game[-1])},
        "competitions": [
            {
                "date": f"{season}-09-0{game[-1]}T19:00Z",
                "status": {"type": {"completed": True}},
                "competitors": [
                    {"homeAway": side, "score": str(score), "team": {"id": identity, "displayName": name}}
                    for side, identity, name, score in [("home", "1", "FBS School", 28), ("away", "2", "FCS School", 14)]
                ],
            }
        ],
    }


def summary(game, season):
    index = int(game[-1])
    completions, attempts = ((10, 10) if index == 1 else (10, 30)) if season == 2024 else ((15, 20) if index == 1 else (25, 30))
    conversion = ("2-2" if index == 1 else "2-18") if season == 2024 else ("2-4" if index == 1 else "6-16")
    return {
        "header": {**event(game, season), "season": {"year": season, "type": 2}},
        "boxscore": {
            "teams": [
                {
                    "team": {"id": identity},
                    "statistics": [
                        {"name": "thirdDownEff", "displayValue": conversion},
                        {"name": "totalYards", "displayValue": "400"},
                        {"name": "rushingYards", "displayValue": "100"},
                        {"name": "rushingAttempts", "displayValue": "25"},
                    ],
                }
                for identity in ("1", "2")
            ],
            "players": [
                {
                    "team": {"id": "1" if season == 2024 else "2"},
                    "statistics": [
                        {
                            "name": "passing",
                            "labels": ["C/ATT", "YDS", "TD", "INT"],
                            "athletes": [
                                {
                                    "athlete": {"id": "10", "displayName": "Transfer QB"},
                                    "stats": [f"{completions}/{attempts}", "200", "2", "0"],
                                }
                            ],
                        },
                        {
                            "name": "rushing",
                            "labels": ["CAR", "YDS", "TD"],
                            "athletes": [{"athlete": {"id": "11", "displayName": "Runner"}, "stats": ["10", "80", "1"]}],
                        },
                        {
                            "name": "receiving",
                            "labels": ["REC", "YDS", "TD"],
                            "athletes": [{"athlete": {"id": "12", "displayName": "Receiver"}, "stats": ["5", "100", "1"]}],
                        },
                    ],
                }
            ],
        },
        "scoringPlays": [{"text": "Recorded touchdown", "period": {"number": 1}, "clock": {"displayValue": "10:00"}}],
    }


@pytest.fixture
def source(monkeypatch):
    calls = Counter()
    failing = set()

    def request(url):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        path = parsed.path
        calls[path] += 1
        if path.endswith("/plays"):
            game = path.split("/competitions/")[1].split("/")[0]
            return {
                "items": [
                    {
                        "id": f"{game}0000000000001",
                        "text": "Shotgun Transfer QB complete to receiver",
                        "type": {"text": "Pass Reception"},
                        "statYardage": 15,
                        "start": {"down": 3, "distance": 10, "yardsToEndzone": 60, "team": {"id": "1"}},
                        "end": {"yardsToEndzone": 45, "team": {"id": "1"}},
                        "participants": [{"type": "passer", "athlete": {"id": "10"}}],
                    }
                ]
            }
        if path.endswith("/personnel"):
            return {"items": [{"description": "Recorded personnel context"}]}
        if path.endswith("/summary"):
            game = query["event"][0]
            if game in failing:
                failing.remove(game)
                raise TimeoutError("Temporary source failure")
            return summary(game, int(game[:4]))
        if path.endswith("/schedule"):
            year = int(query["season"][0])
            return {
                "season": {"year": 2026},
                "requestedSeason": {"year": year},
                "events": [event(f"{year}{index}", year) for index in (1, 2)] if query.get("seasontype") == ["2"] else [],
            }
        if path.endswith("/roster"):
            year = int(query["season"][0])
            return {
                "season": {"year": year},
                "athletes": [{"items": [{"id": "10", "displayName": "Transfer QB", "position": {"abbreviation": "QB"}}]}],
            }
        if path.endswith("/statisticslog"):
            return {"entries": [{"season": {"$ref": f"{CORE}/seasons/{year}"}} for year in (2024, 2025)]}
        if path.endswith("/gamelog"):
            year = int(query["season"][0])
            return {"events": {f"{year}{index}": {} for index in (1, 2)}}
        if path.endswith("/seasons"):
            return {"items": [{"$ref": f"{CORE}/seasons/{year}"} for year in (2024, 2025)]}
        if "/groups" in path:
            prefix, suffix = path.split("/groups", 1)
            if not suffix:
                return {"items": [{"$ref": f"https://sports.core.api.espn.com{prefix}/groups/90"}]}
            if suffix == "/90":
                return {"id": "90", "name": "NCAA Division I", "children": {"$ref": f"https://sports.core.api.espn.com{path}/children"}}
            if suffix == "/90/children":
                return {"items": [{"$ref": f"https://sports.core.api.espn.com{prefix}/groups/{identity}"} for identity in (80, 81)]}
            if suffix in {"/80", "/81"}:
                return {
                    "id": suffix[1:],
                    "name": "Football Bowl Subdivision" if suffix == "/80" else "Football Championship Subdivision",
                    "children": {"$ref": f"https://sports.core.api.espn.com{path}/children"},
                }
            if suffix.endswith("/children"):
                return {
                    "items": [
                        {"$ref": f"https://sports.core.api.espn.com{prefix}/groups/8"},
                        {"$ref": f"https://sports.core.api.espn.com{prefix}/groups/9"},
                    ]
                }
            if suffix in {"/8", "/9"}:
                return {
                    "id": suffix[1:],
                    "name": "Season Conference" if suffix == "/8" else "Independents",
                    "teams": {"$ref": f"https://sports.core.api.espn.com{path}/teams"},
                }
            if suffix.endswith("/teams"):
                page = int(query.get("page", ["1"])[0])
                team = page if "/2024/" in prefix else page + 1
                return {"pageCount": 2, "items": [{"$ref": f"https://sports.core.api.espn.com{prefix.split('/types')[0]}/teams/{team}"}]}
        if "/teams/" in path:
            identity = path.rsplit("/", 1)[1]
            return {"id": identity, "displayName": f"School {identity}"}
        raise AssertionError(f"Unexpected or unscoped source request: {url}")

    monkeypatch.setattr(CFBSource, "_request", staticmethod(request))
    return calls, failing


def test_conference_discovery_is_seasonal_paginated_and_does_not_load_rosters(tmp_path, source):
    connector = SportsDataverseCFBConnector(Settings(_env_file=None, data_dir=tmp_path))
    for year, level in [(2024, "fbs"), (2025, "fcs")]:
        catalog = connector.catalog(year, level, "8")
        assert len(catalog["teams"]) == 2
        assert {row["value"] for row in catalog["teams"]} == ({"1", "2"} if year == 2024 else {"2", "3"})
        assert any(row["label"] == "Independents" for row in catalog["conferences"])
    assert not any("roster" in path or "summary" in path for path in source[0])
    assert connector.catalog(2025, "fcs", "8")["cached"]
    with pytest.raises(ValueError):
        connector.catalog(2025, "fcs", "999")


def test_scoped_sync_resumes_and_shares_games_without_national_downloads(tmp_path, source):
    connector = SportsDataverseCFBConnector(Settings(_env_file=None, data_dir=tmp_path))
    source[1].add("20242")
    first = connector.prepare(2024, team_id="1")
    assert first[0].coverage["completed_matches"] == 1
    second = connector.prepare(2024, team_id="1")
    assert second[0].coverage["completed_matches"] == 2
    before = source[0]["/apis/site/v2/sports/football/college-football/summary"]
    connector.prepare(2024, team_id="2")
    connector.prepare(2024, team_id="1")
    assert source[0]["/apis/site/v2/sports/football/college-football/summary"] == before
    assert all("/teams/1/" in path or "/teams/2/" in path or path.endswith("/summary") for path in source[0])


@pytest.mark.parametrize("durable", [False, True])
def test_missing_roster_preserves_games_rechecks_and_discovers_recorded_participants(tmp_path, source, monkeypatch, durable):
    settings = Settings(_env_file=None, data_dir=tmp_path, langsmith_tracing=False)
    persistence = DurableMemory() if durable else None
    application = AnalystApplication(settings, persistence=persistence)
    connector = application.connectors["cfb"]
    original = CFBSource._request
    mode = ["empty"]

    def request(url):
        if urlparse(url).path.endswith("/roster"):
            if mode[0] == "failed":
                raise TimeoutError("Temporary source failure")
            if mode[0] == "unverified":
                return {"season": {"year": 2026}, "athletes": []}
            if mode[0] == "empty":
                return {"season": {"year": 2024}, "athletes": [{"position": "offense", "items": []}]}
        return original(url)

    monkeypatch.setattr(CFBSource, "_request", staticmethod(request))
    first = connector.prepare(2024, team_id="1", manifest_callback=application.store.save_manifest)
    roster = next(item for item in first if item.dataset == "rosters")
    assert roster.availability == "source_unavailable"
    assert roster.coverage["completed_matches"] == 0
    assert next(item for item in first if item.dataset == "team_stats").availability == "available"
    assert application.resolve_players("Transfer", "cfb", team_id="1", season=2024)[0].discovery_source == "recorded_game_participants"
    assert application.resolve_players("not-a-recorded-player", "cfb", team_id="1", season=2024) == []
    if durable:
        replica = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path / "replica", langsmith_tracing=False), persistence=persistence)
        assert replica.resolve_players("Transfer", "cfb", team_id="1", season=2024)[0].player_id == "10"

    clock = time.time()
    monkeypatch.setattr(time, "time", lambda: clock + 3700)
    mode[0] = "failed"
    failed = connector.prepare(2024, team_id="1")
    assert next(item for item in failed if item.dataset == "rosters").availability == "download_failed"
    mode[0] = "unverified"
    unverified = connector.prepare(2024, team_id="1")
    assert next(item for item in unverified if item.dataset == "rosters").availability == "season_unverified"
    monkeypatch.setattr(time, "time", lambda: clock + 7400)
    mode[0] = "available"
    refreshed = connector.prepare(2024, team_id="1")
    assert next(item for item in refreshed if item.dataset == "rosters").row_count == 1
    before = sum(source[0].values())
    connector.prepare(2025, team_id="1", datasets=["schedules", "team_stats"])
    assert sum(count for path, count in source[0].items() if path.endswith("/roster")) == 1
    assert sum(source[0].values()) > before


@pytest.mark.parametrize("durable", [False, True])
def test_historical_roster_sources_are_scoped_paginated_resumable_and_season_verified(tmp_path, source, monkeypatch, durable):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    store = LocalStore(settings, DurableMemory() if durable else None)
    connector = SportsDataverseCFBConnector(settings)
    connector.source.persistence = store.persistence
    original = CFBSource._request
    requests = Counter()
    fail = [True]

    def request(url):
        parsed = urlparse(url)
        path, query = parsed.path, parse_qs(parsed.query)
        requests[path] += 1
        if path.endswith("/teams/1/roster"):
            return {"season": {"year": int(query["season"][0])}, "athletes": []}
        if path.endswith("/teams/1/athletes"):
            year = path.split("/seasons/")[1].split("/")[0]
            if year == "2025":
                return {"items": [], "pageCount": 1}
            page = int(query["page"][0])
            return {"pageCount": 2, "items": [{"$ref": f"{CORE}/seasons/2024/athletes/{9 + page}"}]}
        if "/seasons/" in path and "/athletes/" in path:
            identity = path.rsplit("/", 1)[-1]
            if identity == "11" and fail[0]:
                fail[0] = False
                raise TimeoutError("Retry this athlete only")
            return {"id": identity, "displayName": f"Recorded {identity}", "position": {"abbreviation": "QB"}}
        if "/competitors/1/roster" in path:
            return {"team": {"$ref": f"{CORE}/seasons/2025/teams/1"}, "entries": [
                {"valid": True, "athlete": {"$ref": f"{CORE}/seasons/2025/athletes/10"}},
                {"valid": True, "athlete": {"$ref": f"{CORE}/seasons/2026/athletes/99"}},
            ]}
        return original(url)

    monkeypatch.setattr(CFBSource, "_request", staticmethod(request))
    first = connector.prepare(2024, team_id="1", manifest_callback=store.save_manifest)
    roster = next(item for item in first if item.dataset == "rosters")
    assert roster.availability == "partial" and roster.row_count == 1
    second = connector.prepare(2024, team_id="1", manifest_callback=store.save_manifest)
    roster = next(item for item in second if item.dataset == "rosters")
    assert roster.availability == "available" and roster.row_count == 2
    assert requests[urlparse(f"{CORE}/seasons/2024/athletes/10").path] == 1
    game_roster = connector.prepare(2025, team_id="1", manifest_callback=store.save_manifest)
    roster = next(item for item in game_roster if item.dataset == "rosters")
    assert roster.row_count == 1 and roster.availability == "source_unavailable"
    assert connector.players("1", 2025)[0].discovery_source == "partial_recorded_roster"
    assert not any("/seasons/2026/athletes/" in path or "/teams/2/" in path for path in requests)
    saved = store.manifest_for_season(2024, "rosters", "cfb", partition_key="team:1")
    assert set(connector.load(saved)["season"].to_list()) == {2024}


def test_conference_download_progress_is_monotonic_and_identifies_school_and_season(tmp_path, source):
    connector = SportsDataverseCFBConnector(Settings(_env_file=None, data_dir=tmp_path))
    updates = []
    connector.sync([2024, 2025], ["schedules", "team_stats"], team_ids=["1", "2"],
                   progress_callback=lambda *args: updates.append(args))
    fractions = [update[5] for update in updates]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1
    assert any("School 1" in update[6] and update[2] == 2024 for update in updates)
    assert "School 2" in updates[-1][6] and "4/4" in updates[-1][6]


@pytest.mark.parametrize("durable", [False, True])
def test_partition_catalog_preserves_teams_legacy_records_and_durable_restore(tmp_path, source, durable):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    persistence = DurableMemory() if durable else None
    store = LocalStore(settings, persistence)
    connector = SportsDataverseCFBConnector(settings)
    connector.source.persistence = store.persistence
    for team in ("1", "2"):
        connector.prepare(2024, team_id=team, manifest_callback=store.save_manifest)
    assert len(store.manifests("schedules", "cfb")) == 2
    assert store.manifest_for_season(2024, "schedules", "cfb", partition_key="team:1").partition_key == "team:1"
    with pytest.raises(KeyError):
        store.manifest_for_season(2024, "schedules", "cfb")
    path = tmp_path / "legacy.parquet"
    pl.DataFrame({"value": [1]}).write_parquet(path)
    legacy = DatasetManifest(
        manifest_id="legacy",
        season=2024,
        source_url="test",
        sha256="abc",
        row_count=1,
        columns=["value"],
        package_version="test",
        local_path=str(path),
    )
    store.save_manifest(legacy)
    assert store.manifest_for_season(2024).manifest_id == "legacy"
    if durable:
        restored = LocalStore(Settings(_env_file=None, data_dir=tmp_path / "replica"), persistence)
        assert len(restored.manifests("schedules", "cfb")) == 2
        assert restored.materialize_manifest(restored.manifest_for_season(2024, "schedules", "cfb", partition_key="team:2"))


def test_investigation_prepares_team_and_transfer_player_evidence_with_weighted_rates(tmp_path, source):
    from sports_analyst.analysis.agents import SynthesisDraft
    from sports_analyst.models import Claim, ClaimType

    application = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, model_provider="ollama", langsmith_tracing=False))
    client = TestClient(create_app(application))
    assert any(option["value"] == "cfb" for option in client.get("/api/sports").json())
    assert client.get("/api/sports/cfb/catalog?season=2025&subdivision=fbs&conference_id=8").status_code == 200
    assert client.get("/api/sports/cfb/players?team_id=1&season=2024").json()[0]["player_id"] == "10"
    assert client.get("/api/sports/cfb/players/10/seasons").json()["seasons"] == [2024, 2025]
    request = AnalysisRequest(
        sport="cfb",
        question="How did third-down conversion change?",
        analysis_domain="offense",
        subject={"type": "team", "id": "1"},
        metrics=["third_down_rate"],
        scope={"team": "1", "baseline_season": 2024, "comparison_season": 2025, "comparison_design": "full_seasons"},
    )
    partition, _ = application._prepare_cfb(request, "prepare-test")
    manifests = {year: application.store.manifest_for_season(year, "schedules", "cfb", partition_key=partition) for year in (2024, 2025)}
    datasets = {year: application._load_dataset(application.connectors["cfb"], manifest) for year, manifest in manifests.items()}
    stats = {
        year: application._load_dataset(
            application.connectors["cfb"], application.store.manifest_for_season(year, "team_stats", "cfb", partition_key=partition)
        )
        for year in (2024, 2025)
    }
    result = CFBPlugin().analyze(request, datasets, manifests, {"team_stats": stats})
    assert result.aggregate_evidence[0].baseline_value == 0.2
    assert result.aggregate_evidence[0].comparison_value == 0.4
    assert result.play_evidence[0].visualization.sport == "cfb"
    missing = request.model_copy(update={"metrics": ["third_down_rate", "fourth_down_rate"]})
    partial = CFBPlugin().analyze(missing, datasets, manifests, {"team_stats": stats})
    assert len(partial.aggregate_evidence) == 1 and any("fourth_down_rate" in message for message in partial.caveats)
    with pytest.raises(ValueError, match="No comparable"):
        CFBPlugin().analyze(request.model_copy(update={"metrics": ["fourth_down_rate"]}), datasets, manifests, {"team_stats": stats})
    player = request.model_copy(
        update={
            "subject": request.subject.model_copy(update={"type": "player", "id": "10"}),
            "analysis_domain": "quarterback",
            "metrics": ["completion_rate"],
        }
    )
    partition, _ = application._prepare_cfb(player, "player-test")
    player_stats = {}
    for year in (2024, 2025):
        manifests[year] = application.store.manifest_for_season(year, "schedules", "cfb", partition_key=partition)
        datasets[year] = application._load_dataset(application.connectors["cfb"], manifests[year])
        player_stats[year] = application._load_dataset(
            application.connectors["cfb"], application.store.manifest_for_season(year, "player_stats", "cfb", partition_key=partition)
        )
    result = CFBPlugin().analyze(player, datasets, manifests, {"player_stats": player_stats})
    assert result.aggregate_evidence[0].baseline_value == 0.5
    assert result.aggregate_evidence[0].comparison_value == 0.8
    assert set(player_stats[2024]["team_id"]) == {"1"} and set(player_stats[2025]["team_id"]) == {"2"}

    class Agent:
        def synthesize(self, *args, **kwargs):
            aggregates = args[4]
            return (
                SynthesisDraft(
                    summary="Recorded conversion rate changed across these covered games.",
                    claims=[
                        Claim(
                            claim_id="claim",
                            claim_type=ClaimType.MEASURED,
                            statement="Recorded conversion rate changed.",
                            evidence_ids=[aggregates[0].evidence_id],
                        )
                    ],
                ),
                "deterministic-test",
                True,
            )

    application.agent = Agent()
    bundle = application.investigate(request, "cfb-end-to-end")
    assert all(play.play_id > 0 for play in bundle.play_evidence)
    assert {play.window for play in bundle.play_evidence} == {"baseline", "comparison"}
    assert all(play.selection_reason and play.candidate_pool_size for play in bundle.play_evidence)
    assert all(play.visualization.cfb_statistics["selected_play"]["formation"] == "Shotgun" for play in bundle.play_evidence)
    assert all(play.visualization.cfb_statistics["selected_play"]["personnel_context"]["status"] == "recorded"
               for play in bundle.play_evidence)
    from sports_analyst.presentation.reports import render_markdown
    exported = render_markdown(bundle)
    assert "Formation: Shotgun" in exported and str(bundle.play_evidence[0].play_id) in exported
    assert client.get("/api/investigations/cfb-end-to-end").status_code == 200
    game = bundle.play_evidence[0]
    assert client.get(f"/api/investigations/cfb-end-to-end/evidence/{game.evidence_id}").json()["sport"] == "cfb"
    detail = client.post(f"/api/investigations/cfb-end-to-end/evidence/{game.evidence_id}/plays")
    assert detail.status_code == 200
    assert detail.json()["plays"][0]["participants"][0]["athlete_id"] == "10"
    assert detail.json()["plays"][0]["yards_to_goal"] == 60
    child = application.follow_up("cfb-end-to-end", "Which games were covered?", "cfb-follow-up")
    assert child.run.sport == "cfb" and child.aggregate_evidence == bundle.aggregate_evidence
    assert child.play_evidence == bundle.play_evidence


def test_durable_source_coalesces_inflight_requests_across_replicas(tmp_path, monkeypatch):
    persistence = DurableMemory()
    count = Counter()

    def request(url):
        count[url] += 1
        time.sleep(0.15)
        return {"id": "1"}

    monkeypatch.setattr(CFBSource, "_request", staticmethod(request))
    sources = [CFBSource(tmp_path / name, persistence) for name in ("one", "two")]
    url = f"{CORE}/seasons/2025/teams/1"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda source: source.get(url), sources)) == [{"id": "1"}, {"id": "1"}]
    assert count[url] == 1


@pytest.mark.parametrize("namespace,prefix", [("cfb", ""), ("soccer", "eng.1/")])
def test_durable_source_reuses_local_cache_and_observes_league_resets(tmp_path, namespace, prefix):
    class CountingPersistence(DurableMemory):
        def __init__(self):
            super().__init__()
            self.reads = Counter()

        def read_bytes(self, key):
            self.reads[key] += 1
            return super().read_bytes(key)

    persistence = CountingPersistence()
    sources = [CFBSource(tmp_path / name, persistence, namespace=namespace) for name in ("one", "two")]
    key = prefix + "games/2025/101.json"
    remote = f"raw/{namespace}/{key}"
    sources[0].store(key, {"plays": [1]})
    for _ in range(3):
        assert sources[0]._cached(key, 60) == {"plays": [1]}
    assert persistence.reads[remote] == 0
    for _ in range(3):
        assert sources[1]._cached(key, 60) == {"plays": [1]}
    assert persistence.reads[remote] == 1  # Durable hit promoted to disk.
    assert sources[1]._cached(key, -1) is None  # Local reuse never extends source freshness.
    scope = "eng.1" if namespace == "soccer" else "all"
    persistence.write_bytes(f"metadata/dataset-resets/{namespace}/{scope}.txt", b"new-generation")
    for source in sources:
        source._generations.clear()  # Next bounded generation recheck, without sleeping.
        assert source._cached(key, 60) is None  # Even surviving old remote objects are invalid.
    sources[0].store(key, {"plays": [2]})
    assert sources[1]._cached(key, 60) == {"plays": [2]}


def test_scoped_preparation_refills_workers_and_resumes_failed_games(tmp_path, source, monkeypatch):
    connector = SportsDataverseCFBConnector(Settings(_env_file=None, data_dir=tmp_path, dataset_sync_concurrency=2))
    schedules = {str(game): connector.schedule_rows({"events": [event(str(game), 2025)]}, "1", 2025)[0]
                 for game in (20251, 20252, 20253)}
    monkeypatch.setattr(connector, "schedule", lambda *args: schedules)
    original = connector.summary
    third_started = threading.Event()
    failures = {"20253"}

    def fetch(game, season):
        if game == "20251":
            assert third_started.wait(3), "A slow first request blocked the next batch"
        if game == "20253":
            third_started.set()
            if failures:
                failures.clear()
                raise TimeoutError("Retryable source failure")
        return original(game, season)

    monkeypatch.setattr(connector, "summary", fetch)
    first = connector.prepare(2025, team_id="1", datasets=["schedules", "team_stats"])
    assert all(item.coverage["completed_matches"] == 2 for item in first)
    second = connector.prepare(2025, team_id="1", datasets=["schedules", "team_stats"])
    assert all(item.coverage["completed_matches"] == 3 for item in second)
    assert source[0]["/apis/site/v2/sports/football/college-football/summary"] == 3
    reference = next(item for item in second if item.dataset == "team_stats")
    reordered = connector.snapshot(2025, "team:1", {"team_stats": connector.load(reference).reverse().to_dicts()}, 3, 3, None)[0]
    assert reordered.sha256 == reference.sha256  # Network completion order does not cause spurious uploads.
    pending = {**schedules["20251"], "game_id": "20254", "completed": False}
    requested = []

    def recorded(game, season):
        requested.append(game)
        return {"plays": [{"id": game + "001", "text": "Recorded play"}], "teams": []}

    monkeypatch.setattr(connector, "game_plays", recorded)
    saved = connector.prepare_recorded(2025, "team:1", pl.from_dicts([*schedules.values(), pending]))
    assert set(requested) == set(schedules)  # Upcoming fixtures are not attempted or counted as gaps.
    assert saved.coverage["expected_matches"] == saved.coverage["completed_matches"] == 3


@pytest.mark.parametrize("durable", [False, True])
def test_recorded_sync_skips_unplayed_fixtures_and_tracks_only_completed_gaps(tmp_path, source, monkeypatch, caplog, durable):
    import logging

    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, dataset_sync_concurrency=2),
                             persistence=DurableMemory() if durable else None, analysis_runtime=False)
    connector = app.connectors["cfb"]
    logger = logging.getLogger("sports_analyst.datasets.cfb")
    monkeypatch.setattr(logger, "handlers", [*logger.handlers, caplog.handler])

    def schedule(team, season):
        rows = {str(season) + str(index): connector.schedule_rows(
            {"events": [event(str(season) + str(index), season)]}, team, season)[0] for index in (1, 2, 3, 4)}
        for index, row in enumerate(rows.values(), 1):
            # Include a live/scheduled fixture and an unknown completion flag.
            row["completed"] = (index <= 2 if season == 2025 else False) if index != 4 else None
        return rows

    monkeypatch.setattr(connector, "schedule", schedule)
    requested = Counter()
    fail = {"20252"}

    def recorded(game, season):
        requested[game] += 1
        assert game in {"20251", "20252"}, "Unplayed game was requested"
        if game in fail:
            raise TimeoutError("Missing completed-game source coverage")
        return {"plays": [{"id": game + "001", "text": "Recorded play"}], "teams": []}

    monkeypatch.setattr(connector, "game_plays", recorded)
    first = app.sync([2025], "mixed-games", ["recorded_plays"], "cfb", team_ids=["1"])
    plays = next(item for item in first if item.dataset == "recorded_plays")
    assert plays.availability == "partial"
    assert {key: plays.coverage[key] for key in (
        "scheduled_matches", "expected_matches", "completed_matches", "missing_completed_matches", "skipped_uncompleted_matches"
    )} == {"scheduled_matches": 4, "expected_matches": 2, "completed_matches": 1,
           "missing_completed_matches": 1, "skipped_uncompleted_matches": 2}
    failures = [record for record in caplog.records if record.msg.startswith("cfb_recorded_plays_unavailable")]
    assert len(failures) == 1 and failures[0].args == ("20252", 2025)
    fail.add("20251")
    missing = app.sync([2025], "all-completed-missing", ["recorded_plays"], "cfb", team_ids=["1"])
    missing = next(item for item in missing if item.dataset == "recorded_plays")
    assert missing.availability == "partial" and missing.row_count == 0
    assert missing.coverage["missing_completed_matches"] == 2
    assert missing.coverage["skipped_uncompleted_matches"] == 2
    fail.clear()
    resumed = app.sync([2025], "resumed-games", ["recorded_plays"], "cfb", team_ids=["1"])
    plays = next(item for item in resumed if item.dataset == "recorded_plays")
    assert plays.availability == "available" and plays.coverage["missing_completed_matches"] == 0
    assert set(requested) == {"20251", "20252"}
    caplog.clear()
    before = dict(requested)
    future = app.sync([2026], "future-games", ["recorded_plays", "enriched_plays"], "cfb", team_ids=["1"])
    plays = next(item for item in future if item.dataset == "recorded_plays")
    assert dict(requested) == before  # Future-only sync completes without source attempts.
    assert plays.availability == "available" and "not expected yet" in plays.availability_message
    assert plays.row_count == 0
    assert plays.coverage["scheduled_matches"] == plays.coverage["skipped_uncompleted_matches"] == 4
    assert plays.coverage["expected_matches"] == plays.coverage["missing_completed_matches"] == 0
    modeled = next(item for item in future if item.dataset == "enriched_plays")
    assert modeled.availability == "available" and modeled.row_count == 0
    assert modeled.coverage["missing_completed_matches"] == 0
    assert not any(record.exc_info for record in caplog.records)
    if durable:
        replica = LocalStore(Settings(_env_file=None, data_dir=tmp_path / "replica"), app.store.persistence)
        assert replica.manifest_for_season(2026, "recorded_plays", "cfb", partition_key="team:1").coverage == plays.coverage


@pytest.mark.parametrize("durable", [False, True])
def test_sync_checkpoints_partial_success_and_batches_catalog_publication(tmp_path, source, monkeypatch, durable):
    from sports_analyst.datasets.errors import SyncFailure

    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path),
                             persistence=DurableMemory() if durable else None, analysis_runtime=False)
    connector = app.connectors["cfb"]
    published = []
    original = app.store.publish_dataset_catalog

    def publish(manifests):
        published.append(list(manifests))
        return original(manifests)

    monkeypatch.setattr(app.store, "publish_dataset_catalog", publish)

    def interrupted(seasons, datasets, *, manifest_callback, **kwargs):
        connector.prepare(2025, team_id="1", datasets=datasets, manifest_callback=manifest_callback)
        raise TimeoutError("Interrupted after checkpoint")

    monkeypatch.setattr(connector, "sync", interrupted)
    with pytest.raises(SyncFailure):
        app.sync([2025], "checkpoint", ["schedules", "team_stats"], "cfb", team_ids=["1"])
    assert len(published) == 1 and len(published[0]) == 2
    assert len(app.store.manifests(sport="cfb")) == 2
    if durable:
        restored = LocalStore(Settings(_env_file=None, data_dir=tmp_path / "replica"), app.store.persistence)
        assert len(restored.manifests(sport="cfb")) == 2
    monkeypatch.setattr(connector, "sync", lambda seasons, datasets, **kwargs: connector.prepare(
        seasons[0], team_id="1", datasets=datasets, manifest_callback=kwargs["manifest_callback"]))
    app.sync([2025], "resume", ["schedules", "team_stats"], "cfb", team_ids=["1"])
    assert len(published) == 1  # Reused snapshots are neither uploaded nor republished.
    from datetime import UTC, datetime, timedelta

    previous = app.store.manifests(sport="cfb")[0]
    refreshed = previous.model_copy(update={"acquired_at": datetime.now(UTC) + timedelta(seconds=1)})

    def refresh(seasons, datasets, **kwargs):
        kwargs["manifest_callback"](refreshed)
        return [refreshed]

    if durable:
        monkeypatch.setattr(app.store.persistence, "upload_file", lambda *args: pytest.fail("Unchanged data was uploaded again"))
    monkeypatch.setattr(connector, "sync", refresh)
    app.sync([2025], "refresh", [previous.dataset], "cfb", team_ids=["1"])
    assert len(published) == 2
    stored = app.store.manifest_for_season(2025, previous.dataset, "cfb", partition_key="team:1")
    assert stored.acquired_at == refreshed.acquired_at  # Freshness advances even when the checksum is unchanged.


def test_play_evidence_resumes_partial_sources_and_filters_players_and_nullified_plays(tmp_path, source, monkeypatch):
    application = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, langsmith_tracing=False))
    original = CFBSource._request
    failed = [True]

    def request_source(url):
        if urlparse(url).path.endswith("/plays"):
            game = urlparse(url).path.split("/competitions/")[1].split("/")[0]
            if game == "20242" and failed[0]:
                failed[0] = False
                raise TimeoutError("One source game will succeed on retry")
            prototype = original(url)["items"][0]
            return {"items": [{**prototype, "id": f"{game}{index + 1:02}", "statYardage": yards,
                "text": "Shotgun complete to receiver" if index != 3 else "Penalty, NO PLAY",
                "participants": [{"type": "passer", "athlete": {"id": "99" if index == 2 else "10"}}]}
                for index, yards in enumerate((0, 10, 20, 99))]}
        return original(url)

    monkeypatch.setattr(CFBSource, "_request", staticmethod(request_source))
    request = AnalysisRequest(sport="cfb", question="Explain third-down conversion", analysis_domain="offense",
        subject={"type": "team", "id": "1"}, metrics=["third_down_rate"],
        scope={"team": "1", "baseline_season": 2024, "comparison_season": 2025, "comparison_design": "full_seasons"})
    partition, _ = application._prepare_cfb(request, "partial-play-evidence")
    assert application.store.manifest_for_season(2024, "recorded_plays", "cfb", partition_key=partition).availability == "partial"
    application._prepare_cfb(request, "resumed-play-evidence")
    manifests = {year: application.store.manifest_for_season(year, "schedules", "cfb", partition_key=partition) for year in (2024, 2025)}
    datasets = {year: application._load_dataset(application.connectors["cfb"], manifest) for year, manifest in manifests.items()}
    supplemental, saved = {}, {}
    for dataset in ("recorded_plays", "team_stats", "player_stats"):
        saved[dataset] = {year: application.store.manifest_for_season(year, dataset, "cfb", partition_key=partition) for year in manifests}
        supplemental[dataset] = {year: application._load_dataset(application.connectors["cfb"], manifest)
                                 for year, manifest in saved[dataset].items()}
    result = CFBPlugin().analyze(request, datasets, manifests, supplemental, saved)
    assert len(result.play_evidence) == 8
    assert {play.evidence_role for play in result.play_evidence} == {"typical", "metric_example", "supports_change", "counterexample"}
    assert all(play.candidate_pool_size == 6 and not str(play.play_id).endswith("04") for play in result.play_evidence)
    assert result.aggregate_evidence[0].baseline_value == .2 and result.aggregate_evidence[0].comparison_value == .4
    player = request.model_copy(update={"subject": request.subject.model_copy(update={"type": "player", "id": "10"}),
                                       "analysis_domain": "quarterback", "metrics": ["passing_yards"]})
    player_partition, _ = application._prepare_cfb(player, "player-play-evidence")
    for year in manifests:
        player_manifest = application.store.manifest_for_season(year, "player_stats", "cfb", partition_key=player_partition)
        supplemental["player_stats"][year] = application._load_dataset(application.connectors["cfb"], player_manifest)
    result = CFBPlugin().analyze(player, datasets, manifests, supplemental, saved)
    assert result.play_evidence and all(not str(play.play_id).endswith(("03", "04")) for play in result.play_evidence)
    assert all(play.dataset_manifest_id in {manifest.manifest_id for manifest in saved["recorded_plays"].values()}
               for play in result.play_evidence)
    supplemental["enriched_plays"], saved["enriched_plays"] = {}, {}
    for year, frame in supplemental["recorded_plays"].items():
        supplemental["enriched_plays"][year] = pl.from_dicts([
            {**row, "scrimmage": row["scrimmage"] and not row["play_id"].endswith("01"),
             "epa": .2 if row["play_id"].endswith("02") else -.3,
             "air_yards": (row["yards_gained"] - 2) if row.get("complete") and not row.get("no_play") else None,
             "yards_after_catch": 2 if row.get("complete") and not row.get("no_play") else None,
             "provider_context_json": json.dumps({"qb_hurry": True, "cp": .75,
                                                   "penalty_negated_play": row["play_id"].endswith("03")}),
             "provider_version": "verified-test-model", "model_family": "SportsDataverse test EP"}
            for row in frame.to_dicts()], infer_schema_length=None)
        saved["enriched_plays"][year] = saved["recorded_plays"][year].model_copy(
            update={"dataset": "enriched_plays", "manifest_id": f"modeled-{year}"})
    advanced = request.model_copy(update={"metrics": ["passing_epa_per_play"]})
    modeled_result = CFBPlugin().analyze(advanced, datasets, manifests, supplemental, saved)
    assert all(not str(play.play_id).endswith(("01", "03", "04")) for play in modeled_result.play_evidence)
    assert all(play.visualization.cfb_statistics["selected_play"]["model_provenance"]["provider_version"] == "verified-test-model"
               for play in modeled_result.play_evidence)
    assert all(play.visualization.cfb_statistics["provider_context"]["qb_hurry"] is True for play in modeled_result.play_evidence)
    assert all(play.visualization.air_yards is not None for play in modeled_result.play_evidence)


def test_game_identity_resolution_preserves_roles_roster_positions_and_saved_evidence(tmp_path, source, monkeypatch):
    from sports_analyst.datasets.cfb_identity import with_identity_context

    original = CFBSource._request
    identity_calls = Counter()

    def request(url):
        path = urlparse(url).path
        identity_calls[path] += 1
        if path.endswith("/plays"):
            return {"items": [{"id": "100", "type": {"text": "Pass Reception"}, "statYardage": 15,
                               "start": {"team": {"id": "1"}, "yardsToEndzone": 60},
                               "participants": [
                                   {"athlete": {"id": identity}, "type": role, "position": {"$ref": f"{CORE}/positions/{position}"},
                                    "statistics": {"$ref": f"{CORE}/events/20251/competitions/20251/competitors/2/roster/{identity}/statistics/0"}}
                                   for identity, role, position in [("10", "passer", "8"), ("12", "receiver", "7"),
                                                                    ("22", "assisted_by", "264"), ("99", "sacked_by", "35"),
                                                                    ("22", "tackler", "264")]]}]}
        if "/competitors/" in path and path.endswith("/roster"):
            team = path.split("/competitors/")[1].split("/")[0]
            players = [("12", "Roster TE", "7", False), ("66", "Roster Guard", "45", False),
                       ("77", "Did Not Play", "45", True)] if team == "1" else [("22", "Recorded Defender", "264", False)]
            entries = [{"athlete": {"$ref": f"{CORE}/seasons/2025/athletes/{identity}"}, "displayName": name,
                        "position": {"$ref": f"{CORE}/positions/{position}"}, "starter": True, "didNotPlay": dnp}
                       for identity, name, position, dnp in players]
            entries.append({"athlete": {"$ref": f"{CORE}/seasons/2026/athletes/88"}, "starter": True})
            return {"team": {"$ref": f"{CORE}/seasons/2025/teams/{team}"}, "entries": entries}
        if "/positions/" in path:
            identity = path.rsplit("/", 1)[1]
            return {"id": identity, "abbreviation": {"8": "QB", "7": "TE", "45": "G", "264": "EDGE", "35": "S"}[identity]}
        if path.endswith("/seasons/2025/athletes/99"):
            return {"id": "99", "displayName": "Resolved Safety", "team": {"id": "2"}}
        return original(url)

    monkeypatch.setattr(CFBSource, "_request", staticmethod(request))
    application = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, langsmith_tracing=False))
    connector = application.connectors["cfb"]
    detail = connector.game_plays("20251", 2025)
    row = detail["plays"][0]
    assert [(actor["name"], actor["position"]) for actor in row["participants"]] == [
        ("Transfer QB", "QB"), ("Receiver", "TE"), ("Recorded Defender", "EDGE"),
        ("Resolved Safety", "S"), ("Recorded Defender", "EDGE")]
    assert all(actor["position_source"] == "ESPN participant position" for actor in row["participants"])
    # A transferred QB's historical participant statistics link can now point
    # at the opponent. Snap possession, not that mutable link, sets his school.
    assert row["participants"][0]["team_id"] == "1"
    assert row["participants"][0]["team_source"] == "Recorded play possession and offensive role"
    assert next(actor for actor in row["participants"] if actor["athlete_id"] == "99")["team_id"] == "2"
    assert next(actor for actor in detail["game_roster"] if actor["athlete_id"] == "66")["position"] == "G"
    assert all(actor["athlete_id"] != "88" for actor in detail["game_roster"])
    assert not any(actor["athlete_id"] in {"66", "77"} for actor in row["participants"])
    assert connector.game_plays("20251", 2025) == detail
    assert max(identity_calls.values()) == 1  # Positions, roster and missing names are shared/cached.
    assert not any("seasons/2026" in path or path.endswith("/athletes/66") for path in identity_calls)
    saved = {"play_id": "100", "identity_context_version": 1,
             "participants": [{"athlete_id": "12", "role": "receiver", "team_id": "2"}], "epa": .25}
    merged = with_identity_context(saved, row)
    assert merged["epa"] == .25 and len(merged["participants"]) == 5
    assert merged["participants"][0]["team_id"] == "1"
    assert saved["participants"] == [{"athlete_id": "12", "role": "receiver", "team_id": "2"}]
    # Opening an older saved analysis upgrades labels without replacing model values.
    from types import SimpleNamespace

    saved.update(source_play_count=1, provider_version="saved-model", render_context_version=2)
    item = SimpleNamespace(sport="cfb", game_id="20251", season=2025,
                           visualization=SimpleNamespace(cfb_statistics={"modeled_plays": [saved], "teams": detail["teams"]}))
    monkeypatch.setattr(application, "evidence", lambda *args: item)
    response = TestClient(create_app(application)).post("/api/investigations/legacy/evidence/play/plays")
    assert response.status_code == 200
    assert response.json()["plays"][0]["epa"] == .25
    assert len(response.json()["plays"][0]["participants"]) == 5
    assert response.json()["game_roster"] == detail["game_roster"]
    # Optional lookups can fail without turning a real play into an empty game.
    def unavailable(url):
        if "/positions/" in url or "/roster" in url or "/athletes/" in url:
            raise TimeoutError("Optional identity source unavailable")
        return request(url)

    monkeypatch.setattr(CFBSource, "_request", staticmethod(unavailable))
    fallback = SportsDataverseCFBConnector(Settings(_env_file=None, data_dir=tmp_path / "fallback")).game_plays("20251", 2025)
    assert len(fallback["plays"][0]["participants"]) == 5
    assert fallback["plays"][0]["participants"][0]["name"] == "Transfer QB"
    assert fallback["plays"][0]["participants"][2]["name"] is None
    assert fallback["game_roster"] == []


def test_game_scoped_render_context_is_cached_and_refreshes_legacy_saved_geometry(tmp_path, source, monkeypatch):
    from types import SimpleNamespace
    from sports_analyst.datasets.cfb_plays import teams_and_athletes

    application = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, langsmith_tracing=False))
    connector = application.connectors["cfb"]
    raw = {**summary("20251", 2025), "drives": {"previous": []}}
    monkeypatch.setattr(connector, "summary", lambda *args: raw)
    directory = (*teams_and_athletes(raw), {})
    monkeypatch.setattr("sports_analyst.datasets.cfb_identity.game_directory", lambda *args: (
        directory, [{"athlete_id": "10", "team_id": "1"}, {"athlete_id": "20", "team_id": "2"}]))
    source_plays = [{"id": "101", "type": {"text": "Pass Reception"},
                     "text": "Pass complete to receiver caught at ABC35", "statYardage": 15,
                     "start": {"yardsToEndzone": 60, "team": {"id": "1"}},
                     "end": {"yardsToEndzone": 45, "team": {"id": "1"}}},
                    {"id": "102", "type": {"text": "Pass Incompletion"}, "text": "Pass incomplete",
                     "start": {"yardsToEndzone": 60, "team": {"id": "1"}}}]
    monkeypatch.setattr(connector.source, "collection", lambda *args, **kwargs: source_plays)
    calls = []

    def clean(game, summary, *, context_only=False):
        calls.append(context_only)
        return {"plays": [{"id": "101", "air_yards": 10, "yards_after_catch": 99,
                           "air_yardsToEndzone": 50, "pass_direction": "right", "pass_depth": "short",
                           "qb_hurry": False, "cp": 0.0, "gameSpread": 0.0},
                          {"id": "102", "air_yards": None, "yards_after_catch": None}]}

    monkeypatch.setattr("sports_analyst.datasets.cfb_enrichment.process_summary", clean)
    normalizations = []
    normalize = connector._game_plays

    def normalize_counted(*args):
        normalizations.append(args[0])
        return normalize(*args)

    monkeypatch.setattr(connector, "_game_plays", normalize_counted)
    first = connector.game_plays("20251", 2025)
    second = connector.game_plays("20251", 2025)
    assert calls == [True]  # Cached lightweight cleaning, never the full model pipeline.
    assert normalizations == ["20251"]  # Reuse the entire normalized game, not only cleaning.
    assert first == second
    assert first["plays"][0]["air_yards"] == 10
    assert first["plays"][0]["yards_after_catch"] == 5  # Trust recorded net yards, not the inconsistent 99.
    assert first["plays"][0]["pass_direction"] == "right"
    context = json.loads(first["plays"][0]["provider_context_json"])
    assert context["qb_hurry"] is False and context["cp"] == 0.0
    assert "gameSpread" not in context
    assert first["plays"][1].get("air_yards") is None
    assert first["plays"][1].get("yards_after_catch") is None
    saved = {"play_id": "101", "participants": [], "epa": .25, "provider_version": "saved-model",
             "source_play_count": 2}
    item = SimpleNamespace(sport="cfb", game_id="20251", season=2025,
                           visualization=SimpleNamespace(cfb_statistics={"modeled_plays": [saved], "teams": first["teams"]}))
    monkeypatch.setattr(application, "evidence", lambda *args: item)
    response = TestClient(create_app(application)).post("/api/investigations/legacy/evidence/play/plays")
    assert response.status_code == 200
    row = response.json()["plays"][0]
    assert (row["air_yards"], row["yards_after_catch"], row["epa"]) == (10, 5, .25)
    assert "air_yards" not in saved  # Saved analysis remains immutable.
    raw["header"]["source_revision"] = 2
    connector.game_plays("20251", 2025)
    assert normalizations == ["20251", "20251"]  # A changed summary invalidates derived output.


def test_on_demand_modeled_plays_preserve_attribution_coverage_and_weighting(tmp_path, source, monkeypatch):
    from sports_analyst.datasets.cfb_enrichment import athlete_roles

    assert athlete_roles({"participants": [{"type": "passer", "athlete": {"displayName": "Transfer QB"}}]}) == {}
    original = CFBSource.collection
    modeled_calls = Counter()

    def collection(self, url, ttl=86400, maximum=500):
        if url.endswith("/plays"):
            game = url.split("/competitions/")[1].split("/")[0]
            count = 1 if game.endswith("1") else 3
            return [
                {
                    "id": f"{game}-{index}",
                    "text": "Recorded pass complete to receiver",
                    "type": {"text": "Pass Reception"},
                    "statYardage": 15,
                    "period": {"number": 1},
                    "participants": [{"type": "passer", "athlete": {"$ref": f"{CORE}/athletes/10"}}] if index == 0 else [],
                }
                for index in range(count)
            ]
        return original(self, url, ttl, maximum)

    def pipeline(game, raw):
        modeled_calls[game] += 1
        count = 1 if game.endswith("1") else 3
        epa = 3.0 if game.startswith("2025") else 0.0 if count == 1 else 2.0
        return {
            "plays": [
                {
                    "id": f"{game}-{index}",
                    "start.pos_team.id": "1",
                    "scrimmage_play": True,
                    "pass": True,
                    "rush": False,
                    "EPA": epa,
                    "wpa_naive": 0.01,
                    "air_yards": 10 if game.startswith("2025") else None,
                    "yards_after_catch": 99 if game.startswith("2025") else None,
                    "pass_direction": "right",
                    "pass_depth": "short",
                    # This name/ID is deliberately not authoritative.
                    "passer_player_name": "Transfer QB",
                    "passer_player_id": "10",
                }
                for index in range(count)
            ],
            "advBoxScore": {"team": []},
        }

    monkeypatch.setattr(CFBSource, "collection", collection)
    monkeypatch.setattr("sports_analyst.datasets.cfb_enrichment.process_summary", pipeline)
    application = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, model_provider="ollama", langsmith_tracing=False))
    request = AnalysisRequest(
        sport="cfb",
        question="How did modeled passing efficiency change?",
        analysis_domain="offense",
        subject={"type": "team", "id": "1"},
        metrics=["epa_per_play", "offensive_wpa"],
        scope={"team": "1", "baseline_season": 2024, "comparison_season": 2025},
    )
    partition, _ = application._prepare_cfb(request, "advanced-prepare")
    connector = application.connectors["cfb"]
    manifests = {year: application.store.manifest_for_season(year, "schedules", "cfb", partition_key=partition) for year in (2024, 2025)}
    schedules = {year: connector.load(item) for year, item in manifests.items()}
    modeled = {
        year: connector.load(application.store.manifest_for_season(year, "enriched_plays", "cfb", partition_key=partition))
        for year in (2024, 2025)
    }
    result = CFBPlugin().analyze(request, schedules, manifests, {"enriched_plays": modeled})
    assert result.aggregate_evidence[0].baseline_value == 1.5
    assert result.aggregate_evidence[0].comparison_value == 3.0
    assert result.aggregate_evidence[0].sample_size == 4
    assert result.aggregate_evidence[1].comparison_value == 0.04
    assert "modeled_plays" in result.play_evidence[0].visualization.cfb_statistics
    assert modeled[2025]["air_yards"].to_list() == [10.0] * 4
    assert modeled[2025]["yards_after_catch"].to_list() == [5.0] * 4
    assert modeled[2025]["pass_direction"].to_list() == ["right"] * 4
    assert modeled[2025]["render_context_version"].to_list() == [2] * 4
    saved_rows = [row for play in result.play_evidence if play.season == 2025
                  for row in play.visualization.cfb_statistics["modeled_plays"]]
    assert saved_rows and all(row["air_yards"] == 10 for row in saved_rows)
    assert result.play_evidence[0].visualization.cfb_statistics["covered_team_epa"][0]["epa_per_play"] == 1.5
    player = request.subject.model_copy(update={"type": "player", "id": "10"})
    assert CFBPlugin.value("player_passing_epa", schedules[2024], modeled[2024], player) == (1.0, 2)
    assert CFBPlugin.value("player_passing_cpoe", schedules[2024], modeled[2024], player) == (None, 0)
    cpoe = modeled[2024].with_columns(pl.lit(4.0).alias("cpoe"))
    assert CFBPlugin.value("player_passing_cpoe", schedules[2024], cpoe, player) == (4.0, 2)
    application._prepare_cfb(request, "advanced-repeat")
    assert all(count == 1 for count in modeled_calls.values())
    # Rendering context is also analytical evidence, with play-level coverage,
    # unique structured attribution and missing values excluded from the mean.
    contextual = {year: data.with_columns(
        pl.when(pl.col("passer_id").is_not_null()).then(pl.lit(10.0 if year == 2024 else 12.0)).otherwise(None).alias("air_yards"),
        pl.when(pl.col("passer_id").is_not_null()).then(pl.lit(5.0 if year == 2024 else 3.0)).otherwise(None).alias("yards_after_catch"),
    ) for year, data in modeled.items()}
    enriched_result = CFBPlugin().analyze(request, schedules, manifests, {"enriched_plays": contextual})
    context_evidence = {item.metric: item for item in enriched_result.aggregate_evidence}
    assert (context_evidence["passing_air_yards"].baseline_value, context_evidence["passing_air_yards"].comparison_value) == (10, 12)
    assert (context_evidence["passing_yac"].baseline_value, context_evidence["passing_yac"].comparison_value) == (5, 3)
    assert context_evidence["passing_air_yards"].sample_size == 2
    assert context_evidence["passing_air_yards"].context["supporting_context"] is True
    assert context_evidence["passing_air_yards"].context["play_context_coverage"]["passing_air_yards"]["baseline"] == {"available": 2, "eligible": 4}
    assert CFBPlugin.value("player_passing_air_yards", schedules[2024], contextual[2024], player) == (10, 2)
    from sports_analyst.analysis.agents import _citation_ledger
    _, agent_aggregates, agent_plays = _citation_ledger(enriched_result.aggregate_evidence, enriched_result.play_evidence)
    assert any(item["metric"] == "passing_air_yards" for item in agent_aggregates)
    assert any(row.get("air_yards") == 12 for item in agent_plays
               for row in item["visualization"]["cfb_statistics"].get("modeled_plays", []))
    mismatched = modeled[2025].with_columns(pl.lit("different-provider").alias("provider_version"))
    with pytest.raises(ValueError, match="No comparable"):
        CFBPlugin().analyze(request, schedules, manifests, {"enriched_plays": {2024: modeled[2024], 2025: mismatched}})
