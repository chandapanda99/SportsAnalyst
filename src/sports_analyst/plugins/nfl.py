from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import polars as pl

from sports_analyst.models import (
    AggregateEvidence,
    AnalysisOptions,
    AnalysisPlan,
    AnalysisRequest,
    AnalysisWindow,
    ChartArtifact,
    ComparisonWindowOption,
    DatasetManifest,
    MetricDefinition,
    MetricOption,
    PlannedToolCall,
    PlayerOption,
    PlayEvidence,
    SplitDimensionOption,
    TeamOption,
    ToolDefinition,
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
}
DEFAULT_METRICS = ["epa_per_dropback", "success_rate", "cpoe", "explosive_pass_rate"]
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
}
HIGHER_IS_BETTER: dict[str, bool | None] = {
    metric: (False if metric in {"sack_rate", "interception_rate"} else None if metric == "air_yards" else True) for metric in METRICS
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
            "baseline": WINDOW_SCHEMA,
            "comparison": WINDOW_SCHEMA,
            "metrics": {"type": "array", "items": {"type": "string", "enum": list(METRICS)}},
            "season_type": {"type": "string", "enum": ["REG", "POST", "ALL"]},
        },
        "required": ["team", "baseline", "comparison", "metrics"],
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


def _present(frame: pl.DataFrame, name: str, default: Any = None) -> pl.Expr:
    return pl.col(name) if name in frame.columns else pl.lit(default)


def _first_column(frame: pl.DataFrame, *candidates: str) -> str | None:
    return next((candidate for candidate in candidates if candidate in frame.columns), None)


def _dropbacks(frame: pl.DataFrame, team: str, season_type: str, weeks: tuple[int, int]) -> pl.DataFrame:
    scoped = frame.filter(_present(frame, "posteam", "") == team)
    if season_type != "ALL" and "season_type" in scoped.columns:
        scoped = scoped.filter(pl.col("season_type") == season_type)
    if "week" in scoped.columns:
        scoped = scoped.filter(pl.col("week").is_between(weeks[0], weeks[1], closed="both"))
    if "qb_dropback" in scoped.columns:
        scoped = scoped.filter(pl.col("qb_dropback") == 1)
    elif "play_type" in scoped.columns:
        scoped = scoped.filter(pl.col("play_type").is_in(["pass", "qb_kneel", "qb_spike"]).not_())
    distance = _present(scoped, "ydstogo", None).cast(pl.Float64, strict=False)
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
    population = [float(value) for value in values]
    rng = random.Random(seed)
    samples = sorted(sum(rng.choice(population) for _ in population) / len(population) for _ in range(iterations))
    low_index = round(0.025 * (len(samples) - 1))
    high_index = round(0.975 * (len(samples) - 1))
    return samples[low_index], samples[high_index]


def _bootstrap_mean(values: list[float], seed: int, iterations: int = 500) -> tuple[float | None, float | None]:
    if len(values) < 10:
        return None, None
    rng = random.Random(seed)
    samples = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(iterations))
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
    values: list[tuple[float, int]] = []
    for game in target.select("game_id", "defteam").unique().iter_rows(named=True):
        game_plays = target.filter(pl.col("game_id") == game["game_id"])
        opponent_sample = league.filter((pl.col("defteam") == game["defteam"]) & (pl.col("game_id") != game["game_id"]))
        if opponent_sample.height < 30:
            continue
        actual = game_plays["_epa"].drop_nulls().mean()
        expected = opponent_sample["epa"].drop_nulls().mean()
        if actual is not None and expected is not None:
            values.append((float(actual - expected), game_plays.height))
    total = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / total if total else None


class NFLPlugin:
    sport_id = "nfl"
    display_name = "NFL"

    def tools(self) -> list[ToolDefinition]:
        tools = [
            ToolDefinition(
                name="get_analysis_options", description="Return valid teams, datasets, metrics, splits, and comparison windows."
            ),
            ToolDefinition(name="validate_analysis_scope", description="Validate entities, windows, fields, and sample requirements."),
            ToolDefinition(name="compare_time_windows", description="Compare versioned metrics across arbitrary season/week windows."),
            ToolDefinition(name="analyze_season_trends", description="Measure every season in an inclusive full-season range."),
            ToolDefinition(name="analyze_weekly_trends", description="Measure week-level trends and uncertainty within each window."),
            ToolDefinition(name="rank_game_outliers", description="Rank games that most exceeded or trailed the baseline expectation."),
            ToolDefinition(name="benchmark_against_league", description="Calculate league ranks and percentiles for requested metrics."),
            ToolDefinition(name="analyze_situational_split", description="Compare performance across a registered situational dimension."),
            ToolDefinition(name="find_representative_plays", description="Return supporting and counterexample plays for a diagnosis."),
            ToolDefinition(name="explain_metric", description="Return a metric definition, formula, qualifying rules, and limitations."),
            ToolDefinition(name="decompose_metric_change", description="Separate metric changes into mix and within-group performance."),
            ToolDefinition(name="adjust_for_opponents", description="Compare raw performance with leave-one-game-out opponent context."),
            ToolDefinition(name="analyze_game_state", description="Analyze performance while leading, tied, and trailing."),
            ToolDefinition(name="compare_play_mix", description="Measure changes in formation, personnel, tempo, and situational shares."),
            ToolDefinition(name="identify_change_points", description="Find descriptive week boundaries with the largest sustained shift."),
            ToolDefinition(name="resolve_player", description="Resolve a player name or identifier from synced play and roster data."),
            ToolDefinition(name="get_roster_context", description="Compare roster composition by position across windows."),
            ToolDefinition(
                name="analyze_starter_availability", description="Summarize injured, inactive, and limited-player availability."
            ),
            ToolDefinition(name="compare_player_usage", description="Compare player target and passing involvement across windows."),
            ToolDefinition(name="analyze_qb_receiver_pairs", description="Compare quarterback-receiver volume and efficiency."),
            ToolDefinition(name="summarize_injured_or_inactive_players", description="Rank players most frequently listed unavailable."),
            ToolDefinition(name="join_nextgen_passing_metrics", description="Compare synced Next Gen Stats passing measurements."),
            ToolDefinition(name="join_schedule_context", description="Add opponent, location, scoring-margin, and schedule context."),
            ToolDefinition(name="compare_passing_efficiency", description="Compatibility alias for compare_time_windows."),
            ToolDefinition(name="decompose_situational_splits", description="Compatibility alias for decompose_metric_change."),
            ToolDefinition(name="rank_representative_plays", description="Compatibility alias for find_representative_plays."),
            ToolDefinition(name="query_play_by_play", description="Run constrained read-only SQL against registered play-by-play views."),
        ]
        return [tool.model_copy(update={"input_schema": TOOL_INPUT_SCHEMAS.get(tool.name, tool.input_schema)}) for tool in tools]

    def analysis_options(self, manifests: list[DatasetManifest]) -> AnalysisOptions:
        available_seasons = sorted({manifest.season for manifest in manifests})

        def seasons_with(required: set[str]) -> list[int]:
            return sorted(manifest.season for manifest in manifests if required <= set(manifest.columns))

        metrics = [
            MetricOption(
                value=value,
                label=METRICS[value][1],
                category=METRIC_METADATA[value][0],
                description=METRIC_METADATA[value][1],
                available_seasons=seasons_with(METRIC_METADATA[value][2]),
            )
            for value in METRICS
        ]
        splits = [
            SplitDimensionOption(
                value=value,
                label=metadata[0],
                description=metadata[1],
                available_seasons=seasons_with(metadata[2]),
            )
            for value, metadata in SPLIT_DIMENSIONS.items()
        ]
        return AnalysisOptions(
            sport=self.sport_id,
            teams=[TeamOption(value=code, label=label) for code, label in NFL_TEAMS.items()],
            available_seasons=available_seasons,
            syncable_seasons=list(range(LATEST_SYNCABLE_SEASON, 1998, -1)),
            metrics=metrics,
            default_metrics=DEFAULT_METRICS,
            split_dimensions=splits,
            comparison_windows=[
                ComparisonWindowOption(
                    value="full_seasons",
                    label="Full season range",
                    description="Analyze every complete season from the selected start through end season.",
                ),
                ComparisonWindowOption(value="week_ranges", label="Custom week ranges", description="Compare two inclusive week ranges."),
                ComparisonWindowOption(
                    value="before_after",
                    label="Before vs. after",
                    description="Split one season around a selected week.",
                ),
            ],
            syncable_datasets=[
                "play_by_play",
                "player_stats",
                "rosters",
                "injuries",
                "schedules",
                "snap_counts",
                "nextgen_passing",
            ],
        )

    def explain_metric(self, metric: str) -> MetricDefinition:
        normalized = metric.strip().lower()
        if normalized not in METRICS:
            raise ValueError(f"unsupported metric {metric!r}")
        category, description, _required = METRIC_METADATA[normalized]
        return MetricDefinition(
            value=normalized,
            label=METRICS[normalized][1],
            category=category,
            description=description,
            formula=METRIC_FORMULAS[normalized],
            qualifying_plays="Team quarterback dropbacks within the selected season type and inclusive week window.",
            interpretation=METRIC_INTERPRETATIONS[normalized],
            higher_is_better=HIGHER_IS_BETTER[normalized],
            limitations=[
                "Missing source values are excluded from the metric mean or rate denominator.",
                "The metric is descriptive and does not by itself establish causality.",
            ],
        )

    def resolve_players(self, query: str, sources: list[tuple[int, pl.DataFrame]]) -> list[PlayerOption]:
        token = query.strip().lower()
        players: dict[str, dict[str, Any]] = {}
        for season, frame in sources:
            candidates = [
                ("gsis_id", "full_name", "team", "position"),
                ("player_id", "player_name", "recent_team", "position"),
                ("passer_player_id", "passer_player_name", "posteam", None),
                ("receiver_player_id", "receiver_player_name", "posteam", None),
            ]
            for id_column, name_column, team_column, position_column in candidates:
                if id_column not in frame.columns or name_column not in frame.columns:
                    continue
                selected_columns = [id_column, name_column]
                selected_columns.extend(column for column in (team_column, position_column) if column and column in frame.columns)
                for row in frame.select(selected_columns).drop_nulls([id_column, name_column]).unique().iter_rows(named=True):
                    player_id, name = str(row[id_column]), str(row[name_column])
                    if token and token not in player_id.lower() and token not in name.lower():
                        continue
                    record = players.setdefault(
                        player_id,
                        {"player_id": player_id, "name": name, "teams": set(), "positions": set(), "seasons": set()},
                    )
                    if team_column and row.get(team_column):
                        record["teams"].add(str(row[team_column]))
                    if position_column and row.get(position_column):
                        record["positions"].add(str(row[position_column]))
                    record["seasons"].add(season)
        return [
            PlayerOption(
                player_id=record["player_id"],
                name=record["name"],
                teams=sorted(record["teams"]),
                positions=sorted(record["positions"]),
                seasons=sorted(record["seasons"]),
            )
            for record in sorted(players.values(), key=lambda item: (item["name"], item["player_id"]))[:25]
        ]

    def resolve_team(self, team: str) -> str:
        token = team.strip().upper()
        resolved = TEAM_ALIASES.get(token, token)
        if not 2 <= len(resolved) <= 3:
            raise ValueError(f"could not resolve NFL team {team!r}")
        return resolved

    def default_plan(self, request: AnalysisRequest) -> AnalysisPlan:
        calls = [
            PlannedToolCall(
                tool="validate_analysis_scope",
                arguments={"scope": request.scope.model_dump(), "metrics": request.metrics, "splits": request.splits},
                purpose="Confirm that requested entities, windows, fields, and samples are valid.",
            ),
            PlannedToolCall(
                tool="compare_time_windows",
                arguments={
                    "metrics": request.metrics,
                    "splits": request.splits,
                    "baseline": request.scope.baseline.model_dump(),
                    "comparison": request.scope.comparison.model_dump(),
                },
                purpose="Measure the direction and size of the change.",
            ),
            PlannedToolCall(
                tool="analyze_season_trends" if request.scope.comparison_design == "full_seasons" else "analyze_weekly_trends",
                arguments={"metric": request.metrics[0] if request.metrics else DEFAULT_METRICS[0]},
                purpose=(
                    "Measure the trajectory across every season in the inclusive range."
                    if request.scope.comparison_design == "full_seasons"
                    else "Determine whether the change was sustained or concentrated in a few weeks."
                ),
            ),
            PlannedToolCall(
                tool="rank_game_outliers",
                arguments={"metric": request.metrics[0] if request.metrics else DEFAULT_METRICS[0]},
                purpose="Identify games that contributed most strongly to the comparison.",
            ),
            PlannedToolCall(
                tool="benchmark_against_league",
                arguments={"metrics": request.metrics or DEFAULT_METRICS},
                purpose="Place the team-level changes in league context.",
            ),
            PlannedToolCall(
                tool="decompose_metric_change",
                arguments={
                    "metric": request.metrics[0] if request.metrics else DEFAULT_METRICS[0],
                    "splits": request.splits or DEFAULT_SPLITS,
                },
                purpose="Separate situational mix changes from performance changes.",
            ),
            PlannedToolCall(
                tool="adjust_for_opponents",
                arguments={"metric": "epa_per_dropback"},
                purpose="Check whether opponent quality helps explain the result.",
            ),
            PlannedToolCall(
                tool="compare_play_mix",
                arguments={"splits": request.splits or DEFAULT_SPLITS},
                purpose="Measure how the offense's situational and structural mix changed.",
            ),
            PlannedToolCall(
                tool="identify_change_points",
                arguments={"metric": request.metrics[0] if request.metrics else DEFAULT_METRICS[0]},
                purpose="Locate candidate week boundaries for sustained changes.",
            ),
            PlannedToolCall(
                tool="compare_player_usage",
                arguments={"team": request.scope.team},
                purpose="Identify players whose involvement changed most.",
            ),
            PlannedToolCall(
                tool="analyze_qb_receiver_pairs",
                arguments={"team": request.scope.team},
                purpose="Measure changes in quarterback-receiver volume and efficiency.",
            ),
            PlannedToolCall(
                tool="analyze_starter_availability",
                arguments={"team": request.scope.team},
                purpose="Check whether recorded availability changed between windows when injury data is synced.",
            ),
            PlannedToolCall(
                tool="find_representative_plays",
                arguments={},
                purpose="Ground the diagnosis in source plays and counterexamples.",
            ),
        ]
        payload = {"question": request.question, "scope": request.scope.model_dump(), "calls": [item.model_dump() for item in calls]}
        return AnalysisPlan(plan_id=stable_id("plan", payload), question=request.question, scope=request.scope, calls=calls)

    def analyze(
            self,
            request: AnalysisRequest,
            datasets: dict[int, pl.DataFrame],
            manifests: dict[int, DatasetManifest],
            supplemental: dict[str, dict[int, pl.DataFrame]] | None = None,
            supplemental_manifests: dict[str, dict[int, DatasetManifest]] | None = None,
    ) -> NFLAnalysisResult:
        supplemental = supplemental or {}
        supplemental_manifests = supplemental_manifests or {}
        team = self.resolve_team(request.scope.team)
        seasons = request.scope.included_seasons
        endpoint_seasons = [request.scope.baseline_season, request.scope.comparison_season]
        missing = [season for season in seasons if season not in datasets]
        if missing:
            raise ValueError(f"missing synced seasons: {missing}")
        windows = [request.scope.baseline, request.scope.comparison]
        for window, frame in zip(windows, (datasets[endpoint_seasons[0]], datasets[endpoint_seasons[1]]), strict=True):
            if window.weeks != (1, 22) and "week" not in frame.columns:
                raise ValueError(f"season {window.season} does not contain the week field required for a custom window")
        baseline = _dropbacks(datasets[endpoint_seasons[0]], team, request.scope.season_type, windows[0].weeks)
        comparison = _dropbacks(datasets[endpoint_seasons[1]], team, request.scope.season_type, windows[1].weeks)
        if baseline.height < 30 or comparison.height < 30:
            raise ValueError("each comparison window requires at least 30 qualifying dropbacks")
        season_frames = (
            {season: _dropbacks(datasets[season], team, request.scope.season_type, (1, 22)) for season in seasons}
            if request.scope.comparison_design == "full_seasons"
            else None
        )
        if season_frames:
            undersized = [season for season, frame in season_frames.items() if frame.height < 30]
            if undersized:
                raise ValueError(f"each season in a full-season range requires at least 30 qualifying dropbacks: {undersized}")

        unknown_metrics = sorted(set(request.metrics) - set(METRICS))
        if unknown_metrics:
            raise ValueError(f"unsupported metrics: {unknown_metrics}")
        selected_metrics = request.metrics or DEFAULT_METRICS
        unknown_splits = sorted(set(request.splits) - set(SPLIT_DIMENSIONS))
        if unknown_splits:
            raise ValueError(f"unsupported split dimensions: {unknown_splits}")
        selected_splits = request.splits or DEFAULT_SPLITS

        selected_manifests = list({manifests[season].manifest_id: manifests[season] for season in seasons}.values())
        validation_parameters = {
            "team": team,
            "windows": [window.model_dump() for window in windows],
            "metrics": selected_metrics,
            "splits": selected_splits,
            "minimum_window_sample": 30,
        }
        validation_id = stable_id("execution", {"tool": "validate_analysis_scope", **validation_parameters})
        validation_started_at, validation_started = datetime.now(UTC), perf_counter()
        validation_execution = _execution_record(
            "validate_analysis_scope",
            validation_id,
            validation_parameters,
            [],
            selected_manifests,
            validation_started_at,
            validation_started,
        )
        started_at = datetime.now(UTC)
        start = perf_counter()
        execution_id = stable_id(
            "execution",
            {
                "tool": "compare_time_windows",
                "team": team,
                "windows": [window.model_dump() for window in windows],
                "metrics": selected_metrics,
                "splits": selected_splits,
            },
        )
        aggregate: list[AggregateEvidence] = []
        for index, metric in enumerate(selected_metrics):
            source, label = METRICS[metric]
            base_value = _metric_value(baseline, source)
            comp_value = _metric_value(comparison, source)
            if base_value is None or comp_value is None:
                continue
            low, high = _game_bootstrap(comparison, source, seed=endpoint_seasons[1] * 100 + index)
            payload = {
                "metric": metric,
                "team": team,
                "windows": [window.model_dump() for window in windows],
                "baseline": base_value,
                "comparison": comp_value,
            }
            caveats = []
            if min(baseline.height, comparison.height) < 100:
                caveats.append("The qualifying sample is under 100 plays; interpret the change cautiously.")
            aggregate.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric=metric,
                    label=label,
                    value=round(comp_value - base_value, 4),
                    baseline_value=round(base_value, 4),
                    comparison_value=round(comp_value, 4),
                    unit="rate" if "rate" in metric or metric in {"success_rate", "cpoe"} else "per play",
                    sample_size=comparison.height,
                    confidence_low=round(low, 4) if low is not None else None,
                    confidence_high=round(high, 4) if high is not None else None,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                    caveats=caveats,
                )
            )

        if not aggregate:
            raise ValueError(f"selected metrics are unavailable for the requested windows: {selected_metrics}")

        comparison_evidence = list(aggregate)
        comparison_execution = _execution_record(
            "compare_time_windows",
            execution_id,
            {
                "team": team,
                "baseline": windows[0].model_dump(),
                "comparison": windows[1].model_dump(),
                "metrics": selected_metrics,
            },
            comparison_evidence,
            selected_manifests,
            started_at,
            start,
        )
        executions = [validation_execution, comparison_execution]

        primary_metric = "epa_per_dropback" if "epa_per_dropback" in selected_metrics else selected_metrics[0]
        decomposition_parameters = {"metric": primary_metric, "splits": selected_splits}
        decomposition_id = stable_id("execution", {"tool": "decompose_metric_change", **decomposition_parameters})
        decomposition_started_at, decomposition_started = datetime.now(UTC), perf_counter()
        decomposition_evidence: list[AggregateEvidence] = []
        for split_name in (split for split in selected_splits if split != "score_state"):
            decomposition_evidence.extend(
                _decomposition(
                    baseline,
                    comparison,
                    SPLIT_COLUMNS[split_name],
                    selected_manifests,
                    decomposition_id,
                    split_name,
                    primary_metric,
                )
            )
        aggregate.extend(decomposition_evidence)
        executions.append(
            _execution_record(
                "decompose_metric_change",
                decomposition_id,
                decomposition_parameters,
                decomposition_evidence,
                selected_manifests,
                decomposition_started_at,
                decomposition_started,
            )
        )

        if "score_state" in selected_splits:
            game_state_parameters = {"metric": primary_metric, "split": "score_state"}
            game_state_id = stable_id("execution", {"tool": "analyze_game_state", **game_state_parameters})
            game_state_started_at, game_state_started = datetime.now(UTC), perf_counter()
            game_state_evidence = _decomposition(
                baseline,
                comparison,
                SPLIT_COLUMNS["score_state"],
                selected_manifests,
                game_state_id,
                "score_state",
                primary_metric,
            )
            aggregate.extend(game_state_evidence)
            executions.append(
                _execution_record(
                    "analyze_game_state",
                    game_state_id,
                    game_state_parameters,
                    game_state_evidence,
                    selected_manifests,
                    game_state_started_at,
                    game_state_started,
                )
            )

        adjusted_values = [
            _opponent_adjusted_epa(datasets[season], frame, team)
            for season, frame in zip(endpoint_seasons, (baseline, comparison), strict=True)
        ]
        opponent_evidence: list[AggregateEvidence] = []
        opponent_parameters = {"metric": "epa_per_dropback", "windows": [window.model_dump() for window in windows]}
        opponent_id = stable_id("execution", {"tool": "adjust_for_opponents", **opponent_parameters})
        opponent_started_at, opponent_started = datetime.now(UTC), perf_counter()
        if "epa_per_dropback" in selected_metrics and all(value is not None for value in adjusted_values):
            base_adjusted, comp_adjusted = (float(value) for value in adjusted_values if value is not None)
            payload = {
                "metric": "opponent_adjusted_epa_per_dropback",
                "team": team,
                "windows": [window.model_dump() for window in windows],
            }
            opponent_evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", {**payload, "values": adjusted_values}),
                    metric="opponent_adjusted_epa_per_dropback",
                    label="Opponent-adjusted EPA/dropback",
                    value=round(comp_adjusted - base_adjusted, 4),
                    baseline_value=round(base_adjusted, 4),
                    comparison_value=round(comp_adjusted, 4),
                    unit="EPA/dropback above opponent baseline",
                    sample_size=comparison.height,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=opponent_id,
                    caveats=["Opponent baselines exclude the target game and require at least 30 other defensive dropbacks."],
                )
            )
        aggregate.extend(opponent_evidence)
        executions.append(
            _execution_record(
                "adjust_for_opponents",
                opponent_id,
                opponent_parameters,
                opponent_evidence,
                selected_manifests,
                opponent_started_at,
                opponent_started,
            )
        )

        if season_frames:
            trend_evidence, trend_execution = self._season_trends(
                season_frames, selected_metrics, selected_manifests, team, request.scope.season_type
            )
        else:
            trend_evidence, trend_execution = self._weekly_trends([baseline, comparison], windows, primary_metric, selected_manifests)
        aggregate.extend(trend_evidence)
        executions.append(trend_execution)

        outlier_evidence, outlier_execution = self._game_outliers(baseline, comparison, windows[1], primary_metric, selected_manifests)
        aggregate.extend(outlier_evidence)
        executions.append(outlier_execution)

        benchmark_evidence, benchmark_execution = self._league_benchmarks(
            team, datasets, windows, request.scope.season_type, selected_metrics, selected_manifests
        )
        aggregate.extend(benchmark_evidence)
        executions.append(benchmark_execution)

        situational_evidence, situational_execution = self._situational_splits(
            baseline, comparison, primary_metric, selected_splits, selected_manifests
        )
        aggregate.extend(situational_evidence)
        executions.append(situational_execution)

        mix_evidence, mix_execution = self._play_mix(baseline, comparison, selected_splits, selected_manifests)
        aggregate.extend(mix_evidence)
        executions.append(mix_execution)

        change_evidence, change_execution = self._change_points(comparison, windows[1], primary_metric, selected_manifests)
        aggregate.extend(change_evidence)
        executions.append(change_execution)

        usage_evidence, usage_execution = self._player_usage(baseline, comparison, selected_manifests)
        aggregate.extend(usage_evidence)
        executions.append(usage_execution)

        pair_evidence, pair_execution = self._qb_receiver_pairs(baseline, comparison, selected_manifests)
        aggregate.extend(pair_evidence)
        executions.append(pair_execution)

        missing_supplemental: list[str] = []
        roster_result = self._roster_context(team, windows, supplemental.get("rosters", {}), supplemental_manifests.get("rosters", {}))
        if roster_result:
            roster_evidence, roster_execution = roster_result
            aggregate.extend(roster_evidence)
            executions.append(roster_execution)
        else:
            missing_supplemental.append("rosters")

        availability_result = self._availability_context(
            team, windows, supplemental.get("injuries", {}), supplemental_manifests.get("injuries", {})
        )
        if availability_result:
            availability_evidence, availability_executions = availability_result
            aggregate.extend(availability_evidence)
            executions.extend(availability_executions)
        else:
            missing_supplemental.append("injuries")

        nextgen_result = self._nextgen_context(
            team,
            windows,
            supplemental.get("nextgen_passing", {}),
            supplemental_manifests.get("nextgen_passing", {}),
        )
        if nextgen_result:
            nextgen_evidence, nextgen_execution = nextgen_result
            aggregate.extend(nextgen_evidence)
            executions.append(nextgen_execution)
        else:
            missing_supplemental.append("nextgen_passing")

        schedule_result = self._schedule_context(
            team, windows, supplemental.get("schedules", {}), supplemental_manifests.get("schedules", {})
        )
        if schedule_result:
            schedule_evidence, schedule_execution = schedule_result
            aggregate.extend(schedule_evidence)
            executions.append(schedule_execution)
        else:
            missing_supplemental.append("schedules")

        play_parameters = {
            "team": team,
            "window": windows[1].model_dump(),
            "supporting": 3,
            "counterexamples": 2,
            "minimum_absolute_epa": 0.0,
        }
        play_id = stable_id("execution", {"tool": "find_representative_plays", **play_parameters})
        play_started_at, play_started = datetime.now(UTC), perf_counter()
        plays = self._representative_plays(
            comparison,
            team,
            manifests[endpoint_seasons[1]],
            play_id,
            supporting_count=int(play_parameters["supporting"]),
            counterexample_count=int(play_parameters["counterexamples"]),
            minimum_absolute_epa=float(play_parameters["minimum_absolute_epa"]),
        )
        executions.append(
            _execution_record(
                "find_representative_plays",
                play_id,
                play_parameters,
                plays,
                selected_manifests,
                play_started_at,
                play_started,
            )
        )
        charts = self._charts(aggregate, baseline, comparison, windows, season_frames, primary_metric)
        caveats = [
            "The analysis is observational; football interpretations are not causal estimates.",
            "EPA and CPOE are nflverse model outputs and inherit their model assumptions.",
            "Formation and personnel conclusions are omitted when source fields or subgroup samples are insufficient.",
        ]
        if missing_supplemental:
            caveats.append(
                "Supplemental tools were skipped because these datasets were not synced for both windows: "
                + ", ".join(missing_supplemental)
                + "."
            )
        if season_frames:
            caveats.append(
                "Season-range trends include every selected season; situational decompositions, representative plays, and contextual "
                "diagnostics compare the range's first and final seasons."
            )
        return NFLAnalysisResult(aggregate, plays, charts, executions, caveats)

    def _season_trends(
            self,
            frames: dict[int, pl.DataFrame],
            metrics: list[str],
            manifests: list[DatasetManifest],
            team: str,
            season_type: str,
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"team": team, "season_type": season_type, "seasons": sorted(frames), "metrics": metrics}
        execution_id = stable_id("execution", {"tool": "analyze_season_trends", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        for season, frame in sorted(frames.items()):
            for index, metric in enumerate(metrics):
                source, label = METRICS[metric]
                value = _metric_value(frame, source)
                if value is None:
                    continue
                low, high = _game_bootstrap(frame, source, seed=season * 100 + index)
                payload = {"tool": "analyze_season_trends", "team": team, "season": season, "metric": metric}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"seasonal_{metric}",
                        label=f"{season} · {label}",
                        value=round(value, 4),
                        unit="rate" if "rate" in metric or metric in {"success_rate", "cpoe"} else "per play",
                        sample_size=frame.height,
                        confidence_low=round(low, 4) if low is not None else None,
                        confidence_high=round(high, 4) if high is not None else None,
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests if item.season == season],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("analyze_season_trends", execution_id, parameters, evidence, manifests, started_at, started)

    def _weekly_trends(
            self,
            frames: list[pl.DataFrame],
            windows: list[AnalysisWindow],
            metric: str,
            manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        moving_average_weeks = 3
        parameters = {
            "metric": metric,
            "windows": [window.model_dump() for window in windows],
            "moving_average_weeks": moving_average_weeks,
            "classification": "direction agreement across aligned weeks",
        }
        execution_id = stable_id("execution", {"tool": "analyze_weekly_trends", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        column = f"_{METRICS[metric][0]}"
        evidence: list[AggregateEvidence] = []
        window_series: list[list[dict[str, Any]]] = []
        for window, frame in zip(windows, frames, strict=True):
            if "week" not in frame.columns or column not in frame.columns:
                window_series.append([])
                continue
            weekly = frame.group_by("week").agg(pl.col(column).mean().alias("value"), pl.col(column).count().alias("n")).sort("week")
            rows = list(weekly.iter_rows(named=True))
            window_series.append(rows)
            for row_index, row in enumerate(rows):
                values = [float(value) for value in frame.filter(pl.col("week") == row["week"])[column].drop_nulls().to_list()]
                confidence_low, confidence_high = _bootstrap_mean(
                    values,
                    seed=window.season * 1000 + int(row["week"]) * 10 + list(METRICS).index(metric),
                )
                payload = {"tool": "analyze_weekly_trends", "metric": metric, "window": window.model_dump(), "week": row["week"]}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"weekly_{metric}",
                        label=f"{window.season} week {row['week']} · {METRICS[metric][1]}",
                        value=round(float(row["value"]), 4),
                        unit=METRICS[metric][1],
                        sample_size=int(row["n"]),
                        confidence_low=round(confidence_low, 4) if confidence_low is not None else None,
                        confidence_high=round(confidence_high, 4) if confidence_high is not None else None,
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=["Weekly subgroup has fewer than 10 plays."] if row["n"] < 10 else [],
                    )
                )
                if row_index + 1 >= moving_average_weeks:
                    moving_rows = rows[row_index + 1 - moving_average_weeks: row_index + 1]
                    moving_payload = {
                        "tool": "analyze_weekly_trends",
                        "kind": "moving_average",
                        "metric": metric,
                        "window": window.model_dump(),
                        "through_week": row["week"],
                        "weeks": [item["week"] for item in moving_rows],
                    }
                    evidence.append(
                        AggregateEvidence(
                            evidence_id=stable_id("evidence", moving_payload),
                            metric=f"weekly_moving_average_{metric}",
                            label=f"{window.season} through week {row['week']} · 3-week moving average",
                            value=round(sum(float(item["value"]) for item in moving_rows) / moving_average_weeks, 4),
                            unit=METRICS[metric][1],
                            sample_size=sum(int(item["n"]) for item in moving_rows),
                            row_set_sha256=_sha(moving_payload),
                            dataset_manifest_ids=[item.manifest_id for item in manifests if item.season == window.season],
                            tool_execution_id=execution_id,
                        )
                    )

        if len(window_series) == 2 and all(window_series):
            paired = list(zip(window_series[0], window_series[1], strict=False))
            baseline_mean = sum(float(left["value"]) for left, _right in paired) / len(paired)
            comparison_mean = sum(float(right["value"]) for _left, right in paired) / len(paired)
            overall_change = comparison_mean - baseline_mean
            agreements = [
                (float(right["value"]) - float(left["value"])) * overall_change > 0
                or (float(right["value"]) - float(left["value"]) == overall_change == 0)
                for left, right in paired
            ]
            agreement_rate = sum(agreements) / len(agreements)
            classification = "sustained" if agreement_rate >= 2 / 3 else "mixed" if agreement_rate >= 0.4 else "outlier-concentrated"
            trend_payload = {
                "tool": "analyze_weekly_trends",
                "kind": "classification",
                "metric": metric,
                "windows": [window.model_dump() for window in windows],
                "agreement_rate": agreement_rate,
                "classification": classification,
            }
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", trend_payload),
                    metric=f"weekly_trend_classification_{metric}",
                    label=f"Weekly change pattern: {classification}",
                    value=round(agreement_rate, 4),
                    baseline_value=round(baseline_mean, 4),
                    comparison_value=round(comparison_mean, 4),
                    unit="share of aligned weeks matching the overall direction",
                    sample_size=sum(int(right["n"]) for _left, right in paired),
                    row_set_sha256=_sha(trend_payload),
                    dataset_manifest_ids=[item.manifest_id for item in manifests],
                    tool_execution_id=execution_id,
                    caveats=[
                        "Weeks are aligned by their ordinal position within each window; this is descriptive, not a change-point test."
                    ],
                )
            )
        return evidence, _execution_record("analyze_weekly_trends", execution_id, parameters, evidence, manifests, started_at, started)

    def _game_outliers(
            self,
            baseline: pl.DataFrame,
            comparison: pl.DataFrame,
            window: AnalysisWindow,
            metric: str,
            manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"metric": metric, "comparison": window.model_dump(), "limit": 6}
        execution_id = stable_id("execution", {"tool": "rank_game_outliers", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        column = f"_{METRICS[metric][0]}"
        baseline_value = _metric_value(baseline, METRICS[metric][0])
        evidence: list[AggregateEvidence] = []
        if baseline_value is not None and {"game_id", column} <= set(comparison.columns):
            games = comparison.group_by("game_id").agg(pl.col(column).mean().alias("value"), pl.col(column).count().alias("n"))
            games = (
                games.with_columns((pl.col("value") - baseline_value).abs().alias("magnitude"))
                .sort(["magnitude", "game_id"], descending=[True, False])
                .head(6)
            )
            for row in games.iter_rows(named=True):
                payload = {"tool": "rank_game_outliers", "metric": metric, "game_id": row["game_id"], "window": window.model_dump()}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"game_outlier_{metric}",
                        label=f"{row['game_id']} · {METRICS[metric][1]}",
                        value=round(float(row["value"] - baseline_value), 4),
                        baseline_value=round(baseline_value, 4),
                        comparison_value=round(float(row["value"]), 4),
                        unit=f"difference from baseline-window {METRICS[metric][1]}",
                        sample_size=int(row["n"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=["Game sample has fewer than 10 qualifying plays."] if row["n"] < 10 else [],
                    )
                )
        return evidence, _execution_record("rank_game_outliers", execution_id, parameters, evidence, manifests, started_at, started)

    def _league_benchmarks(
            self,
            team: str,
            datasets: dict[int, pl.DataFrame],
            windows: list[AnalysisWindow],
            season_type: str,
            metrics: list[str],
            manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"team": team, "metrics": metrics, "windows": [window.model_dump() for window in windows]}
        execution_id = stable_id("execution", {"tool": "benchmark_against_league", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        for metric in metrics:
            summaries: list[dict[str, float | int] | None] = []
            for window in windows:
                raw = datasets[window.season]
                teams = raw["posteam"].drop_nulls().unique().to_list() if "posteam" in raw.columns else []
                values: dict[str, float] = {}
                counts: dict[str, int] = {}
                for candidate in teams:
                    scoped = _dropbacks(raw, str(candidate), season_type, window.weeks)
                    value = _metric_value(scoped, METRICS[metric][0])
                    if value is not None and scoped.height >= 30:
                        values[str(candidate)] = value
                        counts[str(candidate)] = scoped.height
                target = values.get(team)
                if target is None or not values:
                    summaries.append(None)
                    continue
                higher_is_better = HIGHER_IS_BETTER[metric] is not False
                ordered = sorted(values, key=values.get, reverse=higher_is_better)
                conference = TEAM_CONFERENCES.get(team)
                conference_values = {
                    candidate: value for candidate, value in values.items() if TEAM_CONFERENCES.get(candidate) == conference
                }
                conference_ordered = sorted(conference_values, key=conference_values.get, reverse=higher_is_better)
                percentile = 100 * sum(value <= target if higher_is_better else value >= target for value in values.values()) / len(values)
                summaries.append(
                    {
                        "league_percentile": percentile,
                        "league_rank": ordered.index(team) + 1,
                        "conference_rank": conference_ordered.index(team) + 1,
                        "league_average_delta": target - (sum(values.values()) / len(values)),
                        "sample": counts[team],
                        "league_teams": len(values),
                        "conference_teams": len(conference_values),
                    }
                )
            if not all(summary is not None for summary in summaries):
                continue
            baseline_summary, comparison_summary = (summary for summary in summaries if summary is not None)
            benchmark_kinds = [
                ("league_percentile", "league percentile", "percentile"),
                ("league_rank", "league rank", "rank (1 is best)"),
                ("conference_rank", f"{TEAM_CONFERENCES.get(team, 'conference')} rank", "rank (1 is best)"),
                ("league_average_delta", "distance from league average", METRICS[metric][1]),
            ]
            for kind, label, unit in benchmark_kinds:
                baseline_value = float(baseline_summary[kind])
                comparison_value = float(comparison_summary[kind])
                payload = {"tool": "benchmark_against_league", "metric": metric, "kind": kind, **parameters}
                population = (
                    int(comparison_summary["conference_teams"]) if kind == "conference_rank" else int(comparison_summary["league_teams"])
                )
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"{kind}_{metric}",
                        label=f"{METRICS[metric][1]} {label}",
                        value=round(comparison_value - baseline_value, 4),
                        baseline_value=round(baseline_value, 4),
                        comparison_value=round(comparison_value, 4),
                        unit=unit,
                        sample_size=int(comparison_summary["sample"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=[f"Benchmark includes {population} teams with at least 30 qualifying dropbacks."],
                    )
                )
        return evidence, _execution_record("benchmark_against_league", execution_id, parameters, evidence, manifests, started_at, started)

    def _situational_splits(
            self,
            baseline: pl.DataFrame,
            comparison: pl.DataFrame,
            metric: str,
            splits: list[str],
            manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"metric": metric, "splits": splits, "minimum_subgroup_sample": 10}
        execution_id = stable_id("execution", {"tool": "analyze_situational_split", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        metric_column = f"_{METRICS[metric][0]}"
        evidence: list[AggregateEvidence] = []
        for split in splits:
            split_column = SPLIT_COLUMNS[split]
            if {split_column, metric_column} - set(baseline.columns) or {split_column, metric_column} - set(comparison.columns):
                continue
            base = (
                baseline.filter(pl.col(split_column).is_not_null())
                .group_by(split_column)
                .agg(pl.col(metric_column).mean().alias("value"), pl.col(metric_column).count().alias("n"))
            )
            comp = (
                comparison.filter(pl.col(split_column).is_not_null())
                .group_by(split_column)
                .agg(pl.col(metric_column).mean().alias("value"), pl.col(metric_column).count().alias("n"))
            )
            joined = (
                base.join(comp, on=split_column, how="inner", suffix="_comparison")
                .filter((pl.col("n") >= 10) & (pl.col("n_comparison") >= 10))
                .sort(split_column)
            )
            for row in joined.iter_rows(named=True):
                payload = {
                    "tool": "analyze_situational_split",
                    "metric": metric,
                    "split": split,
                    "value": row[split_column],
                }
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"situational_{metric}__{split}",
                        label=f"{SPLIT_DIMENSIONS[split][0]}: {row[split_column]}",
                        value=round(float(row["value_comparison"] - row["value"]), 4),
                        baseline_value=round(float(row["value"]), 4),
                        comparison_value=round(float(row["value_comparison"]), 4),
                        unit=METRICS[metric][1],
                        sample_size=int(row["n_comparison"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("analyze_situational_split", execution_id, parameters, evidence, manifests, started_at, started)

    def _play_mix(
            self,
            baseline: pl.DataFrame,
            comparison: pl.DataFrame,
            splits: list[str],
            manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"splits": splits}
        execution_id = stable_id("execution", {"tool": "compare_play_mix", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        for split in splits:
            column = SPLIT_COLUMNS[split]
            if column not in baseline.columns or column not in comparison.columns:
                continue
            base = baseline.filter(pl.col(column).is_not_null()).group_by(column).len().rename({"len": "n"})
            comp = comparison.filter(pl.col(column).is_not_null()).group_by(column).len().rename({"len": "n"})
            joined = (
                base.join(comp, on=column, how="inner", suffix="_comparison")
                .filter((pl.col("n") >= 10) & (pl.col("n_comparison") >= 10))
                .sort(column)
            )
            for row in joined.iter_rows(named=True):
                baseline_share = row["n"] / baseline.height
                comparison_share = row["n_comparison"] / comparison.height
                payload = {"tool": "compare_play_mix", "split": split, "value": row[column]}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"play_mix_{split}",
                        label=f"{SPLIT_DIMENSIONS[split][0]} mix: {row[column]}",
                        value=round(comparison_share - baseline_share, 4),
                        baseline_value=round(baseline_share, 4),
                        comparison_value=round(comparison_share, 4),
                        unit="share of dropbacks",
                        sample_size=int(row["n_comparison"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("compare_play_mix", execution_id, parameters, evidence, manifests, started_at, started)

    def _change_points(
            self,
            frame: pl.DataFrame,
            window: AnalysisWindow,
            metric: str,
            manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"metric": metric, "window": window.model_dump()}
        execution_id = stable_id("execution", {"tool": "identify_change_points", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        column = f"_{METRICS[metric][0]}"
        if "week" in frame.columns and column in frame.columns:
            weekly = frame.group_by("week").agg(pl.col(column).mean().alias("value")).drop_nulls().sort("week")
            rows = list(weekly.iter_rows(named=True))
            candidates = []
            for index in range(2, len(rows) - 1):
                before = sum(float(row["value"]) for row in rows[:index]) / index
                after = sum(float(row["value"]) for row in rows[index:]) / (len(rows) - index)
                candidates.append((abs(after - before), index, before, after))
            if candidates:
                _magnitude, index, before, after = max(candidates)
                boundary = int(rows[index]["week"])
                payload = {"tool": "identify_change_points", "metric": metric, "window": window.model_dump(), "week": boundary}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"change_point_{metric}",
                        label=f"Candidate change point before week {boundary}",
                        value=round(after - before, 4),
                        baseline_value=round(before, 4),
                        comparison_value=round(after, 4),
                        unit=METRICS[metric][1],
                        sample_size=frame.height,
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=["The boundary is descriptive and was selected from the observed weekly series; it is not causal."],
                    )
                )
        return evidence, _execution_record("identify_change_points", execution_id, parameters, evidence, manifests, started_at, started)

    def _player_usage(
            self,
            baseline: pl.DataFrame,
            comparison: pl.DataFrame,
            manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"unit": "target_share", "minimum_targets": 5}
        execution_id = stable_id("execution", {"tool": "compare_player_usage", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        id_column = _first_column(comparison, "receiver_player_id", "receiver_id")
        name_column = _first_column(comparison, "receiver_player_name", "receiver_name")
        baseline_id = _first_column(baseline, "receiver_player_id", "receiver_id")
        baseline_name = _first_column(baseline, "receiver_player_name", "receiver_name")
        if name_column and baseline_name:
            join_column = "player_key"

            def usage(frame: pl.DataFrame, player_id: str | None, player_name: str) -> pl.DataFrame:
                key = pl.col(player_id).cast(pl.Utf8) if player_id else pl.col(player_name).cast(pl.Utf8)
                return (
                    frame.filter(pl.col(player_name).is_not_null())
                    .with_columns(key.alias(join_column), pl.col(player_name).cast(pl.Utf8).alias("player_name"))
                    .group_by(join_column)
                    .agg(pl.first("player_name"), pl.len().alias("targets"), pl.col("_epa").mean().alias("epa"))
                )

            base = usage(baseline, baseline_id, baseline_name)
            comp = usage(comparison, id_column, name_column)
            joined = base.join(comp, on=join_column, how="inner", suffix="_comparison").filter(
                (pl.col("targets") >= 5) | (pl.col("targets_comparison") >= 5)
            )
            rows = []
            for row in joined.iter_rows(named=True):
                baseline_share = row["targets"] / baseline.height
                comparison_share = row["targets_comparison"] / comparison.height
                rows.append((abs(comparison_share - baseline_share), row, baseline_share, comparison_share))
            for _magnitude, row, baseline_share, comparison_share in sorted(rows, key=lambda item: (-item[0], item[1][join_column]))[:8]:
                payload = {"tool": "compare_player_usage", "player": row[join_column]}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric="receiver_target_share",
                        label=f"{row.get('player_name_comparison') or row['player_name']} target share",
                        value=round(comparison_share - baseline_share, 4),
                        baseline_value=round(baseline_share, 4),
                        comparison_value=round(comparison_share, 4),
                        unit="share of team dropbacks",
                        sample_size=int(row["targets_comparison"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("compare_player_usage", execution_id, parameters, evidence, manifests, started_at, started)

    def _qb_receiver_pairs(
            self,
            baseline: pl.DataFrame,
            comparison: pl.DataFrame,
            manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"metric": "epa_per_target", "minimum_targets": 5}
        execution_id = stable_id("execution", {"tool": "analyze_qb_receiver_pairs", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        passer = _first_column(comparison, "passer_player_name", "passer_name")
        receiver = _first_column(comparison, "receiver_player_name", "receiver_name")
        base_passer = _first_column(baseline, "passer_player_name", "passer_name")
        base_receiver = _first_column(baseline, "receiver_player_name", "receiver_name")
        if passer and receiver and base_passer and base_receiver:

            def pairs(frame: pl.DataFrame, qb: str, target: str) -> pl.DataFrame:
                return (
                    frame.filter(pl.col(qb).is_not_null() & pl.col(target).is_not_null())
                    .with_columns(
                        pl.col(qb).cast(pl.Utf8).alias("quarterback"),
                        pl.col(target).cast(pl.Utf8).alias("receiver"),
                    )
                    .group_by("quarterback", "receiver")
                    .agg(pl.len().alias("targets"), pl.col("_epa").mean().alias("epa"))
                )

            joined = (
                pairs(baseline, base_passer, base_receiver)
                .join(pairs(comparison, passer, receiver), on=["quarterback", "receiver"], how="inner", suffix="_comparison")
                .filter((pl.col("targets") >= 5) | (pl.col("targets_comparison") >= 5))
            )
            rows = sorted(
                joined.iter_rows(named=True),
                key=lambda row: (-int(row["targets_comparison"]), row["quarterback"], row["receiver"]),
            )[:8]
            for row in rows:
                payload = {"tool": "analyze_qb_receiver_pairs", "qb": row["quarterback"], "receiver": row["receiver"]}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric="qb_receiver_epa_per_target",
                        label=f"{row['quarterback']} → {row['receiver']}",
                        value=round(float(row["epa_comparison"] - row["epa"]), 4),
                        baseline_value=round(float(row["epa"]), 4),
                        comparison_value=round(float(row["epa_comparison"]), 4),
                        unit="EPA/target",
                        sample_size=int(row["targets_comparison"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("analyze_qb_receiver_pairs", execution_id, parameters, evidence, manifests, started_at, started)

    def _roster_context(
            self,
            team: str,
            windows: list[AnalysisWindow],
            frames: dict[int, pl.DataFrame],
            manifests: dict[int, DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
        parameters = {"team": team, "windows": [window.model_dump() for window in windows]}
        execution_id = stable_id("execution", {"tool": "get_roster_context", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        counts: list[dict[str, int]] = []
        for window in windows:
            frame = frames[window.season]
            team_column = _first_column(frame, "team", "team_abbr", "recent_team")
            position_column = _first_column(frame, "position", "position_group")
            if not team_column or not position_column:
                counts.append({})
                continue
            scoped = frame.filter(pl.col(team_column) == team)
            counts.append(
                {str(row[position_column]): int(row["n"]) for row in scoped.group_by(position_column).len(name="n").iter_rows(named=True)}
            )
        evidence: list[AggregateEvidence] = []
        for position in sorted(set(counts[0]) | set(counts[1])):
            baseline_count, comparison_count = counts[0].get(position, 0), counts[1].get(position, 0)
            payload = {"tool": "get_roster_context", "team": team, "position": position, "windows": parameters["windows"]}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric="roster_count_by_position",
                    label=f"{position} roster count",
                    value=comparison_count - baseline_count,
                    baseline_value=baseline_count,
                    comparison_value=comparison_count,
                    unit="players",
                    sample_size=comparison_count,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                )
            )
        return evidence, _execution_record(
            "get_roster_context", execution_id, parameters, evidence, selected_manifests, started_at, started
        )

    def _availability_context(
            self,
            team: str,
            windows: list[AnalysisWindow],
            frames: dict[int, pl.DataFrame],
            manifests: dict[int, DatasetManifest],
    ) -> tuple[list[AggregateEvidence], list[ToolExecutionRecord]] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
        parameters = {"team": team, "windows": [window.model_dump() for window in windows]}
        availability_id = stable_id("execution", {"tool": "analyze_starter_availability", **parameters})
        summary_id = stable_id("execution", {"tool": "summarize_injured_or_inactive_players", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        unavailable: list[list[str]] = []
        for window in windows:
            frame = frames[window.season]
            team_column = _first_column(frame, "team", "team_abbr", "recent_team")
            week_column = _first_column(frame, "week")
            status_column = _first_column(frame, "report_status", "game_status", "practice_status", "status")
            name_column = _first_column(frame, "full_name", "player_name", "player_display_name")
            if not team_column or not status_column or not name_column:
                unavailable.append([])
                continue
            scoped = frame.filter(pl.col(team_column) == team)
            if week_column:
                scoped = scoped.filter(pl.col(week_column).is_between(window.weeks[0], window.weeks[1], closed="both"))
            scoped = scoped.filter(pl.col(status_column).cast(pl.Utf8).str.to_uppercase().str.contains("OUT|DOUBTFUL|INACTIVE|RESERVE|IR"))
            unavailable.append([str(value) for value in scoped[name_column].drop_nulls().to_list()])
        evidence: list[AggregateEvidence] = []
        availability_payload = {"tool": "analyze_starter_availability", **parameters}
        evidence.append(
            AggregateEvidence(
                evidence_id=stable_id("evidence", availability_payload),
                metric="unavailable_player_reports",
                label="Unavailable player reports",
                value=len(unavailable[1]) - len(unavailable[0]),
                baseline_value=len(unavailable[0]),
                comparison_value=len(unavailable[1]),
                unit="player-week reports",
                sample_size=len(unavailable[1]),
                row_set_sha256=_sha(availability_payload),
                dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                tool_execution_id=availability_id,
                caveats=["Injury reports describe listed availability and do not establish performance impact."],
            )
        )
        from collections import Counter

        base_counts, comparison_counts = Counter(unavailable[0]), Counter(unavailable[1])
        player_evidence: list[AggregateEvidence] = []
        for player, count in sorted(comparison_counts.items(), key=lambda item: (-item[1], item[0]))[:8]:
            payload = {"tool": "summarize_injured_or_inactive_players", "player": player, **parameters}
            player_evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric="player_unavailable_reports",
                    label=f"{player} unavailable reports",
                    value=count - base_counts.get(player, 0),
                    baseline_value=base_counts.get(player, 0),
                    comparison_value=count,
                    unit="player-week reports",
                    sample_size=count,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=summary_id,
                )
            )
        evidence.extend(player_evidence)
        records = [
            _execution_record(
                "analyze_starter_availability",
                availability_id,
                parameters,
                evidence[:1],
                selected_manifests,
                started_at,
                started,
            ),
            _execution_record(
                "summarize_injured_or_inactive_players",
                summary_id,
                parameters,
                player_evidence,
                selected_manifests,
                started_at,
                started,
            ),
        ]
        return evidence, records

    def _nextgen_context(
            self,
            team: str,
            windows: list[AnalysisWindow],
            frames: dict[int, pl.DataFrame],
            manifests: dict[int, DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
        parameters = {"team": team, "windows": [window.model_dump() for window in windows]}
        execution_id = stable_id("execution", {"tool": "join_nextgen_passing_metrics", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        metric_candidates = {
            "avg_time_to_throw": "Average time to throw",
            "avg_completed_air_yards": "Completed air yards",
            "aggressiveness": "Aggressiveness",
            "completion_percentage_above_expectation": "NGS CPOE",
            "avg_air_yards_differential": "Air-yards differential",
        }
        summaries: list[dict[str, tuple[float, int]]] = []
        for window in windows:
            frame = frames[window.season]
            team_column = _first_column(frame, "team_abbr", "team", "recent_team")
            week_column = _first_column(frame, "week", "week_number")
            if not team_column:
                summaries.append({})
                continue
            scoped = frame.filter(pl.col(team_column) == team)
            if week_column:
                scoped = scoped.filter(pl.col(week_column).is_between(window.weeks[0], window.weeks[1], closed="both"))
            summary: dict[str, tuple[float, int]] = {}
            for metric in metric_candidates:
                if metric not in scoped.columns or not scoped[metric].drop_nulls().len():
                    continue
                summary[metric] = (float(scoped[metric].drop_nulls().mean()), scoped[metric].drop_nulls().len())
            summaries.append(summary)
        evidence: list[AggregateEvidence] = []
        for metric in sorted(set(summaries[0]) & set(summaries[1])):
            baseline_value, _baseline_n = summaries[0][metric]
            comparison_value, comparison_n = summaries[1][metric]
            payload = {"tool": "join_nextgen_passing_metrics", "metric": metric, **parameters}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric=f"nextgen_{metric}",
                    label=metric_candidates[metric],
                    value=round(comparison_value - baseline_value, 4),
                    baseline_value=round(baseline_value, 4),
                    comparison_value=round(comparison_value, 4),
                    unit="NGS published value",
                    sample_size=comparison_n,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                )
            )
        return evidence, _execution_record(
            "join_nextgen_passing_metrics", execution_id, parameters, evidence, selected_manifests, started_at, started
        )

    def _schedule_context(
            self,
            team: str,
            windows: list[AnalysisWindow],
            frames: dict[int, pl.DataFrame],
            manifests: dict[int, DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
        parameters = {"team": team, "windows": [window.model_dump() for window in windows]}
        execution_id = stable_id("execution", {"tool": "join_schedule_context", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        summaries: list[tuple[float | None, int, int]] = []
        for window in windows:
            frame = frames[window.season]
            required = {"home_team", "away_team", "home_score", "away_score"}
            if not required <= set(frame.columns):
                summaries.append((None, 0, 0))
                continue
            scoped = frame.filter((pl.col("home_team") == team) | (pl.col("away_team") == team))
            if "week" in scoped.columns:
                scoped = scoped.filter(pl.col("week").is_between(window.weeks[0], window.weeks[1], closed="both"))
            scoped = scoped.with_columns(
                pl.when(pl.col("home_team") == team)
                .then(pl.col("home_score") - pl.col("away_score"))
                .otherwise(pl.col("away_score") - pl.col("home_score"))
                .cast(pl.Float64, strict=False)
                .alias("team_margin")
            )
            margin = scoped["team_margin"].drop_nulls().mean()
            summaries.append(
                (float(margin) if margin is not None else None, scoped.height, scoped.filter(pl.col("home_team") == team).height)
            )
        evidence: list[AggregateEvidence] = []
        if summaries[0][0] is not None and summaries[1][0] is not None:
            payload = {"tool": "join_schedule_context", "metric": "average_scoring_margin", **parameters}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric="schedule_average_scoring_margin",
                    label="Average scoring margin",
                    value=round(float(summaries[1][0] - summaries[0][0]), 3),
                    baseline_value=round(float(summaries[0][0]), 3),
                    comparison_value=round(float(summaries[1][0]), 3),
                    unit="points/game",
                    sample_size=summaries[1][1],
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                )
            )
        return evidence, _execution_record(
            "join_schedule_context", execution_id, parameters, evidence, selected_manifests, started_at, started
        )

    def _representative_plays(
            self,
            frame: pl.DataFrame,
            team: str,
            manifest: DatasetManifest,
            execution_id: str,
            supporting_count: int = 3,
            counterexample_count: int = 2,
            minimum_absolute_epa: float = 0,
    ) -> list[PlayEvidence]:
        required = {"game_id", "play_id", "_epa"}
        if not required <= set(frame.columns):
            return []
        candidates = frame.filter(pl.col("_epa").is_not_null() & (pl.col("_epa").abs() >= minimum_absolute_epa))
        supporting = candidates.sort(["_epa", "game_id", "play_id"], descending=[True, False, False]).head(supporting_count)
        counterexamples = candidates.sort(["_epa", "game_id", "play_id"], descending=[False, False, False]).head(counterexample_count)
        selected = pl.concat([supporting, counterexamples]).unique(["game_id", "play_id"], keep="first", maintain_order=True)
        records = []
        for index, row in enumerate(selected.iter_rows(named=True)):
            payload = {"season": manifest.season, "game_id": row["game_id"], "play_id": row["play_id"]}
            records.append(
                PlayEvidence(
                    evidence_id=stable_id("play", payload),
                    season=manifest.season,
                    game_id=str(row["game_id"]),
                    play_id=int(row["play_id"]),
                    team=team,
                    description=str(row.get("desc") or "Play description unavailable"),
                    epa=round(float(row["_epa"]), 4) if row["_epa"] is not None else None,
                    supporting=index < supporting.height,
                    dataset_manifest_id=manifest.manifest_id,
                    tool_execution_id=execution_id,
                )
            )
        return records

    def _charts(
            self,
            evidence: list[AggregateEvidence],
            baseline: pl.DataFrame,
            comparison: pl.DataFrame,
            windows: list[AnalysisWindow],
            season_frames: dict[int, pl.DataFrame] | None = None,
            primary_metric: str = "epa_per_dropback",
    ) -> list[ChartArtifact]:
        window_labels = [f"{window.season} W{window.weeks[0]}–{window.weeks[1]}" for window in windows]
        metric_items = [item for item in evidence if item.metric in METRICS]
        if season_frames:
            values = [
                {"metric": item.label, "season": season, "value": _metric_value(frame, METRICS[item.metric][0])}
                for item in metric_items
                for season, frame in sorted(season_frames.items())
            ]
            series_field = "season"
            chart_title = "All seasons · Passing efficiency comparison"
            chart_evidence_ids = [item.evidence_id for item in evidence if item.metric.startswith("seasonal_")]
        else:
            values = [
                record
                for item in metric_items
                for record in (
                    {"metric": item.label, "window": window_labels[0], "value": item.baseline_value},
                    {"metric": item.label, "window": window_labels[1], "value": item.comparison_value},
                )
            ]
            series_field = "window"
            chart_title = "Passing efficiency comparison"
            chart_evidence_ids = [item.evidence_id for item in metric_items]
        comparison_chart = ChartArtifact(
            chart_id=stable_id(
                "chart",
                {
                    "type": "season-metric-comparison" if season_frames else "metric-comparison",
                    "windows": [window.model_dump() for window in windows],
                },
            ),
            title=chart_title,
            specification={
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {"values": values},
                "mark": {"type": "bar", "cornerRadiusEnd": 3},
                "encoding": {
                    "x": {"field": "metric", "type": "nominal", "sort": None, "axis": {"labelAngle": -25}},
                    "y": {"field": "value", "type": "quantitative"},
                    "color": {"field": series_field, "type": "nominal", "sort": "ascending"},
                    "xOffset": {"field": series_field, "sort": "ascending"},
                    "tooltip": [{"field": "metric"}, {"field": series_field}, {"field": "value", "format": ".3f"}],
                },
            },
            evidence_ids=chart_evidence_ids,
        )
        if season_frames:
            source, label = METRICS[primary_metric]
            seasonal_values = [
                {"series": label, "season": season, "value": _metric_value(frame, source)}
                for season, frame in sorted(season_frames.items())
            ]
            seasonal_evidence = [item for item in evidence if item.metric == f"seasonal_{primary_metric}"]
            season_trend = ChartArtifact(
                chart_id=stable_id(
                    "chart",
                    {"type": "season-range-trend", "seasons": sorted(season_frames), "metric": primary_metric},
                ),
                title=f"Season-by-season {label}",
                specification={
                    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                    "data": {"values": seasonal_values},
                    "mark": {"type": "line", "point": True},
                    "encoding": {
                        "x": {
                            "field": "season",
                            "type": "ordinal",
                            "sort": "ascending",
                            "axis": {"labelAngle": 0, "title": "Season"},
                        },
                        "y": {"field": "value", "type": "quantitative", "axis": {"title": label}},
                        "color": {"field": "series", "type": "nominal", "legend": None},
                        "tooltip": [
                            {"field": "season", "type": "ordinal"},
                            {"field": "value", "title": label, "format": ".3f"},
                        ],
                    },
                },
                evidence_ids=[item.evidence_id for item in seasonal_evidence],
            )
            return [comparison_chart, season_trend]

        weekly_values = []
        for label, frame in zip(window_labels, (baseline, comparison), strict=True):
            if "week" in frame.columns:
                for row in frame.group_by("week").agg(pl.col("_epa").mean().alias("epa")).sort("week").iter_rows(named=True):
                    weekly_values.append({"window": label, "week": row["week"], "epa": row["epa"]})
        trend = ChartArtifact(
            chart_id=stable_id("chart", {"type": "weekly-trend", "windows": [window.model_dump() for window in windows]}),
            title="Weekly EPA per dropback",
            specification={
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {"values": weekly_values},
                "mark": {"type": "line", "point": True},
                "encoding": {
                    "x": {"field": "week", "type": "quantitative"},
                    "y": {"field": "epa", "type": "quantitative"},
                    "color": {"field": "window", "type": "nominal"},
                    "tooltip": [{"field": "window"}, {"field": "week"}, {"field": "epa", "format": ".3f"}],
                },
            },
            evidence_ids=[item.evidence_id for item in metric_items if item.metric == "epa_per_dropback"],
        )
        return [comparison_chart, trend] if any(item.metric == "epa_per_dropback" for item in metric_items) else [comparison_chart]
