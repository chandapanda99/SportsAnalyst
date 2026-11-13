"""NBA team identity, opponent rows, rest, situational splits and shot-mix accounting.

ESPN box scores and play-by-play record short codes (``GS``, ``NY``, ``SA``, ``NO``, ``UTAH``) and
include exhibition teams; analyses compare canonical franchises. Possession estimates use both
teams' box-score rows where the opponent row is recorded. Play-by-play splits measure field-goal
attempts only; free throws are never treated as shots.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import polars as pl

from sports_analyst.models import AggregateEvidence, ChartArtifact, ToolExecutionRecord, stable_id

ADMIN_EVENTS = (r"(?i)substitution|timeout|end (?:of )?(?:period|game|quarter)|start (?:of )?(?:period|game|quarter)"
                r"|jump ?ball|ejection|replay|challenge|^not available$|no turnover|no shot")
FREE_THROW = r"(?i)free throw"
OPPONENT_FIELDS = (
    "team_score", "field_goals_made", "field_goals_attempted", "three_point_field_goals_made",
    "three_point_field_goals_attempted", "free_throws_made", "free_throws_attempted", "offensive_rebounds",
    "defensive_rebounds", "total_rebounds", "turnovers", "total_turnovers", "assists", "steals", "blocks",
)
GAME_SPLITS = ("home_away", "opponent", "rest")
PLAY_SPLITS = ("period", "score_state", "clutch")
SPLIT_LABELS = {"home_away": "Home / away", "opponent": "Opponent", "rest": "Rest", "period": "Period",
                "score_state": "Score state", "clutch": "Clutch time"}
MIN_SPLIT_GAMES = 3
MIN_SPLIT_ATTEMPTS = {"team": 20, "player": 10}
ZONES = ("Rim", "Short midrange", "Long midrange", "Three", "Unlocated two")


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _canonical(value: Any) -> str | None:
    from sports_analyst.plugins.nba import canonical_nba_team

    return canonical_nba_team(value)


def identifier(value: Any) -> str:
    """Recorded ids arrive as strings, ints or floats; compare their integer text."""
    token = str(value if value is not None else "").strip()
    return token[:-2] if token.endswith(".0") and token[:-2].isdigit() else token


def team_spellings(values: Any, team: Any) -> list[str]:
    """Every recorded value naming the same canonical franchise as ``team`` (e.g. GS, GSW and 9 for Golden State)."""
    target = _canonical(team)
    if target is None:
        return []
    return sorted({str(value) for value in values if value is not None and _canonical(value) == target})


DID_NOT_PLAY = "did_not_play"


def appearance_predicate(columns: set[str]) -> pl.Expr | None:
    """Player-game rows where the player appeared: not a did-not-play listing, and not recorded at zero minutes.

    Unrecorded minutes stay in (older seasons can lack them); only a recorded zero is a non-appearance.
    """
    predicates = []
    if DID_NOT_PLAY in columns:
        predicates.append(~pl.col(DID_NOT_PLAY).cast(pl.Boolean, strict=False).fill_null(False))
    if "minutes" in columns:
        minutes = pl.col("minutes").cast(pl.Float64, strict=False)
        predicates.append(minutes.is_null() | (minutes > 0))
    return pl.all_horizontal(predicates) if predicates else None


def team_predicate(frame: pl.DataFrame, team: Any, columns: tuple[str, ...] = ("team_abbreviation", "team_id")) -> pl.Expr | None:
    """Match every recorded spelling (ESPN code, NBA Stats id, full name) of one canonical franchise."""
    target = _canonical(team) or str(team or "").strip().upper()
    predicates = []
    for column in columns:
        if column not in frame.columns:
            continue
        values = [value for value in frame.get_column(column).cast(pl.String).drop_nulls().unique().to_list()
                  if _canonical(value) == target]
        if values:
            predicates.append(pl.col(column).cast(pl.String).is_in(values))
    return pl.any_horizontal(predicates) if predicates else None


def filter_team(frame: pl.DataFrame, team: Any, columns: tuple[str, ...] = ("team_abbreviation", "team_id")) -> pl.DataFrame:
    if not any(column in frame.columns for column in columns):
        return frame
    predicate = team_predicate(frame, team, columns)
    return frame.filter(predicate) if predicate is not None else frame.head(0)


def canonical_column(frame: pl.DataFrame, column: str, alias: str) -> pl.DataFrame:
    if column not in frame.columns:
        return frame.with_columns(pl.lit(None, dtype=pl.String).alias(alias))
    mapping = {value: _canonical(value) for value in frame.get_column(column).cast(pl.String).drop_nulls().unique().to_list()}
    return frame.with_columns(pl.col(column).cast(pl.String).replace_strict(mapping, default=None, return_dtype=pl.String).alias(alias))


def franchise_rows(frame: pl.DataFrame, column: str = "team_abbreviation") -> pl.DataFrame:
    """Drop All-Star and other exhibition rows; league context covers the 30 franchises only."""
    if column not in frame.columns:
        return frame
    return canonical_column(frame, column, "_franchise").filter(pl.col("_franchise").is_not_null()).drop("_franchise")


def with_opponents(frame: pl.DataFrame) -> pl.DataFrame:
    """Attach the opposing team's recorded box-score row as ``opp_*`` columns (same game)."""
    if (frame.is_empty() or not {"game_id", "team_id", "opponent_team_id"} <= set(frame.columns)
            or any(column.startswith("opp_") for column in frame.columns)):
        return frame
    stats = [column for column in OPPONENT_FIELDS if column in frame.columns]
    if not stats:
        return frame
    keyed = frame.with_columns(pl.col("game_id").cast(pl.String), pl.col("team_id").cast(pl.String),
                               pl.col("opponent_team_id").cast(pl.String))
    opponents = keyed.select(
        "game_id", pl.col("team_id").alias("opponent_team_id"), *[pl.col(column).alias(f"opp_{column}") for column in stats]
    ).unique(["game_id", "opponent_team_id"], keep="first", maintain_order=True)
    return keyed.join(opponents, on=["game_id", "opponent_team_id"], how="left")


def _as_date(frame: pl.DataFrame, column: str) -> pl.Expr:
    dtype = frame.schema[column]
    if dtype == pl.Date:
        return pl.col(column)
    if dtype == pl.String:
        return pl.col(column).str.slice(0, 10).str.to_date(strict=False)
    return pl.col(column).cast(pl.Date, strict=False)


def rest_days(team_box: pl.DataFrame) -> pl.DataFrame:
    """Days between each franchise's consecutive recorded games; a season opener has no rest value."""
    if team_box.is_empty() or not {"game_id", "team_abbreviation", "game_date"} <= set(team_box.columns):
        return pl.DataFrame(schema={"game_id": pl.String, "_team": pl.String, "_split_rest": pl.String})
    frame = canonical_column(team_box, "team_abbreviation", "_team").filter(pl.col("_team").is_not_null())
    frame = frame.select(pl.col("game_id").cast(pl.String), "_team", _as_date(frame, "game_date").alias("_date"))
    frame = frame.unique(["_team", "game_id"]).drop_nulls("_date").sort(["_team", "_date", "game_id"])
    days = (pl.col("_date") - pl.col("_date").shift(1).over("_team")).dt.total_days() - 1
    return frame.with_columns(
        pl.when(days.is_null()).then(None).when(days <= 0).then(pl.lit("0 days (back-to-back)"))
        .when(days == 1).then(pl.lit("1 day")).otherwise(pl.lit("2+ days")).alias("_split_rest")
    ).select("game_id", "_team", "_split_rest")


def attach_game_splits(frame: pl.DataFrame, team_box: pl.DataFrame) -> pl.DataFrame:
    """Add venue, canonical opponent and rest labels to subject box-score rows."""
    if frame.is_empty():
        return frame
    venue = next((column for column in ("team_home_away", "home_away") if column in frame.columns), None)
    frame = frame.with_columns(
        (pl.col(venue).cast(pl.String).str.to_titlecase() if venue else pl.lit(None, dtype=pl.String)).alias("_split_home_away")
    )
    opponent = next((column for column in ("opponent_team_abbreviation", "opponent_abbreviation") if column in frame.columns), None)
    frame = canonical_column(frame, opponent, "_split_opponent") if opponent else frame.with_columns(
        pl.lit(None, dtype=pl.String).alias("_split_opponent"))
    frame = canonical_column(frame, "team_abbreviation", "_team").with_columns(pl.col("game_id").cast(pl.String))
    return frame.join(rest_days(team_box), on=["game_id", "_team"], how="left").drop("_team")


def _clock_seconds(frame: pl.DataFrame) -> pl.Expr:
    parsed = None
    if "clock" in frame.columns:
        text = pl.col("clock").cast(pl.String)
        minutes = text.str.extract(r"^(\d+):", 1).cast(pl.Float64, strict=False)
        seconds = text.str.extract(r"(?::)?(\d+(?:\.\d+)?)$", 1).cast(pl.Float64, strict=False)
        parsed = pl.when(text.str.contains(":")).then(minutes * 60 + seconds).otherwise(seconds)
    recorded = (pl.col("start_quarter_seconds_remaining").cast(pl.Float64, strict=False)
                if "start_quarter_seconds_remaining" in frame.columns else None)
    if parsed is not None and recorded is not None:
        return pl.coalesce(parsed, recorded)
    return parsed if parsed is not None else recorded if recorded is not None else pl.lit(None, dtype=pl.Float64)


def shot_attempts(pbp: pl.DataFrame, game_ids: set[str] | None, subject_type: str, subject_id: str,
                  side: str = "offense") -> pl.DataFrame:
    """Field-goal attempts for one subject, with zone, value, result and pre-shot game state.

    ``side="defense"`` (team subjects) returns the opponents' attempts in the subject's games; the
    margin is always read from the subject team's side.
    """
    columns = set(pbp.columns)
    if pbp.is_empty() or "game_id" not in columns:
        return pl.DataFrame()
    frame = pbp.filter(pl.col("game_id").cast(pl.String).is_in(sorted(game_ids))) if game_ids else pbp
    text = pl.col("description" if "description" in columns else "text").cast(pl.String).fill_null("")
    kind = pl.col("type_text").cast(pl.String).fill_null("") if "type_text" in columns else pl.lit("")
    is_shot = (pl.col("shooting_play").cast(pl.Boolean, strict=False).fill_null(False) if "shooting_play" in columns
               else text.str.contains(r"(?i)\b(?:makes|misses)\b"))
    frame = frame.filter(is_shot & ~kind.str.contains(FREE_THROW) & ~text.str.contains(FREE_THROW))
    frame = canonical_column(frame, "team_abbreviation", "_shooting_team")
    frame = canonical_column(frame, "home_team_abbrev", "_home")
    frame = canonical_column(frame, "away_team_abbrev", "_away")
    if subject_type == "player":
        if "athlete_id_1" not in frame.columns:
            return frame.head(0)
        ids = {value for value in frame.get_column("athlete_id_1").cast(pl.String).drop_nulls().unique().to_list()
               if identifier(value) == identifier(subject_id)}
        frame = frame.filter(pl.col("athlete_id_1").cast(pl.String).is_in(sorted(ids)))
        subject_team = pl.col("_shooting_team")
    else:
        team = _canonical(subject_id) or str(subject_id).upper()
        if side == "defense":
            frame = frame.filter(((pl.col("_home") == team) | (pl.col("_away") == team)) & (pl.col("_shooting_team") != team))
        else:
            frame = frame.filter(pl.col("_shooting_team") == team)
        subject_team = pl.lit(team)
    if frame.is_empty():
        return frame
    made = (pl.col("scoring_play").cast(pl.Boolean, strict=False).fill_null(False) if "scoring_play" in frame.columns
            else pl.lit(False)) | text.str.contains(r"(?i)\bmakes\b")
    three = text.str.contains(r"(?i)three point|three-point|3-pt|3 point")
    if "points_attempted" in frame.columns:
        three = (pl.col("points_attempted").cast(pl.Int64, strict=False) == 3) | three
    raw_x = pl.col("coordinate_x_raw").cast(pl.Float64, strict=False) if "coordinate_x_raw" in frame.columns else pl.lit(None, pl.Float64)
    raw_y = pl.col("coordinate_y_raw").cast(pl.Float64, strict=False) if "coordinate_y_raw" in frame.columns else pl.lit(None, pl.Float64)
    near = raw_x.is_between(0, 50) & raw_y.is_between(0, 47)
    far = raw_x.is_between(0, 50) & (raw_y > 47) & (raw_y <= 94)
    x = pl.when(near).then(raw_x).when(far).then(50 - raw_x)
    y = pl.when(near).then(raw_y).when(far).then(94 - raw_y)
    # NBA hoop center is 5.25 feet from the baseline on a 50-foot-wide court.
    located = ((x - 25.0) ** 2 + (y - 5.25) ** 2).sqrt()
    described = text.str.extract(r"(\d+(?:\.\d+)?)\s*[- ]\s*(?:foot|feet)\b", 1).cast(pl.Float64, strict=False)
    recorded = pl.col("shot_distance").cast(pl.Float64, strict=False) if "shot_distance" in frame.columns else pl.lit(None, pl.Float64)
    distance = pl.coalesce(recorded, described, located)
    home_score = pl.col("home_score").cast(pl.Float64, strict=False) if "home_score" in frame.columns else pl.lit(None, pl.Float64)
    away_score = pl.col("away_score").cast(pl.Float64, strict=False) if "away_score" in frame.columns else pl.lit(None, pl.Float64)
    points = (pl.when(made).then(pl.when(three).then(3).otherwise(2)).otherwise(0)).cast(pl.Float64)
    shooter_home = pl.col("_shooting_team") == pl.col("_home")
    shooter_before = pl.when(shooter_home).then(home_score).otherwise(away_score) - points
    other_before = pl.when(shooter_home).then(away_score).otherwise(home_score)
    subject_shooting = pl.col("_shooting_team") == subject_team
    margin = pl.when(subject_shooting).then(shooter_before - other_before).otherwise(other_before - shooter_before)
    period = pl.col("period").cast(pl.Int64, strict=False) if "period" in frame.columns else pl.lit(None, pl.Int64)
    frame = frame.with_columns(
        made.alias("_made"), three.alias("_three"), points.alias("_points"), distance.alias("_distance"),
        margin.alias("_margin"), period.alias("_period"), _clock_seconds(frame).alias("_period_seconds"),
    )
    return frame.with_columns(
        pl.when(pl.col("_three")).then(pl.lit("Three")).when(pl.col("_distance").is_null()).then(pl.lit("Unlocated two"))
        .when(pl.col("_distance") <= 4).then(pl.lit("Rim")).when(pl.col("_distance") <= 14).then(pl.lit("Short midrange"))
        .otherwise(pl.lit("Long midrange")).alias("_zone"),
        pl.when(pl.col("_period") >= 5).then(pl.lit("OT")).when(pl.col("_period").is_between(1, 4))
        .then(pl.concat_str(pl.lit("Q"), pl.col("_period").cast(pl.String))).alias("_split_period"),
        pl.when(pl.col("_margin") > 0).then(pl.lit("Leading")).when(pl.col("_margin") < 0).then(pl.lit("Trailing"))
        .when(pl.col("_margin") == 0).then(pl.lit("Tied")).alias("_split_score_state"),
        pl.when(pl.col("_period").is_null() | pl.col("_margin").is_null() | pl.col("_period_seconds").is_null()).then(None)
        .when((pl.col("_period") >= 4) & (pl.col("_period_seconds") <= 300) & (pl.col("_margin").abs() <= 5))
        .then(pl.lit("Clutch")).otherwise(pl.lit("Non-clutch")).alias("_split_clutch"),
    )


def effective_fg(frame: pl.DataFrame) -> float | None:
    if frame.is_empty():
        return None
    made, threes = frame["_made"].sum(), (frame["_made"] & frame["_three"]).sum()
    return float((made + 0.5 * threes) / frame.height)


def _evidence(metric: str, label: str, before: float, after: float, unit: str, sample: int, payload: dict[str, Any],
              manifest_ids: list[str], execution_id: str, context: dict[str, Any], caveats: list[str]) -> AggregateEvidence:
    return AggregateEvidence(
        evidence_id=stable_id("evidence", payload), metric=metric, label=label, value=round(after - before, 6),
        baseline_value=round(before, 6), comparison_value=round(after, 6), unit=unit, sample_size=sample,
        row_set_sha256=_sha(payload), dataset_manifest_ids=manifest_ids, tool_execution_id=execution_id,
        context=context, caveats=caveats,
    )


def situational_splits(
        *, metric: str, metric_label: str, unit: str, splits: list[str], subject_type: str,
        baseline_games: pl.DataFrame, comparison_games: pl.DataFrame,
        baseline_shots: pl.DataFrame, comparison_shots: pl.DataFrame,
        measure: Callable[[pl.DataFrame], float | None], manifest_ids: list[str], parameters: dict[str, Any],
) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
    """Compare the subject inside each recorded situation, in both windows, with minimum samples."""
    started_at = datetime.now(UTC)
    minimum_attempts = MIN_SPLIT_ATTEMPTS.get(subject_type, 20)
    parameters = {**parameters, "metric": metric, "splits": splits, "minimum_games": MIN_SPLIT_GAMES,
                  "minimum_field_goal_attempts": minimum_attempts}
    execution_id = stable_id("execution", {"tool": "analyze_situational_split", **parameters})
    evidence: list[AggregateEvidence] = []
    excluded: dict[str, int] = {}
    for split in splits:
        column = f"_split_{split}"
        game_level = split in GAME_SPLITS
        before_frame, after_frame = (baseline_games, comparison_games) if game_level else (baseline_shots, comparison_shots)
        if column not in before_frame.columns or column not in after_frame.columns:
            continue
        values = sorted(set(before_frame[column].drop_nulls().to_list()) & set(after_frame[column].drop_nulls().to_list()))
        for value in values:
            before, after = before_frame.filter(pl.col(column) == value), after_frame.filter(pl.col(column) == value)
            if game_level:
                before_n, after_n = before["game_id"].n_unique(), after["game_id"].n_unique()
                if min(before_n, after_n) < MIN_SPLIT_GAMES:
                    excluded[split] = excluded.get(split, 0) + 1
                    continue
                before_value, after_value = measure(before), measure(after)
                label, split_unit, split_metric = f"{SPLIT_LABELS[split]}: {value} · {metric_label}", unit, metric
                sample_unit = "games"
                caveats = ["Descriptive subgroup comparison over recorded games; subgroups are not controlled for opponent or minutes."]
            else:
                before_n, after_n = before.height, after.height
                if min(before_n, after_n) < minimum_attempts:
                    excluded[split] = excluded.get(split, 0) + 1
                    continue
                before_value, after_value = effective_fg(before), effective_fg(after)
                label, split_unit, split_metric = f"{SPLIT_LABELS[split]}: {value} · eFG% on field-goal attempts", "rate", "effective_fg_pct"
                sample_unit = "field-goal attempts"
                caveats = ["Play-by-play split of field-goal attempts (free throws excluded); it is not the box-score metric."]
            if before_value is None or after_value is None or not all(map(math.isfinite, (before_value, after_value))):
                continue
            payload = {"tool": "analyze_situational_split", **parameters, "split": split, "value": value}
            evidence.append(_evidence(
                f"situational_{split_metric}__{split}", label, before_value, after_value, split_unit, int(after_n), payload,
                manifest_ids, execution_id,
                {"split": split, "split_value": value, "baseline_sample": int(before_n), "comparison_sample": int(after_n),
                 "sample_unit": sample_unit}, caveats))
    execution = ToolExecutionRecord(
        execution_id=execution_id, tool="analyze_situational_split", parameters={**parameters, "excluded_small_subgroups": excluded},
        started_at=started_at, duration_ms=int((datetime.now(UTC) - started_at).total_seconds() * 1000),
        result_sha256=_sha([item.model_dump(mode="json") for item in evidence]), dataset_manifest_ids=manifest_ids,
    )
    return evidence, execution


def stats_shot_attempts(stats_shots: pl.DataFrame, game_ids: set[str], team: str, player_id: str | None = None) -> pl.DataFrame:
    """NBA Stats shot-chart attempts with the officially recorded distance, in the same zone scheme."""
    required = {"game_id", "team_abbreviation", "shot_value", "shot_distance", "shot_result"}
    if stats_shots.is_empty() or not required <= set(stats_shots.columns):
        return pl.DataFrame()
    frame = canonical_column(stats_shots.with_columns(pl.col("game_id").cast(pl.String)), "team_abbreviation", "_team")
    frame = frame.filter((pl.col("_team") == team) & pl.col("game_id").is_in(sorted(game_ids)))
    if player_id is not None:
        if "player_id" not in frame.columns:
            return frame.head(0)
        frame = frame.filter(pl.col("player_id").cast(pl.String) == identifier(player_id))
    value = pl.col("shot_value").cast(pl.Int64, strict=False)
    distance = pl.col("shot_distance").cast(pl.Float64, strict=False)
    made = pl.col("shot_result").cast(pl.String).str.to_lowercase().str.starts_with("made")
    return frame.with_columns(
        made.alias("_made"), (value == 3).alias("_three"), pl.when(made).then(value).otherwise(0).cast(pl.Float64).alias("_points"),
        pl.when(value == 3).then(pl.lit("Three")).when(distance.is_null()).then(pl.lit("Unlocated two"))
        .when(distance <= 4).then(pl.lit("Rim")).when(distance <= 14).then(pl.lit("Short midrange"))
        .otherwise(pl.lit("Long midrange")).alias("_zone"),
    )


ROLLING_GAMES = 5
MIN_CHANGE_POINT_SIDE = 5


def rolling_mean(values: list[float], window: int = ROLLING_GAMES) -> list[float | None]:
    """Trailing mean of the last ``window`` games; None until enough games have been played."""
    return [None if index + 1 < window else sum(values[index + 1 - window: index + 1]) / window for index in range(len(values))]


def trend_pattern(before: list[float], after: list[float]) -> dict[str, Any] | None:
    """Whether the window-over-window change holds across aligned blocks of games.

    Games are grouped into consecutive blocks (10 games, or 5 when a window has fewer than 30) and
    aligned by position. ``sustained`` means at least two thirds of block pairs move the same way as
    the overall change; ``outlier-concentrated`` means fewer than 40% do.
    """
    size = 10 if min(len(before), len(after)) >= 30 else 5
    blocks = min(len(before), len(after)) // size
    if blocks < 2:
        return None

    def means(values: list[float]) -> list[float]:
        return [sum(values[index * size:(index + 1) * size]) / size for index in range(blocks)]

    base, comp = means(before), means(after)
    overall = sum(after) / len(after) - sum(before) / len(before)
    agree = [(right - left) * overall > 0 or (right - left == 0 and overall == 0) for left, right in zip(base, comp, strict=True)]
    rate = sum(agree) / len(agree)
    return {"agreement_rate": rate, "blocks": blocks, "block_games": size, "overall_change": overall,
            "classification": "sustained" if rate >= 2 / 3 else "mixed" if rate >= 0.4 else "outlier-concentrated"}


def change_point(values: list[float], minimum: int = MIN_CHANGE_POINT_SIDE) -> dict[str, Any] | None:
    """The split of an ordered game series with the largest before/after difference in means."""
    best = None
    for index in range(minimum, len(values) - minimum + 1):
        left, right = values[:index], values[index:]
        before, after = sum(left) / len(left), sum(right) / len(right)
        if best is None or abs(after - before) > abs(best["after"] - best["before"]):
            best = {"index": index, "before": before, "after": after}
    # A flat series has no shift to report.
    return best if best and best["after"] != best["before"] else None


def zone_profile(shots: pl.DataFrame) -> dict[str, dict[str, float]]:
    profile = {zone: {"attempts": 0.0, "makes": 0.0, "points": 0.0} for zone in ZONES}
    if shots.is_empty():
        return profile
    for row in shots.group_by("_zone").agg(pl.len().alias("attempts"), pl.col("_made").sum().alias("makes"),
                                           pl.col("_points").sum().alias("points")).iter_rows(named=True):
        profile[row["_zone"]] = {"attempts": float(row["attempts"]), "makes": float(row["makes"]), "points": float(row["points"])}
    return profile


def shot_mix_accounting(before: dict[str, dict[str, float]], after: dict[str, dict[str, float]], subject: dict[str, Any],
                        manifest_ids: list[str]) -> tuple[list[AggregateEvidence], ToolExecutionRecord | None, ChartArtifact | None]:
    """Split the change in points per field-goal attempt into shot-mix and within-zone conversion parts.

    change = Σ (share₁ − share₀)·pps₀ + Σ share₁·(pps₁ − pps₀); the two parts reconcile exactly.
    """
    total_before = sum(item["attempts"] for item in before.values())
    total_after = sum(item["attempts"] for item in after.values())
    if not total_before or not total_after:
        return [], None, None
    zones = [zone for zone in ZONES if before[zone]["attempts"] or after[zone]["attempts"]]
    rows = []
    for zone in zones:
        share0, share1 = before[zone]["attempts"] / total_before, after[zone]["attempts"] / total_after
        pps1 = after[zone]["points"] / after[zone]["attempts"] if after[zone]["attempts"] else 0.0
        # An empty baseline zone has zero baseline share, so its baseline value cancels; use pps₁.
        pps0 = before[zone]["points"] / before[zone]["attempts"] if before[zone]["attempts"] else pps1
        rows.append({"zone": zone, "share0": share0, "share1": share1, "pps0": pps0, "pps1": pps1,
                     "mix": (share1 - share0) * pps0, "conversion": share1 * (pps1 - pps0)})
    pps_before = sum(item["points"] for item in before.values()) / total_before
    pps_after = sum(item["points"] for item in after.values()) / total_after
    mix, conversion = sum(row["mix"] for row in rows), sum(row["conversion"] for row in rows)
    if not math.isclose(mix + conversion, pps_after - pps_before, abs_tol=1e-9):
        raise ValueError("NBA shot-mix accounting failed reconciliation")
    parameters = {"method": "shot_mix_conversion_v1", "subject": subject, "zones": zones,
                  "formula": "Σ(share₁−share₀)·pps₀ + Σ share₁·(pps₁−pps₀)", "free_throws": "excluded"}
    execution_id = stable_id("execution", {"tool": "decompose_metric_change", **parameters, "rows": rows})
    caveats = ["Descriptive accounting on recorded field-goal attempts, not causal attribution; free throws are excluded."]
    context = {"role": "accounting_contribution", "validation": "reconciled", "baseline_points_per_attempt": pps_before,
               "comparison_points_per_attempt": pps_after, "baseline_attempts": int(total_before),
               "comparison_attempts": int(total_after)}
    evidence = [
        _evidence("shot_mix_effect", "Shot-mix effect on points per shot", 0.0, mix, "points per field-goal attempt",
                  int(total_after), {**parameters, "part": "mix"}, manifest_ids, execution_id,
                  {**context, "zones": {row["zone"]: row["mix"] for row in rows}}, caveats),
        _evidence("shot_conversion_effect", "Shot-making effect on points per shot", 0.0, conversion,
                  "points per field-goal attempt", int(total_after), {**parameters, "part": "conversion"}, manifest_ids,
                  execution_id, {**context, "zones": {row["zone"]: row["conversion"] for row in rows}}, caveats),
    ]
    for row in rows:
        made0, made1 = before[row["zone"]]["makes"], after[row["zone"]]["makes"]
        attempts0, attempts1 = before[row["zone"]]["attempts"], after[row["zone"]]["attempts"]
        if attempts0 and attempts1:
            evidence.append(_evidence(
                "shot_zone_fg_pct", f"{row['zone']} field-goal percentage", made0 / attempts0, made1 / attempts1, "rate",
                int(attempts1), {**parameters, "part": "zone_fg", "zone": row["zone"]}, manifest_ids, execution_id,
                {"zone": row["zone"], "baseline_attempts": int(attempts0), "comparison_attempts": int(attempts1)}, []))
    execution = ToolExecutionRecord(
        execution_id=execution_id, tool="decompose_metric_change", parameters=parameters, started_at=datetime.now(UTC),
        duration_ms=0, result_sha256=_sha([item.model_dump(mode="json") for item in evidence]), dataset_manifest_ids=manifest_ids,
    )
    chart_rows = [{"part": f"{row['zone']} · {kind}", "contribution": round(row[key], 6)}
                  for row in rows for kind, key in (("mix", "mix"), ("shot-making", "conversion"))]
    chart = ChartArtifact(
        chart_id=stable_id("chart", {"view": "shot-mix-accounting", "execution": execution_id}),
        title="Where the points-per-shot change came from",
        evidence_ids=[item.evidence_id for item in evidence[:2]],
        specification={
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json", "data": {"values": chart_rows}, "mark": "bar",
            "height": 220, "width": "container",
            "encoding": {
                "y": {"field": "part", "type": "nominal", "sort": None, "title": None},
                "x": {"field": "contribution", "type": "quantitative", "scale": {"zero": True},
                      "title": "Contribution to points per field-goal attempt"},
                "tooltip": [{"field": "part", "title": "Zone and part"}, {"field": "contribution", "format": "+.3f"}],
            },
        },
    )
    return evidence, execution, chart
