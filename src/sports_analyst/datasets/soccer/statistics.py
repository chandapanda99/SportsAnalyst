"""Recorded match counters and explicit, source-specific comparison definitions."""
from __future__ import annotations

import math
import re


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").removesuffix("%"))
        return parsed if math.isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def stat_key(value):
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value)).lower()).strip("_")


ALIASES = {
    "ball_possesion": "possession_pct", "possession": "possession_pct", "possession_percentage": "possession_pct",
    "shots_on_goal": "shots_on_target", "shots_on_target": "shots_on_target", "total_shots": "total_shots",
    "passes": "total_passes", "pass_completions": "accurate_passes", "passes_completed": "accurate_passes",
    "fouls": "fouls_committed", "fouls_conceded": "fouls_committed", "fouls_committed": "fouls_committed",
    "won_tackle": "tackles_won", "total_tackles": "tackles", "interceptions": "interceptions",
    "corner_kicks": "corners", "total_corners": "corners", "yellow_card": "yellow_cards", "red_card": "red_cards",
    "big_chance": "big_chances", "big_chance_missed_title": "big_chances_missed",
    "expected_goals_on_target_variant": "expected_goals_on_target", "expected_goals_on_target": "expected_goals_on_target",
    "keeper_saves": "saves", "accurate_long_balls": "accurate_long_balls",
    "long_balls_accurate": "accurate_long_balls", "matchstats_headers_tackles": "tackles",
    "duel_won": "duels_won", "shot_blocks": "defensive_shot_blocks",
}


# field, label, domain. Additional recorded columns remain available to scoped research.
COUNTERS = [
    ("total_passes", "Passes", "control"), ("accurate_passes", "Completed passes", "control"),
    ("chances_created", "Chances created", "attack"), ("touches_opp_box", "Touches in opposition box", "attack"),
    ("passes_into_final_third", "Passes into final third", "control"),
    ("line_breaking_passes", "Line-breaking passes", "control"),
    ("accurate_crosses", "Completed crosses", "attack"), ("accurate_long_balls", "Completed long balls", "control"),
    ("tackles", "Tackles", "defense"), ("tackles_won", "Tackles won", "defense"),
    ("interceptions", "Interceptions", "defense"), ("clearances", "Clearances", "defense"),
    ("defensive_shot_blocks", "Defensive shot blocks", "defense"), ("recoveries", "Recoveries", "defense"),
    ("duels_won", "Duels won", "defense"), ("aerials_won", "Aerial duels won", "defense"),
    ("saves", "Saves", "defense"), ("corners", "Corners", "attack"),
    ("fouls_committed", "Fouls committed", "defense"), ("offsides", "Offsides", "attack"),
    ("yellow_cards", "Yellow cards", "defense"), ("red_cards", "Red cards", "defense"),
]
MATCH_METRICS = {}
for prefix, source in (("", "team_stats"), ("fotmob_", "match_analytics")):
    for field, label, domain in COUNTERS:
        name = f"{prefix}{field}_per_match"
        MATCH_METRICS[name] = (f"{label} per match" + (" (FotMob)" if prefix else ""), source, domain, field, None, "count")
    MATCH_METRICS[prefix + "pass_completion_rate"] = (
        "Pass completion" + (" (FotMob)" if prefix else ""), source, "control", "accurate_passes", "total_passes", "rate")
for field, label, domain in [
    ("expected_goals", "Expected goals", "attack"),
    ("expected_goals_on_target", "Expected goals on target", "attack"),
    ("expected_assists", "Expected assists", "attack"),
    ("big_chances", "Big chances", "attack"), ("big_chances_missed", "Big chances missed", "attack"),
    ("total_shots", "Shots", "attack"), ("shots_on_target", "Shots on target", "attack"),
]:
    MATCH_METRICS[f"fotmob_{field}_per_match"] = (f"{label} per match (FotMob)", "match_analytics", domain, field, None,
                                                  "goals" if field.startswith("expected") else "count")
for field, label in (("asa_team_xgoals", "ASA team-model xG"), ("asa_player_xgoals", "ASA player-shot-model xG"),
                     ("asa_expected_points", "ASA expected points")):
    MATCH_METRICS[field + "_per_match"] = (label + " per match", "asa_analytics", "attack", field, None,
                                          "points" if field.endswith("points") else "goals")


def measured_value(metric, rows, frame, team_id):
    _, _, _, field, denominator, _ = MATCH_METRICS[metric]
    if not {"game_id", "team_id", field} <= set(frame.columns):
        return None, 0
    games = {str(row["game_id"]) for row in rows}
    selected = [row for row in frame.iter_rows(named=True)
                if str(row["game_id"]) in games and str(row["team_id"]) == team_id]
    source = MATCH_METRICS[metric][1]
    expected_provider = {"match_analytics": "fotmob", "asa_analytics": "asa"}.get(source)
    if expected_provider and any(row.get("provider") != expected_provider for row in selected):
        raise ValueError("Incompatible provider rows; missing values cannot be filled from another model")
    keys = [str(row["game_id"]) for row in selected]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate team-match statistics; refusing to multiply observations")
    pairs = [(number(row.get(field)), number(row.get(denominator)) if denominator else 1.) for row in selected]
    pairs = [(n, d) for n, d in pairs if n is not None and d is not None and n >= 0 and d >= 0
             and (not denominator or n <= d)]
    total = sum(d for _, d in pairs)
    return (sum(n for n, _ in pairs) / total, len(pairs)) if pairs and total > 0 else (None, 0)


EVENT_METRICS = {
    "open_xt_per_match": ("Expected threat per covered match (StatsBomb actions)", "control", "xt"),
    "open_xg_per_match": ("Shot xG per covered match (StatsBomb)", "attack", "xg"),
}


def event_value(metric, rows, frame, team_id):
    field = EVENT_METRICS[metric][2]
    if not {"game_id", "team_id", field} <= set(frame.columns):
        return None, 0
    games = {str(row["game_id"]) for row in rows}
    by_game = {}
    for row in frame.iter_rows(named=True):
        if str(row["game_id"]) in games and str(row["team_id"]) == team_id:
            value = number(row.get(field))
            if value is not None:
                by_game.setdefault(str(row["game_id"]), []).append(value)
    return (sum(sum(values) for values in by_game.values()) / len(by_game), len(by_game)) if by_game else (None, 0)
