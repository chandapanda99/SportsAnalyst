"""NFL metadata, tool schemas, and stateless analytical primitives."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any

import numpy as np
import polars as pl

from sports_analyst.models import (
    AggregateEvidence,
    ChartArtifact,
    DatasetManifest,
    PlayEvidence,
    ToolExecutionRecord,
    stable_id,
)

LATEST_SYNCABLE_SEASON = 2025

NFL_TEAMS = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LV": "Las Vegas Raiders",
    "LAC": "Los Angeles Chargers",
    "LA": "Los Angeles Rams",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SF": "San Francisco 49ers",
    "SEA": "Seattle Seahawks",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}

AFC_TEAMS = {"BAL", "BUF", "CIN", "CLE", "DEN", "HOU", "IND", "JAX", "KC", "LAC", "LV", "MIA", "NE", "NYJ", "PIT", "TEN"}
TEAM_CONFERENCES = {team: ("AFC" if team in AFC_TEAMS else "NFC") for team in NFL_TEAMS}

TEAM_ALIASES = {
    "ARIZONA": "ARI",
    "ATLANTA": "ATL",
    "BALTIMORE": "BAL",
    "BUFFALO": "BUF",
    "CAROLINA": "CAR",
    "CHICAGO": "CHI",
    "CINCINNATI": "CIN",
    "CLEVELAND": "CLE",
    "DALLAS": "DAL",
    "DENVER": "DEN",
    "DETROIT": "DET",
    "GREEN BAY": "GB",
    "HOUSTON": "HOU",
    "INDIANAPOLIS": "IND",
    "JACKSONVILLE": "JAX",
    "KANSAS CITY": "KC",
    "KC": "KC",
    "LAS VEGAS": "LV",
    "LOS ANGELES CHARGERS": "LAC",
    "LOS ANGELES RAMS": "LA",
    "MIAMI": "MIA",
    "MINNESOTA": "MIN",
    "NEW ENGLAND": "NE",
    "NEW ORLEANS": "NO",
    "NEW YORK GIANTS": "NYG",
    "NEW YORK JETS": "NYJ",
    "PHILADELPHIA": "PHI",
    "PITTSBURGH": "PIT",
    "SAN FRANCISCO": "SF",
    "SEATTLE": "SEA",
    "TAMPA BAY": "TB",
    "TENNESSEE": "TEN",
    "WASHINGTON": "WAS",
}
TEAM_ALIASES.update({code: code for code in NFL_TEAMS})
TEAM_ALIASES.update({label.upper(): code for code, label in NFL_TEAMS.items()})

METRICS: dict[str, tuple[str, str]] = {
    "epa_per_dropback": ("epa", "EPA/dropback"),
    "success_rate": ("success", "Success rate"),
    "cpoe": ("cpoe", "CPOE"),
    "explosive_pass_rate": ("explosive", "Explosive pass rate"),
    "yards_per_play": ("yards_gained", "Yards/play"),
    "sack_rate": ("sack", "Sack rate"),
    "interception_rate": ("interception", "Interception rate"),
    "air_yards": ("air_yards", "Air yards/attempt"),
    "yards_after_catch": ("yards_after_catch", "YAC/completion"),
    "epa_per_rush": ("epa", "EPA/rush"),
    "rush_success_rate": ("success", "Rush success rate"),
    "yards_per_rush": ("yards_gained", "Yards/rush"),
    "explosive_run_rate": ("explosive_run", "Explosive run rate"),
    "stuff_rate": ("stuff", "Stuff rate"),
    "rush_first_down_rate": ("first_down", "Rushing first-down rate"),
    "epa_per_play": ("epa", "EPA/play"),
    "overall_success_rate": ("success", "Overall success rate"),
    "overall_yards_per_play": ("yards_gained", "Overall yards/play"),
    "turnover_rate": ("turnover", "Turnover rate"),
}
DEFAULT_METRICS = ["epa_per_dropback", "success_rate", "cpoe", "explosive_pass_rate"]
DEFAULT_METRICS_BY_DOMAIN = {
    "passing": DEFAULT_METRICS,
    "rushing": ["epa_per_rush", "rush_success_rate", "yards_per_rush", "explosive_run_rate"],
    "offense": ["epa_per_play", "overall_success_rate", "overall_yards_per_play", "turnover_rate"],
}
METRIC_DOMAINS = {
    **{
        metric: "passing"
        for metric in DEFAULT_METRICS + ["yards_per_play", "sack_rate", "interception_rate", "air_yards", "yards_after_catch"]
    },
    **{
        metric: "rushing"
        for metric in [
            "epa_per_rush",
            "rush_success_rate",
            "yards_per_rush",
            "explosive_run_rate",
            "stuff_rate",
            "rush_first_down_rate",
        ]
    },
    **{metric: "offense" for metric in ["epa_per_play", "overall_success_rate", "overall_yards_per_play", "turnover_rate"]},
}
DEFAULT_SPLITS = ["down", "field_zone", "score_state", "personnel", "formation"]

METRIC_METADATA = {
    "epa_per_dropback": ("Efficiency", "Expected points added per qualifying quarterback dropback.", {"epa"}),
    "success_rate": ("Efficiency", "Share of dropbacks with positive EPA.", {"success"}),
    "cpoe": ("Passing", "Completion percentage over expectation on qualifying attempts.", {"cpoe"}),
    "explosive_pass_rate": ("Passing", "Share of dropbacks gaining at least 20 yards.", {"yards_gained"}),
    "yards_per_play": ("Efficiency", "Average yards gained per qualifying dropback.", {"yards_gained"}),
    "sack_rate": ("Negative outcomes", "Share of qualifying dropbacks ending in a sack.", {"sack"}),
    "interception_rate": ("Negative outcomes", "Share of qualifying dropbacks ending in an interception.", {"interception"}),
    "air_yards": ("Passing", "Average intended air yards per pass attempt.", {"air_yards"}),
    "yards_after_catch": ("Passing", "Average yards after catch on completed passes.", {"yards_after_catch"}),
    "epa_per_rush": ("Rushing Efficiency", "Expected points added per qualifying rushing attempt.", {"epa", "rush_attempt"}),
    "rush_success_rate": ("Rushing Efficiency", "Share of rushing attempts with positive EPA.", {"success", "rush_attempt"}),
    "yards_per_rush": ("Rushing Production", "Average yards gained per qualifying rushing attempt.", {"yards_gained", "rush_attempt"}),
    "explosive_run_rate": ("Rushing Production", "Share of rushing attempts gaining at least 10 yards.", {"yards_gained", "rush_attempt"}),
    "stuff_rate": (
        "Rushing Outcomes",
        "Share of rushing attempts stopped at or behind the line of scrimmage.",
        {"yards_gained", "rush_attempt"},
    ),
    "rush_first_down_rate": (
        "Rushing Outcomes",
        "Share of rushing attempts that gained a first down.",
        {"yards_gained", "ydstogo", "rush_attempt"},
    ),
    "epa_per_play": (
        "Overall Efficiency",
        "Expected points added per qualifying offensive play.",
        {"epa", "qb_dropback", "rush_attempt"},
    ),
    "overall_success_rate": (
        "Overall Efficiency",
        "Share of qualifying offensive plays with positive EPA.",
        {"success", "qb_dropback", "rush_attempt"},
    ),
    "overall_yards_per_play": (
        "Overall Production",
        "Average yards gained per qualifying offensive play.",
        {"yards_gained", "qb_dropback", "rush_attempt"},
    ),
    "turnover_rate": (
        "Overall Outcomes",
        "Share of qualifying offensive plays ending in an interception or lost fumble.",
        {"interception", "qb_dropback", "rush_attempt"},
    ),
}
METRIC_FORMULAS = {
    "epa_per_dropback": "mean(epa) over qualifying quarterback dropbacks",
    "success_rate": "count(epa > 0) / qualifying quarterback dropbacks",
    "cpoe": "mean(completion percentage over expectation) on qualifying attempts",
    "explosive_pass_rate": "count(yards_gained >= 20) / qualifying quarterback dropbacks",
    "yards_per_play": "sum(yards_gained) / qualifying quarterback dropbacks",
    "sack_rate": "sacks / qualifying quarterback dropbacks",
    "interception_rate": "interceptions / qualifying quarterback dropbacks",
    "air_yards": "mean(air_yards) on recorded pass attempts",
    "yards_after_catch": "mean(yards_after_catch) on recorded completions",
    "epa_per_rush": "mean(epa) over qualifying rushing attempts",
    "rush_success_rate": "count(epa > 0) / qualifying rushing attempts",
    "yards_per_rush": "sum(yards_gained) / qualifying rushing attempts",
    "explosive_run_rate": "count(yards_gained >= 10) / qualifying rushing attempts",
    "stuff_rate": "count(yards_gained <= 0) / qualifying rushing attempts",
    "rush_first_down_rate": "count(yards_gained >= yards_to_go) / qualifying rushing attempts",
    "epa_per_play": "mean(epa) over qualifying offensive rushes and quarterback dropbacks",
    "overall_success_rate": "count(epa > 0) / qualifying offensive plays",
    "overall_yards_per_play": "sum(yards_gained) / qualifying offensive plays",
    "turnover_rate": "count(interception or lost_fumble) / qualifying offensive plays",
}
METRIC_INTERPRETATIONS = {
    "epa_per_dropback": (
        "Positive values indicate that the offense added expected points on an average dropback; higher is generally better."
    ),
    "success_rate": "Higher values indicate that a larger share of dropbacks improved the offense's expected-points position.",
    "cpoe": "Positive values indicate completions above the model's expectation after accounting for throw difficulty.",
    "explosive_pass_rate": "Higher values indicate a larger share of dropbacks gained at least 20 yards, but do not measure consistency.",
    "yards_per_play": "Higher values indicate more yardage per qualifying dropback, without adjusting for game situation or opponent.",
    "sack_rate": "Lower values are generally better because fewer dropbacks ended in a sack.",
    "interception_rate": "Lower values are generally better because fewer dropbacks ended in an interception.",
    "air_yards": "Higher values indicate a deeper average target, but are not inherently better without efficiency and completion context.",
    "yards_after_catch": "Higher values indicate more yards after completed catches, combining receiver, scheme, and defensive effects.",
    "epa_per_rush": "Positive values indicate that the offense added expected points on an average rushing attempt.",
    "rush_success_rate": "Higher values indicate that a larger share of rushing attempts improved expected points.",
    "yards_per_rush": "Higher values indicate more rushing yardage per attempt, without adjusting for situation or opponent.",
    "explosive_run_rate": "Higher values indicate that a larger share of rushing attempts gained at least 10 yards.",
    "stuff_rate": "Lower values are generally better because fewer rushing attempts were stopped at or behind the line.",
    "rush_first_down_rate": "Higher values indicate that more rushing attempts converted the required yards for a first down.",
    "epa_per_play": "Positive values indicate that the offense added expected points on an average qualifying play.",
    "overall_success_rate": "Higher values indicate that a larger share of qualifying offensive plays improved expected points.",
    "overall_yards_per_play": "Higher values indicate more yardage per qualifying offensive play.",
    "turnover_rate": "Lower values are generally better because fewer qualifying plays ended in a turnover.",
}
HIGHER_IS_BETTER: dict[str, bool | None] = {
    metric: (
        False if metric in {"sack_rate", "interception_rate", "stuff_rate", "turnover_rate"} else None if metric == "air_yards" else True
    )
    for metric in METRICS
}

SPLIT_DIMENSIONS = {
    "down": ("Down", "Compare performance by down.", {"down"}),
    "distance": ("Distance", "Compare short, medium, and long yards-to-go situations.", {"ydstogo"}),
    "field_zone": ("Field zone", "Compare backed-up, open-field, and red-zone plays.", {"yardline_100"}),
    "score_state": ("Score state", "Compare plays while leading, tied, or trailing.", {"score_differential"}),
    "shotgun": ("Shotgun", "Compare shotgun and under-center usage.", {"shotgun"}),
    "no_huddle": ("No huddle", "Compare no-huddle and standard-tempo plays.", {"no_huddle"}),
    "personnel": ("Personnel", "Compare offensive personnel groupings.", {"offense_personnel"}),
    "formation": ("Formation", "Compare recorded offensive formations.", {"offense_formation"}),
}
SPLIT_COLUMNS = {value: f"_split_{value}" for value in SPLIT_DIMENSIONS}

WINDOW_SCHEMA = {
    "type": "object",
    "properties": {
        "season": {"type": "integer", "minimum": 1999},
        "weeks": {
            "type": "array",
            "prefixItems": [{"type": "integer", "minimum": 1}, {"type": "integer", "maximum": 22}],
            "minItems": 2,
            "maxItems": 2,
        },
    },
    "required": ["season", "weeks"],
    "additionalProperties": False,
}
TOOL_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_analysis_options": {"type": "object", "properties": {}, "additionalProperties": False},
    "compare_time_windows": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "analysis_domain": {"type": "string", "enum": ["passing", "rushing", "offense"]},
            "baseline": WINDOW_SCHEMA,
            "comparison": WINDOW_SCHEMA,
            "metrics": {"type": "array", "items": {"type": "string", "enum": list(METRICS)}},
            "season_type": {"type": "string", "enum": ["REG", "POST", "ALL"]},
        },
        "required": ["team", "analysis_domain", "baseline", "comparison", "metrics"],
        "additionalProperties": False,
    },
    "analyze_weekly_trends": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "windows": {"type": "array", "items": WINDOW_SCHEMA, "minItems": 1, "maxItems": 2},
            "metric": {"type": "string", "enum": list(METRICS)},
            "moving_average_weeks": {"type": "integer", "minimum": 2, "maximum": 6, "default": 3},
        },
        "required": ["team", "windows", "metric"],
        "additionalProperties": False,
    },
    "rank_game_outliers": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "window": WINDOW_SCHEMA,
            "metric": {"type": "string", "enum": list(METRICS)},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 6},
        },
        "required": ["team", "window", "metric"],
        "additionalProperties": False,
    },
    "benchmark_against_league": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "windows": {"type": "array", "items": WINDOW_SCHEMA, "minItems": 1, "maxItems": 2},
            "metrics": {"type": "array", "items": {"type": "string", "enum": list(METRICS)}},
        },
        "required": ["team", "windows", "metrics"],
        "additionalProperties": False,
    },
    "analyze_situational_split": {
        "type": "object",
        "properties": {
            "metric": {"type": "string", "enum": list(METRICS)},
            "splits": {"type": "array", "items": {"type": "string", "enum": list(SPLIT_DIMENSIONS)}},
            "minimum_subgroup_sample": {"type": "integer", "minimum": 10, "default": 10},
        },
        "required": ["metric", "splits"],
        "additionalProperties": False,
    },
    "find_representative_plays": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "window": WINDOW_SCHEMA,
            "supporting": {"type": "integer", "minimum": 0, "maximum": 10, "default": 3},
            "counterexamples": {"type": "integer", "minimum": 0, "maximum": 10, "default": 2},
            "minimum_absolute_epa": {"type": "number", "minimum": 0, "default": 0},
        },
        "required": ["team", "window"],
        "additionalProperties": False,
    },
    "explain_metric": {
        "type": "object",
        "properties": {"metric": {"type": "string", "enum": list(METRICS)}},
        "required": ["metric"],
        "additionalProperties": False,
    },
    "build_player_week_dataset": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "windows": {"type": "array", "items": WINDOW_SCHEMA, "minItems": 1, "maxItems": 2},
        },
        "required": ["team", "windows"],
        "additionalProperties": False,
    },
    "compare_player_usage": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "baseline": WINDOW_SCHEMA,
            "comparison": WINDOW_SCHEMA,
            "minimum_opportunities": {"type": "integer", "minimum": 1, "default": 5},
        },
        "required": ["team", "baseline", "comparison"],
        "additionalProperties": False,
    },
    "analyze_position_group_availability": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "baseline": WINDOW_SCHEMA,
            "comparison": WINDOW_SCHEMA,
        },
        "required": ["team", "baseline", "comparison"],
        "additionalProperties": False,
    },
    "analyze_lineup_continuity": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "baseline": WINDOW_SCHEMA,
            "comparison": WINDOW_SCHEMA,
        },
        "required": ["team", "baseline", "comparison"],
        "additionalProperties": False,
    },
    "decompose_lineup_continuity": {
        "type": "object",
        "properties": {
            "team": {"type": "string"},
            "baseline": WINDOW_SCHEMA,
            "comparison": WINDOW_SCHEMA,
        },
        "required": ["team", "baseline", "comparison"],
        "additionalProperties": False,
    },
}


@dataclass
class NFLAnalysisResult:
    aggregate_evidence: list[AggregateEvidence]
    play_evidence: list[PlayEvidence]
    charts: list[ChartArtifact]
    executions: list[ToolExecutionRecord]
    caveats: list[str]


def _sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _row_number(row: dict[str, Any], name: str) -> float | None:
    value = row.get(name)
    return float(value) if value is not None else None


def _row_integer(row: dict[str, Any], name: str) -> int | None:
    value = row.get(name)
    return int(value) if value is not None else None


def _row_boolean(row: dict[str, Any], name: str) -> bool | None:
    value = row.get(name)
    return bool(value) if value is not None else None


def _row_text(row: dict[str, Any], name: str) -> str | None:
    value = row.get(name)
    return str(value) if value not in (None, "") else None


def _row_text_list(row: dict[str, Any], name: str) -> list[str]:
    value = _row_text(row, name)
    return [item.strip() for item in value.split(";") if item.strip()] if value else []


def _present(frame: pl.DataFrame, name: str, default: Any = None) -> pl.Expr:
    return pl.col(name) if name in frame.columns else pl.lit(default)


def _first_column(frame: pl.DataFrame, *candidates: str) -> str | None:
    return next((candidate for candidate in candidates if candidate in frame.columns), None)


def _scope_plays(
    frame: pl.DataFrame,
    team: str,
    season_type: str,
    weeks: tuple[int, int],
    analysis_domain: str = "passing",
) -> pl.DataFrame:
    scoped = frame.filter(_present(frame, "posteam", "") == team)
    if season_type != "ALL" and "season_type" in scoped.columns:
        scoped = scoped.filter(pl.col("season_type") == season_type)
    if "week" in scoped.columns:
        scoped = scoped.filter(pl.col("week").is_between(weeks[0], weeks[1], closed="both"))
    if analysis_domain == "passing":
        qualifier = (
            _present(scoped, "qb_dropback", None) == 1 if "qb_dropback" in scoped.columns else _present(scoped, "play_type") == "pass"
        )
    elif analysis_domain == "rushing":
        qualifier = (
            _present(scoped, "rush_attempt", None) == 1 if "rush_attempt" in scoped.columns else _present(scoped, "play_type") == "run"
        )
        qualifier &= (_present(scoped, "qb_kneel", 0) != 1) & (_present(scoped, "qb_spike", 0) != 1)
    elif analysis_domain == "offense":
        dropback = (
            _present(scoped, "qb_dropback", None) == 1 if "qb_dropback" in scoped.columns else _present(scoped, "play_type") == "pass"
        )
        rush = _present(scoped, "rush_attempt", None) == 1 if "rush_attempt" in scoped.columns else _present(scoped, "play_type") == "run"
        qualifier = (dropback | rush) & (_present(scoped, "qb_kneel", 0) != 1) & (_present(scoped, "qb_spike", 0) != 1)
    else:
        raise ValueError(f"unsupported analysis domain: {analysis_domain}")
    scoped = scoped.filter(qualifier)
    distance = _present(scoped, "ydstogo", None).cast(pl.Float64, strict=False)
    yards = _present(scoped, "yards_gained", None).cast(pl.Float64, strict=False)
    yardline = _present(scoped, "yardline_100", None).cast(pl.Float64, strict=False)
    score = _present(scoped, "score_differential", None).cast(pl.Float64, strict=False)
    shotgun = _present(scoped, "shotgun", None).cast(pl.Int64, strict=False)
    no_huddle = _present(scoped, "no_huddle", None).cast(pl.Int64, strict=False)
    return scoped.with_columns(
        _present(scoped, "epa", None).cast(pl.Float64, strict=False).alias("_epa"),
        _present(scoped, "success", None).cast(pl.Float64, strict=False).alias("_success"),
        _present(scoped, "cpoe", None).cast(pl.Float64, strict=False).alias("_cpoe"),
        (_present(scoped, "yards_gained", 0).cast(pl.Float64, strict=False) >= 20).cast(pl.Float64).alias("_explosive"),
        _present(scoped, "yards_gained", None).cast(pl.Float64, strict=False).alias("_yards_gained"),
        _present(scoped, "sack", 0).cast(pl.Float64, strict=False).alias("_sack"),
        _present(scoped, "interception", 0).cast(pl.Float64, strict=False).alias("_interception"),
        _present(scoped, "air_yards", None).cast(pl.Float64, strict=False).alias("_air_yards"),
        _present(scoped, "yards_after_catch", None).cast(pl.Float64, strict=False).alias("_yards_after_catch"),
        (yards >= 10).cast(pl.Float64).alias("_explosive_run"),
        (yards <= 0).cast(pl.Float64).alias("_stuff"),
        (yards >= distance).cast(pl.Float64).alias("_first_down"),
        (
            (_present(scoped, "interception", 0).cast(pl.Int64, strict=False) == 1)
            | (_present(scoped, "fumble_lost", 0).cast(pl.Int64, strict=False) == 1)
        )
        .cast(pl.Float64)
        .alias("_turnover"),
        _present(scoped, "down", None).cast(pl.Utf8, strict=False).alias("_split_down"),
        pl.when(distance.is_null())
        .then(None)
        .when(distance <= 3)
        .then(pl.lit("short"))
        .when(distance <= 7)
        .then(pl.lit("medium"))
        .otherwise(pl.lit("long"))
        .alias("_split_distance"),
        pl.when(yardline.is_null())
        .then(None)
        .when(yardline <= 20)
        .then(pl.lit("red_zone"))
        .when(yardline >= 80)
        .then(pl.lit("backed_up"))
        .otherwise(pl.lit("open_field"))
        .alias("_split_field_zone"),
        pl.when(score.is_null())
        .then(None)
        .when(score > 0)
        .then(pl.lit("leading"))
        .when(score < 0)
        .then(pl.lit("trailing"))
        .otherwise(pl.lit("tied"))
        .alias("_split_score_state"),
        pl.when(shotgun.is_null())
        .then(None)
        .when(shotgun == 1)
        .then(pl.lit("shotgun"))
        .otherwise(pl.lit("under_center"))
        .alias("_split_shotgun"),
        pl.when(no_huddle.is_null())
        .then(None)
        .when(no_huddle == 1)
        .then(pl.lit("no_huddle"))
        .otherwise(pl.lit("standard_tempo"))
        .alias("_split_no_huddle"),
        _present(scoped, "offense_personnel", None).cast(pl.Utf8, strict=False).alias("_split_personnel"),
        _present(scoped, "offense_formation", None).cast(pl.Utf8, strict=False).alias("_split_formation"),
    )


def _metric_value(frame: pl.DataFrame, source: str) -> float | None:
    column = f"_{source}"
    if column not in frame.columns or frame[column].drop_nulls().len() == 0:
        return None
    # noinspection bad-argument-type
    return float(frame[column].drop_nulls().mean())


def _game_bootstrap(frame: pl.DataFrame, source: str, seed: int, iterations: int = 500) -> tuple[float | None, float | None]:
    column = f"_{source}"
    if "game_id" not in frame.columns or column not in frame.columns:
        return None, None
    games = frame.group_by("game_id").agg(pl.col(column).drop_nulls().mean().alias("value")).drop_nulls()
    values = games["value"].to_list()
    if len(values) < 3:
        return None, None
    population = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    samples = np.sort(population[rng.integers(0, len(population), size=(iterations, len(population)))].mean(axis=1))
    low_index = round(0.025 * (len(samples) - 1))
    high_index = round(0.975 * (len(samples) - 1))
    return samples[low_index], samples[high_index]


def _bootstrap_mean(values: list[float], seed: int, iterations: int = 500) -> tuple[float | None, float | None]:
    if len(values) < 10:
        return None, None
    population = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    samples = np.sort(population[rng.integers(0, len(population), size=(iterations, len(population)))].mean(axis=1))
    return samples[round(0.025 * (iterations - 1))], samples[round(0.975 * (iterations - 1))]


def _decomposition(
    baseline: pl.DataFrame,
    comparison: pl.DataFrame,
    dimension: str,
    manifests: list[DatasetManifest],
    execution_id: str,
    split_name: str,
    metric: str = "epa_per_dropback",
) -> list[AggregateEvidence]:
    if dimension not in baseline.columns or dimension not in comparison.columns:
        return []
    if baseline[dimension].is_not_null().mean() < 0.7 or comparison[dimension].is_not_null().mean() < 0.7:
        return []

    metric_column = f"_{METRICS[metric][0]}"
    if metric_column not in baseline.columns or metric_column not in comparison.columns:
        return []
    base = (
        baseline.filter(pl.col(dimension).is_not_null())
        .group_by(dimension)
        .agg(pl.len().alias("n"), pl.col(metric_column).mean().alias("metric_value"))
    )
    comp = (
        comparison.filter(pl.col(dimension).is_not_null())
        .group_by(dimension)
        .agg(pl.len().alias("n"), pl.col(metric_column).mean().alias("metric_value"))
    )
    if not base.height or not comp.height:
        return []

    joined = base.join(comp, on=dimension, how="inner", suffix="_comparison").filter((pl.col("n") >= 10) & (pl.col("n_comparison") >= 10))
    results = []
    for row in joined.sort(dimension).iter_rows(named=True):
        base_share = row["n"] / baseline.height
        comp_share = row["n_comparison"] / comparison.height
        performance = comp_share * (row["metric_value_comparison"] - row["metric_value"])
        mix = (comp_share - base_share) * row["metric_value"]
        payload = {
            "dimension": split_name,
            "metric": metric,
            "value": str(row[dimension]),
            "performance": performance,
            "mix": mix,
        }
        evidence_id = stable_id("evidence", payload)
        results.append(
            AggregateEvidence(
                evidence_id=evidence_id,
                metric=f"{metric}__{split_name}_decomposition",
                label=f"{SPLIT_DIMENSIONS[split_name][0]}: {row[dimension]}",
                value=round(performance + mix, 4),
                baseline_value=round(float(row["metric_value"]), 4),
                comparison_value=round(float(row["metric_value_comparison"]), 4),
                unit=f"{METRICS[metric][1]} contribution",
                sample_size=int(row["n_comparison"]),
                row_set_sha256=_sha(payload),
                dataset_manifest_ids=[item.manifest_id for item in manifests],
                tool_execution_id=execution_id,
                caveats=["Contributions within a dimension are descriptive and must not be summed across overlapping dimensions."],
            )
        )
    return sorted(results, key=lambda item: abs(float(item.value or 0)), reverse=True)[:8]


def _execution_record(
    tool: str,
    execution_id: str,
    parameters: dict[str, Any],
    evidence: list[AggregateEvidence] | list[PlayEvidence],
    manifests: list[DatasetManifest],
    started_at: datetime,
    started: float,
) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        execution_id=execution_id,
        tool=tool,
        parameters=parameters,
        started_at=started_at,
        duration_ms=int((perf_counter() - started) * 1000),
        result_sha256=_sha([item.model_dump(mode="json") for item in evidence]),
        dataset_manifest_ids=[item.manifest_id for item in manifests],
    )


def _opponent_adjusted_epa(frame: pl.DataFrame, target: pl.DataFrame, team: str) -> float | None:
    required = {"posteam", "defteam", "game_id", "epa"}
    if not required <= set(frame.columns) or not required <= set(target.columns):
        return None
    league = frame.filter((pl.col("posteam") != team) & pl.col("defteam").is_not_null() & pl.col("epa").is_not_null())
    opponent = (
        league.group_by("defteam")
        .agg(pl.col("epa").drop_nulls().mean().alias("expected"), pl.col("epa").drop_nulls().len().alias("opponent_n"))
        .filter(pl.col("opponent_n") >= 30)
    )
    actual = target.group_by("game_id", "defteam").agg(
        pl.col("_epa").drop_nulls().mean().alias("actual"),
        pl.col("_epa").drop_nulls().len().alias("weight"),
    )
    adjusted = actual.join(opponent, on="defteam", how="inner").drop_nulls(["actual", "expected"])
    if adjusted.is_empty():
        return None
    weighted = adjusted.select(
        ((pl.col("actual") - pl.col("expected")) * pl.col("weight")).sum().alias("weighted"),
        pl.col("weight").sum().alias("total"),
    ).row(0)
    return float(weighted[0] / weighted[1]) if weighted[1] else None
