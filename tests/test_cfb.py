"""Major conference, scoped preparation, transfer, and evidence workflows."""

import threading
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
                        "id": f"{game}-pass",
                        "text": "Transfer QB recorded pass",
                        "type": {"text": "Pass"},
                        "start": {"down": 1, "distance": 10, "yardsToEndzone": 60, "team": {"id": "1"}},
                        "end": {"yardsToEndzone": 45, "team": {"id": "1"}},
                        "participants": [{"type": "passer", "athlete": {"id": "10"}}],
                    }
                ]
            }
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
    assert client.get("/api/investigations/cfb-end-to-end").status_code == 200
    game = bundle.play_evidence[0]
    assert client.get(f"/api/investigations/cfb-end-to-end/evidence/{game.evidence_id}").json()["sport"] == "cfb"
    detail = client.post(f"/api/investigations/cfb-end-to-end/evidence/{game.evidence_id}/plays")
    assert detail.status_code == 200
    assert detail.json()["plays"][0]["participants"][0]["athlete_id"] == "10"
    assert detail.json()["plays"][0]["yards_to_goal"] == 60
    child = application.follow_up("cfb-end-to-end", "Which games were covered?", "cfb-follow-up")
    assert child.run.sport == "cfb" and child.aggregate_evidence == bundle.aggregate_evidence


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
                    "text": "Recorded pass",
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
    assert result.play_evidence[0].visualization.cfb_statistics["covered_team_epa"][0]["epa_per_play"] == 1.5
    player = request.subject.model_copy(update={"type": "player", "id": "10"})
    assert CFBPlugin.value("player_passing_epa", schedules[2024], modeled[2024], player) == (1.0, 2)
    assert CFBPlugin.value("player_passing_cpoe", schedules[2024], modeled[2024], player) == (None, 0)
    cpoe = modeled[2024].with_columns(pl.lit(4.0).alias("cpoe"))
    assert CFBPlugin.value("player_passing_cpoe", schedules[2024], cpoe, player) == (4.0, 2)
    application._prepare_cfb(request, "advanced-repeat")
    assert all(count == 1 for count in modeled_calls.values())
    mismatched = modeled[2025].with_columns(pl.lit("different-provider").alias("provider_version"))
    with pytest.raises(ValueError, match="No comparable"):
        CFBPlugin().analyze(request, schedules, manifests, {"enriched_plays": {2024: modeled[2024], 2025: mismatched}})
