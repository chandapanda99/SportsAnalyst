"""Recorded ESPN expected goals, fetched through SportsDataverse's Core API."""

from __future__ import annotations

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

import polars as pl

logger = logging.getLogger(__name__)
CORE_ROOT = "https://sports.core.api.espn.com/v2/sports/soccer/leagues"
STAT_FIELDS = {
    "expected_goals": "expectedGoals",
    "expected_goals_conceded": "expectedGoalsConceded",
    "expected_goals_non_penalty": "expectedGoalsNonPenalty",
    "expected_goals_non_penalty_conceded": "expectedGoalsNonPenaltyConceded",
    "total_goals": "totalGoals",
    "total_shots": "totalShots",
}
TEAM_XG_FIELDS = {
    "xg_per_match": ("expected_goals",),
    "xga_per_match": ("expected_goals_conceded",),
    "xg_difference_per_match": ("expected_goals", "expected_goals_conceded"),
    "non_penalty_xg_per_match": ("expected_goals_non_penalty",),
    "goals_minus_xg_per_match": ("expected_goals",),
}
PLAYER_XG_FIELDS = {
    "expected_goals": ("expected_goals",),
    "non_penalty_expected_goals": ("expected_goals_non_penalty",),
    "goals_minus_xg": ("expected_goals", "total_goals"),
}


def numeric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def core_statistics(payload: dict[str, Any]) -> dict[str, float | None]:
    """ESPN uses either a split object or a list; prefer its Total split."""
    splits = payload.get("splits") or []
    if isinstance(splits, dict):
        splits = [splits]
    totals = [split for split in splits if isinstance(split, dict)
              and str(split.get("type") or split.get("name") or "").lower() == "total"]
    selected = totals or [split for split in splits if isinstance(split, dict)][:1]
    return {stat["name"]: numeric(stat.get("value", stat.get("displayValue")))
            for split in selected for category in split.get("categories") or []
            for stat in category.get("stats") or [] if stat.get("name")}


def coverage(frame: pl.DataFrame, expected_matches: int) -> dict[str, int]:
    if frame.is_empty():
        return {"completed_matches": 0, "expected_matches": expected_matches, "recorded_matches": 0}
    # Team data must have both sides fetched; selected-player data has one row per match.
    expected_rows = 1 if "athlete_id" in frame.columns else 2
    counts = frame.group_by("game_id").agg(
        pl.len().alias("rows"), pl.col("stats_available").sum().alias("fetched"),
        pl.col("expected_goals").is_not_null().sum().alias("recorded"),
    )
    complete = counts.filter((pl.col("rows") == expected_rows) & (pl.col("fetched") == expected_rows)).height
    recorded = counts.filter((pl.col("rows") == expected_rows) & (pl.col("recorded") == expected_rows)).height
    result = {"completed_matches": complete, "expected_matches": expected_matches, "recorded_matches": recorded}
    for field in STAT_FIELDS:
        result[f"{field}_rows"] = frame.get_column(field).is_not_null().sum()
    for metric, fields in TEAM_XG_FIELDS.items():
        result[f"{metric}_rows"] = frame.filter(pl.all_horizontal(pl.col(field).is_not_null() for field in fields)).height
    return result


class ExpectedGoalsSource:
    def __init__(self, data_dir: Path, concurrency: int) -> None:
        self.data_dir = data_dir
        self.concurrency = min(max(concurrency, 1), 8)

    @staticmethod
    def _team_statistics(competition: str, game_id: str, team_id: str) -> dict:
        from sportsdataverse.soccer import espn_soccer_game_team_statistics
        from sportsdataverse.errors import SportsDataverseError

        # The package's parsed form currently assumes splits is a list. Preserve
        # the authoritative numeric values and normalize both raw shapes here.
        try:
            return espn_soccer_game_team_statistics(
                league=competition, event_id=game_id, team_id=team_id,
                return_parsed=False, timeout=30, num_retries=2,
            )
        except SportsDataverseError as error:
            raise OSError(str(error)) from error

    @staticmethod
    def _player_statistics(competition: str, game_id: str, team_id: str, athlete_id: str) -> dict:
        from sportsdataverse.dl_utils import download
        from sportsdataverse.errors import SportsDataverseError

        # This is the statistics resource linked by the documented Core roster
        # endpoint. Use SDV's shared transport rather than one request per roster member.
        url = f"{CORE_ROOT}/{competition}/events/{game_id}/competitions/{game_id}/competitors/{team_id}/roster/{athlete_id}/statistics/0"
        try:
            response = download(url=url, timeout=30, num_retries=2)
        except SportsDataverseError as error:
            raise OSError(str(error)) from error
        if response is None:
            raise OSError("ESPN returned no player match statistics")
        return response.json()

    def _row(self, competition: str, season: int, game_id: str, team_id: str,
             athlete_id: str | None = None, *, refresh: bool = False) -> dict:
        if not all(value.isdigit() for value in (game_id, team_id, *([athlete_id] if athlete_id else []))):
            raise ValueError("Expected numeric ESPN match, team and player IDs")
        suffix = f"/roster/{athlete_id}" if athlete_id else ""
        url = f"{CORE_ROOT}/{competition}/events/{game_id}/competitions/{game_id}/competitors/{team_id}{suffix}/statistics/0"
        checkpoint = self.data_dir / competition / str(season) / "core_statistics" / game_id / f"{team_id}_{athlete_id or 'team'}.json"
        stats: dict[str, float | None] = {}
        try:
            try:
                payload = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() and not refresh else {}
            except (OSError, ValueError):
                payload = {}
            stats = core_statistics(payload)
            if not stats:
                payload = (self._player_statistics(competition, game_id, team_id, athlete_id) if athlete_id
                           else self._team_statistics(competition, game_id, team_id))
                stats = core_statistics(payload)
                if stats:
                    checkpoint.parent.mkdir(parents=True, exist_ok=True)
                    temporary = checkpoint.with_suffix(".tmp")
                    temporary.write_text(json.dumps(payload), encoding="utf-8")
                    temporary.replace(checkpoint)
        except (OSError, ValueError, TypeError, KeyError) as error:
            logger.warning("soccer_xg_unavailable competition=%s game=%s team=%s player=%s error=%s",
                           competition, game_id, team_id, athlete_id, error)
        return {"game_id": game_id, "team_id": team_id, **({"athlete_id": athlete_id} if athlete_id else {}),
                "stats_available": bool(stats), "source_url": url,
                **{field: stats.get(name) for field, name in STAT_FIELDS.items()}}

    def team_matches(self, competition: str, season: int, schedule: pl.DataFrame,
                     progress: Callable[[], None] | None = None, *,
                     progress_counts: Callable[[int, int], None] | None = None, refresh: bool = False) -> pl.DataFrame:
        rows = []
        with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="soccer-xg") as pool:
            futures = [pool.submit(self._row, competition, season, str(match["event_id"]), str(match[f"{side}_team_id"]), refresh=refresh)
                       for match in schedule.iter_rows(named=True) for side in ("home", "away")]
            for index, future in enumerate(as_completed(futures), 1):
                rows.append(future.result())
                if progress_counts:
                    progress_counts(index, len(futures))
                if progress and (index % 20 == 0 or index == len(futures)):
                    progress()
        return self._frame(rows)

    def player_matches(self, competition: str, season: int, athlete_id: str,
                       appearances: pl.DataFrame, progress: Callable[[], None] | None = None) -> pl.DataFrame:
        rows = []
        with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="soccer-player-xg") as pool:
            futures = [pool.submit(self._row, competition, season, str(row["game_id"]), str(row["team_id"]), athlete_id)
                       for row in appearances.select("game_id", "team_id").unique().iter_rows(named=True)]
            for index, future in enumerate(as_completed(futures), 1):
                rows.append(future.result())
                if progress and (index % 10 == 0 or index == len(futures)):
                    progress()
        return self._frame(rows)

    @staticmethod
    def _frame(rows: list[dict]) -> pl.DataFrame:
        if not rows:
            return pl.DataFrame()
        # Historical/qualifying matches may have no xG in the entire inference
        # sample. Set dtypes before construction; casting afterward is too late.
        return pl.DataFrame(rows, schema_overrides={field: pl.Float64 for field in STAT_FIELDS}).sort("game_id", "team_id")
