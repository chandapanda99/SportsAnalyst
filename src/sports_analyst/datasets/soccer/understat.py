"""SoccerData 1.9.0 parsing through bounded, durable Understat acquisition."""
from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import logging
import os
import re
from http.cookiejar import CookieJar
from threading import Lock
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import polars as pl

from sports_analyst.analysis.research.state import ACTIVE_BUDGET, ContextPool, ResearchLimit, ResearchState
from sports_analyst.datasets.availability import SourceUnavailable
from sports_analyst.datasets.cfb_source import CFBSource
from sports_analyst.datasets.optional import load_optional_module
from sports_analyst.datasets.soccer.enrichment import name_key
from sports_analyst.datasets.soccer.club_identity import club_key
from sports_analyst.datasets.soccer.statistics import number
from sports_analyst.models import DatasetManifest, stable_id

VERSION = "understat-soccerdata-1"
logger = logging.getLogger(__name__)
PACKAGE_VERSION = "1.9.0"
DATASETS = ("understat_team_matches", "understat_player_matches", "understat_shots")
LEAGUES = {"eng.1": ("ENG-Premier League", "EPL"), "esp.1": ("ESP-La Liga", "La_liga"),
           "ger.1": ("GER-Bundesliga", "Bundesliga"), "ita.1": ("ITA-Serie A", "Serie_A"),
           "fra.1": ("FRA-Ligue 1", "Ligue_1")}
def team_key(value, competition=None):
    return club_key(value, competition)


def fixture_signature(fixture):
    fields = {key: str(fixture.get(key)) for key in ("event_id", "home_team_id", "away_team_id")}
    fields.update(date=str(fixture.get("date", ""))[:10],
                  home_score=number(fixture.get("home_score")), away_score=number(fixture.get("away_score")))
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def records(frame):
    if frame.empty:
        return []
    # Keep named MultiIndex identities before crossing the pandas/Polars boundary.
    return json.loads(frame.reset_index().to_json(orient="records", date_format="iso"))


def fixture_match(native, fixture):
    return (all(native.get(f"{side}_team_id") is not None and fixture.get(f"{side}_team_id") is not None
                and native.get(f"{side}_team") and fixture.get(f"{side}_team")
                for side in ("home", "away")) and native.get("game_id") is not None
            and native.get("is_result") is True
            and str(native.get("date", ""))[:10] == str(fixture.get("date", ""))[:10]
            and all(team_key(native.get(f"{side}_team"), fixture.get("competition")) == team_key(fixture.get(f"{side}_team"), fixture.get("competition"))
                    and bool(team_key(native.get(f"{side}_team"), fixture.get("competition")))
                    and number(native.get(f"{side}_goals")) is not None
                    and number(native.get(f"{side}_goals")) == number(fixture.get(f"{side}_score"))
                    for side in ("home", "away")))


def tablet_rows(game_id, datasets):
    """Adapt recorded event points to the existing shot view, without trajectories."""
    rows = {}
    for dataset in DATASETS:
        frame = datasets.get(dataset, pl.DataFrame())
        if "game_id" not in frame.columns:
            continue
        for item in frame.filter(pl.col("game_id").cast(pl.String) == str(game_id)).iter_rows(named=True):
            team = str(item["team_id"])
            row = rows.setdefault(team, {"team_id": team, "team_name": item.get("team_name", team),
                                        "provider": "understat", "shots": [], "players": []})
            if dataset == "understat_team_matches":
                row.update(item)
            elif dataset == "understat_shots":
                row["shots"].append({"id": item["id"], "espn_team_id": team, "x": item["x"], "y": item["y"],
                    "provider_player_id": item.get("provider_player_id"), "coordinate_system": item.get("coordinate_system"),
                    "min": item["minute"], "playerName": item["player_name"], "eventType": item["outcome"],
                    "expectedGoals": item["expected_goals"], "shotType": item["body_part"], "situation": item["situation"]})
            else:
                row["players"].append({**item, "name": item["player_name"]})
    for row in rows.values():
        row["shots_json"] = json.dumps(row.pop("shots"))
        row["players_json"] = json.dumps(row.pop("players"))
        row["context_json"] = json.dumps({"coordinate_system": "Understat attacking direction scaled to 105x68",
            "coverage_level": "Recorded shots/player counters only; no tracking or inferred xGOT"})
    return list(rows.values())


def attach_tablets(plays, access):
    """Expose newly acquired research inputs on already selected match evidence."""
    by_season = {}
    for manifest in access.manifests.values():
        if manifest.dataset in DATASETS and manifest.row_count:
            by_season.setdefault(manifest.season, {})[manifest.dataset] = manifest
    for play in plays:
        if not play.visualization or play.season not in by_season:
            continue
        manifests = by_season[play.season]
        frames = {key: access.app._load_dataset(access.app.connectors["soccer"], value) for key, value in manifests.items()}
        rows = tablet_rows(play.game_id, frames)
        if rows:
            visual = play.visualization
            play.visualization = visual.model_copy(update={
                "soccer_analytics": [row for row in visual.soccer_analytics if row.get("provider") != "understat"] + rows,
                "source_packages": list(dict.fromkeys([*visual.source_packages, *manifests])),
                "soccer_analytics_manifest_ids": list(dict.fromkeys([*visual.soccer_analytics_manifest_ids,
                    *[manifest.manifest_id for manifest in manifests.values()]]))})


class UnderstatSource:
    def __init__(self, connector):
        self.connector = connector
        self.source = connector.source_cache or CFBSource(connector.data_dir, namespace="soccer")
        self.inputs = {}
        self.cookies = CookieJar()
        self.cookie_lock = Lock()
        self.cookies_initialized = False

    def client(self, competition, season, refresh):
        os.environ.setdefault("SOCCERDATA_DIR", str(self.connector.data_dir / "soccerdata"))
        module = load_optional_module("soccerdata", "Understat xG and shot data")
        if importlib.metadata.version("soccerdata") != PACKAGE_VERSION:
            raise RuntimeError("Understat transport requires the locked SoccerData 1.9.0 release")
        owner = self

        class BoundedUnderstat(module.Understat):
            @classmethod
            def _all_leagues(cls):
                # Upstream selects its league map by class name.
                return module.Understat._all_leagues()

            # All API requests use our transport; no cookie/browser session is used.
            def _ensure_cookies(self):
                return None

            def _request_api(self, url, filepath=None, no_cache=False):
                parsed = urlparse(url)
                slug = LEAGUES[competition][1]
                allowed = ("/getStatData", f"/getLeagueData/{slug}/{season - 1}")
                if (parsed.scheme != "https" or parsed.netloc != "understat.com" or parsed.query or parsed.fragment
                        or not (parsed.path in allowed or re.fullmatch(r"/getMatchData/\d+", parsed.path))):
                    raise ValueError("Unapproved Understat source request")
                key = f"{competition}/providers/understat/{VERSION}/{season}/raw/{parsed.path.strip('/').replace('/', '-')}.json"
                with owner.source.lease(key, seconds=180):
                    cached = owner.source._cached(key, 3600 if refresh else 365 * 86400)
                    if cached is None:
                        budget = ACTIVE_BUDGET.get()
                        if budget is None:
                            raise RuntimeError("Understat requests must run within the worker acquisition budget")
                        # Mirror upstream's session initialization, charging that
                        # request too. Cached reads require no session/network.
                        with owner.cookie_lock:
                            if not owner.cookies_initialized:
                                budget.fetch("https://understat.com/", max_bytes=4 * 1024**2,
                                    headers={"X-Requested-With": "XMLHttpRequest"}, cookie_jar=owner.cookies)
                                owner.cookies_initialized = True
                        cached = json.loads(budget.fetch(url, max_bytes=16 * 1024**2,
                            headers={"X-Requested-With": "XMLHttpRequest"}, cookie_jar=owner.cookies))
                        if not isinstance(cached, dict) or not cached:
                            raise ValueError("Understat returned no usable payload")
                        if ((parsed.path == "/getStatData" and cached.get("stat") == [])
                                or (parsed.path.startswith("/getLeagueData/") and cached.get("dates") == [])):
                            raise SourceUnavailable("Understat has no recorded season data for this lookup")
                        checksum = hashlib.sha256(json.dumps(cached, sort_keys=True).encode()).hexdigest()
                        payload_key = f"{competition}/providers/understat/{VERSION}/{season}/raw/payload-{checksum}.json"
                        owner.source.store(payload_key, cached)
                        owner.source.store(key, cached)
                owner.inputs[parsed.path] = hashlib.sha256(json.dumps(cached, sort_keys=True).encode()).hexdigest()
                return io.BytesIO(json.dumps(cached).encode())

        return BoundedUnderstat(leagues=LEAGUES[competition][0], seasons=f"{season - 1}/{season}",
            data_dir=self.connector.data_dir / competition / str(season) / "soccerdata", no_store=True)

    def prepare(self, competition, season, fixtures, datasets, refresh=False, progress=None):
        if competition not in LEAGUES:
            raise ValueError("Understat is supported only for the five configured European domestic leagues")
        if not self.connector.settings.soccer_understat_enabled:
            raise ValueError("Understat acquisition is disabled by SOCCER_UNDERSTAT_ENABLED")
        if season < 2015 or not set(datasets) <= set(DATASETS):
            raise ValueError("Unsupported Understat season or dataset")
        if fixtures.is_empty():
            return [(name, pl.DataFrame(), {"expected_matches": 0, "completed_matches": 0,
                "recorded_matches": 0, "failed_requests": 0}) for name in datasets]
        # Explicit syncs also use persisted request/byte/time bounds. Research
        # acquisitions reuse their existing cumulative budget, including retries.
        budget = ACTIVE_BUDGET.get() or ResearchState(SimpleNamespace(settings=self.connector.settings,
            store=SimpleNamespace(persistence=self.source.persistence)), f"understat-sync-{uuid4().hex}")
        token = ACTIVE_BUDGET.set(budget)
        try:
            return self._prepare(competition, season, fixtures, datasets, refresh, progress)
        finally:
            ACTIVE_BUDGET.reset(token)

    def _prepare(self, competition, season, fixtures, datasets, refresh, progress):
        client = self.client(competition, season, refresh)
        schedule_frame = client.read_schedule(include_matches_without_data=True, force_cache=not refresh)
        schedule = records(schedule_frame)
        team_stats = records(client.read_team_match_stats(force_cache=not refresh))
        stats = {str(row["game_id"]): row for row in team_stats}
        if len(stats) != len(team_stats):
            raise ValueError("Duplicate Understat team-match records")
        mapped, ambiguous, missing = [], 0, 0
        for fixture in fixtures.iter_rows(named=True):
            matches = [row for row in schedule if fixture_match(row, fixture)]
            if len(matches) == 1:
                mapped.append((fixture, matches[0]))
            elif matches:
                ambiguous += 1
            else:
                missing += 1
        # No provider match may represent two ESPN observations.
        counts = {}
        for _, row in mapped:
            counts[str(row["game_id"])] = counts.get(str(row["game_id"]), 0) + 1
        ambiguous += sum(1 for _, row in mapped if counts[str(row["game_id"])] != 1)
        mapped = [(f, r) for f, r in mapped if counts[str(r["game_id"])] == 1]
        rows = {dataset: [] for dataset in datasets}
        failures = {dataset: 0 for dataset in datasets}

        def match_work(pair):
            fixture, native = pair
            match_id = int(native["game_id"])
            if not set(datasets) & {"understat_player_matches", "understat_shots"}:
                return fixture, native, {}, []
            # A client per worker avoids shared mutable provider sessions.
            reader = self.client(competition, season, refresh)
            # The package resolves match IDs through its schedule on every call.
            # Reuse this verified season table rather than reparsing it per match.
            reader.read_schedule = lambda include_matches_without_data=True, **kwargs: (
                schedule_frame if include_matches_without_data else schedule_frame[schedule_frame["has_data"]])
            values, failed = {}, []
            for dataset, method in (("understat_player_matches", reader.read_player_match_stats),
                                    ("understat_shots", reader.read_shot_events)):
                if dataset not in datasets:
                    continue
                try:
                    values[dataset] = records(method(match_id=match_id))
                except ResearchLimit:
                    raise
                except (OSError, ValueError, KeyError, TypeError):
                    failed.append(dataset)
            return fixture, native, values, failed

        with ContextPool(max_workers=self.connector.settings.dataset_sync_concurrency) as pool:
            # map is bounded to this scoped fixture list, never opponent seasons.
            for index, (fixture, native, values, failed) in enumerate(pool.map(match_work, mapped), 1):
                for dataset in failed:
                    failures[dataset] += 1
                team_map = {str(native[f"{side}_team_id"]): (side, str(fixture[f"{side}_team_id"]))
                            for side in ("home", "away")}
                shared = {"game_id": str(fixture["event_id"]), "provider_game_id": str(native["game_id"]),
                    "fixture_sha256": fixture_signature(fixture),
                    "source_payloads_json": json.dumps({key: self.inputs[key] for key in sorted(self.inputs)
                        if key in {"/getStatData", f"/getLeagueData/{LEAGUES[competition][1]}/{season - 1}",
                                   f"/getMatchData/{native['game_id']}"}}, sort_keys=True),
                    "date": str(fixture["date"])[:10], "season": season, "competition": competition,
                    "provider": "understat", "definition_version": VERSION,
                    "source_model": "Understat reported xG; upstream model version undisclosed",
                    "crosswalk_json": json.dumps({"method": "unique_competition_date_sides_score", "version": VERSION,
                        "espn_game_id": str(fixture["event_id"]), "understat_game_id": str(native["game_id"])})}
                raw = stats.get(str(native["game_id"]), {})
                for native_team, (side, canonical) in team_map.items():
                    if "understat_team_matches" in rows and raw:
                        values_row = {"expected_goals": raw.get(f"{side}_xg"),
                            "non_penalty_xg": raw.get(f"{side}_np_xg"), "expected_points": raw.get(f"{side}_expected_points"),
                            "goals": raw.get(f"{side}_goals"), "ppda": raw.get(f"{side}_ppda"),
                            "deep_completions": raw.get(f"{side}_deep_completions")}
                        rows["understat_team_matches"].append({**shared, "team_id": canonical,
                            "team_name": fixture[f"{side}_team"], "provider_team_id": native_team,
                            **{key: number(value) for key, value in values_row.items()}, "extensions_json": json.dumps(raw)})
                for dataset, people in values.items():
                    for person in people:
                        native_team = str(person.get("team_id"))
                        if native_team not in team_map:
                            continue
                        if ((dataset == "understat_player_matches" and person.get("player_id") is None)
                                or (dataset == "understat_shots" and person.get("shot_id") is None)):
                            failures[dataset] += 1
                            continue
                        side, canonical = team_map[native_team]
                        row = {**shared, "team_id": canonical, "team_name": fixture[f"{side}_team"], "provider_team_id": native_team,
                            "provider_player_id": str(person["player_id"]) if person.get("player_id") is not None else None,
                            "player_name": person.get("player"), "expected_goals": number(person.get("xg")),
                            "extensions_json": json.dumps(person)}
                        if dataset == "understat_player_matches":
                            row.update({key: number(person.get(field)) for key, field in {
                                "goals": "goals", "shots": "shots", "minutes_played": "minutes",
                                "expected_assists": "xa", "xg_chain": "xg_chain", "xg_buildup": "xg_buildup"}.items()})
                        else:
                            x, y = number(person.get("location_x")), number(person.get("location_y"))
                            row.update(id=str(person["shot_id"]), minute=number(person.get("minute")),
                                x=x * 105 if x is not None and 0 <= x <= 1 else None,
                                y=y * 68 if y is not None and 0 <= y <= 1 else None,
                                outcome=person.get("result"), situation=person.get("situation"), body_part=person.get("body_part"),
                                coordinate_system="Understat normalized attacking direction scaled to 105x68; not tracking")
                        rows[dataset].append(row)
                if progress:
                    progress(index, len(mapped))
        produced = []
        for dataset in datasets:
            frame = pl.from_dicts(rows[dataset], infer_schema_length=None) if rows[dataset] else pl.DataFrame()
            keys = ["game_id", "team_id"] + (["id"] if dataset == "understat_shots" else
                ["provider_player_id"] if dataset == "understat_player_matches" else [])
            if not frame.is_empty() and frame.select(keys).is_duplicated().any():
                raise ValueError("Duplicate Understat observations; refusing to publish multiplied evidence")
            if not frame.is_empty():
                frame = frame.sort([k for k in ("game_id", "minute", "id", "team_id", "provider_player_id") if k in frame.columns])
            covered = frame["game_id"].n_unique() if "game_id" in frame.columns else 0
            coverage = {"expected_matches": fixtures.height, "completed_matches": covered,
                "matched_matches": len(mapped), "recorded_matches": covered,
                "unmatched_matches": missing, "ambiguous_matches": ambiguous, "failed_requests": failures[dataset],
                **{f"{key}_rows": frame[key].is_not_null().sum() for key in frame.columns if frame.schema[key].is_numeric()}}
            produced.append((dataset, frame, coverage))
        return produced

    def publish(self, competition, season, fixtures, datasets, team_id=None, refresh=False, progress=None):
        output = []
        try:
            prepared = self.prepare(competition, season, fixtures, datasets, refresh, progress)
        except (OSError, SourceUnavailable) as error:
            logger.warning("soccer_understat_acquisition_unavailable competition=%s season=%s error_type=%s",
                           competition, season, type(error).__name__)
            prepared = [(name, pl.DataFrame(), {"expected_matches": fixtures.height, "recorded_matches": 0,
                "completed_matches": 0, "failed_requests": int(isinstance(error, OSError)), "matched_matches": 0}) for name in datasets]
        for dataset, frame, coverage in prepared:
            partition = f"team:{team_id}" if team_id else None
            path = (self.connector.data_dir / competition / "providers" / "understat" / VERSION / str(season)
                    / (team_id or "competition") / f"{dataset}.parquet")
            # Failed refreshes retain previous observations from this exact scope.
            if path.exists():
                previous = pl.read_parquet(path)
                if {"game_id", "fixture_sha256"} <= set(previous.columns):
                    fresh = frame["game_id"].unique().to_list() if "game_id" in frame.columns else []
                    signatures = [fixture_signature(row) for row in fixtures.iter_rows(named=True)]
                    previous = previous.filter(pl.col("game_id").is_in(fixtures["event_id"].cast(pl.String).to_list())
                                               & pl.col("fixture_sha256").is_in(signatures) & ~pl.col("game_id").is_in(fresh))
                    if previous.height:
                        frame = pl.concat([frame, previous], how="diagonal_relaxed") if frame.width else previous
                        coverage["retained_matches"] = previous["game_id"].n_unique()
            if not frame.is_empty():
                frame = frame.sort([k for k in ("game_id", "minute", "id", "team_id", "provider_player_id") if k in frame.columns])
                coverage.update({f"{key}_rows": frame[key].is_not_null().sum()
                                 for key in frame.columns if frame.schema[key].is_numeric()})
            buffer = io.BytesIO()
            frame.write_parquet(buffer)
            CFBSource._write_local(path, buffer.getvalue())
            checksum = hashlib.sha256(buffer.getvalue()).hexdigest()
            # Reports and join plans reference immutable bytes even after a
            # later current-season refresh replaces the working snapshot.
            snapshot = path.with_name(f"{dataset}-{checksum}.parquet")
            if not snapshot.exists():
                CFBSource._write_local(snapshot, buffer.getvalue())
            count = frame["game_id"].n_unique() if "game_id" in frame.columns else 0
            coverage.update(recorded_matches=count, completed_matches=count)
            availability = "available" if count and count == fixtures.height else "partial" if count else "source_unavailable"
            if coverage["failed_requests"]:
                availability = "partial" if count else "download_failed"
            output.append(DatasetManifest(manifest_id=stable_id("dataset", {"provider": "understat", "version": VERSION,
                "dataset": dataset, "season": season, "competition": competition, "partition": partition, "sha256": checksum}),
                sport="soccer", competition=competition, dataset=dataset, season=season, partition_key=partition,
                download_scope="team" if team_id else "league", source_scope="league",
                source_sha256=hashlib.sha256(json.dumps(sorted(set(frame["source_payloads_json"].to_list()))).encode()).hexdigest()
                    if "source_payloads_json" in frame.columns else None,
                source_url="https://understat.com/", provider_id="understat", processing_version=VERSION,
                resolution_version=VERSION, sha256=checksum, row_count=frame.height, columns=frame.columns,
                package_version=f"soccerdata:{PACKAGE_VERSION}", license="See Understat data terms; no redistribution rights inferred.",
                attribution="Understat data acquired using SoccerData; corroborated ESPN fixture/team mapping.",
                local_path=str(snapshot.resolve()), file_size=snapshot.stat().st_size, modified_ns=snapshot.stat().st_mtime_ns,
                coverage=coverage, availability=availability,
                availability_message=("Understat requests failed; retry acquisition. Previously verified rows were retained."
                    if coverage["failed_requests"] else
                    "Unmatched fixtures and missing source fields remain explicit; xGOT is not inferred.")
                    if availability != "available" else None))
        return output
