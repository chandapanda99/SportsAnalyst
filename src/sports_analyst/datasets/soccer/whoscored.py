"""Optional SoccerData parsing with bounded HTTP transport and native event IDs."""
from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import logging
import re
import time
from threading import Lock
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import polars as pl

from sports_analyst.analysis.research.state import ACTIVE_BUDGET, ResearchState
from sports_analyst.datasets.cfb_source import CFBSource
from sports_analyst.datasets.optional import load_optional_module
from sports_analyst.datasets.soccer.statistics import number
from sports_analyst.datasets.soccer.club_identity import normalized_name, same_club, VERSION as CLUB_IDENTITY_VERSION
from sports_analyst.datasets.soccer.understat import LEAGUES, fixture_signature, records
from sports_analyst.models import stable_id

VERSION = "whoscored-soccerdata-1"
DATASET = "whoscored_events"
logger = logging.getLogger(__name__)
_REQUEST_LOCK = Lock()
_LAST_REQUEST = 0.0


def extract(payload: bytes, variable):
    """Decode literal JSON only; never evaluate JavaScript from a source page."""
    text = payload.decode("utf-8")
    if variable is None or text.lstrip().startswith(("{", "[")):
        return payload
    key = "matchCentreData" if variable == "require.config.params['args'].matchCentreData" else variable
    if key not in {"matchCentreData", "allRegions", "wsCalendar"}:
        raise ValueError("Unsupported WhoScored source variable")
    for match in re.finditer(r"\b" + re.escape(key) + r"[\"']?\s*[:=]\s*", text):
        try:
            value, _ = json.JSONDecoder().raw_decode(text[match.end():])
            return json.dumps(value).encode()
        except ValueError:
            continue
    raise ValueError("WhoScored returned no literal event data; access may be unavailable")


def normalize(raw, fixture, provider_game, metadata):
    sides = {str(metadata[side]["teamId"]): str(fixture[f"{side}_team_id"]) for side in ("home", "away")}
    names = metadata.get("playerIdNameDictionary") or {}
    checksum = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    rows = []
    for sequence, event in enumerate(raw):
        kind = (event.get("type") or {}).get("displayName", "Event")
        team = sides.get(str(event.get("teamId")))
        if not event.get("id") or not team:
            continue
        qualifiers = {str((q.get("type") or {}).get("value")): q.get("value") for q in event.get("qualifiers") or []}
        def point(x, y):
            x, y = number(x), number(y)
            return (x * 1.05, y * .68) if x is not None and y is not None and 0 <= x <= 100 and 0 <= y <= 100 else (None, None)
        # Non-spatial administrative events commonly carry a sentinel (0, 0).
        spatial = kind in {"Pass", "MissedShots", "SavedShot", "ShotOnPost", "Goal", "Tackle", "Interception", "BallRecovery", "Clearance", "TakeOn", "Foul", "BlockedPass"}
        start = point(event.get("x"), event.get("y")) if spatial else (None, None)
        # Opta 140/141 are pass end coordinates, not a shot's goal-mouth coordinates.
        end = point(qualifiers.get("140"), qualifiers.get("141")) if kind == "Pass" else (None, None)
        rows.append({"id": str(event["id"]), "provider": "whoscored", "game_id": str(fixture["event_id"]),
            "provider_game_id": str(provider_game), "provider_player_id": str(event.get("playerId") or ""),
            "player_name": names.get(str(event.get("playerId"))), "team_id": team, "sequence": sequence,
            "period": number((event.get("period") or {}).get("value")), "minute": number(event.get("minute")),
            "second": number(event.get("second")), "event_type": kind,
            "outcome": (event.get("outcomeType") or {}).get("displayName"), "is_goal": bool(event.get("isGoal")),
            "start_x": start[0], "start_y": start[1], "end_x": end[0], "end_y": end[1],
            "coordinate_system": "WhoScored/Opta provider 0–100 coordinates scaled to 105 × 68; stadium direction unverified.",
            "fixture_sha256": fixture_signature(fixture), "source_sha256": checksum, "club_identity_version": CLUB_IDENTITY_VERSION,
            "raw_event_json": json.dumps(event, sort_keys=True)})
    return rows


class WhoScoredSource:
    def __init__(self, connector):
        self.connector = connector
        self.source = connector.source_cache or CFBSource(connector.data_dir, namespace="soccer")
        try:
            self.package_version = importlib.metadata.version("soccerdata")
        except importlib.metadata.PackageNotFoundError:
            self.package_version = "uninstalled"

    def client(self, competition, season, refresh):
        module = load_optional_module("soccerdata", "WhoScored spatial enrichment")
        common = load_optional_module("soccerdata._common", "WhoScored spatial enrichment")
        if self.package_version not in {"1.9.0", "2026.43.0"}:
            raise ValueError("WhoScored parser compatibility has not been verified for this SoccerData version")
        owner = self
        class Reader(module.WhoScored):
            @classmethod
            def _all_leagues(cls):
                return module.WhoScored._all_leagues()

            def __init__(self):
                # Deliberately initialize only configuration, never Selenium.
                common.BaseReader.__init__(self, leagues=LEAGUES[competition][0], no_store=True,
                    data_dir=owner.connector.data_dir / "whoscored")
                self.seasons = f"{season - 1}/{season}"

            def get(self, url, filepath=None, var=None, no_cache=False, **kwargs):
                global _LAST_REQUEST
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.netloc != "www.whoscored.com" or parsed.fragment or not (
                    parsed.path in {"", "/"} or re.fullmatch(r"/Regions/\d+/Tournaments/\d+(?:/Seasons/\d+)?(?:/Stages/\d+)?(?:/[^/?]+)?", parsed.path)
                    or re.fullmatch(r"/tournaments/\d+/data/", parsed.path) or re.fullmatch(r"/Matches/\d+/Live", parsed.path)):
                    raise ValueError("Unapproved WhoScored source request")
                identity = hashlib.sha256(json.dumps([url, var]).encode()).hexdigest()
                key = f"{competition}/providers/whoscored/{VERSION}/{season}/raw/{identity}.json"
                with owner.source.lease(key, seconds=180):
                    saved = owner.source._cached(key, 3600 if refresh else 365 * 86400)
                    if saved is None:
                        budget = ACTIVE_BUDGET.get()
                        if budget is None:
                            raise RuntimeError("WhoScored must run inside a worker acquisition budget")
                        # Match upstream's five-second pacing across concurrent
                        # scopes; cached reads need neither a delay nor a request.
                        with _REQUEST_LOCK:
                            time.sleep(max(0, 5 - (time.monotonic() - _LAST_REQUEST)))
                            _LAST_REQUEST = time.monotonic()
                            payload = budget.fetch(url, max_bytes=16 * 1024**2)
                        # Check extraction before caching. Block pages are not empty successes.
                        extract(payload, var)
                        saved = {"text": payload.decode("utf-8")}
                        owner.source.store(key, saved)
                decoded = extract(saved["text"].encode(), var)
                if var == "require.config.params['args'].matchCentreData":
                    owner.match_payload = json.loads(decoded)
                return io.BytesIO(decoded)
        return Reader()

    def publish(self, competition, season, fixtures, team_id=None, refresh=False, progress=None):
        coverage = {"expected_matches": fixtures.height, "completed_matches": 0, "recorded_matches": 0,
                    "failed_requests": 0, "unmatched_matches": 0}
        rows, message = [], None
        working_bytes = 0
        budget = ACTIVE_BUDGET.get() or ResearchState(SimpleNamespace(settings=self.connector.settings,
            store=SimpleNamespace(persistence=self.source.persistence)), f"whoscored-sync-{uuid4().hex}")
        token = ACTIVE_BUDGET.set(budget)
        try:
            if not self.connector.settings.soccer_whoscored_enabled:
                message = "WhoScored is disabled; enable SOCCER_WHOSCORED_ENABLED to request enrichment."
            elif competition not in LEAGUES:
                message = "WhoScored discovery is currently configured for the five European domestic leagues only."
            elif not fixtures.is_empty():
                client = self.client(competition, season, refresh)
                schedule = records(client.read_schedule())
                for index, fixture in enumerate(fixtures.iter_rows(named=True), 1):
                    candidates = [game for game in schedule if str(game.get("date", ""))[:10] == str(fixture["date"])[:10]
                        and all(same_club(game.get(f"{side}_team"), fixture.get(f"{side}_team"), competition)
                            and number(game.get(f"{side}_score")) is not None
                            and number(game.get(f"{side}_score")) == number(fixture.get(f"{side}_score")) for side in ("home", "away"))]
                    if len(candidates) != 1:
                        coverage["unmatched_matches"] += 1
                        continue
                    game = candidates[0]
                    try:
                        key = f"{competition}/providers/whoscored/{VERSION}/{season}/games/{fixture['event_id']}.json"
                        with self.source.lease(key, seconds=180):
                            saved = self.source._cached(key, 3600 if refresh else 365 * 86400)
                            if not saved or saved.get("fixture_sha256") != fixture_signature(fixture):
                                raw = client.read_events(match_id=int(game["game_id"]), output_fmt="raw", retry_missing=False)
                                metadata = self.match_payload
                                if any(not same_club(metadata[side]["name"], fixture[f"{side}_team"], competition) for side in ("home", "away")):
                                    raise ValueError("WhoScored match header conflicts with fixture sides")
                                events = normalize(raw[int(game["game_id"])], fixture, game["game_id"], metadata)
                                if not events:
                                    raise ValueError("No recorded WhoScored events")
                                saved = {"fixture_sha256": fixture_signature(fixture), "fixture": fixture, "events": events}
                                self.source.store(key, saved)
                            size = len(json.dumps(saved["events"]).encode())
                            if working_bytes + size > self.connector.settings.research_working_bytes // 4:
                                message = "WhoScored working-memory bound reached; sync a selected team for the remaining coverage."
                                break
                            rows.extend(saved["events"])
                            working_bytes += size
                    except Exception as error:
                        coverage["failed_requests"] += 1
                        logger.warning("soccer_whoscored_match_failed game=%s error_type=%s", fixture["event_id"], type(error).__name__)
                    if progress:
                        progress(index, fixtures.height)
        except Exception as error:
            coverage["failed_requests"] += 1
            status = getattr(error, "code", None)
            reason = f"HTTP {status}" if isinstance(status, int) else type(error).__name__
            message = f"WhoScored acquisition unavailable ({reason}); static recaps remain available."
            logger.warning("soccer_whoscored_unavailable competition=%s season=%s error_type=%s", competition, season, type(error).__name__)
        finally:
            ACTIVE_BUDGET.reset(token)
        frame = pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame()
        scope = f"team:{team_id}" if team_id else None
        path = self.connector.data_dir / competition / "providers" / "whoscored" / VERSION / str(season) / (team_id or "competition") / f"{DATASET}.parquet"
        # Keep successful matches through partial refreshes, but not changed fixtures.
        if path.exists():
            previous = pl.read_parquet(path)
            if {"game_id", "fixture_sha256"} <= set(previous.columns):
                fresh = frame["game_id"].unique().to_list() if frame.width else []
                previous = previous.filter(pl.col("fixture_sha256").is_in([fixture_signature(row) for row in fixtures.iter_rows(named=True)])
                    & ~pl.col("game_id").is_in(fresh))
                if previous.height:
                    frame = pl.concat([frame, previous], how="diagonal_relaxed") if frame.width else previous
        if frame.height:
            frame = frame.sort("game_id", "sequence", "id")
        buffer = io.BytesIO()
        frame.write_parquet(buffer)
        CFBSource._write_local(path, buffer.getvalue())
        checksum = hashlib.sha256(buffer.getvalue()).hexdigest()
        snapshot = path.with_name(f"{DATASET}-{checksum}.parquet")
        CFBSource._write_local(snapshot, buffer.getvalue())
        count = frame["game_id"].n_unique() if frame.height else 0
        coverage.update(completed_matches=count, recorded_matches=count)
        manifest = self.connector.manifest_for(snapshot, competition, season, DATASET, frame, count, fixtures.height, count, scope)
        return manifest.model_copy(update={"manifest_id": stable_id("dataset", {"provider": "whoscored", "version": VERSION,
            "season": season, "competition": competition, "partition": scope, "sha256": checksum}),
            "provider_id": "whoscored", "processing_version": VERSION, "resolution_version": VERSION,
            "package_version": f"soccerdata:{self.package_version}", "source_url": "https://www.whoscored.com/", "coverage": coverage,
            "attribution": "WhoScored through SoccerData; unique competition/date/sides/score fixture crosswalk.",
            "license": "WhoScored source terms apply; no redistribution rights inferred.",
            "availability": "available" if count == fixtures.height and count and not coverage["failed_requests"] else "partial" if count else "download_failed" if coverage["failed_requests"] else "source_unavailable",
            "availability_message": message or "Unmatched fixtures and unavailable event fields remain explicit."})


def cached_recap(connector, competition, season, game_id, visual):
    """Use worker-prepared spatial context only; opening a tablet never downloads."""
    if competition not in LEAGUES or not str(game_id).isdigit():
        return visual
    source = connector.source_cache or CFBSource(connector.data_dir, namespace="soccer")
    saved = source._cached(f"{competition}/providers/whoscored/{VERSION}/{season}/games/{game_id}.json", float("inf"))
    if not saved or not isinstance(saved.get("fixture"), dict):
        return visual
    fixture = saved["fixture"]
    if str(fixture.get("event_id")) != str(game_id) or saved.get("fixture_sha256") != fixture_signature(fixture):
        return visual
    if any(not same_club(fixture.get(f"{side}_team"), getattr(visual, f"{side}_team_name"), competition)
           or number(fixture.get(f"{side}_score")) != getattr(visual, f"{side}_score") for side in ("home", "away")):
        return visual
    if visual.game_date and str(fixture.get("date"))[:10] != str(visual.game_date)[:10]:
        return visual
    actions = saved.get("events") or []
    # A game/team-scoped, unique full-name identity plus native ESPN athlete ID
    # is required; initials, fuzzy names, or clock-only matches are not enough.
    def signature(event):
        clock = str(event.get("clock") or "").replace("′", "'").replace("’", "'").replace(" ", "")
        match = re.fullmatch(r"(\d+)'?(?:\+(\d+)'?)?", clock)
        return int(match[1]) + int(match[2] or 0) if match else None
    proposals = []
    for event in visual.soccer_timeline:
        name = normalized_name(event.get("athlete_name") or "")
        native_name = str(event.get("athlete_name") or "")
        period = number(event.get("period"))
        minute = signature(event)
        team = str(event.get("team_id") or "")
        identities = {row.get("provider_player_id") for row in actions if row.get("team_id") == team
            and normalized_name(row.get("player_name") or "") == name}
        kind = str(event.get("type") or "").lower()
        candidates = []
        if event.get("athlete_id") and len(native_name.split()) >= 2 and len(identities) == 1 and period is not None and minute is not None:
            for row in actions:
                if row.get("team_id") != team or row.get("provider_player_id") not in identities or row.get("period") != period or row.get("minute") != minute:
                    continue
                if event.get("scoring_play") is True and row.get("is_goal") is True:
                    candidates.append(row)
                elif not event.get("scoring_play") and (("card" in kind and row.get("event_type") == "Card")
                    or ("substitution" in kind and row.get("event_type") in {"SubstitutionOn", "SubstitutionOff"})):
                    candidates.append(row)
        proposals.append(candidates[0] if len(candidates) == 1 else None)
    counts = {}
    for row in proposals:
        if row:
            counts[row["id"]] = counts.get(row["id"], 0) + 1
    timeline = []
    for event, row in zip(visual.soccer_timeline, proposals):
        if row and counts[row["id"]] == 1 and row.get("start_x") is not None:
            event = {**event, "spatial_context": {key: row.get(key) for key in (
                "start_x", "start_y", "end_x", "end_y", "coordinate_system", "source_sha256")},
                "spatial_provider": "whoscored", "spatial_event_id": row["id"],
                "spatial_match_method": "unique_game_team_full_name_period_minute_type_v1"}
        timeline.append(event)
    names = {str(fixture[f"{side}_team_id"]): fixture[f"{side}_team"] for side in ("home", "away")}
    return visual.model_copy(update={"soccer_timeline": timeline,
        "soccer_actions": [row for row in visual.soccer_actions if row.get("provider") != "whoscored"]
            + [{**row, "team_name": names.get(row["team_id"])} for row in actions],
        "soccer_actions_count": max(visual.soccer_actions_count, len(actions)),
        "source_packages": list(dict.fromkeys([*visual.source_packages, DATASET]))})
