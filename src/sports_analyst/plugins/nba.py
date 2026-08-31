"""SportsDataverse-backed NBA analysis plugin."""

from __future__ import annotations

import hashlib
import json
import math
import re
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
    ChartArtifact,
    ComparisonWindowOption,
    DatasetManifest,
    MetricDefinition,
    MetricOption,
    PlannedToolCall,
    PlayerOption,
    PlayEvidence,
    PlayVisualization,
    SplitDimensionOption,
    TeamOption,
    ToolDefinition,
    ToolExecutionRecord,
    stable_id,
)
from sports_analyst.nba_data import NBA_ALL_DATASETS, NBA_DATASETS, nba_live_transport_available
from sports_analyst.plugins.nba_segments import NBA_SEGMENTS, available_segments, segment_game_ids

NBA_TEAMS = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GS": "Golden State Warriors",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NO": "New Orleans Pelicans",
    "NOP": "New Orleans Pelicans",
    "NY": "New York Knicks",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SA": "San Antonio Spurs",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTAH": "Utah Jazz",
    "UTA": "Utah Jazz",
    "WSH": "Washington Wizards",
}
TEAM_ALIASES = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA"}
NBA_TEAM_CODES = frozenset(code for code in NBA_TEAMS if code not in TEAM_ALIASES)
NBA_TEAM_NAMES = {name.upper(): code for code, name in NBA_TEAMS.items() if code in NBA_TEAM_CODES}
SHOT_DISTANCE_PATTERN = re.compile(r"(?P<distance>\d+(?:\.\d+)?)\s*[- ]\s*(?:foot|feet)\b", re.IGNORECASE)


def _recorded_boolean(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "t", "yes", "y", "1"}:
            return True
        if normalized in {"false", "f", "no", "n", "0", ""}:
            return False
    return bool(value)


def _shot_result(description: str, scoring_play: Any, shooting_play: Any) -> str | None:
    text = description.casefold()
    if re.search(r"\b(?:makes|made)\b", text):
        return "Made"
    if re.search(r"\b(?:misses|missed)\b", text):
        return "Missed"
    if _recorded_boolean(shooting_play) and _recorded_boolean(scoring_play):
        return "Made"
    return None


def _shot_distance(description: str, row: dict[str, Any], point: tuple[float, float] | None) -> float | None:
    recorded = row.get("shot_distance")
    if recorded is not None:
        return float(recorded)
    match = SHOT_DISTANCE_PATTERN.search(description)
    if match:
        return float(match.group("distance"))
    if point:
        # NBA hoop center is 5.25 feet from the baseline on a 50-foot-wide court.
        return round(math.hypot(point[0] - 25.0, point[1] - 5.25), 1)
    return None


def _shot_value(description: str, row: dict[str, Any]) -> int | None:
    attempted = row.get("points_attempted")
    if attempted not in (None, 0, "0"):
        return int(attempted)
    text = description.casefold()
    if "three point" in text or "three-point" in text or "3-pt" in text or "3 point" in text:
        return 3
    score = row.get("score_value")
    return int(score) if score not in (None, 0, "0") else None


def _shot_point(row: dict[str, Any]) -> tuple[float, float] | None:
    """Normalize source coordinates to half-court feet with the near basket at y=5.25."""
    raw_x, raw_y = row.get("coordinate_x_raw"), row.get("coordinate_y_raw")
    if raw_x is not None and raw_y is not None:
        x, y = float(raw_x), float(raw_y)
        if 0 <= x <= 50 and 0 <= y <= 47:
            return x, y
        if 0 <= x <= 50 and 47 < y <= 94:
            return 50 - x, 94 - y
    x, y = row.get("coordinate_x"), row.get("coordinate_y")
    if x is None or y is None:
        return None
    x, y = float(x), float(y)
    return (x, y) if 0 <= x <= 50 and 0 <= y <= 47 else None


ESPN_TEAM_IDS = {
    "1": "ATL",
    "2": "BOS",
    "3": "NOP",
    "4": "CHI",
    "5": "CLE",
    "6": "DAL",
    "7": "DEN",
    "8": "DET",
    "9": "GSW",
    "10": "HOU",
    "11": "IND",
    "12": "LAC",
    "13": "LAL",
    "14": "MIA",
    "15": "MIL",
    "16": "MIN",
    "17": "BKN",
    "18": "NYK",
    "19": "ORL",
    "20": "PHI",
    "21": "PHX",
    "22": "POR",
    "23": "SAC",
    "24": "SAS",
    "25": "OKC",
    "26": "UTA",
    "27": "WSH",
    "28": "TOR",
    "29": "MEM",
    "30": "CHA",
}
NBA_STATS_TEAM_IDS = {
    str(1610612737 + index): code
    for index, code in enumerate(
        (
            "ATL",
            "BOS",
            "CLE",
            "NOP",
            "CHI",
            "DAL",
            "DEN",
            "GSW",
            "HOU",
            "LAC",
            "LAL",
            "MIA",
            "MIL",
            "MIN",
            "BKN",
            "NYK",
            "ORL",
            "IND",
            "PHI",
            "PHX",
            "POR",
            "SAC",
            "SAS",
            "OKC",
            "TOR",
            "UTA",
            "MEM",
            "WSH",
            "DET",
            "CHA",
        )
    )
}


def canonical_nba_team(value: Any) -> str | None:
    token = str(value or "").strip().upper()
    if token.endswith(".0") and token[:-2].isdigit():
        token = token[:-2]
    token = TEAM_ALIASES.get(token, token)
    if token in NBA_TEAM_CODES:
        return token
    return NBA_TEAM_NAMES.get(token) or ESPN_TEAM_IDS.get(token) or NBA_STATS_TEAM_IDS.get(token)


# metric -> label, category, domain, subjects, description, higher-is-better
METRICS: dict[str, tuple[str, str, str, list[str], str, bool | None]] = {
    "points_per_game": ("Points per game", "Scoring", "offense", ["team", "player"], "Average points scored per game.", True),
    "offensive_rating": ("Offensive rating", "Efficiency", "offense", ["team"], "Points scored per 100 estimated possessions.", True),
    "defensive_rating": ("Defensive rating", "Efficiency", "defense", ["team"], "Points allowed per 100 estimated possessions.", False),
    "pace": ("Estimated pace", "Tempo", "offense", ["team"], "Estimated possessions per game.", None),
    "win_pct": ("Win percentage", "Results", "offense", ["team"], "Share of games won.", True),
    "field_goal_pct": ("Field-goal percentage", "Shooting", "shooting", ["team", "player"], "Made field goals divided by attempts.", True),
    "three_point_pct": ("Three-point percentage", "Shooting", "shooting", ["team", "player"], "Made threes divided by attempts.", True),
    "effective_fg_pct": (
        "Effective field-goal percentage",
        "Shooting",
        "shooting",
        ["team", "player"],
        "Field-goal percentage adjusted for the value of threes.",
        True,
    ),
    "true_shooting_pct": (
        "True-shooting percentage",
        "Shooting",
        "shooting",
        ["team", "player"],
        "Scoring efficiency including field goals and free throws.",
        True,
    ),
    "three_point_rate": (
        "Three-point attempt rate",
        "Shot profile",
        "shooting",
        ["team", "player"],
        "Share of field-goal attempts taken from three.",
        None,
    ),
    "assists_per_game": ("Assists per game", "Playmaking", "playmaking", ["team", "player"], "Average assists per game.", True),
    "assist_turnover_ratio": (
        "Assist-to-turnover ratio",
        "Playmaking",
        "playmaking",
        ["team", "player"],
        "Assists divided by turnovers.",
        True,
    ),
    "rebounds_per_game": ("Rebounds per game", "Rebounding", "rebounding", ["team", "player"], "Average total rebounds per game.", True),
    "offensive_rebounds_per_game": (
        "Offensive rebounds per game",
        "Rebounding",
        "rebounding",
        ["team", "player"],
        "Average offensive rebounds per game.",
        True,
    ),
    "turnovers_per_game": ("Turnovers per game", "Ball security", "turnovers", ["team", "player"], "Average turnovers per game.", False),
    "turnover_rate": ("Turnover rate", "Ball security", "turnovers", ["team"], "Turnovers per estimated possession.", False),
    "minutes_per_game": ("Minutes per game", "Usage", "usage", ["player"], "Average minutes played.", None),
    "usage_proxy": ("Usage proxy", "Usage", "usage", ["player"], "Shooting attempts, free throws, and turnovers per minute.", None),
    "plus_minus_per_game": ("Plus/minus per game", "Impact", "impact", ["player"], "Average recorded box-score plus/minus.", True),
    "lineup_net_rating": (
        "Lineup net rating",
        "Lineups",
        "lineups",
        ["team", "player"],
        "Minutes-weighted five-player-unit net rating.",
        True,
    ),
    "lineup_off_rating": (
        "Lineup offensive rating",
        "Lineups",
        "lineups",
        ["team", "player"],
        "Minutes-weighted five-player-unit offensive rating.",
        True,
    ),
    "lineup_def_rating": (
        "Lineup defensive rating",
        "Lineups",
        "lineups",
        ["team", "player"],
        "Minutes-weighted five-player-unit defensive rating.",
        False,
    ),
}

DEFAULTS = {
    "offense": ["points_per_game", "offensive_rating", "effective_fg_pct", "turnover_rate"],
    "defense": ["defensive_rating", "win_pct"],
    "shooting": ["effective_fg_pct", "true_shooting_pct", "three_point_rate"],
    "playmaking": ["assists_per_game", "assist_turnover_ratio"],
    "rebounding": ["rebounds_per_game", "offensive_rebounds_per_game"],
    "turnovers": ["turnovers_per_game", "turnover_rate"],
    "lineups": ["lineup_net_rating", "lineup_off_rating", "lineup_def_rating"],
    "scoring": ["points_per_game", "true_shooting_pct"],
    "usage": ["minutes_per_game", "usage_proxy"],
    "impact": ["plus_minus_per_game", "lineup_net_rating"],
}

DOMAINS = [
    {"value": "offense", "label": "Offense", "description": "Team scoring, efficiency, and pace.", "subject_type": "team"},
    {"value": "defense", "label": "Defense", "description": "Opponent scoring and defensive efficiency.", "subject_type": "team"},
    {"value": "scoring", "label": "Scoring", "description": "Player scoring volume and efficiency.", "subject_type": "player"},
    {"value": "shooting", "label": "Shooting", "description": "Shot efficiency and three-point mix.", "subject_type": "both"},
    {"value": "playmaking", "label": "Playmaking", "description": "Assists and ball distribution.", "subject_type": "both"},
    {"value": "rebounding", "label": "Rebounding", "description": "Total and offensive rebounding.", "subject_type": "both"},
    {"value": "turnovers", "label": "Turnovers", "description": "Turnover volume and possession security.", "subject_type": "both"},
    {"value": "usage", "label": "Usage", "description": "Player minutes and offensive involvement.", "subject_type": "player"},
    {"value": "impact", "label": "Impact", "description": "Box plus/minus and lineup context.", "subject_type": "player"},
    {"value": "lineups", "label": "Lineups", "description": "Five-player-unit performance.", "subject_type": "both"},
]


@dataclass
class NBAAnalysisResult:
    aggregate_evidence: list[AggregateEvidence]
    play_evidence: list[PlayEvidence]
    charts: list[ChartArtifact]
    executions: list[ToolExecutionRecord]
    caveats: list[str]


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _numeric(frame: pl.DataFrame, column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Float64, strict=False) if column in frame.columns else pl.lit(None, dtype=pl.Float64)


def _ratio(frame: pl.DataFrame, numerator: str, denominator: str) -> float | None:
    if numerator not in frame.columns or denominator not in frame.columns:
        return None
    values = frame.select(_numeric(frame, numerator).sum().alias("n"), _numeric(frame, denominator).sum().alias("d")).row(0)
    return float(values[0] / values[1]) if values[1] else None


def _mean(frame: pl.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    value = frame.select(_numeric(frame, column).mean()).item()
    return float(value) if value is not None else None


def _sum(frame: pl.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    value = frame.select(_numeric(frame, column).sum()).item()
    return float(value) if value is not None else None


def _possessions(frame: pl.DataFrame) -> float | None:
    required = {"field_goals_attempted", "offensive_rebounds", "turnovers", "free_throws_attempted"}
    if not required <= set(frame.columns):
        return None
    value = frame.select(
        (
            _numeric(frame, "field_goals_attempted")
            - _numeric(frame, "offensive_rebounds")
            + _numeric(frame, "turnovers")
            + 0.44 * _numeric(frame, "free_throws_attempted")
        ).sum()
    ).item()
    return float(value) if value is not None else None


def _metric(frame: pl.DataFrame, name: str, subject_type: str) -> float | None:
    games = frame.get_column("game_id").n_unique() if "game_id" in frame.columns else frame.height
    points_col = "team_score" if subject_type == "team" else "points"
    rebound_col = "total_rebounds" if subject_type == "team" else "rebounds"
    turnover_col = "turnovers" if "turnovers" in frame.columns else "team_turnovers"
    if name == "points_per_game":
        points = _sum(frame, points_col)
        return points / games if games and points is not None else None
    if name == "field_goal_pct":
        return _ratio(frame, "field_goals_made", "field_goals_attempted")
    if name == "three_point_pct":
        return _ratio(frame, "three_point_field_goals_made", "three_point_field_goals_attempted")
    if name == "effective_fg_pct":
        fga = _sum(frame, "field_goals_attempted") or 0
        if not fga:
            return None
        made = _sum(frame, "field_goals_made") or 0
        threes = _sum(frame, "three_point_field_goals_made") or 0
        return float((made + 0.5 * threes) / fga)
    if name == "true_shooting_pct":
        if not {points_col, "field_goals_attempted", "free_throws_attempted"} <= set(frame.columns):
            return None
        points = _sum(frame, points_col) or 0
        attempts = (_sum(frame, "field_goals_attempted") or 0) + 0.44 * (_sum(frame, "free_throws_attempted") or 0)
        return float(points / (2 * attempts)) if attempts else None
    if name == "three_point_rate":
        return _ratio(frame, "three_point_field_goals_attempted", "field_goals_attempted")
    if name == "assists_per_game":
        assists = _sum(frame, "assists")
        return assists / games if games and assists is not None else None
    if name == "assist_turnover_ratio":
        return _ratio(frame, "assists", turnover_col)
    if name == "rebounds_per_game":
        rebounds = _sum(frame, rebound_col)
        return rebounds / games if games and rebounds is not None else None
    if name == "offensive_rebounds_per_game":
        rebounds = _sum(frame, "offensive_rebounds")
        return rebounds / games if games and rebounds is not None else None
    if name == "turnovers_per_game":
        turnovers = _sum(frame, turnover_col)
        return turnovers / games if games and turnovers is not None else None
    if name in {"pace", "offensive_rating", "defensive_rating", "turnover_rate"}:
        possessions = _possessions(frame)
        if not possessions:
            return None
        if name == "pace":
            return possessions / games if games else None
        if name == "turnover_rate":
            turnovers = _sum(frame, turnover_col)
            return turnovers / possessions if turnovers is not None else None
        score = points_col if name == "offensive_rating" else "opponent_team_score"
        points = _sum(frame, score)
        return 100 * points / possessions if points is not None else None
    if name == "win_pct":
        return _mean(frame, "team_winner")
    if name == "minutes_per_game":
        return _mean(frame, "minutes")
    if name == "usage_proxy":
        required = {"field_goals_attempted", "free_throws_attempted", turnover_col, "minutes"}
        if not required <= set(frame.columns):
            return None
        minutes = _sum(frame, "minutes") or 0
        events = (
            (_sum(frame, "field_goals_attempted") or 0) + 0.44 * (_sum(frame, "free_throws_attempted") or 0) + (_sum(frame, turnover_col) or 0)
        )
        return float(events / minutes) if minutes else None
    if name == "plus_minus_per_game":
        return _mean(frame, "plus_minus")
    if name.startswith("lineup_"):
        source = {"lineup_net_rating": "net_rating", "lineup_off_rating": "off_rating", "lineup_def_rating": "def_rating"}[name]
        if source not in frame.columns:
            return None
        weight = "min" if "min" in frame.columns else None
        if weight:
            values = frame.select(
                (_numeric(frame, source) * _numeric(frame, weight)).sum().alias("n"), _numeric(frame, weight).sum().alias("d")
            ).row(0)
            return float(values[0] / values[1]) if values[1] else None
        return _mean(frame, source)
    return None


class NBAPlugin:
    sport_id = "nba"
    display_name = "NBA"

    def required_play_by_play_columns(self, request: AnalysisRequest) -> set[str]:
        del request
        return {
            "season",
            "season_type",
            "game_id",
            "play_id",
            "description",
            "text",
            "period",
            "clock",
            "type_text",
            "type_abbreviation",
            "team_id",
            "team_abbreviation",
            "athlete_id_1",
            "athlete_id_2",
            "athlete_id_3",
            "athlete_name_1",
            "athlete_name_2",
            "athlete_name_3",
            "home_team_id",
            "away_team_id",
            "home_team_abbrev",
            "away_team_abbrev",
            "home_score",
            "away_score",
            "score_value",
            "scoring_play",
            "shooting_play",
            "points_attempted",
            "coordinate_x",
            "coordinate_y",
            "coordinate_x_raw",
            "coordinate_y_raw",
            "game_date",
        }

    def required_supplemental_datasets(self, request: AnalysisRequest) -> set[str]:
        selected = {
            "schedules",
            "lineups_v3",
            "possessions_v3",
            "team_boxscores" if request.subject is None or request.subject.type == "team" else "player_boxscores",
        }
        if request.analysis_domain == "shooting":
            selected.add("shots")
        if request.analysis_domain in {"lineups", "impact"}:
            selected.update({"lineups", "lineups_v3", "possessions_v3"})
        if request.subject and request.subject.type == "player":
            selected.update({"player_crosswalk", "player_core"})
        return selected

    def tools(self) -> list[ToolDefinition]:
        definitions = [
            ("get_analysis_options", "Return valid NBA subjects, datasets, metrics, segments, and splits."),
            ("validate_analysis_scope", "Validate NBA subjects, segments, fields, and sample requirements."),
            ("compare_time_windows", "Compare team or player metrics across NBA season segments."),
            ("analyze_season_trends", "Measure every NBA season in an inclusive range."),
            ("analyze_game_trends", "Measure game-by-game trends inside each selected segment."),
            ("rank_game_outliers", "Rank games that most exceeded or trailed the segment expectation."),
            ("benchmark_against_league", "Calculate league ranks and percentiles for NBA metrics."),
            ("analyze_situational_split", "Compare home/away, opponent, period, score-state, and rest splits."),
            ("decompose_metric_change", "Separate changes in shot mix from within-category performance."),
            ("adjust_for_opponents", "Add SportsDataverse opponent-adjusted team context."),
            ("compare_shot_profiles", "Compare shot volume, location, value, and result."),
            ("compare_possession_outcomes", "Compare scoring, turnover, transition, and second-chance possessions."),
            ("compare_player_usage", "Compare player minutes, attempts, assists, and turnover involvement."),
            ("analyze_lineup_performance", "Rank five-player units by minutes and efficiency."),
            ("find_representative_possessions", "Return supporting and counterexample NBA plays or possessions."),
            ("explain_metric", "Return an NBA metric definition, formula, and limitations."),
            ("query_play_by_play", "Run constrained read-only SQL against registered NBA play-by-play views."),
        ]
        return [ToolDefinition(name=name, description=description) for name, description in definitions]

    def analysis_options(self, manifests: list[DatasetManifest], context: Any = None) -> AnalysisOptions:
        context = context if isinstance(context, dict) else {}
        pbp_manifests = [item for item in manifests if item.dataset == "play_by_play"]
        available = sorted({item.season for item in pbp_manifests})
        # Exhibition entries can appear in schedule and box-score releases. The
        # analysis subject list is intentionally limited to the 30 NBA franchises.
        teams = [TeamOption(value=code, label=NBA_TEAMS[code]) for code in sorted(NBA_TEAM_CODES)]
        availability: dict[str, list[str]] = {}
        schedules = context.get("schedules", {})
        for season, schedule in schedules.items():
            availability[str(season)] = [item["value"] for item in available_segments(schedule, int(season))]
        dataset_seasons = {dataset: sorted({item.season for item in manifests if item.dataset == dataset}) for dataset in NBA_ALL_DATASETS}
        metric_options = [
            MetricOption(
                value=value,
                label=metadata[0],
                category=metadata[1],
                description=metadata[4],
                analysis_domain=metadata[2],
                available_seasons=dataset_seasons["lineups"] if value.startswith("lineup_") else available,
                subject_types=metadata[3],
            )
            for value, metadata in METRICS.items()
        ]
        return AnalysisOptions(
            sport=self.sport_id,
            teams=teams,
            available_seasons=available,
            syncable_seasons=sorted({season for definition in NBA_DATASETS.values() for season in definition.available_seasons}, reverse=True),
            metrics=metric_options,
            default_metrics=DEFAULTS["offense"],
            analysis_domains=DOMAINS,
            default_metrics_by_domain=DEFAULTS,
            split_dimensions=[
                SplitDimensionOption(
                    value="home_away", label="Home / away", description="Compare venue context.", available_seasons=available
                ),
                SplitDimensionOption(
                    value="opponent", label="Opponent", description="Compare performance by opponent.", available_seasons=available
                ),
                SplitDimensionOption(
                    value="period", label="Period", description="Compare play outcomes by quarter or overtime.", available_seasons=available
                ),
                SplitDimensionOption(
                    value="score_state",
                    label="Score state",
                    description="Compare while leading, tied, or trailing.",
                    available_seasons=available,
                ),
                SplitDimensionOption(value="rest", label="Rest", description="Compare games by days of rest.", available_seasons=available),
            ],
            comparison_windows=[
                ComparisonWindowOption(
                    value="full_seasons", label="Full season range", description="Analyze every season from the selected start through end."
                ),
                ComparisonWindowOption(
                    value="season_segments", label="Season segments", description="Compare named NBA phases within or across seasons."
                ),
                ComparisonWindowOption(
                    value="before_after_milestone", label="Before vs. after", description="Compare phases around a reviewed season milestone."
                ),
            ],
            week_values=[],
            syncable_datasets=list(NBA_DATASETS),
            dataset_min_seasons={dataset: definition.minimum for dataset, definition in NBA_DATASETS.items()},
            dataset_available_seasons={dataset: list(definition.available_seasons) for dataset, definition in NBA_DATASETS.items()},
            subject_types=[{"value": "team", "label": "Team"}, {"value": "player", "label": "Player"}],
            season_segments=NBA_SEGMENTS,
            segment_availability=availability,
            optional_capabilities={
                "live_nba_stats": nba_live_transport_available(),
                "lineups": bool(dataset_seasons["lineups"]),
                "possession_evidence": bool(dataset_seasons["possessions_v3"]),
            },
        )

    def explain_metric(self, metric: str) -> MetricDefinition:
        normalized = metric.strip().lower()
        if normalized not in METRICS:
            raise ValueError(f"unsupported NBA metric {metric!r}")
        label, category, _domain, _subjects, description, higher = METRICS[normalized]
        formulas = {
            "offensive_rating": "100 × points / estimated possessions",
            "defensive_rating": "100 × opponent points / estimated possessions",
            "effective_fg_pct": "(FGM + 0.5 × 3PM) / FGA",
            "true_shooting_pct": "points / (2 × (FGA + 0.44 × FTA))",
            "usage_proxy": "(FGA + 0.44 × FTA + TOV) / minutes",
        }
        return MetricDefinition(
            value=normalized,
            label=label,
            category=category,
            description=description,
            formula=formulas.get(normalized, "Aggregate the named box-score statistic over qualifying games."),
            qualifying_plays="Completed games in the selected NBA season segment and subject scope.",
            interpretation="Compare the baseline and comparison values together with sample size and game context.",
            higher_is_better=higher,
            limitations=["Possession-based rates use the standard box-score possession estimate unless possession data is synced."],
        )

    def resolve_team(self, team: str) -> str:
        normalized = team.strip().upper()
        return TEAM_ALIASES.get(normalized, normalized)

    def resolve_players(self, query: str, sources: list[tuple[int, pl.DataFrame]]) -> list[PlayerOption]:
        needle = query.strip().lower()
        found: dict[str, dict[str, Any]] = {}
        for season, frame in sources:
            id_candidates = ("athlete_id", "espn_athlete_id", "player_id", "nba_player_id", "nba_id", "person_id")
            id_col = next((name for name in id_candidates if name in frame.columns), None)
            name_col = next(
                (
                    name
                    for name in (
                        "display_name",
                        "athlete_display_name",
                        "espn_full_name",
                        "player_name",
                        "player",
                        "full_name",
                        "nba_player_name",
                        "name",
                    )
                    if name in frame.columns
                ),
                None,
            )
            if not name_col and {"first_name", "last_name"} <= set(frame.columns):
                name_col = "__resolved_player_name"
                frame = frame.with_columns(pl.concat_str("first_name", "last_name", separator=" ").alias(name_col))
            if not id_col or not name_col:
                continue
            team_col = next((name for name in ("team_abbreviation", "team_name", "team_id") if name in frame.columns), None)
            position_col = next(
                (
                    name
                    for name in ("athlete_position_abbreviation", "athlete_position", "position_abbreviation", "position", "nba_position")
                    if name in frame.columns
                ),
                None,
            )
            columns = [id_col, name_col, *([team_col] if team_col else []), *([position_col] if position_col else [])]
            for row in frame.select(columns).drop_nulls([id_col, name_col]).unique().iter_rows(named=True):
                player_id, name = str(row[id_col]), str(row[name_col])
                team_code = canonical_nba_team(row.get(team_col)) if team_col else None
                if team_col and row.get(team_col) and not team_code:
                    continue
                if needle and needle not in name.lower() and needle not in player_id.lower() and needle not in (team_code or "").lower():
                    continue
                identity_key = " ".join(name.casefold().split())
                priority = id_candidates.index(id_col)
                item = found.setdefault(
                    identity_key,
                    {"player_id": player_id, "id_priority": priority, "name": name, "teams": set(), "positions": set(), "seasons": set()},
                )
                if priority < item["id_priority"]:
                    item.update(player_id=player_id, id_priority=priority, name=name)
                item["seasons"].add(season)
                if team_code:
                    item["teams"].add(team_code)
                if position_col and row.get(position_col):
                    item["positions"].add(str(row[position_col]))
        players = [
            PlayerOption(
                player_id=item["player_id"],
                name=item["name"],
                teams=sorted(item["teams"]),
                positions=sorted(item["positions"]),
                seasons=sorted(item["seasons"]),
            )
            for _identity, item in sorted(found.items(), key=lambda pair: pair[1]["name"])
            if item["teams"]
        ]
        return players

    def default_plan(self, request: AnalysisRequest) -> AnalysisPlan:
        calls = [
            PlannedToolCall(tool="validate_analysis_scope", arguments={}, purpose="Validate the NBA subject, data, and segments."),
            PlannedToolCall(tool="compare_time_windows", arguments={}, purpose="Compare selected NBA metrics across the two windows."),
            PlannedToolCall(tool="analyze_game_trends", arguments={}, purpose="Measure game-level variation and sample context."),
            PlannedToolCall(
                tool="find_representative_possessions", arguments={}, purpose="Attach representative and counterexample evidence."
            ),
        ]
        if request.analysis_domain == "shooting":
            calls.append(PlannedToolCall(tool="compare_shot_profiles", arguments={}, purpose="Explain changes in shot mix and conversion."))
        if request.analysis_domain in {"lineups", "impact"}:
            calls.append(PlannedToolCall(tool="analyze_lineup_performance", arguments={}, purpose="Compare five-player-unit results."))
        payload = {
            "sport": self.sport_id,
            "question": request.question,
            "scope": request.scope.model_dump(),
            "subject": request.subject.model_dump() if request.subject else None,
        }
        return AnalysisPlan(plan_id=stable_id("plan", payload), question=request.question, scope=request.scope, calls=calls)

    @staticmethod
    def _window_frame(
        request: AnalysisRequest,
        season: int,
        segment: str,
        supplemental: dict[str, dict[int, pl.DataFrame]],
    ) -> pl.DataFrame:
        subject = request.subject
        dataset = "team_boxscores" if subject is None or subject.type == "team" else "player_boxscores"
        frame = supplemental.get(dataset, {}).get(season, pl.DataFrame())
        if frame.is_empty():
            return frame
        if subject is None or subject.type == "team":
            team = str(subject.id if subject else request.scope.team)
            team = TEAM_ALIASES.get(team.upper(), team.upper())
            conditions = []
            if "team_abbreviation" in frame.columns:
                conditions.append(pl.col("team_abbreviation").cast(pl.String).str.to_uppercase() == team)
            if "team_id" in frame.columns:
                conditions.append(pl.col("team_id").cast(pl.String) == str(subject.id if subject else team))
            if conditions:
                predicate = conditions[0]
                for condition in conditions[1:]:
                    predicate |= condition
                frame = frame.filter(predicate)
        else:
            identifier = str(subject.id)
            if "player_id" in frame.columns:
                frame = frame.filter(pl.col("player_id").cast(pl.String) == identifier)
            elif "athlete_id" in frame.columns:
                frame = frame.filter(pl.col("athlete_id").cast(pl.String) == identifier)
            if subject.team_id:
                team_id = str(subject.team_id).upper()
                if "team_abbreviation" in frame.columns:
                    frame = frame.filter(pl.col("team_abbreviation").cast(pl.String).str.to_uppercase() == team_id)
                elif "team_id" in frame.columns:
                    frame = frame.filter(pl.col("team_id").cast(pl.String) == str(subject.team_id))
        schedule = supplemental.get("schedules", {}).get(season, pl.DataFrame())
        game_ids = segment_game_ids(schedule, season, segment)
        if game_ids and "game_id" in frame.columns:
            frame = frame.filter(pl.col("game_id").cast(pl.String).is_in(game_ids))
        elif segment in {"regular_season", "playoffs"} and "season_type" in frame.columns:
            frame = frame.filter(pl.col("season_type") == (2 if segment == "regular_season" else 3))
        elif segment != "full_season" and not game_ids:
            return frame.head(0)
        return frame

    def analyze(
        self,
        request: AnalysisRequest,
        datasets: dict[int, pl.DataFrame],
        manifests: dict[int, DatasetManifest],
        supplemental: dict[str, dict[int, pl.DataFrame]] | None = None,
        supplemental_manifests: dict[str, dict[int, DatasetManifest]] | None = None,
    ) -> NBAAnalysisResult:
        supplemental = supplemental or {}
        supplemental_manifests = supplemental_manifests or {}
        subject = request.subject
        if subject is None:
            raise ValueError("NBA investigations require a team or player subject")
        baseline_segment = request.scope.baseline.segment or "full_season"
        comparison_segment = request.scope.comparison.segment or "full_season"
        baseline = self._window_frame(request, request.scope.baseline.season, baseline_segment, supplemental)
        comparison = self._window_frame(request, request.scope.comparison.season, comparison_segment, supplemental)
        if baseline.is_empty() or comparison.is_empty():
            raise ValueError("each NBA comparison window requires synced box scores and at least one qualifying game")
        subject_type = subject.type
        selected_metrics = request.metrics or DEFAULTS.get(request.analysis_domain, DEFAULTS["offense"])
        unknown = sorted(set(selected_metrics) - set(METRICS))
        if unknown:
            raise ValueError(f"unsupported NBA metrics: {unknown}")
        incompatible = [name for name in selected_metrics if subject_type not in METRICS[name][3]]
        if incompatible:
            raise ValueError(f"metrics are incompatible with an NBA {subject_type} subject: {incompatible}")
        if request.analysis_domain in {"lineups", "impact"} and any(name.startswith("lineup_") for name in selected_metrics):
            lineup_frames = supplemental.get("lineups", {})
            required = {request.scope.baseline.season, request.scope.comparison.season}
            if not required <= set(lineup_frames):
                raise ValueError("lineup metrics require a synced NBA Stats lineup package for both comparison seasons")
            baseline = self._scope_lineups(lineup_frames[request.scope.baseline.season], subject)
            comparison = self._scope_lineups(lineup_frames[request.scope.comparison.season], subject)
        all_manifests = list(manifests.values()) + [
            manifest for per_season in supplemental_manifests.values() for manifest in per_season.values()
        ]
        started_at, started = datetime.now(UTC), perf_counter()
        parameters = {
            "sport": self.sport_id,
            "subject": subject.model_dump(),
            "baseline": request.scope.baseline.model_dump(),
            "comparison": request.scope.comparison.model_dump(),
            "metrics": selected_metrics,
        }
        execution_id = stable_id("execution", {"tool": "compare_time_windows", **parameters})
        aggregate: list[AggregateEvidence] = []
        for metric_name in selected_metrics:
            baseline_value = _metric(baseline, metric_name, subject_type)
            comparison_value = _metric(comparison, metric_name, subject_type)
            if baseline_value is None or comparison_value is None:
                continue
            payload = {**parameters, "metric": metric_name, "baseline_value": baseline_value, "comparison_value": comparison_value}
            aggregate.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric=metric_name,
                    label=METRICS[metric_name][0],
                    value=round(comparison_value - baseline_value, 4),
                    baseline_value=round(baseline_value, 4),
                    comparison_value=round(comparison_value, 4),
                    unit="rate" if metric_name.endswith("pct") or "rate" in metric_name else "per game",
                    sample_size=comparison.height,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in all_manifests],
                    tool_execution_id=execution_id,
                    caveats=["NBA possession rates use box-score possession estimates unless possession data is synced."],
                )
            )
        if not aggregate:
            raise ValueError("the selected NBA metrics are unavailable in the synced datasets")
        execution = ToolExecutionRecord(
            execution_id=execution_id,
            tool="compare_time_windows",
            parameters=parameters,
            started_at=started_at,
            duration_ms=int((perf_counter() - started) * 1000),
            result_sha256=_sha([item.model_dump(mode="json") for item in aggregate]),
            dataset_manifest_ids=[item.manifest_id for item in all_manifests],
        )
        plays = self._representative_plays(
            request, datasets[request.scope.comparison.season], supplemental, manifests[request.scope.comparison.season]
        )
        endpoint_labels = (
            (str(request.scope.baseline.season), str(request.scope.comparison.season))
            if request.scope.comparison_design == "full_seasons"
            else ("Baseline", "Comparison")
        )
        comparison_values = [
            {"metric": item.label, "window": window, "value": value}
            for item in aggregate
            for window, value in zip(endpoint_labels, (item.baseline_value, item.comparison_value), strict=True)
        ]
        comparison_chart = ChartArtifact(
            chart_id=stable_id("chart", {**parameters, "view": "endpoint-comparison"}),
            title=(
                "NBA range endpoints"
                if request.scope.comparison_design == "full_seasons"
                else f"{baseline_segment.replace('_', ' ').title()} vs {comparison_segment.replace('_', ' ').title()}"
            ),
            specification={
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {"values": comparison_values},
                "mark": {"type": "bar", "cornerRadiusEnd": 3},
                "encoding": {
                    "x": {"field": "metric", "type": "nominal", "axis": {"labelAngle": -25}},
                    "y": {"field": "value", "type": "quantitative"},
                    "color": {"field": "window", "type": "nominal"},
                    "xOffset": {"field": "window"},
                    "tooltip": ["window", "metric", "value"],
                },
            },
            evidence_ids=[item.evidence_id for item in aggregate],
        )
        charts = [comparison_chart]
        if request.scope.comparison_design == "full_seasons":
            primary = aggregate[0]
            trend_values: list[dict[str, Any]] = []
            for season in request.scope.included_seasons:
                if primary.metric.startswith("lineup_"):
                    season_frame = self._scope_lineups(supplemental.get("lineups", {}).get(season, pl.DataFrame()), subject)
                else:
                    season_frame = self._window_frame(request, season, "full_season", supplemental)
                value = _metric(season_frame, primary.metric, subject_type)
                if value is not None:
                    trend_values.append({"series": primary.label, "season": season, "value": value})
            if trend_values:
                charts.append(
                    ChartArtifact(
                        chart_id=stable_id("chart", {**parameters, "view": "season-trend", "metric": primary.metric}),
                        title=f"Season-by-season {primary.label}",
                        specification={
                            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                            "data": {"values": trend_values},
                            "mark": {"type": "line", "point": True},
                            "encoding": {
                                "x": {"field": "season", "type": "ordinal", "sort": "ascending"},
                                "y": {"field": "value", "type": "quantitative", "axis": {"title": primary.label}},
                                "color": {"field": "series", "type": "nominal", "legend": None},
                                "tooltip": ["season", "series", "value"],
                            },
                        },
                        evidence_ids=[primary.evidence_id],
                    )
                )
        caveats = [
            "SportsDataverse bulk releases are authoritative for this investigation; live NBA Stats data is optional.",
            "Detailed segments are shown only when schedule labels or reviewed milestone dates resolve them.",
        ]
        if request.analysis_domain in {"lineups", "impact"} and "lineups" not in supplemental:
            caveats.append("Lineup analysis was unavailable because the NBA Stats lineup package was not synced.")
        return NBAAnalysisResult(aggregate, plays, charts, [execution], caveats)

    @staticmethod
    def _scope_lineups(frame: pl.DataFrame, subject: Any) -> pl.DataFrame:
        scoped = frame
        if subject.type == "team":
            if "team_abbreviation" in scoped.columns:
                scoped = scoped.filter(pl.col("team_abbreviation").cast(pl.String).str.to_uppercase() == str(subject.id).upper())
            elif "team_id" in scoped.columns:
                scoped = scoped.filter(pl.col("team_id").cast(pl.String) == str(subject.id))
        else:
            token = str(subject.id)
            if "group_id" in scoped.columns:
                scoped = scoped.filter(pl.col("group_id").cast(pl.String).str.contains(token, literal=True))
            elif "group_name" in scoped.columns:
                scoped = scoped.filter(pl.col("group_name").cast(pl.String).str.contains(token, literal=True))
        return scoped

    @staticmethod
    def _representative_plays(
        request: AnalysisRequest,
        frame: pl.DataFrame,
        supplemental: dict[str, dict[int, pl.DataFrame]],
        manifest: DatasetManifest,
    ) -> list[PlayEvidence]:
        subject = request.subject
        if subject is None or frame.is_empty():
            return []
        schedule = supplemental.get("schedules", {}).get(request.scope.comparison.season, pl.DataFrame())
        game_ids = segment_game_ids(schedule, request.scope.comparison.season, request.scope.comparison.segment or "full_season")
        scoped = frame.filter(pl.col("game_id").cast(pl.String).is_in(game_ids)) if game_ids and "game_id" in frame.columns else frame
        if subject.type == "team":
            team = str(subject.id).upper()
            if "team_abbreviation" in scoped.columns:
                scoped = scoped.filter(pl.col("team_abbreviation").fill_null("").str.to_uppercase() == team)
            elif {"home_team_abbrev", "away_team_abbrev"} <= set(scoped.columns):
                scoped = scoped.filter((pl.col("home_team_abbrev") == team) | (pl.col("away_team_abbrev") == team))
        else:
            columns = [column for column in ("athlete_id_1", "athlete_id_2", "athlete_id_3", "player_id") if column in scoped.columns]
            if columns:
                predicate = pl.col(columns[0]).cast(pl.String) == str(subject.id)
                for column in columns[1:]:
                    predicate |= pl.col(column).cast(pl.String) == str(subject.id)
                scoped = scoped.filter(predicate)
        if scoped.is_empty():
            return []
        if "score_value" in scoped.columns:
            scoped = scoped.with_columns(_numeric(scoped, "score_value").fill_null(0).alias("_rank"))
        else:
            scoped = scoped.with_columns(pl.lit(0.0).alias("_rank"))
        supporting = scoped.sort("_rank", descending=True).head(3).with_columns(pl.lit(True).alias("_supporting"))
        counter = scoped.filter(pl.col("_rank") == 0).head(2).with_columns(pl.lit(False).alias("_supporting"))
        selected = pl.concat([supporting, counter], how="diagonal_relaxed").unique(subset=["game_id", "play_id"], keep="first")
        evidence = []
        season = request.scope.comparison.season
        lineup_frame = supplemental.get("lineups_v3", {}).get(season, pl.DataFrame())
        possession_frame = supplemental.get("possessions_v3", {}).get(season, pl.DataFrame())
        for row in selected.iter_rows(named=True):
            play_id = int(float(row.get("play_id") or 0))
            description = str(row.get("description") or row.get("text") or "NBA play")
            game_id = str(row.get("game_id"))
            period = int(row.get("period") or 0) or None
            possession_number = None
            offense_players: list[str] = []
            defense_players: list[str] = []
            source_packages = ["play_by_play"]
            if not possession_frame.is_empty() and {
                "game_id",
                "start_order_index",
                "end_order_index",
            } <= set(possession_frame.columns):
                possession = possession_frame.filter(
                    (pl.col("game_id").cast(pl.String) == game_id)
                    & (_numeric(possession_frame, "start_order_index") <= play_id)
                    & (_numeric(possession_frame, "end_order_index") >= play_id)
                )
                if period is not None and "period" in possession.columns:
                    possession = possession.filter(_numeric(possession, "period") == period)
                if possession.height:
                    possession_row = possession.row(0, named=True)
                    possession_number = possession_row.get("possession_number")
                    offense_players = [
                        str(possession_row[column])
                        for column in (f"off_player_{index}" for index in range(1, 6))
                        if possession_row.get(column) is not None
                    ]
                    defense_players = [
                        str(possession_row[column])
                        for column in (f"def_player_{index}" for index in range(1, 6))
                        if possession_row.get(column) is not None
                    ]
                    source_packages.append("possessions_v3")
            if not offense_players and not lineup_frame.is_empty() and "game_id" in lineup_frame.columns:
                lineup = lineup_frame.filter(pl.col("game_id").cast(pl.String) == game_id)
                action_column = "action_number" if "action_number" in lineup.columns else "play_id" if "play_id" in lineup.columns else None
                if action_column:
                    exact = lineup.filter(_numeric(lineup, action_column) == play_id)
                    lineup = exact if exact.height else lineup.filter(_numeric(lineup, action_column) <= play_id).tail(1)
                if lineup.height:
                    lineup_row = lineup.row(0, named=True)
                    home_players = [
                        str(lineup_row[column])
                        for column in (f"home_player_{index}" for index in range(1, 6))
                        if lineup_row.get(column) is not None
                    ]
                    away_players = [
                        str(lineup_row[column])
                        for column in (f"away_player_{index}" for index in range(1, 6))
                        if lineup_row.get(column) is not None
                    ]
                    event_team = str(row.get("team_abbreviation") or subject.team_id or subject.id).upper()
                    if event_team == str(row.get("away_team_abbrev") or "").upper():
                        offense_players, defense_players = away_players, home_players
                    else:
                        offense_players, defense_players = home_players, away_players
                    source_packages.append("lineups_v3")
            payload = {"season": season, "game": game_id, "play": play_id, "subject": subject.id}
            scoring_play = _recorded_boolean(row.get("scoring_play"))
            shooting_play = _recorded_boolean(row.get("shooting_play"))
            shot_result = _shot_result(description, scoring_play, shooting_play)
            shot_point = _shot_point(row) if shooting_play or shot_result else None
            shot_distance = _shot_distance(description, row, shot_point) if shooting_play or shot_result else None
            evidence.append(
                PlayEvidence(
                    evidence_id=stable_id("play", payload),
                    sport="nba",
                    season=season,
                    game_id=game_id,
                    play_id=play_id,
                    team=str(row.get("team_abbreviation") or subject.team_id or subject.id),
                    description=description,
                    metric_value=float(row.get("_rank") or 0),
                    supporting=bool(row.get("_supporting")),
                    dataset_manifest_id=manifest.manifest_id,
                    visualization=PlayVisualization(
                        sport="nba",
                        source_packages=source_packages,
                        period=period,
                        quarter=period,
                        clock=str(row.get("clock") or "") or None,
                        event_type=str(row.get("type_text") or row.get("type_abbreviation") or "") or None,
                        player_id=str(row.get("athlete_id_1") or "") or None,
                        player_name=str(row.get("athlete_name_1") or "") or None,
                        team_id=str(row.get("team_id") or "") or None,
                        team_abbreviation=str(row.get("team_abbreviation") or "") or None,
                        home_team_abbreviation=str(row.get("home_team_abbrev") or "") or None,
                        away_team_abbreviation=str(row.get("away_team_abbrev") or "") or None,
                        home_score=int(row.get("home_score") or 0),
                        away_score=int(row.get("away_score") or 0),
                        scoring_play=scoring_play,
                        shooting_play=shooting_play,
                        shot_result=shot_result,
                        shot_value=_shot_value(description, row) if shooting_play or shot_result else None,
                        shot_distance=shot_distance,
                        shot_x=shot_point[0] if shot_point else None,
                        shot_y=shot_point[1] if shot_point else None,
                        shot_coordinate_system="court_feet" if shot_point else None,
                        possession_number=int(possession_number) if possession_number is not None else None,
                        offense_player_ids=offense_players,
                        defense_player_ids=defense_players,
                    ),
                )
            )
        return evidence
