"""Local ESPN soccer match snapshots using the endpoints catalogued by Sports Dataverse."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from threading import RLock
from typing import Any

import polars as pl

from sports_analyst.config import Settings, get_settings
from sports_analyst.data import sha256_file
from sports_analyst.models import DatasetManifest, stable_id

logger = logging.getLogger(__name__)

SOCCER_COMPETITIONS = {
    "eng.1": ("Premier League", False),
    "usa.1": ("MLS", True),
    "esp.1": ("La Liga", False),
    "ger.1": ("Bundesliga", False),
    "ita.1": ("Serie A", False),
    "fra.1": ("Ligue 1", False),
    "usa.nwsl": ("NWSL", True),
}
SOCCER_DATASETS = ("play_by_play", "team_stats", "lineups", "key_events")
SOCCER_DEFAULT_DATASETS = list(SOCCER_DATASETS)


def _stat_column(name: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.replace("-", "_")).lower()


def soccer_season_label(competition: str, season: int) -> str:
    return str(season) if SOCCER_COMPETITIONS[competition][1] else f"{season - 1}–{str(season)[-2:]}"


def _months(competition: str, season: int):
    first = date(season, 1, 1) if SOCCER_COMPETITIONS[competition][1] else date(season - 1, 7, 1)
    last = date(season, 12, 31) if SOCCER_COMPETITIONS[competition][1] else date(season, 6, 30)
    cursor = first
    while cursor <= last:
        next_month = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        yield f"{cursor:%Y%m}"
        cursor = next_month


class SportsDataverseSoccerConnector:
    sport_id = "soccer"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        self.data_dir = self.settings.data_dir / "raw" / "soccer"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cache: OrderedDict[str, pl.DataFrame] = OrderedDict()
        self._fixture_coverage: dict[tuple[str, int], tuple[int, int]] = {}
        self._lock = RLock()

    @staticmethod
    def _request(competition: str, endpoint: str, params: dict[str, str | int]) -> dict[str, Any]:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition}/{endpoint}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "SportsAnalyst/1.0", "Accept": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    @staticmethod
    def _parse_scoreboard(payload: dict[str, Any]) -> pl.DataFrame:
        rows = []
        for event in payload.get("events") or []:
            game = (event.get("competitions") or [{}])[0]
            competitors = game.get("competitors") or []
            home = next((item for item in competitors if item.get("homeAway") == "home"), {})
            away = next((item for item in competitors if item.get("homeAway") == "away"), {})
            rows.append({
                "event_id": str(event.get("id") or ""), "date": event.get("date"),
                "home_team_id": str((home.get("team") or {}).get("id") or ""),
                "away_team_id": str((away.get("team") or {}).get("id") or ""),
                "home_team": (home.get("team") or {}).get("displayName"),
                "away_team": (away.get("team") or {}).get("displayName"),
                "home_score": home.get("score"), "away_score": away.get("score"),
                "status": ((event.get("status") or {}).get("type") or {}).get("name"),
            })
        return pl.DataFrame(rows) if rows else pl.DataFrame()

    @staticmethod
    def _parse_summary(payload: dict[str, Any], section: str) -> pl.DataFrame:
        rows: list[dict[str, Any]] = []
        if section == "team_stats":
            for entry in (payload.get("boxscore") or {}).get("teams") or []:
                team = entry.get("team") or {}
                row = {"team_id": str(team.get("id") or ""), "team_name": team.get("displayName")}
                for stat in entry.get("statistics") or []:
                    name = stat.get("name")
                    if name:
                        column = _stat_column(str(name))
                        row[column] = stat.get("displayValue", stat.get("value"))
                rows.append(row)
        elif section == "lineups":
            for entry in payload.get("rosters") or []:
                for player in entry.get("roster") or []:
                    athlete = player.get("athlete") or {}
                    rows.append({"team_id": str((entry.get("team") or {}).get("id") or ""),
                                 "athlete": athlete.get("displayName"), "athlete_id": str(athlete.get("id") or ""),
                                 "position": (player.get("position") or {}).get("abbreviation"),
                                 "starter": player.get("starter")})
        elif section == "key_events":
            for event in payload.get("keyEvents") or []:
                participants = event.get("participants") or []
                athlete = (participants[0].get("athlete") or {}) if participants else {}
                rows.append({"id": str(event.get("id") or ""), "type": (event.get("type") or {}).get("text"),
                             "text": event.get("text"), "clock": (event.get("clock") or {}).get("displayValue"),
                             "team_id": str((event.get("team") or {}).get("id") or ""),
                             "scoring_play": event.get("scoringPlay"),
                             "athlete_id": str(athlete.get("id") or ""), "athlete_name": athlete.get("displayName")})
        return pl.DataFrame(rows) if rows else pl.DataFrame()

    def _scoreboard(self, competition: str, season: int) -> pl.DataFrame:
        frames = []
        intervals = list(_months(competition, season))
        successful = 0
        for interval in intervals:
            try:
                frame = self._parse_scoreboard(self._request(competition, "scoreboard", {"dates": interval, "limit": 500}))
                successful += 1
                if isinstance(frame, pl.DataFrame) and not frame.is_empty():
                    frames.append(frame)
            except Exception as error:
                logger.warning("soccer_scoreboard_unavailable competition=%s interval=%s error=%s", competition, interval, error)
        self._fixture_coverage[(competition, season)] = (successful, len(intervals))
        if not frames:
            raise ValueError(f"No fixtures were returned for {competition} {soccer_season_label(competition, season)}")
        frame = pl.concat(frames, how="diagonal_relaxed").filter(
            pl.col("event_id").str.contains(r"^\d+$")
        ).unique(subset=["event_id"], keep="last")
        return frame.with_columns(pl.lit(season).alias("season"), pl.lit(competition).alias("competition"))

    def _summary(self, competition: str, season: int, event_id: str) -> dict[str, Any]:
        if not event_id.isdigit():
            raise ValueError("Invalid ESPN soccer event ID")
        checkpoint = self.data_dir / competition / str(season) / "events" / f"{event_id}.json"
        if checkpoint.exists():
            try:
                cached = json.loads(checkpoint.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached.get("header"):
                    return cached
            except (OSError, json.JSONDecodeError):
                logger.warning("soccer_summary_cache_invalid competition=%s event=%s", competition, event_id)
        raw = self._request(competition, "summary", {"event": event_id})
        if not isinstance(raw, dict) or not raw.get("header"):
            raise ValueError(f"Match {event_id} returned no summary header")
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(raw), encoding="utf-8")
        temporary.replace(checkpoint)
        return raw

    def sync(
        self,
        seasons: list[int],
        datasets: list[str] | None = None,
        progress_callback: Callable[[str, str, int, int, int], None] | None = None,
        manifest_callback: Callable[[DatasetManifest], None] | None = None,
        skip: set[tuple[str, int]] | None = None,
        *,
        competition: str | None = None,
    ) -> list[DatasetManifest]:
        if competition not in SOCCER_COMPETITIONS:
            raise ValueError(f"Unsupported soccer competition: {competition}")
        selected = list(dict.fromkeys(datasets or SOCCER_DEFAULT_DATASETS))
        if set(selected) - set(SOCCER_DATASETS):
            raise ValueError(f"Unsupported soccer datasets: {sorted(set(selected) - set(SOCCER_DATASETS))}")
        if not seasons or any(year < 2000 or year > date.today().year + 1 for year in seasons):
            raise ValueError("Choose valid soccer seasons")
        produced = []
        work = [(year, dataset) for year in sorted(set(seasons)) for dataset in selected]
        completed = 0
        for season in sorted(set(seasons)):
            pending = [dataset for dataset in selected if (dataset, season) not in (skip or set())]
            if not pending:
                completed += len(selected)
                continue
            if progress_callback:
                progress_callback("downloading", "play_by_play", season, completed, len(work))
            schedule = self._scoreboard(competition, season)
            final = schedule.filter(pl.col("status").cast(pl.String).str.to_lowercase().is_in(["status_final", "status_full_time", "final"]))
            ids = final.get_column("event_id").cast(pl.String).to_list()
            summaries: dict[str, dict] = {}
            if any(dataset != "play_by_play" for dataset in pending) and ids:
                workers = min(self.settings.dataset_sync_concurrency, len(ids), 8)
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="soccer-sync") as pool:
                    futures = {pool.submit(self._summary, competition, season, match): match for match in ids}
                    for future in as_completed(futures):
                        match = futures[future]
                        try:
                            summaries[match] = future.result()
                        except Exception as error:
                            logger.warning("soccer_match_unavailable competition=%s event=%s error=%s", competition, match, error)
            completed_ids = set(ids)
            fetched_ids = set(summaries) | {match for match in ids if (
                self.data_dir / competition / str(season) / "events" / f"{match}.json").exists()}
            schedule = schedule.with_columns(pl.Series("summary_status", [
                "fetched" if str(event_id) in fetched_ids else
                "unavailable" if str(event_id) in completed_ids and any(dataset != "play_by_play" for dataset in pending) else
                "not_requested" if str(event_id) in completed_ids else "not_completed"
                for event_id in schedule.get_column("event_id").to_list()
            ]))
            frames: dict[str, pl.DataFrame] = {"play_by_play": schedule}
            if "play_by_play" in selected and "play_by_play" not in pending and any(dataset != "play_by_play" for dataset in pending):
                pending.insert(0, "play_by_play")
            for dataset in pending:
                if dataset == "play_by_play":
                    continue
                section = "key_events" if dataset == "key_events" else dataset
                parts = []
                for match, raw in summaries.items():
                    frame = self._parse_summary(raw, section)
                    if isinstance(frame, pl.DataFrame) and not frame.is_empty():
                        parts.append(frame.with_columns(pl.lit(match).alias("game_id")))
                    elif dataset == "key_events" and isinstance(raw.get("keyEvents"), list):
                        # A fetched summary with no key events is a verified zero,
                        # unlike a summary that could not be fetched at all.
                        parts.append(pl.DataFrame({"game_id": [match], "athlete_id": [""],
                                                   "type": [None], "text": [None],
                                                   "clock": [None], "scoring_play": [False]}))
                frames[dataset] = pl.concat(parts, how="diagonal_relaxed") if parts else pl.DataFrame()
            for dataset in pending:
                frame = frames[dataset]
                completed += 1
                if frame.is_empty():
                    if progress_callback:
                        progress_callback("skipped", dataset, season, completed, len(work))
                    continue
                frame = frame.with_columns(pl.lit(season).alias("season"), pl.lit(competition).alias("competition"))
                path = self.data_dir / competition / str(season) / f"{dataset}.parquet"
                path.parent.mkdir(parents=True, exist_ok=True)
                frame.write_parquet(path)
                completed_count, expected_count = (self._fixture_coverage.get((competition, season), (1, 1))
                                                   if dataset == "play_by_play" else (len(summaries), len(ids)))
                recorded_count = (frame.get_column("game_id").n_unique() if dataset != "play_by_play" and "game_id" in frame.columns else 0)
                manifest = self.manifest_for(path, competition, season, dataset, frame, completed_count, expected_count, recorded_count)
                produced.append(manifest)
                if manifest_callback:
                    manifest_callback(manifest)
                if progress_callback:
                    progress_callback("downloaded", dataset, season, completed, len(work))
        return produced

    def manifest_for(self, path: Path, competition: str, season: int, dataset: str, frame: pl.DataFrame,
                     completed_matches: int = 0, expected_matches: int = 0, recorded_matches: int = 0) -> DatasetManifest:
        checksum = sha256_file(path)
        stat = path.stat()
        return DatasetManifest(
            manifest_id=stable_id("dataset", {"sport": "soccer", "competition": competition, "season": season, "dataset": dataset, "sha256": checksum}),
            sport="soccer", competition=competition, dataset=dataset, season=season,
            source_url=(f"https://site.web.api.espn.com/apis/common/v3/sports/soccer/{competition}/athletes/{dataset.removeprefix('player_game_logs_')}/gamelog"
                        if dataset.startswith("player_game_logs_") else f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition}/"),
            sha256=checksum, row_count=frame.height, columns=frame.columns,
            package_version=importlib.metadata.version("sportsdataverse"),
            license="See ESPN data terms.",
            attribution="Match data provided by ESPN; endpoint selection follows the Sports Dataverse soccer catalog.",
            local_path=str(path.resolve()), file_size=stat.st_size, modified_ns=stat.st_mtime_ns,
            coverage=({"fetched_intervals": completed_matches, "expected_intervals": expected_matches}
                      if dataset == "play_by_play" else {"completed_matches": completed_matches, "expected_matches": expected_matches,
                                                         "recorded_matches": recorded_matches}),
        )

    def player_game_log_manifest(self, competition: str, season: int, athlete_id: str) -> DatasetManifest:
        """Fetch only a selected player's season log; keep it in the local catalog."""
        if competition not in SOCCER_COMPETITIONS or not athlete_id.isdigit():
            raise ValueError("Expected a supported competition and numeric player ID")
        dataset = f"player_game_logs_{athlete_id}"
        path = self.data_dir / competition / str(season) / "player_game_logs" / f"{athlete_id}.parquet"
        if path.exists():
            frame = pl.read_parquet(path)
            return self.manifest_for(path, competition, season, dataset, frame)
        source_season = season if SOCCER_COMPETITIONS[competition][1] else season - 1
        url = (f"https://site.web.api.espn.com/apis/common/v3/sports/soccer/{competition}"
               f"/athletes/{athlete_id}/gamelog?{urlencode({'season': source_season})}")
        with urlopen(Request(url, headers={"User-Agent": "SportsAnalyst/1.0", "Accept": "application/json"}), timeout=30) as response:
            raw = json.load(response)
        rows = []
        for season_type in raw.get("seasonTypes") or []:
            for category in season_type.get("categories") or []:
                names = category.get("names") or category.get("labels") or raw.get("names") or []
                for event in category.get("events") or []:
                    game_id = event.get("eventId") or event.get("id") or (event.get("event") or {}).get("id")
                    if not game_id:
                        continue
                    row = {"game_id": str(game_id), "date": event.get("date")}
                    for index, value in enumerate(event.get("stats") or []):
                        if index >= len(names):
                            continue
                        key = _stat_column(str(names[index]))
                        if key in {"goal_assists", "assists", "ast", "a"}:
                            row["assists"] = value
                    rows.append(row)
        if not rows:
            raise ValueError(f"No player game logs were returned for {athlete_id} in {season}")
        frame = pl.DataFrame(rows)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(path)
        return self.manifest_for(path, competition, season, dataset, frame)

    def load(self, manifest: DatasetManifest, columns=None) -> pl.DataFrame:
        if manifest.sport != "soccer" or manifest.competition not in SOCCER_COMPETITIONS:
            raise ValueError("Expected a soccer manifest with a supported competition")
        path = Path(manifest.local_path).resolve()
        if self.data_dir.resolve() not in path.parents:
            raise ValueError("Soccer dataset is outside the managed data directory")
        selected = [column for column in (columns or manifest.columns) if column in manifest.columns]
        return pl.read_parquet(path, columns=selected)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
