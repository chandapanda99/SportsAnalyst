"""Scoped secondary match context, linked by corroborated fixture identity.

Provider player IDs never become ESPN athlete IDs. Raw payloads remain cached;
the normalized team-match rows expose counters without repeating event grain.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from concurrent.futures import as_completed
from contextlib import nullcontext
from datetime import date
from urllib.parse import urlencode

import polars as pl

from sports_analyst.analysis.research.state import ACTIVE_BUDGET, ContextPool, ResearchLimit, budget_json
from sports_analyst.datasets.optional import OptionalDependencyError, load_optional_module
from sports_analyst.datasets.soccer.statistics import ALIASES, number, stat_key

VERSION = "soccer-context-1"
# Provider competition IDs, not team/player identity mappings.
FOTMOB_LEAGUES = {"eng.1": 47, "esp.1": 87, "ger.1": 54, "ita.1": 55,
                  "fra.1": 53, "usa.1": 889747, "usa.nwsl": 112, "uefa.champions": 42}
ASA_LEAGUES = {"usa.1": "mls", "usa.nwsl": "nwsl"}


def name_key(name):
    return "".join(c for c in unicodedata.normalize("NFKD", str(name)).casefold() if c.isalnum())


def same_side(native, fixture, side):
    names = {name_key(native.get(key, "")) for key in ("name", "longName", "shortName")}
    return bool(name_key(fixture.get(f"{side}_team", ""))) and name_key(fixture[f"{side}_team"]) in names


def fixture_matches(native, fixture):
    status = native.get("status") or {}
    return (status.get("finished") is True and not status.get("cancelled") and not status.get("awarded")
            and str(status.get("utcTime", ""))[:10] == str(fixture.get("date", ""))[:10]
            and all(same_side(native.get(side, {}), fixture, side)
                    and number(native.get(side, {}).get("score")) is not None
                    and number(native[side]["score"]) == number(fixture.get(f"{side}_score")) for side in ("home", "away")))


def counters(stats):
    """Retain numeric recorded values and fraction denominators, never parse display prose."""
    result = {}
    for key, raw in stats:
        key = ALIASES.get(stat_key(key), stat_key(key))
        if not key or key in {"game_id", "team_id"} or not isinstance(raw, dict):
            continue
        value = number(raw.get("value"))
        if value is not None:
            if key in result and result[key] != value:
                raise ValueError(f"Conflicting provider statistic {key}")
            result[key] = value
        total = number(raw.get("total"))
        if total is not None:
            result[key + "_attempts"] = total
            if key == "accurate_passes":
                result["total_passes"] = total
    return result


def normalize_fotmob(payload, fixture, competition):
    general, header, content = payload.get("general", {}), payload.get("header", {}), payload.get("content", {})
    teams = header.get("teams") or []
    if len(teams) != 2 or general.get("finished") is not True:
        raise ValueError("Uncompleted or unverified FotMob match")
    native = {"home": teams[0], "away": teams[1], "status": {**header.get("status", {}),
              "utcTime": general.get("matchTimeUTCDate")}}
    if int(general.get("parentLeagueId") or general.get("leagueId") or 0) != FOTMOB_LEAGUES[competition]:
        raise ValueError("FotMob competition does not match the selected league")
    if not fixture_matches(native, fixture):
        raise ValueError("FotMob date, teams, result or completion does not corroborate the ESPN fixture")
    team_map = {str(team["id"]): str(fixture[f"{side}_team_id"])
                for side, team in zip(("home", "away"), teams, strict=True)}
    shots = (content.get("shotmap") or {}).get("shots")
    shot_rows = []
    for shot in shots if isinstance(shots, list) else []:
        if str(shot.get("teamId")) not in team_map:
            continue
        # Preserve original units and source fields. These are not tracked trajectories.
        shot_rows.append({**shot, "espn_team_id": team_map[str(shot["teamId"])]})
    lineup = content.get("lineup") or {}
    player_rows = []
    for player in (content.get("playerStats") or {}).values():
        if str(player.get("teamId")) not in team_map:
            continue
        pairs = [(stat.get("key"), stat.get("stat")) for group in player.get("stats") or []
                 for stat in (group.get("stats") or {}).values() if stat.get("key")]
        player_rows.append({"provider_player_id": str(player.get("id")), "name": player.get("name"),
            "team_id": team_map[str(player["teamId"])], "position": player.get("positionId"),
            "shirt_number": player.get("shirtNumber"), "goalkeeper": player.get("isGoalkeeper"),
            "stat_definitions_json": json.dumps({ALIASES.get(stat_key(key), stat_key(key)): {"source_key": key,
                "source_type": value.get("type")} for key, value in pairs if isinstance(value, dict)}), **counters(pairs)})
    groups = (((content.get("stats") or {}).get("Periods") or {}).get("All") or {}).get("stats") or []
    result = []
    for index, side in enumerate(("home", "away")):
        pairs = [(stat.get("key"), (stat.get("rawStats") or [None, None])[index])
                 for group in groups for stat in group.get("stats") or [] if len(stat.get("rawStats") or []) == 2]
        team = str(fixture[f"{side}_team_id"])
        row = {"game_id": str(fixture["event_id"]), "team_id": team,
            "team_name": teams[index].get("name"),
            "provider": "fotmob", "provider_game_id": str(general.get("matchId")), "provider_team_id": str(teams[index]["id"]),
            "source_model": "FotMob reported; upstream model version undisclosed", "definition_version": VERSION,
            "source_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "date": str(fixture["date"])[:10], **counters(pairs)}
        row["shots_json"] = json.dumps([s for s in shot_rows if s["espn_team_id"] == team])
        row["players_json"] = json.dumps([p for p in player_rows if p["team_id"] == team])
        row["context_json"] = json.dumps({"formation": (lineup.get(side + "Team") or {}).get("formation"),
            "lineup": lineup.get(side + "Team"), "momentum": content.get("momentum"),
            "weather": content.get("weather"), "coverage_level": general.get("coverageLevel"),
            "coordinate_system": "FotMob provider pitch coordinates; not tracking",
            "shots_recorded": isinstance(shots, list), "player_identity": "FotMob IDs; not mapped to ESPN athletes"})
        row["extensions_json"] = json.dumps({"stats": groups, "match_info": (content.get("matchFacts") or {}).get("infoBox")})
        result.append(row)
    return result


class SoccerEnrichment:
    def __init__(self, connector):
        self.connector = connector

    def fetch(self, competition, season, function, parameters, refresh=False):
        allowed = {"fotmob_matches", "fotmob_match_details", "asa_games_xgoals", "asa_teams", "statsbomb_open"}
        if function not in allowed:
            raise ValueError("Unsupported soccer enrichment request")
        identity = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()
        key = f"{competition}/{season}/providers/{VERSION}/{function}-{identity}.json"
        source = self.connector.source_cache
        path = self.connector.data_dir / key
        ttl = 3600 if refresh or season >= date.today().year else 365 * 86400
        with source.lease(key, seconds=180) if source else nullcontext():
            cached = source._cached(key, ttl) if source else None
            if cached is not None:
                return cached
            if not source and path.exists() and time.time() - path.stat().st_mtime < ttl:
                return json.loads(path.read_text(encoding="utf-8"))
            if function == "statsbomb_open":
                resource = parameters.get("resource", "")
                if not re.fullmatch(r"competitions\.json|matches/\d+/\d+\.json|(?:events|lineups)/\d+\.json", resource):
                    raise ValueError("Unsupported open-event resource")
                url = f"https://raw.githubusercontent.com/statsbomb/open-data/master/data/{resource}"
                if ACTIVE_BUDGET.get() is not None:
                    raw = budget_json(url)
                else:
                    transport = load_optional_module("sportsdataverse.dl_utils", "Soccer open event data")
                    response = transport.download(url=url, timeout=25, num_retries=1)
                    raw = response.json() if response is not None else None
            elif ACTIVE_BUDGET.get() is not None:
                if function.startswith("fotmob"):
                    endpoint = "matches" if function == "fotmob_matches" else "matchDetails"
                    query = {"matchId" if k == "match_id" else k: v for k, v in parameters.items()}
                    url = f"https://www.fotmob.com/api/data/{endpoint}?{urlencode(query)}"
                else:
                    endpoint = "games/xgoals" if function == "asa_games_xgoals" else "teams"
                    league = ASA_LEAGUES[competition]
                    query = {k: v for k, v in parameters.items() if k != "league_slug"}
                    url = f"https://app.americansocceranalysis.com/api/v1/{league}/{endpoint}?{urlencode(query)}"
                raw = budget_json(url)
            else:
                soccer = load_optional_module("sportsdataverse.soccer", "Soccer advanced match analytics")
                raw = getattr(soccer, function)(**parameters, return_parsed=False, timeout=25, num_retries=1)
            if not isinstance(raw, (dict, list)) or not raw:
                raise ValueError("No usable provider response; no empty success will be cached")
            if source:
                source.store(key, raw)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(raw), encoding="utf-8")
            return raw

    def match(self, competition, season, fixture, refresh=False):
        day = str(fixture["date"])[:10].replace("-", "")
        raw = self.fetch(competition, season, "fotmob_matches", {"date": day, "timezone": "UTC"}, refresh)
        matches = [m for league in raw.get("leagues", []) if league.get("id") == FOTMOB_LEAGUES[competition]
                   for m in league.get("matches", []) if fixture_matches(m, fixture)]
        if len(matches) != 1:
            raise ValueError("No unique, corroborated FotMob fixture mapping")
        detail = self.fetch(competition, season, "fotmob_match_details", {"match_id": str(matches[0]["id"])}, refresh)
        if str(detail.get("general", {}).get("matchId")) != str(matches[0]["id"]):
            raise ValueError("FotMob match ID mismatch")
        return normalize_fotmob(detail, fixture, competition)

    def team_matches(self, competition, season, fixtures, refresh=False, progress=None):
        rows, failures, unmapped = [], 0, 0
        with ContextPool(max_workers=self.connector.settings.dataset_sync_concurrency) as pool:
            futures = {pool.submit(self.match, competition, season, row, refresh): row for row in fixtures.iter_rows(named=True)}
            for index, future in enumerate(as_completed(futures), 1):
                try:
                    rows.extend(future.result())
                except (ResearchLimit, OptionalDependencyError):
                    raise
                except ValueError:
                    unmapped += 1
                except Exception:
                    failures += 1
                if progress:
                    progress(index, len(futures))
        frame = pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame()
        return frame, {"expected_matches": fixtures.height, "recorded_matches": len(rows) // 2,
                       "failed_requests": failures, "unmapped_matches": unmapped}

    def asa_matches(self, competition, season, fixtures, refresh=False, progress=None):
        if competition not in ASA_LEAGUES:
            raise ValueError("ASA adapter supports MLS and NWSL only")
        parameters = {"league_slug": ASA_LEAGUES[competition]}
        try:
            teams = self.fetch(competition, season, "asa_teams", parameters, refresh)
            games = self.fetch(competition, season, "asa_games_xgoals", {**parameters, "season_name": str(season)}, refresh)
        except (ResearchLimit, OptionalDependencyError):
            raise
        except Exception:
            return pl.DataFrame(), {"expected_matches": fixtures.height, "recorded_matches": 0,
                                    "failed_requests": 1, "unmapped_matches": 0}
        if not isinstance(teams, list) or not isinstance(games, list):
            raise ValueError("ASA response schema is not a recorded row list")
        names = {str(t.get("team_id")): t.get("team_name") for t in teams}
        rows, unmapped = [], 0
        for index, fixture in enumerate(fixtures.iter_rows(named=True), 1):
            candidates = []
            for game in games:
                native = {side: {"name": names.get(str(game.get(f"{side}_team_id"))),
                                 "score": game.get(f"{side}_goals")} for side in ("home", "away")}
                native["status"] = {"utcTime": game.get("date_time_utc"), "finished": True}
                if str(game.get("date_time_utc", "")).startswith(str(season)) and fixture_matches(native, fixture):
                    candidates.append(game)
            if len(candidates) != 1:
                unmapped += 1
                continue
            game = candidates[0]
            for side in ("home", "away"):
                rows.append({"game_id": str(fixture["event_id"]), "team_id": str(fixture[f"{side}_team_id"]),
                    "provider": "asa", "provider_game_id": str(game.get("game_id")),
                    "provider_team_id": str(game.get(f"{side}_team_id")),
                    "source_model": "ASA team/player shot models; upstream version undisclosed", "definition_version": VERSION,
                    "asa_team_xgoals": number(game.get(f"{side}_team_xgoals")),
                    "asa_player_xgoals": number(game.get(f"{side}_player_xgoals")),
                    "asa_expected_points": number(game.get(f"{side}_xpoints")),
                    "extensions_json": json.dumps(game, sort_keys=True)})
            if progress:
                progress(index, fixtures.height)
        return (pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame()), {
            "expected_matches": fixtures.height, "recorded_matches": len(rows) // 2,
            "failed_requests": 0, "unmapped_matches": unmapped}
