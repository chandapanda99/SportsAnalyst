"""Team-sized FBS/FCS snapshots; never calls a national bulk loader."""

from __future__ import annotations

import importlib.metadata
import hashlib
import json
import logging
import math
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import polars as pl

from sports_analyst.config import Settings
from sports_analyst.datasets.acquisition import bounded_results, timed_stage
from sports_analyst.datasets.cfb_source import CORE, SITE, WEB, CFBSource, query_url
from sports_analyst.datasets.nfl import sha256_file
from sports_analyst.datasets.optional import OptionalDependencyError
from sports_analyst.models import DatasetManifest, PlayerOption, stable_id

logger = logging.getLogger(__name__)


class CFBCoverageUnavailable(ValueError):
    def __init__(self, message, status="source_unavailable", rows=None):
        super().__init__(message)
        self.status = status
        self.rows = rows or []


CFB_BASE_DATASETS = ["schedules", "team_stats", "player_stats", "rosters", "scoring_events"]
CFB_DATASETS = [*CFB_BASE_DATASETS, "recorded_plays", "enriched_plays"]
TEAM_FIELDS = {
    "totalYards": "total_yards",
    "netPassingYards": "passing_yards",
    "rushingYards": "rushing_yards",
    "rushingAttempts": "rushing_attempts",
    "turnovers": "turnovers",
    "firstDowns": "first_downs",
}
PLAYER_FIELDS = {
    "passing": {"YDS": "passing_yards", "TD": "passing_touchdowns", "INT": "passing_interceptions"},
    "rushing": {"CAR": "rushing_attempts", "YDS": "rushing_yards", "TD": "rushing_touchdowns"},
    "receiving": {"REC": "receptions", "YDS": "receiving_yards", "TD": "receiving_touchdowns"},
}


def number(value):
    try:
        result = float(str(value).replace(",", "")) if value is not None and str(value) not in {"", "--", "-"} else None
        return result if result is not None and math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def pair(value):
    parts = str(value or "").replace("-", "/").split("/")
    return (number(parts[0]), number(parts[1])) if len(parts) == 2 else (None, None)


def frame(rows):
    return pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame({"game_id": pl.Series([], dtype=pl.String)})


def season_ttl(season):
    return 300 if season >= datetime.now(UTC).year else 365 * 86400


class SportsDataverseCFBConnector:
    sport_id = "cfb"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.data_dir = settings.data_dir / "raw" / "cfb"
        self.source = CFBSource(self.data_dir, concurrency=settings.dataset_sync_concurrency)

    @staticmethod
    def validate_id(value):
        if not str(value).isdigit() or len(str(value)) > 16:
            raise ValueError("College-football identifiers must be numeric ESPN IDs")
        return str(value)

    def catalog(self, season: int | None = None, subdivision: str | None = None, conference_id: str | None = None):
        hits, requests = self.source.cache_hits, self.source.requests
        if season is None:
            years = sorted(
                {
                    int(item["$ref"].split("/seasons/")[1].split("?")[0].strip("/"))
                    for item in self.source.collection(f"{CORE}/seasons", maximum=400)
                    if "/seasons/" in item.get("$ref", "")
                },
                reverse=True,
            )
            return {
                "seasons": [year for year in years if 1999 <= year <= datetime.now(UTC).year],
                "conferences": [],
                "teams": [],
                "cached": self.source.requests == requests,
            }
        if not 1999 <= season <= datetime.now(UTC).year:
            raise ValueError("Select a supported college-football season")
        ttl = season_ttl(season)
        groups = self.source.references(f"{CORE}/seasons/{season}/types/2/groups", ttl, 50)
        visited = set()
        subdivisions = {}

        def walk(group, depth=0):
            identity = str(group.get("id", ""))
            if identity in visited:
                return
            visited.add(identity)
            if depth > 4 or len(visited) > 60:
                raise ValueError("Conference discovery exceeds its supported bound")
            name = str(group.get("name", "")).lower()
            kind = (
                "fbs"
                if "bowl subdivision" in name or name.startswith("fbs") or name == "division i-a"
                else "fcs"
                if "championship subdivision" in name or name.startswith("fcs") or name == "division i-aa"
                else None
            )
            if kind:
                subdivisions[kind] = group
                return
            # Do not expand Division II/III into thousands of unrelated teams.
            if "division i" in name and "ii" not in name and (group.get("children") or {}).get("$ref"):
                for child in self.source.references(group["children"]["$ref"], ttl, 60):
                    walk(child, depth + 1)

        for group in groups:
            walk(group)
        if not subdivisions:
            raise ValueError("No verified FBS/FCS subdivisions are recorded for this season")
        if subdivision is None:
            return {
                "season": season,
                "subdivisions": [{"value": key, "label": key.upper()} for key in sorted(subdivisions)],
                "conferences": [],
                "teams": [],
                "cached": self.source.requests == requests,
            }
        if subdivision not in subdivisions:
            raise ValueError("Select a recorded FBS/FCS subdivision")
        parent = subdivisions[subdivision]
        conferences = self.source.references(parent["children"]["$ref"], ttl, 40)
        options = [
            {"value": str(group["id"]), "label": group.get("name") or group.get("shortName") or str(group["id"])} for group in conferences
        ]
        teams = []
        if conference_id:
            selected = next((group for group in conferences if str(group.get("id")) == conference_id), None)
            if selected is None:
                raise ValueError("The conference does not belong to the selected subdivision/season")
            references = self.source.references(selected["teams"]["$ref"], ttl, 60)
            teams = [{"value": str(team["id"]), "label": team.get("displayName") or str(team["id"])} for team in references]
        return {
            "season": season,
            "subdivision": subdivision,
            "conferences": sorted(options, key=lambda row: row["label"]),
            "teams": sorted(teams, key=lambda row: row["label"]),
            "cached": self.source.requests == requests and self.source.cache_hits > hits,
        }

    def roster(self, team_id, season, games=None, progress=None):
        team_id = self.validate_id(team_id)
        if not 1999 <= season <= datetime.now(UTC).year:
            raise ValueError("Select a supported college-football season")
        normalized_key = f"rosters/v2/{team_id}/{season}.json"
        cached = self.source._cached(normalized_key, season_ttl(season))
        if cached:
            return cached["rows"]
        errors = []
        # Historical empty responses must not be frozen for a year.
        try:
            raw = self.source.get(query_url(f"{SITE}/teams/{team_id}/roster", season=season), min(3600, season_ttl(season)))
        except OptionalDependencyError:
            raise
        except Exception as error:
            errors.append(error)
            raw = {}
        rows = []
        verified = ((raw.get("season") or {}).get("year") == season
                    and str((raw.get("team") or {}).get("id", team_id)) == team_id)
        for group in (raw.get("athletes") or []) if verified else []:
            for athlete in group.get("items") or []:
                rows.append(
                    {
                        "athlete_id": self.validate_id(athlete["id"]),
                        "name": athlete.get("displayName"),
                        "position": (athlete.get("position") or {}).get("abbreviation"),
                        "team_id": team_id,
                        "season": season,
                    }
                )
        if rows:
            self.source.store(normalized_key, {"rows": rows})
            return rows
        ttl = min(3600, season_ttl(season))
        try:
            entries = self.source.collection(f"{CORE}/seasons/{season}/teams/{team_id}/athletes", ttl, maximum=300)
            rows, failed = self._roster_references(entries, team_id, season, progress)
            if rows:
                if failed:
                    raise CFBCoverageUnavailable(
                        f"{len(rows)} roster athletes resolved; {failed} references require retry.", "partial", rows)
                self.source.store(normalized_key, {"rows": rows})
                return rows
            if failed:
                errors.append(ValueError("Historical athlete references could not be resolved"))
        except (OptionalDependencyError, CFBCoverageUnavailable):
            raise
        except Exception as error:
            errors.append(error)
            logger.warning("cfb_season_roster_unavailable team_id=%s season=%s error_type=%s", team_id, season, type(error).__name__)
        # Game rosters are an explicitly incomplete substitute, never a current roster relabeled as historical.
        games = games if games is not None else self.schedule(team_id, season)
        for game, context in list(games.items())[:30]:
            if not context.get("completed"):
                continue
            try:
                self.summary(game, season)  # Verify the game's season before following its roster.
                roster = self.source.get(f"{CORE}/events/{game}/competitions/{game}/competitors/{team_id}/roster", ttl)
                roster_team = roster.get("team") or {}
                team_ref = urlparse(roster_team.get("$ref", "")).path
                if roster_team.get("id") and str(roster_team["id"]) != team_id:
                    raise ValueError("Game roster belongs to a different school")
                if team_ref and not team_ref.endswith(f"/teams/{team_id}"):
                    raise ValueError("Game roster school reference could not be verified")
                entries = [entry["athlete"] for entry in roster.get("entries") or []
                           if entry.get("valid") is not False and entry.get("athlete")]
                found, _ = self._roster_references(entries, team_id, season, progress)
                rows.extend(found)
            except OptionalDependencyError:
                raise
            except Exception as error:
                errors.append(error)
        if rows:
            unique = {row["athlete_id"]: row for row in rows}
            raise CFBCoverageUnavailable(
                "Players resolved from recorded game rosters; this is not a verified complete season roster.",
                "source_unavailable", list(unique.values()))
        if errors:
            raise CFBCoverageUnavailable("Historical roster retrieval failed; retry the selected school/season.", "download_failed")
        raise CFBCoverageUnavailable(
            "No recorded roster is available for this school/season" if verified else "Historical roster season could not be verified",
            "source_unavailable" if verified else "season_unverified")

    def _roster_references(self, entries, team_id, season, progress):
        if len(entries) > 300:
            raise ValueError("Selected-school roster exceeds its supported bound")
        refs = {}
        for entry in entries:
            ref = entry.get("$ref", "")
            parts = urlparse(ref).path.split("/")
            prefix = urlparse(CORE).path + f"/seasons/{season}/athletes/"
            if not urlparse(ref).path.startswith(prefix) or not parts[-1].isdigit():
                continue  # Never resolve a current-year or cross-season athlete reference.
            refs[parts[-1]] = ref

        def resolve(item):
            identity, ref = item
            athlete = self.source.get(ref, season_ttl(season))
            if str(athlete.get("id")) != identity or not athlete.get("displayName"):
                raise ValueError("Historical athlete identity could not be verified")
            position = athlete.get("position") or {}
            if "$ref" in position:
                position = self.source.get(position["$ref"], 365 * 86400)
            return {"athlete_id": identity, "name": athlete["displayName"], "position": position.get("abbreviation"),
                    "team_id": team_id, "season": season, "source_url": ref}

        rows, failed = [], len(entries) - len(refs)
        with timed_stage("roster_identities", sport="cfb", team=team_id, season=season):
            for _, future in bounded_results(resolve, refs.items(), self.settings.dataset_sync_concurrency):
                try:
                    rows.append(future.result())
                except OptionalDependencyError:
                    raise
                except Exception:
                    failed += 1
                if progress:
                    progress("downloading", "rosters", season, 0, 1, (len(rows) + failed) / max(1, len(entries)),
                             f"Resolving roster athletes · {len(rows)} recorded · {failed} unavailable", True)
        return rows, failed

    def player_seasons(self, athlete_id):
        athlete_id = self.validate_id(athlete_id)
        raw = self.source.get(f"{CORE}/athletes/{athlete_id}/statisticslog", ttl=3600)
        refs = [entry.get("season") or {} for entry in raw.get("entries") or []]
        years = set()
        for item in refs:
            ref = item.get("$ref", "")
            if "/seasons/" in ref:
                candidate = ref.split("/seasons/")[1].split("/")[0].split("?")[0]
                if candidate.isdigit() and 1999 <= int(candidate) <= datetime.now(UTC).year:
                    years.add(int(candidate))
        if not years:
            raise ValueError("This player's recorded season history could not be verified")
        return sorted(years)

    def players(self, team_id, season, query=""):
        discovery_source = None
        try:
            roster = self.roster(team_id, season)
        except CFBCoverageUnavailable as error:
            if not error.rows:
                raise
            roster, discovery_source = error.rows, "partial_recorded_roster"
        rows = [row for row in roster if query.casefold() in str(row.get("name", "")).casefold()]
        return [
            PlayerOption(
                player_id=row["athlete_id"],
                name=row["name"],
                teams=[str(team_id)],
                positions=[row["position"]] if row["position"] else [],
                seasons=[season],
                discovery_source=discovery_source,
            )
            for row in sorted(rows, key=lambda row: row["name"] or "")[:25]
        ]

    def player_games(self, athlete_id, season):
        """Follow verified player game IDs, not a national roster or name match."""
        athlete_id = self.validate_id(athlete_id)
        raw = self.source.get(query_url(f"{WEB}/athletes/{athlete_id}/gamelog", season=season), season_ttl(season))
        games = {}
        for group in raw.get("seasonTypes") or []:
            for category in group.get("categories") or []:
                for event in category.get("events") or []:
                    identity = event.get("eventId") or event.get("id")
                    if identity and str(identity).isdigit():
                        games[str(identity)] = (raw.get("events") or {}).get(str(identity), {})
        # Some ESPN game logs provide the keyed event directory without categories.
        if not games:
            games = {str(key): value for key, value in (raw.get("events") or {}).items() if str(key).isdigit()}
        if len(games) > 30:
            raise ValueError("Player game-log history exceeds the supported season bound")
        if not games:
            raise ValueError("No verified player games are available; transfer history cannot be inferred")
        return games

    @staticmethod
    def schedule_rows(raw, team_id, season):
        rows = []
        for event in raw.get("events") or []:
            if (event.get("season") or {}).get("year") != season:
                continue
            competition = (event.get("competitions") or [{}])[0]
            competitors = competition.get("competitors") or []
            if str(team_id) not in {str((entry.get("team") or {}).get("id")) for entry in competitors}:
                continue
            sides = {entry.get("homeAway"): entry for entry in competitors}
            if not {"home", "away"} <= sides.keys():
                continue
            row = {
                "game_id": str(event["id"]),
                "date": event.get("date"),
                "season": season,
                "week": (event.get("week") or {}).get("number"),
                "season_type": "POST" if (event.get("seasonType") or {}).get("type") == 3 else "REG",
                "completed": bool(((competition.get("status") or event.get("status") or {}).get("type") or {}).get("completed")),
            }
            for side in ("home", "away"):
                entry = sides[side]
                row[f"{side}_team_id"] = str(entry["team"]["id"])
                row[f"{side}_team_name"] = entry["team"].get("displayName")
                score = entry.get("score")
                row[f"{side}_score"] = number(score.get("value", score.get("displayValue")) if isinstance(score, dict) else score)
            rows.append(row)
        return rows

    def schedule(self, team_id, season):
        rows = {}
        for season_type in (2, 3):
            raw = self.source.get(query_url(f"{SITE}/teams/{team_id}/schedule", season=season, seasontype=season_type), season_ttl(season))
            requested = raw.get("requestedSeason") or {}
            if requested.get("year", season) != season:
                raise ValueError("The source returned a different requested season")
            for row in self.schedule_rows(raw, team_id, season):
                rows[row["game_id"]] = row
        if not rows:
            raise ValueError("No verified games are recorded for this team/season")
        return rows

    def summary(self, game_id, season):
        raw = self.source.get(
            query_url(f"{SITE}/summary", event=game_id),
            3600 if season >= datetime.now(UTC).year else 365 * 86400,
            f"games/{season}/{game_id}/summary.json",
        )
        header = raw.get("header") or {}
        if str(header.get("id")) != str(game_id) or (header.get("season") or {}).get("year") != season:
            raise ValueError("Game summary identity or season could not be verified")
        return raw

    def game_roster(self, game_id, season):
        from sports_analyst.datasets.cfb_identity import game_directory

        game_id = self.validate_id(game_id)
        _, roster = game_directory(self.source, game_id, season, self.summary(game_id, season), [], season_ttl(season))
        return roster

    def game_plays(self, game_id, season):
        """Share successful normalized games across teams; retry coverage gaps."""
        from sports_analyst.datasets.cfb_identity import IDENTITY_VERSION

        game_id = self.validate_id(game_id)
        try:
            provider = importlib.metadata.version("sportsdataverse")
        except importlib.metadata.PackageNotFoundError:
            provider = "unknown"
        raw = self.summary(game_id, season)
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        key = f"normalized-plays/v1/{IDENTITY_VERSION}/{provider}/{season}/{game_id}/{digest}.json"
        ttl = 3600 if season >= datetime.now(UTC).year else 365 * 86400
        cached = self.source._cached(key, ttl)
        if cached is not None:
            return cached
        with self.source.lease(f"normalized-plays:{season}:{game_id}", seconds=1800):
            cached = self.source._cached(key, ttl)
            if cached is not None:
                return cached
            with timed_stage("normalize_game", sport="cfb", game=game_id, season=season):
                result = self._game_plays(game_id, season, raw)
            # Optional request failures must not become persistent empty identities
            # or prevent a later attempt from obtaining provider-derived context.
            complete = all(actor.get("name") and actor.get("position") and actor.get("team_id")
                           for row in result["plays"] for actor in row.get("participants", []))
            roster_teams = {entry["team_id"] for entry in result["game_roster"]}
            teams = {str(entry["id"]) for entry in result["teams"]}
            if (provider != "unknown" and complete and teams and teams <= roster_teams
                    and "could not load" not in result["message"]):
                self.source.store(key, result)
            return result

    def _game_plays(self, game_id, season, raw):
        from sports_analyst.datasets.cfb_plays import recorded_play
        from sports_analyst.datasets.cfb_identity import game_directory

        game_id = self.validate_id(game_id)
        ttl = 3600 if season >= datetime.now(UTC).year else 365 * 86400
        source = self.source.collection(f"{CORE}/events/{game_id}/competitions/{game_id}/plays", ttl, maximum=800)
        directory, game_roster = game_directory(self.source, game_id, season, raw, source, ttl)
        rows = [recorded_play(play, raw, directory) for play in source]
        if not rows:
            raise ValueError("No recorded detailed plays are available; this is not proof of an empty game")
        if len({row["id"] for row in rows if row["id"]}) != len(rows):
            raise ValueError("Recorded play IDs are missing or duplicated")
        # The lightweight provider pipeline derives catch spots and direction, without
        # loading EP/WP models, resolving names remotely, or downloading a national season.
        context_message = ""
        if raw.get("drives"):
            from sports_analyst.datasets.cfb_enrichment import process_summary
            from sports_analyst.datasets.cfb_rendering import hydrate_rows

            version = importlib.metadata.version("sportsdataverse")
            digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
            key = f"render-context/v2/{season}/{game_id}/{version}-{digest}.json"
            try:
                with self.source.lease(f"render-context:{season}:{game_id}", seconds=180):
                    processed = self.source._cached(key, ttl)
                    if processed is None:
                        processed = process_summary(game_id, raw, context_only=True)
                        self.source.store(key, processed)
                rows = hydrate_rows(rows, processed, version)
                context_message = " Available air yards/YAC and directions are provider-derived from play text, not tracking."
            except Exception:
                logger.exception("cfb_render_context_unavailable game_id=%s season=%s", game_id, season)
                context_message = " Additional provider-derived play context could not load; recorded plays remain available."
        return {
            "plays": rows,
            "teams": list(directory[0].values()),
            "game_roster": game_roster,
            "coverage": f"{len(rows)} recorded source plays; participant actors are not a full on-field lineup",
            "message": "Actor locations are illustrative. Narrative formation labels appear only where recorded; "
                       "full lineups, tracking and assignments are not verified." + context_message,
        }

    def prepare_recorded(self, season, partition, schedule, callback=None, progress=None):
        rows, completed = [], 0
        # Future fixtures are not failed downloads and cannot supply play evidence.
        games = schedule.filter(pl.col("completed") == True)["game_id"].unique().sort().to_list()  # noqa: E712
        scheduled = schedule["game_id"].n_unique()
        skipped = scheduled - len(games)
        with self.source.lease(f"recorded:{partition}:{season}", seconds=1800):
            for index, (game, future) in enumerate(bounded_results(
                    lambda game: self.game_plays(game, season), games, self.settings.dataset_sync_concurrency)):
                if progress:
                    progress("downloading", "recorded_plays", season, index, len(games),
                             index / max(1, len(games)),
                             f"Recorded play evidence · completed game {index + 1}/{len(games)} · {skipped} not completed skipped", True)
                try:
                    detail = future.result()
                    if not detail["plays"]:
                        raise ValueError("No recorded plays supplied for this completed game")
                    rows.extend({**row, "play_id": row["id"], "game_id": game, "season": season,
                                 "teams_json": json.dumps(detail["teams"])} for row in detail["plays"])
                    completed += 1
                except OptionalDependencyError:
                    raise
                except Exception:
                    logger.exception("cfb_recorded_plays_unavailable game_id=%s season=%s", game, season)
            if progress:
                detail = (f"Recorded play evidence · {completed}/{len(games)} completed games available · "
                          f"{len(games) - completed} missing · {skipped} not completed skipped" if games else
                          f"No completed games · {skipped} scheduled fixtures skipped; play data are not expected yet")
                progress("downloading", "recorded_plays", season, len(games), len(games), 1,
                         detail, True)
            return self.snapshot(
                season, partition, {"recorded_plays": rows}, len(games), completed, callback,
                extra_coverage={"scheduled_matches": scheduled, "skipped_uncompleted_matches": skipped,
                                "missing_completed_matches": len(games) - completed},
            )[0]

    def play_personnel(self, game, season, play):
        game, play = self.validate_id(str(game)), str(play)
        if not play.isascii() or not play.isdigit() or len(play) > 20:
            raise ValueError("Selected play must have a valid numeric ESPN play ID")
        key = f"personnel/v1/{season}/{game}/{play}.json"
        cached = self.source._cached(key, 3600)
        if cached is not None:
            return cached
        url = f"{CORE}/events/{game}/competitions/{game}/plays/{play}/personnel"
        try:
            self.summary(game, season)
            entries = self.source.collection(url, season_ttl(season), maximum=100)
            result = {"status": "recorded" if entries else "not_recorded", "source_url": url,
                      "entries": entries, "scope": "Recorded personnel entries; completeness and alignment are not established"}
            self.source.store(key, result)
            return result
        except OptionalDependencyError:
            raise
        except Exception as error:
            missing = getattr(getattr(error, "response", None), "status_code", None) == 404
            result = {"status": "not_recorded" if missing else "unavailable", "source_url": url,
                      "entries": [], "scope": "No verified personnel data for this selected play; not evidence of an empty lineup"}
            if missing:
                self.source.store(key, result)
            return result

    def prepare_enriched(self, season, partition, schedule, manifest_callback=None, progress=None):
        """Enrich selected completed games only; ordinary box-score startup stays cheap."""
        games = schedule.filter(pl.col("completed") == True)["game_id"].unique().to_list()  # noqa: E712
        if not games:
            return self.snapshot(
                season, partition, {"enriched_plays": []}, 0, 0, manifest_callback,
                extra_coverage={"scheduled_matches": schedule["game_id"].n_unique(),
                                "skipped_uncompleted_matches": schedule["game_id"].n_unique(),
                                "missing_completed_matches": 0, "complete_play_games": 0},
            )[0]
        if len(games) > 30:
            raise ValueError("Select a bounded completed-game sample for play enrichment")
        from sports_analyst.datasets.cfb_enrichment import CFBEnrichment

        rows, successful, complete = [], 0, 0
        ttl = 3600 if season >= datetime.now(UTC).year else 365 * 86400
        with self.source.lease(f"enrich-partition:{partition}:{season}", seconds=1800):
            enrichment = CFBEnrichment(self.source)
            for index, game in enumerate(games):
                if progress:
                    progress(game, index, len(games))
                try:
                    with timed_stage("model_game", sport="cfb", season=season, game=game):
                        result = enrichment.game(game, season, self.summary(game, season), ttl)
                    rows.extend(result["rows"])
                    successful += 1
                    complete += result["provenance"]["source_plays"] == result["provenance"]["processed_plays"]
                except OptionalDependencyError:
                    raise
                except Exception:
                    logger.exception("cfb_enrichment_unavailable game_id=%s season=%s", game, season)
            if not rows:
                raise ValueError("No usable advanced play values could be prepared; ordinary box-score analysis remains available")
            manifests = self.snapshot(season, partition, {"enriched_plays": rows}, len(games), successful, None)
            manifest = manifests[0].model_copy(update={"coverage": {**manifests[0].coverage, "complete_play_games": complete}})
            if manifest_callback:
                manifest_callback(manifest)
            return manifest

    @staticmethod
    def statistics(raw, game_id, season):
        teams, players, scoring = [], [], []
        for entry in (raw.get("boxscore") or {}).get("teams") or []:
            row = {"game_id": game_id, "team_id": str(entry["team"]["id"]), "season": season}
            for stat in entry.get("statistics") or []:
                name, value = stat.get("name"), stat.get("displayValue", stat.get("value"))
                if name in TEAM_FIELDS:
                    row[TEAM_FIELDS[name]] = number(value)
                if name == "completionAttempts":
                    row["passing_completions"], row["passing_attempts"] = pair(value)
                if name in {"thirdDownEff", "fourthDownEff"}:
                    prefix = "third_down" if name == "thirdDownEff" else "fourth_down"
                    row[f"{prefix}_conversions"], row[f"{prefix}_attempts"] = pair(value)
            if any(value is not None for key, value in row.items() if key not in {"game_id", "team_id", "season"}):
                teams.append(row)
        directory = {}
        for entry in (raw.get("boxscore") or {}).get("players") or []:
            team_id = str(entry["team"]["id"])
            for category in entry.get("statistics") or []:
                name = category.get("name")
                if name not in PLAYER_FIELDS:
                    continue
                for item in category.get("athletes") or []:
                    athlete = item.get("athlete") or {}
                    identity = str(athlete.get("id") or "")
                    if not identity.isdigit():
                        continue
                    key = (team_id, identity)
                    row = directory.setdefault(
                        key,
                        {"game_id": game_id, "team_id": team_id, "athlete_id": identity, "name": athlete.get("displayName"), "season": season},
                    )
                    values = dict(zip(category.get("labels") or [], item.get("stats") or [], strict=False))
                    for label, field in PLAYER_FIELDS[name].items():
                        if label in values:
                            row[field] = number(values[label])
                    if name == "passing" and "C/ATT" in values:
                        row["passing_completions"], row["passing_attempts"] = pair(values["C/ATT"])
        players.extend(row for row in directory.values() if any(
            value is not None for key, value in row.items()
            if key not in {"game_id", "team_id", "athlete_id", "name", "season"}
        ))
        for event in raw.get("scoringPlays") or []:
            scoring.append(
                {
                    "game_id": game_id,
                    "season": season,
                    "text": event.get("text"),
                    "quarter": (event.get("period") or {}).get("number"),
                    "clock": (event.get("clock") or {}).get("displayValue"),
                    "team_id": str((event.get("team") or {}).get("id") or ""),
                }
            )
        return teams, players, scoring

    def snapshot(self, season, partition, rows, total, completed, callback, availability=None, extra_coverage=None):
        manifests = []
        for dataset, values in rows.items():
            status, message = (availability or {}).get(dataset, ("available", None))
            if dataset in {"recorded_plays", "enriched_plays"} and total == 0:
                status, message = "available", "No completed games in this selection; play data are not expected yet."
            elif dataset == "recorded_plays" and completed < total:
                status, message = "partial", f"Recorded plays are missing for {total - completed} of {total} completed games; retry to resume."
            elif status == "available" and not values:
                status, message = "source_unavailable", "The fetched game summaries contain no recorded rows for this package."
            elif status == "available" and dataset != "rosters" and completed < total:
                status, message = "partial", "Some game summaries could not be retrieved; retry to resume."
            data = frame(values)
            # Completion order must not change checksums for identical source
            # data, otherwise parallel refreshes cause unnecessary reuploads.
            order = [field for field in ("game_id", "team_id", "athlete_id", "play_id", "quarter", "clock", "text")
                     if field in data.columns]
            if order:
                data = data.sort(order)
            data = data.select(sorted(data.columns))
            if status == "available" and dataset in {"team_stats", "player_stats"}:
                recorded = data["game_id"].n_unique()
                if recorded < completed:
                    status = "source_unavailable"
                    message = f"Recorded statistics cover {recorded} of {completed} fetched games; remaining sections were not supplied."
            path = self.data_dir / "partitions" / partition.replace(":", "/") / str(season) / f"{dataset}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            with timed_stage("write_snapshot", sport="cfb", season=season, partition=partition, dataset=dataset):
                data.write_parquet(path)
                checksum = sha256_file(path)
            manifest = DatasetManifest(
                manifest_id=stable_id(
                    "dataset", {"sport": "cfb", "season": season, "partition": partition, "dataset": dataset, "checksum": checksum}
                ),
                sport="cfb",
                partition_key=partition,
                dataset=dataset,
                season=season,
                source_url=CORE if dataset == "recorded_plays" else SITE,
                package_version=importlib.metadata.version("sportsdataverse"),
                license="See ESPN data terms.",
                attribution="ESPN data acquired through SportsDataverse.",
                sha256=checksum,
                row_count=data.height,
                columns=data.columns,
                local_path=str(path.resolve()),
                availability=status,
                availability_message=message,
                coverage={
                    "expected_matches": 1 if dataset == "rosters" else total,
                    "completed_matches": int(bool(values)) if dataset == "rosters" else completed,
                    "recorded_matches": data["game_id"].n_unique() if "game_id" in data.columns else 0,
                    "availability_checked_at": int(time.time()),
                    **(extra_coverage or {}),
                },
            )
            if callback:
                callback(manifest)
            manifests.append(manifest)
        return manifests

    def prepare(self, season, team_id=None, athlete_id=None, progress=None, manifest_callback=None, datasets=None):
        if not 1999 <= season <= datetime.now(UTC).year:
            raise ValueError("Select a supported college-football season")
        identity = self.validate_id(athlete_id if athlete_id else team_id)
        partition = f"{'player' if athlete_id else 'team'}:{identity}"
        selection = sorted(datasets or CFB_BASE_DATASETS)
        marker = f"prepared/v2/{partition.replace(':', '/')}/{season}/{'-'.join(selection)}.json"
        with self.source.lease(f"prepare:{partition}:{season}", seconds=1800):
            ready = self.source._cached(marker, season_ttl(season))
            def reusable(item):
                status = item.get("availability", "available")
                if status in {"download_failed", "partial"}:
                    return False
                if item["dataset"] != "rosters" and item["coverage"]["completed_matches"] < item["coverage"]["expected_matches"]:
                    return False
                if not item["row_count"] or status in {"source_unavailable", "season_unverified"}:
                    return time.time() - item["coverage"].get("availability_checked_at", 0) < 3600
                return item["coverage"]["completed_matches"] >= item["coverage"]["expected_matches"]

            if ready and all(reusable(item) for item in ready["manifests"]):
                reused = []
                for item in ready["manifests"]:
                    path = self.data_dir / "partitions" / partition.replace(":", "/") / str(season) / f"{item['dataset']}.parquet"
                    if not path.exists() and self.source.persistence.durable:
                        self.source.persistence.download_file(f"raw/cfb/{path.relative_to(self.data_dir).as_posix()}", path)
                    if not path.exists():
                        break
                    reused.append(DatasetManifest.model_validate(item).model_copy(update={"local_path": str(path.resolve())}))
                if len(reused) == len(ready["manifests"]):
                    for manifest in reused:
                        if manifest_callback:
                            manifest_callback(manifest)
                    return reused
            result = self._prepare(season, team_id, athlete_id, progress, manifest_callback, datasets)
            self.source.store(marker, {"manifests": [item.model_dump(mode="json") for item in result]})
            return result

    def _prepare(self, season, team_id=None, athlete_id=None, progress=None, manifest_callback=None, datasets=None):
        identity = self.validate_id(athlete_id if athlete_id else team_id)
        partition = f"{'player' if athlete_id else 'team'}:{identity}"
        if progress:
            progress("downloading", "schedules", season, 0, 1, detail="Season schedule")
        schedules = {} if athlete_id else self.schedule(identity, season)
        games = self.player_games(identity, season) if athlete_id else {game: row for game, row in schedules.items() if row["completed"]}
        if not games and (athlete_id or not schedules):
            raise ValueError("No completed games are recorded for this subject/season")
        if len(games) > 30:
            raise ValueError("Selected-subject games exceed the supported season bound")
        rows = {"schedules": [], "team_stats": [], "player_stats": [], "scoring_events": [], "rosters": []}
        selected = set(datasets or CFB_BASE_DATASETS)
        availability = {}
        if not games:
            availability.update({dataset: ("source_unavailable", "No completed games in this selection; game statistics are not expected yet.")
                                 for dataset in selected if dataset not in {"schedules", "rosters"}})
        completed = 0
        # Refill immediately as each summary finishes, without retaining a season
        # of pending futures or letting a slow request stall the next batch.
        ids = list(games)
        concurrency = self.settings.dataset_sync_concurrency
        with timed_stage("game_summaries", sport="cfb", season=season, partition=partition):
            for game, future in bounded_results(lambda game: self.summary(game, season), ids, concurrency):
                try:
                    raw = future.result()
                except OptionalDependencyError:
                    raise
                except Exception:
                    logger.exception("cfb_summary_unavailable game_id=%s season=%s", game, season)
                    continue
                header = raw["header"]
                header_event = {
                    **header,
                    "id": game,
                    "date": (header.get("competitions") or [{}])[0].get("date"),
                    "seasonType": {"type": (header.get("season") or {}).get("type", 2)},
                }
                teams, players, scoring = self.statistics(raw, game, season)
                if athlete_id:
                    entries = [row for row in players if row["athlete_id"] == identity]
                    if not entries:
                        continue  # A log entry is not proof of an attributed offensive appearance.
                    subject_team = entries[0]["team_id"]
                    player_schedule = self.schedule_rows({"events": [header_event]}, subject_team, season)
                    if not player_schedule:
                        continue
                    schedules[game] = player_schedule[0]
                    players = entries
                else:
                    teams = [row for row in teams if row["team_id"] == identity]
                    players = [row for row in players if row["team_id"] == identity]
                rows["team_stats"].extend(teams)
                rows["player_stats"].extend(players)
                rows["scoring_events"].extend(scoring)
                completed += 1
                if progress:
                    progress(
                        "downloading", "team_stats", season, 0, 1,
                        completed / len(ids), f"Game summaries · {completed} of {len(ids)}", True,
                    )
            # Successful raw summaries are already cached for an interrupted attempt.
        rows["schedules"] = list(schedules.values())
        if not athlete_id and "rosters" in selected:
            try:
                rows["rosters"] = self.roster(identity, season, schedules, progress)
            except OptionalDependencyError:
                raise
            except CFBCoverageUnavailable as error:
                rows["rosters"] = error.rows
                availability["rosters"] = (error.status, str(error))
                logger.warning("cfb_roster_unavailable team_id=%s season=%s status=%s", identity, season, error.status)
            except Exception:
                availability["rosters"] = ("download_failed", "Roster download failed; retry to retrieve this package.")
                logger.exception("cfb_roster_unavailable team_id=%s season=%s", identity, season)
        if games and not completed:
            raise ValueError("No usable game summaries with attributed statistics were retrieved")
        return self.snapshot(
            season, partition, {key: value for key, value in rows.items() if key in selected},
            len(ids), completed, manifest_callback, availability
        )

    def sync(self, seasons, datasets=None, progress_callback=None, manifest_callback=None, skip=None, team_ids=None, **kwargs):
        if not team_ids or len(team_ids) > 60:
            raise ValueError("Select between one and 60 college-football teams")
        selected = list(datasets or CFB_BASE_DATASETS)
        if set(selected) - set(CFB_DATASETS):
            raise ValueError("Unsupported college-football datasets")
        manifests = []
        if len(set(seasons)) * len(set(team_ids)) > 200:
            raise ValueError("A college-football download may contain at most 200 team-season selections")
        for team in dict.fromkeys(team_ids):
            for season in sorted(set(seasons)):
                selection_index = list(dict.fromkeys(team_ids)).index(team) * len(set(seasons)) + sorted(set(seasons)).index(season)
                selections = len(set(team_ids)) * len(set(seasons))
                school = f"School {team}"
                try:
                    school = self.source.get(f"{CORE}/seasons/{season}/teams/{team}", season_ttl(season)).get("displayName") or school
                except OptionalDependencyError:
                    raise
                except Exception:
                    pass  # Display-name lookup is nonessential to scoped acquisition.
                local_fraction = 0.0

                def scoped_progress(phase, dataset, year, completed, total, fraction=None, detail=None, force=False,
                                    _school=school, _index=selection_index, _selections=selections):
                    nonlocal local_fraction
                    value = (0.65 + 0.25 * (fraction or 0)) if dataset == "rosters" else 0.65 * (fraction or 0)
                    if dataset == "enriched_plays":
                        value = 0.9 + 0.09 * (fraction or 0)
                    local_fraction = max(local_fraction, value)
                    if progress_callback:
                        progress_callback(phase, dataset, year, _index, _selections,
                                          (_index + local_fraction) / _selections,
                                          f"{_school} · school/season {_index + 1}/{_selections} · {detail or dataset}", True)

                scoped_progress("downloading", "schedules", season, 0, 1, detail="Starting selected-school preparation")
                base = [name for name in selected if name not in {"enriched_plays", "recorded_plays"}]
                if set(selected) & {"enriched_plays", "recorded_plays"} and "schedules" not in base:
                    base.append("schedules")
                prepared = self.prepare(season, team_id=team, progress=scoped_progress, manifest_callback=manifest_callback, datasets=base)
                manifests.extend(prepared)
                if "recorded_plays" in selected:
                    schedule = self.load(next(item for item in prepared if item.dataset == "schedules"))
                    manifests.append(self.prepare_recorded(season, f"team:{team}", schedule, manifest_callback, scoped_progress))
                if "enriched_plays" in selected:
                    schedule = self.load(next(item for item in prepared if item.dataset == "schedules"))

                    def advanced_progress(game, index, total, year=season, report=scoped_progress):
                        if progress_callback:
                            report(
                                "downloading",
                                "enriched_plays",
                                year,
                                0,
                                1,
                                index / total,
                                f"Modeling game {game} · {index + 1}/{total}",
                                True,
                            )

                    manifests.append(self.prepare_enriched(season, f"team:{team}", schedule, manifest_callback, advanced_progress))
                if progress_callback:
                    progress_callback("downloading", "schedules", season, selection_index + 1, selections,
                                      (selection_index + 1) / selections,
                                      f"{school} · {season} · school/season {selection_index + 1}/{selections} saved", True)
        return manifests

    @staticmethod
    def load(manifest, columns=None, predicate=None):
        lazy = pl.scan_parquet(manifest.local_path)
        if predicate is not None:
            lazy = lazy.filter(predicate)
        if columns:
            lazy = lazy.select([column for column in columns if column in manifest.columns])
        return lazy.collect()

    @staticmethod
    def clear_cache():
        pass  # Persistent, scoped source cache is cleared through LocalStore.
