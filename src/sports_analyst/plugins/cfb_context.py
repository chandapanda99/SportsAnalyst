"""Coverage-aware, text-derived CFB metrics; not model or tracking measurements."""
from math import isfinite
import polars as pl
from sports_analyst.datasets.cfb_rendering import with_render_context, is_nullified

CONTEXT_METRICS = {
    "passing_air_yards": ("air_yards", "mean", "pass", None),
    "passing_yac": ("yards_after_catch", "mean", "complete", None),
    "player_passing_air_yards": ("air_yards", "mean", "pass", "passer_id"),
    "player_passing_yac": ("yards_after_catch", "mean", "complete", "passer_id"),
    "player_receiving_air_yards": ("air_yards", "mean", "pass", "receiver_id"),
    "player_receiving_yac": ("yards_after_catch", "mean", "complete", "receiver_id"),
}
CONTEXT_LABELS = {
    "passing_air_yards": ("Air yards/covered pass", "team", "offense"),
    "passing_yac": ("YAC/covered completion", "team", "offense"),
    "player_passing_air_yards": ("Air yards/verified covered pass", "player", "quarterback"),
    "player_passing_yac": ("YAC/verified covered completion", "player", "quarterback"),
    "player_receiving_air_yards": ("Air yards/verified covered target", "player", "receiving"),
    "player_receiving_yac": ("YAC/verified covered reception", "player", "receiving"),
}


def context_frame(recorded, modeled):
    by_id = {(row["game_id"], str(row["play_id"])): row for row in modeled.to_dicts()} if not modeled.is_empty() else {}
    rows, seen = [], set()
    for row in recorded.to_dicts():
        key = (row["game_id"], str(row["play_id"]))
        seen.add(key)
        extra = by_id.get(key, {})
        rows.append(with_render_context(row, extra))
    rows.extend(row for key, row in by_id.items() if key not in seen and "participants" in row)
    return pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame()


def context_values(metric, schedule, stats, subject):
    field, _, kind, role = CONTEXT_METRICS[metric]
    games = set(schedule["game_id"].to_list())
    eligible, values, seen = 0, [], set()
    for row in stats.to_dicts():
        key = (row.get("game_id"), str(row.get("play_id") or row.get("id")))
        if key in seen or key[0] not in games or not row.get("scrimmage") or is_nullified(row) or not row.get(kind):
            continue
        if role:
            ids = {str(actor.get("athlete_id")) for actor in row.get("participants") or []
                   if actor.get("role") == role.removesuffix("_id") and actor.get("athlete_id")}
            if ids != {subject.id}:
                continue
        elif str(row.get("team_id")) != subject.id:
            continue
        seen.add(key)
        eligible += 1
        value = row.get(field)
        try:
            numeric = float(value) if value is not None and not isinstance(value, bool) else None
        except (ValueError, TypeError):
            numeric = None
        if numeric is not None and isfinite(numeric):
            values.append(numeric)
    return values, eligible
