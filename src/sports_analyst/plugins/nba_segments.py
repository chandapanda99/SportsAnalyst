from __future__ import annotations

from datetime import date, timedelta

import polars as pl

NBA_SEGMENTS = [
    {"value": "full_season", "label": "Full season", "description": "All regular-season and postseason games."},
    {"value": "regular_season", "label": "Regular season", "description": "Completed regular-season games."},
    {"value": "playoffs", "label": "Playoffs", "description": "Play-in and NBA playoff games."},
    {"value": "opening_month", "label": "Opening month", "description": "First 30 days of the league regular season."},
    {"value": "pre_all_star", "label": "Pre-All-Star", "description": "Regular-season games before the All-Star break."},
    {"value": "post_all_star", "label": "Post-All-Star", "description": "Regular-season games after the All-Star break."},
    {
        "value": "post_trade_deadline",
        "label": "Post-trade-deadline",
        "description": "Regular-season games after that season's reviewed trade deadline.",
    },
    {"value": "play_in", "label": "Play-in", "description": "NBA Play-In Tournament games."},
    {"value": "first_round", "label": "First round", "description": "First-round playoff games."},
    {"value": "conference_semifinals", "label": "Conference semifinals", "description": "Conference semifinal games."},
    {"value": "conference_finals", "label": "Conference finals", "description": "Conference final games."},
    {"value": "nba_finals", "label": "NBA Finals", "description": "NBA Finals games."},
]

# Canonical NBA seasons use their ending year. These dates are deliberately
# versioned and reviewed rather than inferred. Unknown seasons simply do not
# advertise milestone-dependent segments.
NBA_MILESTONES: dict[int, dict[str, date]] = {
    2022: {"trade_deadline": date(2022, 2, 10), "all_star_start": date(2022, 2, 18), "all_star_end": date(2022, 2, 20)},
    2023: {"trade_deadline": date(2023, 2, 9), "all_star_start": date(2023, 2, 17), "all_star_end": date(2023, 2, 19)},
    2024: {"trade_deadline": date(2024, 2, 8), "all_star_start": date(2024, 2, 16), "all_star_end": date(2024, 2, 18)},
    2025: {"trade_deadline": date(2025, 2, 6), "all_star_start": date(2025, 2, 14), "all_star_end": date(2025, 2, 16)},
    2026: {"trade_deadline": date(2026, 2, 5), "all_star_start": date(2026, 2, 13), "all_star_end": date(2026, 2, 15)},
}

ROUND_PATTERNS = {
    "play_in": r"(?i)play[ -]?in",
    "first_round": r"(?i)(first|1st) round",
    "conference_semifinals": r"(?i)(conference semi|second|2nd) round",
    "conference_finals": r"(?i)conference finals?",
    "nba_finals": r"(?i)(nba |league )?finals",
}


def _prepared_schedule(schedule: pl.DataFrame) -> pl.DataFrame:
    if schedule.is_empty() or "game_id" not in schedule.columns:
        return pl.DataFrame()
    frame = schedule
    if "game_date" not in frame.columns:
        if "game_date_time" not in frame.columns:
            return pl.DataFrame()
        frame = frame.with_columns(pl.col("game_date_time").cast(pl.Date, strict=False).alias("game_date"))
    elif frame.schema["game_date"] != pl.Date:
        expression = (
            pl.col("game_date").str.slice(0, 10).str.to_date(strict=False)
            if frame.schema["game_date"] == pl.String
            else pl.col("game_date").cast(pl.Date, strict=False)
        )
        frame = frame.with_columns(expression.alias("game_date"))
    if "season_type" not in frame.columns:
        frame = frame.with_columns(pl.lit(None).cast(pl.Int32).alias("season_type"))
    if "notes_headline" not in frame.columns:
        frame = frame.with_columns(pl.lit("").alias("notes_headline"))
    return frame.with_columns(pl.col("game_id").cast(pl.String))


def available_segments(schedule: pl.DataFrame, season: int) -> list[dict[str, str]]:
    return [option for option in NBA_SEGMENTS if segment_game_ids(schedule, season, option["value"])]


def segment_game_ids(schedule: pl.DataFrame, season: int, segment: str) -> set[str]:
    frame = _prepared_schedule(schedule)
    if frame.is_empty():
        return set()
    segment = segment.lower()
    if segment == "full_season":
        selected = frame.filter(pl.col("season_type").is_in([2, 3]))
    elif segment == "regular_season":
        selected = frame.filter(pl.col("season_type") == 2)
    elif segment == "playoffs":
        selected = frame.filter(pl.col("season_type") == 3)
    elif segment == "opening_month":
        regular = frame.filter(pl.col("season_type") == 2)
        first = regular.get_column("game_date").min()
        selected = regular.filter(pl.col("game_date") < first + timedelta(days=30)) if first else regular.head(0)
    elif segment in {"pre_all_star", "post_all_star", "post_trade_deadline"}:
        milestones = NBA_MILESTONES.get(season)
        if not milestones:
            return set()
        regular = frame.filter(pl.col("season_type") == 2)
        if segment == "pre_all_star":
            selected = regular.filter(pl.col("game_date") < milestones["all_star_start"])
        elif segment == "post_all_star":
            selected = regular.filter(pl.col("game_date") > milestones["all_star_end"])
        else:
            selected = regular.filter(pl.col("game_date") > milestones["trade_deadline"])
    elif segment in ROUND_PATTERNS:
        selected = frame.filter(pl.col("notes_headline").fill_null("").cast(pl.String).str.contains(ROUND_PATTERNS[segment]))
    else:
        return set()
    return set(selected.get_column("game_id").drop_nulls().to_list())
