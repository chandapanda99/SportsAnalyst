"""NFL metadata, tool schemas, and stateless analytical primitives."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any

import numpy as np
import polars as pl

from sports_analyst.datasets.nfl_catalog import LATEST_SYNCABLE_SEASON as LATEST_SYNCABLE_SEASON
from sports_analyst.models import (
    AggregateEvidence,
    ChartArtifact,
    DatasetManifest,
    PlayEvidence,
    ToolExecutionRecord,
    stable_id,
)

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
    # Defense: the opponent's dropbacks and rushes against the selected team.
    "epa_per_play_allowed": ("epa", "EPA/play allowed"),
    "success_rate_allowed": ("success", "Success rate allowed"),
    "epa_per_dropback_allowed": ("pass_epa", "EPA/dropback allowed"),
    "epa_per_rush_allowed": ("rush_epa", "EPA/rush allowed"),
    "yards_per_play_allowed": ("yards_gained", "Yards/play allowed"),
    "explosive_play_rate_allowed": ("explosive_play", "Explosive play rate allowed"),
    "defensive_sack_rate": ("dropback_sack", "Defensive sack rate"),
    "takeaway_rate": ("turnover", "Takeaway rate"),
    "run_stuff_rate": ("rush_stuff", "Run stuff rate"),
    "third_down_stop_rate": ("third_down_stop", "Third-down stop rate"),
}
DEFENSE_METRICS = [
    "epa_per_play_allowed",
    "success_rate_allowed",
    "epa_per_dropback_allowed",
    "epa_per_rush_allowed",
    "yards_per_play_allowed",
    "explosive_play_rate_allowed",
    "defensive_sack_rate",
    "takeaway_rate",
    "run_stuff_rate",
    "third_down_stop_rate",
]
DEFAULT_METRICS = ["epa_per_dropback", "success_rate", "cpoe", "explosive_pass_rate"]
DEFAULT_METRICS_BY_DOMAIN = {
    "passing": DEFAULT_METRICS,
    "rushing": ["epa_per_rush", "rush_success_rate", "yards_per_rush", "explosive_run_rate"],
    "offense": ["epa_per_play", "overall_success_rate", "overall_yards_per_play", "turnover_rate"],
    "defense": ["epa_per_play_allowed", "success_rate_allowed", "explosive_play_rate_allowed", "takeaway_rate"],
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
    **{metric: "defense" for metric in DEFENSE_METRICS},
}
DEFAULT_SPLITS = ["down", "field_zone", "score_state", "personnel", "formation"]
DEFAULT_SPLITS_BY_DOMAIN = {
    "defense": ["down", "field_zone", "score_state", "personnel", "man_zone", "pass_rush", "box_count", "defensive_personnel"],
}

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
    "epa_per_play_allowed": (
        "Defensive Efficiency",
        "Expected points the opponent added per dropback or rush against the defense.",
        {"epa", "qb_dropback", "rush_attempt"},
    ),
    "success_rate_allowed": (
        "Defensive Efficiency",
        "Share of opponent dropbacks and rushes that gained expected points.",
        {"success", "qb_dropback", "rush_attempt"},
    ),
    "epa_per_dropback_allowed": (
        "Defensive Efficiency",
        "Expected points the opponent added per quarterback dropback.",
        {"epa", "qb_dropback"},
    ),
    "epa_per_rush_allowed": (
        "Defensive Efficiency",
        "Expected points the opponent added per rushing attempt.",
        {"epa", "rush_attempt"},
    ),
    "yards_per_play_allowed": (
        "Defensive Production",
        "Average yards the opponent gained per dropback or rush.",
        {"yards_gained", "qb_dropback", "rush_attempt"},
    ),
    "explosive_play_rate_allowed": (
        "Defensive Production",
        "Share of opponent plays gaining 20+ yards on a dropback or 10+ yards on a rush.",
        {"yards_gained", "qb_dropback", "rush_attempt"},
    ),
    "defensive_sack_rate": ("Defensive Outcomes", "Share of opponent dropbacks ending in a sack.", {"sack", "qb_dropback"}),
    "takeaway_rate": (
        "Defensive Outcomes",
        "Share of opponent dropbacks and rushes ending in an interception or lost fumble.",
        {"interception", "qb_dropback", "rush_attempt"},
    ),
    "run_stuff_rate": (
        "Defensive Outcomes",
        "Share of opponent rushes stopped at or behind the line of scrimmage.",
        {"yards_gained", "rush_attempt"},
    ),
    "third_down_stop_rate": (
        "Defensive Outcomes",
        "Share of opponent third-down plays that did not gain a first down or score.",
        {"down", "first_down", "qb_dropback", "rush_attempt"},
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
    "epa_per_play_allowed": "mean(epa) over opponent rushes and quarterback dropbacks against the defense",
    "success_rate_allowed": "count(epa > 0) / opponent qualifying plays",
    "epa_per_dropback_allowed": "mean(epa) over opponent quarterback dropbacks",
    "epa_per_rush_allowed": "mean(epa) over opponent rushing attempts",
    "yards_per_play_allowed": "sum(yards_gained) / opponent qualifying plays",
    "explosive_play_rate_allowed": "count(dropback gaining >= 20 or rush gaining >= 10) / opponent qualifying plays",
    "defensive_sack_rate": "sacks / opponent quarterback dropbacks",
    "takeaway_rate": "count(interception or lost_fumble) / opponent qualifying plays",
    "run_stuff_rate": "count(yards_gained <= 0) / opponent rushing attempts",
    "third_down_stop_rate": "count(no first down and no touchdown) / opponent third-down plays",
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
    "epa_per_play_allowed": "Lower is better: negative values mean opponents lost expected points on an average play against the defense.",
    "success_rate_allowed": "Lower is better: a smaller share of opponent plays improved their expected-points position.",
    "epa_per_dropback_allowed": "Lower is better: opponents added fewer expected points per dropback against the pass defense.",
    "epa_per_rush_allowed": "Lower is better: opponents added fewer expected points per rush against the run defense.",
    "yards_per_play_allowed": "Lower is better, though yardage allowed is not adjusted for game situation or opponent.",
    "explosive_play_rate_allowed": "Lower is better: fewer opponent plays became big gains.",
    "defensive_sack_rate": "Higher is better: more opponent dropbacks ended in a sack. Sacks also reflect coverage and the quarterback.",
    "takeaway_rate": "Higher is better: more opponent plays ended in a turnover. Takeaways vary a lot from season to season.",
    "run_stuff_rate": "Higher is better: more opponent rushes were stopped at or behind the line.",
    "third_down_stop_rate": "Higher is better: more opponent third downs ended without a first down or score.",
}
LOWER_IS_BETTER_METRICS = {
    "sack_rate",
    "interception_rate",
    "stuff_rate",
    "turnover_rate",
    "epa_per_play_allowed",
    "success_rate_allowed",
    "epa_per_dropback_allowed",
    "epa_per_rush_allowed",
    "yards_per_play_allowed",
    "explosive_play_rate_allowed",
}
HIGHER_IS_BETTER: dict[str, bool | None] = {
    metric: False if metric in LOWER_IS_BETTER_METRICS else None if metric == "air_yards" else True for metric in METRICS
}

SPLIT_DIMENSIONS = {
    "down": ("Down", "Compare performance by down.", {"down"}),
    "distance": ("Distance", "Compare short, medium, and long yards-to-go situations.", {"ydstogo"}),
    "field_zone": ("Field zone", "Compare backed-up, open-field, and red-zone plays.", {"yardline_100"}),
    "score_state": ("Score state", "Compare plays while leading, tied, or trailing.", {"score_differential"}),
    "shotgun": ("Shotgun", "Compare shotgun and under-center usage.", {"shotgun"}),
    "no_huddle": ("No huddle", "Compare no-huddle and standard-tempo plays.", {"no_huddle"}),
    "personnel": (
        "Offensive personnel",
        "Compare offensive personnel groupings by running backs and tight ends (11 = one back, one tight end).",
        {"offense_personnel"},
    ),
    "formation": ("Formation", "Compare shotgun, pistol and under-center snaps.", {"offense_formation"}),
    # These come from the participation dataset, joined to plays by game and play.
    "man_zone": ("Man or zone", "Compare plays against man and zone coverage.", {"defense_man_zone_type"}),
    "pass_rush": ("Pass rushers", "Compare dropbacks with four or fewer rushers and with five or more.", {"number_of_pass_rushers"}),
    "box_count": ("Box count", "Compare light boxes (six or fewer defenders) with loaded boxes (seven or more).", {"defenders_in_box"}),
    "defensive_personnel": (
        "Defensive personnel",
        "Compare base (four defensive backs), nickel (five) and dime (six or more) groupings.",
        {"defense_personnel"},
    ),
}
SPLIT_COLUMNS = {value: f"_split_{value}" for value in SPLIT_DIMENSIONS}
PARTICIPATION_SPLITS = {"man_zone", "pass_rush", "box_count", "defensive_personnel"}
# Play-by-play files no longer carry these, so they are filled from participation when it is synced.
PARTICIPATION_FALLBACK_SPLITS = {"personnel", "formation"}

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
            "analysis_domain": {"type": "string", "enum": ["passing", "rushing", "offense", "defense"]},
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
    # Defense measures the opponent's plays against the team, so the team is the defending side.
    scoped = frame.filter(_present(frame, "defteam" if analysis_domain == "defense" else "posteam", "") == team)
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
    elif analysis_domain in {"offense", "defense"}:
        dropback = (
            _present(scoped, "qb_dropback", None) == 1 if "qb_dropback" in scoped.columns else _present(scoped, "play_type") == "pass"
        )
        rush = _present(scoped, "rush_attempt", None) == 1 if "rush_attempt" in scoped.columns else _present(scoped, "play_type") == "run"
        qualifier = (dropback | rush) & (_present(scoped, "qb_kneel", 0) != 1) & (_present(scoped, "qb_spike", 0) != 1)
    else:
        raise ValueError(f"unsupported analysis domain: {analysis_domain}")
    scoped = scoped.filter(qualifier)
    is_dropback = (
        (_present(scoped, "qb_dropback", None) == 1) if "qb_dropback" in scoped.columns else (_present(scoped, "play_type") == "pass")
    ).fill_null(False)
    is_rush = (
        (_present(scoped, "rush_attempt", None) == 1) if "rush_attempt" in scoped.columns else (_present(scoped, "play_type") == "run")
    ).fill_null(False)
    epa = _present(scoped, "epa", None).cast(pl.Float64, strict=False)
    converted = (_present(scoped, "first_down", 0).cast(pl.Int64, strict=False).fill_null(0) == 1) | (
        _present(scoped, "touchdown", 0).cast(pl.Int64, strict=False).fill_null(0) == 1
    )
    distance = _present(scoped, "ydstogo", None).cast(pl.Float64, strict=False)
    yards = _present(scoped, "yards_gained", None).cast(pl.Float64, strict=False)
    yardline = _present(scoped, "yardline_100", None).cast(pl.Float64, strict=False)
    score = _present(scoped, "score_differential", None).cast(pl.Float64, strict=False)
    shotgun = _present(scoped, "shotgun", None).cast(pl.Int64, strict=False)
    personnel = _offense_personnel_group(_present(scoped, "offense_personnel", None).cast(pl.Utf8, strict=False))
    formation = _formation_family(_present(scoped, "offense_formation", None).cast(pl.Utf8, strict=False))
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
        # Phase-specific sources: null outside their phase so the mean uses the right denominator.
        pl.when(is_dropback).then(epa).otherwise(None).alias("_pass_epa"),
        pl.when(is_rush).then(epa).otherwise(None).alias("_rush_epa"),
        pl.when(yards.is_null())
        .then(None)
        .otherwise(((is_dropback & (yards >= 20)) | (is_rush & (yards >= 10))).cast(pl.Float64))
        .alias("_explosive_play"),
        pl.when(is_dropback).then(_present(scoped, "sack", 0).cast(pl.Float64, strict=False)).otherwise(None).alias("_dropback_sack"),
        pl.when(is_rush & yards.is_not_null()).then((yards <= 0).cast(pl.Float64)).otherwise(None).alias("_rush_stuff"),
        pl.when(_present(scoped, "down", None).cast(pl.Int64, strict=False) == 3)
        .then((~converted).cast(pl.Float64))
        .otherwise(None)
        .alias("_third_down_stop"),
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
        personnel.alias("_split_personnel"),
        formation.alias("_split_formation"),
    )


def _position_count(personnel: pl.Expr, position: str) -> pl.Expr:
    return personnel.str.extract(rf"(?:^|, )(\d+) {position}(?:,|$)", 1).cast(pl.Int64, strict=False).fill_null(0)


def _offense_personnel_group(personnel: pl.Expr) -> pl.Expr:
    """Normalize personnel to the standard backs-and-tight-ends code ("11", "12", "21").

    Older participation lists skill players ("1 RB, 1 TE, 3 WR"); 2023 onward lists all eleven
    ("1 C, 2 G, 1 QB, 1 RB, 2 T, 1 TE, 3 WR"). A compact "11" passes through unchanged.
    """
    text = personnel.str.strip_chars()
    backs = _position_count(text, "RB") + _position_count(text, "FB") + _position_count(text, "HB")
    ends = _position_count(text, "TE")
    listed = text.str.contains(r"\d+ (?:RB|FB|HB|TE|WR)(?:,|$)")
    return (
        pl.when(text.str.contains(r"^\d\d$")).then(text)
        .when(listed & (backs <= 9) & (ends <= 9)).then(backs.cast(pl.Utf8) + ends.cast(pl.Utf8))
        .otherwise(None)
    )


def _formation_family(formation: pl.Expr) -> pl.Expr:
    """Map both participation vocabularies to shotgun, pistol and under center.

    Through 2022 the source names alignments (SINGLEBACK, I_FORM, EMPTY...); from 2023 it records only
    SHOTGUN, PISTOL and UNDER CENTER, so finer labels cannot be compared across that boundary.
    """
    value = formation.str.to_uppercase().str.replace_all(r"[ -]+", "_")
    return (
        pl.when(value.is_in(["SHOTGUN", "EMPTY"])).then(pl.lit("shotgun"))
        .when(value == "PISTOL").then(pl.lit("pistol"))
        .when(value.is_in(["UNDER_CENTER", "SINGLEBACK", "I_FORM", "JUMBO", "ACE"])).then(pl.lit("under center"))
        .when(value == "WILDCAT").then(pl.lit("wildcat"))
        .otherwise(None)
    )


def _secondary_count(personnel: pl.Expr) -> pl.Expr:
    """Count defensive backs in a participation personnel string such as "3 CB, 2 DE, 2 DT, 1 FS, 2 ILB, 1 SS"."""
    total = pl.lit(0)
    for position in ("CB", "FS", "SS", "S", "DB"):
        total = total + personnel.str.extract(rf"(\d+) {position}(?:,|$)", 1).cast(pl.Int64, strict=False).fill_null(0)
    return total


def attach_participation_splits(plays: pl.DataFrame, participation: pl.DataFrame | None) -> pl.DataFrame:
    """Join recorded coverage, rush, box and personnel context onto scoped plays as split columns.

    Rows without a participation match keep null splits, so a split drops out of the decomposition
    when too few plays were charted rather than treating uncharted plays as a category.
    """
    if participation is None or participation.is_empty() or not {"game_id", "play_id"} <= set(plays.columns):
        return plays
    game = _first_column(participation, "nflverse_game_id", "game_id")
    play = _first_column(participation, "nflverse_play_id", "play_id")
    wanted = [column for column in ("defense_man_zone_type", "number_of_pass_rushers", "defenders_in_box", "defense_personnel",
                                    "offense_personnel", "offense_formation")
              if column in participation.columns]
    if not game or not play or not wanted:
        return plays
    context = participation.select(
        pl.col(game).cast(pl.Utf8).alias("_join_game"),
        pl.col(play).cast(pl.Int64, strict=False).alias("_join_play"),
        *[pl.col(column).alias(f"_participation_{column}") for column in wanted],
    ).unique(subset=["_join_game", "_join_play"], keep="first")
    joined = plays.with_columns(
        pl.col("game_id").cast(pl.Utf8).alias("_join_game"),
        pl.col("play_id").cast(pl.Int64, strict=False).alias("_join_play"),
    ).join(context, on=["_join_game", "_join_play"], how="left")
    is_dropback = (
        (pl.col("qb_dropback") == 1) if "qb_dropback" in plays.columns else (_present(plays, "play_type") == "pass")
    ).fill_null(False)
    coverage = _present(joined, "_participation_defense_man_zone_type", None).cast(pl.Utf8, strict=False).str.to_uppercase()
    rushers = _present(joined, "_participation_number_of_pass_rushers", None).cast(pl.Int64, strict=False)
    box = _present(joined, "_participation_defenders_in_box", None).cast(pl.Int64, strict=False)
    secondary = _secondary_count(_present(joined, "_participation_defense_personnel", None).cast(pl.Utf8, strict=False))
    personnel = _offense_personnel_group(_present(joined, "_participation_offense_personnel", None).cast(pl.Utf8, strict=False))
    formation = _formation_family(_present(joined, "_participation_offense_formation", None).cast(pl.Utf8, strict=False))
    return joined.with_columns(
        # Participation is the charted source; play-by-play values (normalized in _scope_plays) are the fallback.
        pl.coalesce(personnel, _present(joined, "_split_personnel", None)).alias("_split_personnel"),
        pl.coalesce(formation, _present(joined, "_split_formation", None)).alias("_split_formation"),
        pl.when(coverage.str.contains("MAN")).then(pl.lit("man"))
        .when(coverage.str.contains("ZONE")).then(pl.lit("zone"))
        .otherwise(None).alias("_split_man_zone"),
        # Rusher counts are only charted on dropbacks; zero means "not charted" on runs.
        pl.when(~is_dropback | rushers.is_null() | (rushers <= 0) | (rushers > 11)).then(None)
        .when(rushers >= 5).then(pl.lit("5+ rushers"))
        .otherwise(pl.lit("4 or fewer rushers")).alias("_split_pass_rush"),
        pl.when(box.is_null() | (box <= 0) | (box > 11)).then(None)
        .when(box >= 7).then(pl.lit("7+ in box"))
        .otherwise(pl.lit("6 or fewer in box")).alias("_split_box_count"),
        pl.when(secondary <= 0).then(None)
        .when(secondary >= 6).then(pl.lit("dime"))
        .when(secondary == 5).then(pl.lit("nickel"))
        .when(secondary == 4).then(pl.lit("base"))
        .otherwise(pl.lit("heavy")).alias("_split_defensive_personnel"),
    ).drop("_join_game", "_join_play", *[f"_participation_{column}" for column in wanted])


def _metric_value(frame: pl.DataFrame, source: str) -> float | None:
    column = f"_{source}"
    if column not in frame.columns or frame[column].drop_nulls().len() == 0:
        return None
    # noinspection bad-argument-type
    values = frame[column].drop_nulls().to_list()
    # This value enters evidence identities: avoid order-sensitive floating accumulation.
    return math.fsum(values) / len(values)


def _game_bootstrap(frame: pl.DataFrame, source: str, seed: int, iterations: int = 500) -> tuple[float | None, float | None]:
    column = f"_{source}"
    if "game_id" not in frame.columns or column not in frame.columns:
        return None, None
    games = frame.group_by("game_id").agg(pl.col(column).drop_nulls().mean().alias("value")).drop_nulls().sort("game_id")
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
    # Resampling indices must refer to the same values regardless of input order.
    population = np.sort(np.asarray(values, dtype=float))
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
            # Identity precision excludes sub-picounit reduction noise, not source records.
            "performance": round(performance, 12),
            "mix": round(mix, 12),
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
    return sorted(results, key=lambda item: (-abs(float(item.value or 0)), item.evidence_id))[:8]


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


def _opponent_adjusted_epa(frame: pl.DataFrame, target: pl.DataFrame, team: str, side: str = "offense") -> float | None:
    """Average the team's per-game EPA minus what each opponent typically allows (offense) or produces (defense)."""
    required = {"posteam", "defteam", "game_id", "epa"}
    if not required <= set(frame.columns) or not required <= set(target.columns):
        return None
    # The opponent's baseline excludes its plays against this team; for defense it is the opposing offense.
    own, opponent_column = ("defteam", "posteam") if side == "defense" else ("posteam", "defteam")
    league = frame.filter((pl.col(own) != team) & pl.col(opponent_column).is_not_null() & pl.col("epa").is_not_null())
    if side == "defense":
        dropback = pl.col("qb_dropback") == 1 if "qb_dropback" in league.columns else _present(league, "play_type") == "pass"
        rush = pl.col("rush_attempt") == 1 if "rush_attempt" in league.columns else _present(league, "play_type") == "run"
        league = league.filter((dropback | rush).fill_null(False)
                               & (_present(league, "qb_kneel", 0).fill_null(0) != 1) & (_present(league, "qb_spike", 0).fill_null(0) != 1))
    opponent = (
        league.group_by(opponent_column)
        .agg(pl.col("epa").drop_nulls().mean().alias("expected"), pl.col("epa").drop_nulls().len().alias("opponent_n"))
        .filter(pl.col("opponent_n") >= 30)
    )
    actual = target.group_by("game_id", opponent_column).agg(
        pl.col("_epa").drop_nulls().mean().alias("actual"),
        pl.col("_epa").drop_nulls().len().alias("weight"),
    )
    adjusted = actual.join(opponent, on=opponent_column, how="inner").drop_nulls(["actual", "expected"])
    if adjusted.is_empty():
        return None
    weighted = adjusted.select(
        ((pl.col("actual") - pl.col("expected")) * pl.col("weight")).sum().alias("weighted"),
        pl.col("weight").sum().alias("total"),
    ).row(0)
    return float(weighted[0] / weighted[1]) if weighted[1] else None
