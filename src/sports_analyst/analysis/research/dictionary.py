"""Field meanings for planner discovery: curated definitions first, then name-based inference.

Each entry says what a recorded column means, its unit, and when it is known:
``context`` (known before the play or game, safe to group or filter on), ``outcome``
(the result being measured), ``identifier`` (keys and names) or ``descriptor``.
Inferred entries are marked as such; they are hints, not verified definitions.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import polars as pl


@dataclass(frozen=True)
class Field:
    description: str
    unit: str | None = None
    timing: str = "descriptor"
    aliases: tuple[str, ...] = ()
    values: str | None = None


def _f(description, unit=None, timing="descriptor", aliases=(), values=None):
    return Field(description, unit, timing, tuple(aliases), values)


CTX, OUT, ID = "context", "outcome", "identifier"

# nflverse play-by-play (nflfastR field definitions, paraphrased).
NFL_PLAY_BY_PLAY = {
    "season": _f("NFL season (year the season started).", "year", CTX),
    "season_type": _f("REG for regular season, POST for postseason.", None, CTX, values="REG|POST"),
    "week": _f("Season week number; postseason weeks follow the regular season.", "week", CTX),
    "game_id": _f("nflverse game identifier (season_week_away_home).", None, ID, ("game",)),
    "play_id": _f("Play identifier, unique within a game.", None, ID),
    "desc": _f("Free-text play description from the official gamebook.", None, "descriptor"),
    "posteam": _f("Team with possession on the play (the offense).", None, ID, ("offense", "possession team")),
    "defteam": _f("Team on defense for the play.", None, ID, ("defense", "defensive team")),
    "home_team": _f("Home team abbreviation.", None, ID, ("home",)),
    "away_team": _f("Away team abbreviation.", None, ID, ("away", "road")),
    "qtr": _f("Quarter of the game (5 = overtime).", "quarter", CTX, ("quarter", "period")),
    "game_clock": _f("Time remaining in the quarter (MM:SS).", None, CTX, ("clock",)),
    "down": _f("Down number (1-4); null on kickoffs, extra points and some penalties.", "down", CTX,
               ("third down", "fourth down", "first down"), values="1|2|3|4"),
    "ydstogo": _f("Yards needed for a first down.", "yards", CTX, ("distance", "to go", "short yardage")),
    "yardline_100": _f("Distance in yards from the opponent's end zone before the play.", "yards", CTX,
                       ("field position", "red zone", "goal line")),
    "goal_to_go": _f("1 when the line to gain is the goal line.", "flag", CTX, ("goal to go", "red zone")),
    "posteam_score": _f("Offense's score before the play.", "points", CTX),
    "defteam_score": _f("Defense's score before the play.", "points", CTX),
    "score_differential": _f("Offense score minus defense score before the play.", "points", CTX,
                             ("game state", "leading", "trailing", "margin")),
    "posteam_timeouts_remaining": _f("Offense timeouts remaining before the play.", "timeouts", CTX),
    "defteam_timeouts_remaining": _f("Defense timeouts remaining before the play.", "timeouts", CTX),
    "half_seconds_remaining": _f("Seconds left in the half before the play.", "seconds", CTX, ("two minute", "end of half")),
    "game_seconds_remaining": _f("Seconds left in the game before the play.", "seconds", CTX, ("late game", "clutch")),
    "shotgun": _f("1 when the offense lined up in shotgun.", "flag", CTX, ("formation",)),
    "no_huddle": _f("1 when the offense ran the play without a huddle.", "flag", CTX, ("tempo", "hurry up")),
    "play_type": _f("Play category: pass, run, punt, field_goal, kickoff, extra_point, qb_kneel, qb_spike, no_play.",
                    None, CTX, ("pass", "run", "rush"), values="pass|run|punt|field_goal|kickoff|extra_point|qb_kneel|qb_spike|no_play"),
    "qb_dropback": _f("1 when the quarterback dropped back (passes, sacks and scrambles).", "flag", CTX, ("dropback", "pass play")),
    "rush_attempt": _f("1 for a designed or recorded rushing attempt.", "flag", CTX, ("rush", "carry", "run play")),
    "pass_attempt": _f("1 for a pass attempt, including sacks in nflverse.", "flag", CTX, ("pass attempt",)),
    "qb_kneel": _f("1 for a quarterback kneel.", "flag", CTX),
    "qb_spike": _f("1 for a quarterback spike.", "flag", CTX),
    "qb_scramble": _f("1 when the quarterback scrambled on a dropback.", "flag", OUT, ("scramble",)),
    "pass_length": _f("Pass depth bucket: short or deep (15+ air yards).", None, CTX, ("deep", "short"), values="short|deep"),
    "pass_location": _f("Pass direction: left, middle or right.", None, CTX, ("direction",), values="left|middle|right"),
    "run_location": _f("Run direction: left, middle or right.", None, CTX, ("direction",), values="left|middle|right"),
    "run_gap": _f("Run gap: end, tackle or guard.", None, CTX, values="end|tackle|guard"),
    "air_yards": _f("Yards the pass travelled past the line of scrimmage.", "yards", OUT, ("depth of target", "adot")),
    "yards_after_catch": _f("Yards gained after the catch.", "yards", OUT, ("yac",)),
    "yards_gained": _f("Yards gained on the play (negative for losses).", "yards", OUT,
                       ("yardage", "gain", "big play", "explosive play", "chunk play")),
    "epa": _f("Expected points added by the play (nflfastR model).", "expected_points", OUT,
              ("efficiency", "expected points", "stopping plays", "explosive play")),
    "wpa": _f("Win probability added by the play.", "win_probability", OUT, ("win probability", "leverage")),
    "wp": _f("Offense win probability before the play.", "probability", CTX, ("win probability",)),
    "success": _f("1 when EPA was positive.", "flag", OUT, ("success rate",)),
    "cpoe": _f("Completion percentage over expected on the pass.", "percentage_points", OUT, ("accuracy",)),
    "cp": _f("Modelled completion probability of the pass.", "probability", CTX),
    "xpass": _f("Modelled probability the offense passes in this situation.", "probability", CTX, ("pass rate over expected", "proe")),
    "pass_oe": _f("Pass over expected (dropback minus xpass), percentage points.", "percentage_points", OUT, ("proe",)),
    "complete_pass": _f("1 for a completed pass.", "flag", OUT, ("completion",)),
    "incomplete_pass": _f("1 for an incomplete pass.", "flag", OUT),
    "interception": _f("1 when the pass was intercepted.", "flag", OUT, ("turnover", "pick")),
    "fumble": _f("1 when a fumble occurred.", "flag", OUT),
    "fumble_lost": _f("1 when the offense lost a fumble.", "flag", OUT, ("turnover",)),
    "sack": _f("1 when the quarterback was sacked.", "flag", OUT, ("pressure", "pass rush")),
    "qb_hit": _f("1 when the quarterback was hit.", "flag", OUT, ("pressure", "pass rush")),
    "touchdown": _f("1 when the play scored a touchdown (either team).", "flag", OUT, ("score", "td")),
    "pass_touchdown": _f("1 for a passing touchdown.", "flag", OUT),
    "rush_touchdown": _f("1 for a rushing touchdown.", "flag", OUT),
    "first_down": _f("1 when the play gained a first down.", "flag", OUT, ("conversion", "chains")),
    "third_down_converted": _f("1 when a third-down play converted.", "flag", OUT, ("third down conversion",)),
    "third_down_failed": _f("1 when a third-down play failed to convert.", "flag", OUT),
    "fourth_down_converted": _f("1 when a fourth-down play converted.", "flag", OUT),
    "fourth_down_failed": _f("1 when a fourth-down play failed to convert.", "flag", OUT),
    "penalty": _f("1 when a penalty was called on the play.", "flag", OUT),
    "penalty_yards": _f("Yards assessed for the penalty.", "yards", OUT),
    "penalty_team": _f("Team penalised.", None, ID),
    "passer_player_id": _f("GSIS ID of the passer.", None, ID, ("quarterback",)),
    "passer_player_name": _f("Passer name.", None, ID),
    "rusher_player_id": _f("GSIS ID of the ball carrier on rushes.", None, ID, ("running back",)),
    "rusher_player_name": _f("Ball carrier name.", None, ID),
    "receiver_player_id": _f("GSIS ID of the targeted receiver.", None, ID, ("target", "receiver")),
    "receiver_player_name": _f("Targeted receiver name.", None, ID),
    "drive": _f("Drive number within the game.", None, ID),
    "series_success": _f("1 when the series earned a first down or touchdown.", "flag", OUT),
    "drive_ended_with_score": _f("1 when the drive ended in a score.", "flag", OUT, ("scoring drive",)),
    "roof": _f("Stadium roof type.", None, CTX, values="outdoors|dome|closed|open"),
    "surface": _f("Playing surface.", None, CTX),
    "temp": _f("Temperature at kickoff (outdoor games).", "fahrenheit", CTX, ("weather",)),
    "wind": _f("Wind speed at kickoff (outdoor games).", "mph", CTX, ("weather",)),
    "spread_line": _f("Closing point spread (home team favoured when positive).", "points", CTX, ("betting", "favorite")),
    "total_line": _f("Closing over/under total.", "points", CTX, ("betting",)),
    "result": _f("Home score minus away score at the end of the game.", "points", OUT),
    "total": _f("Combined final score.", "points", OUT),
    "div_game": _f("1 for a divisional game.", "flag", CTX, ("division",)),
}

# Generic fields shared by ESPN-derived CFB/soccer/NBA tables and nflverse summaries.
COMMON = {
    "game_date": _f("Recorded game date.", "date", CTX, ("date", "month", "chronology")),
    "date": _f("Recorded event date.", "date", CTX, ("month", "chronology")),
    "event_id": _f("Provider game/match identifier.", None, ID, ("game", "match")),
    "team_id": _f("Provider team identifier attributed to the row.", None, ID),
    "opponent_id": _f("Opponent team identifier.", None, ID, ("opponent",)),
    "home_team_id": _f("Home team identifier.", None, ID, ("home", "venue")),
    "away_team_id": _f("Away team identifier.", None, ID, ("away", "road", "venue")),
    "home_score": _f("Home team's final score.", "points", OUT, ("result", "scoring")),
    "away_score": _f("Away team's final score.", "points", OUT, ("result", "scoring")),
    "completed": _f("True when the game is final.", "flag", CTX),
    "neutral_site": _f("True for neutral-site games.", "flag", CTX, ("venue",)),
    "conference_game": _f("True when both teams share a conference.", "flag", CTX, ("conference",)),
    "attendance": _f("Recorded attendance.", "people", CTX),
    "player_id": _f("Provider player identifier.", None, ID),
    "athlete_id": _f("Provider athlete identifier.", None, ID),
    "player_name": _f("Player display name.", None, ID),
    "position": _f("Recorded position.", None, CTX),
    "minutes": _f("Minutes played.", "minutes", OUT, ("playing time", "usage")),
    "points": _f("Points scored.", "points", OUT, ("scoring",)),
    "goals": _f("Goals scored.", "goals", OUT, ("scoring",)),
    "assists": _f("Assists credited.", "assists", OUT, ("playmaking",)),
    "shots": _f("Shots attempted.", "shots", OUT),
    "shots_on_target": _f("Shots on target.", "shots", OUT),
    "xg": _f("Expected goals from the provider's shot model.", "expected_goals", OUT, ("expected goals", "chance quality")),
    "possession": _f("Share of possession recorded by the provider.", "percent", OUT, ("possession",)),
    "targets": _f("Pass targets.", "targets", OUT, ("usage", "target share")),
    "receptions": _f("Receptions.", "receptions", OUT),
    "carries": _f("Rushing attempts.", "carries", OUT, ("usage", "rush")),
    "offense_snaps": _f("Offensive snaps played.", "snaps", OUT, ("snap count", "usage", "playing time")),
    "offense_pct": _f("Share of team offensive snaps played.", "proportion", OUT, ("snap share",)),
    "defense_snaps": _f("Defensive snaps played.", "snaps", OUT, ("snap count", "playing time")),
    "defense_pct": _f("Share of team defensive snaps played.", "proportion", OUT, ("snap share",)),
    "sacks": _f("Sacks credited.", "sacks", OUT, ("pass rush", "pressure")),
    "def_sacks": _f("Sacks credited to the defender.", "sacks", OUT, ("pass rush", "pressure")),
    "def_tackles_for_loss": _f("Tackles for loss credited to the defender.", "tackles", OUT, ("tfl", "disruption", "havoc")),
    "def_pass_defended": _f("Passes defended (breakups) credited to the defender.", "plays", OUT, ("pass breakup", "pbu", "disruption")),
    "def_fumbles_forced": _f("Fumbles forced by the defender.", "fumbles", OUT, ("forced fumble", "disruption", "turnover")),
    "def_interceptions": _f("Interceptions by the defender.", "interceptions", OUT, ("takeaway", "turnover")),
    "def_qb_hits": _f("Quarterback hits credited to the defender.", "hits", OUT, ("pressure", "pass rush")),
    "passing_yards": _f("Passing yards.", "yards", OUT),
    "passing_attempts": _f("Pass attempts.", "attempts", OUT),
    "passing_completions": _f("Completions.", "completions", OUT),
    "rushing_yards": _f("Rushing yards.", "yards", OUT),
    "rushing_attempts": _f("Rushing attempts.", "attempts", OUT),
    "receiving_yards": _f("Receiving yards.", "yards", OUT),
}

DICTIONARY = {("nfl", "play_by_play"): NFL_PLAY_BY_PLAY}

_SUFFIXES = (
    (re.compile(r"(^|_)(id|ids|gsis_id|pfr_id)$"), _f("Identifier.", None, ID)),
    (re.compile(r"(^|_)(name|abbreviation|abbrev)$"), _f("Display name or label.", None, ID)),
    (re.compile(r"yards?($|_)|_yds$"), _f("Yardage.", "yards", OUT)),
    (re.compile(r"(_pct|_rate|_percentage|_share)$"), _f("Rate or share.", "proportion", OUT)),
    (re.compile(r"(^|_)epa($|_)"), _f("Expected points added.", "expected_points", OUT)),
    (re.compile(r"(^|_)xg($|_)|expected_goals"), _f("Expected goals.", "expected_goals", OUT)),
    (re.compile(r"(^|_)(date|datetime|date_time)$"), _f("Date.", "date", CTX)),
    (re.compile(r"(^|_)(attempts|att)$"), _f("Attempt count.", "attempts", OUT)),
    (re.compile(r"(^|_)(made|completions|conversions)$"), _f("Successful-event count.", "count", OUT)),
    (re.compile(r"(^|_)(points|score|goals)$"), _f("Scoring.", "points", OUT)),
    (re.compile(r"(^|_)(snaps)$"), _f("Snap count.", "snaps", OUT)),
)


def describe(sport: str, dataset: str, field: str) -> dict | None:
    """Return a field definition with its ``source``; None when nothing is known."""
    alias, _, name = field.rpartition("__")
    entry = DICTIONARY.get((sport, dataset), {}).get(name) or COMMON.get(name)
    source = "curated"
    if entry is None:
        source = "inferred_from_name"
        entry = next((item for pattern, item in _SUFFIXES if pattern.search(name)), None)
    if entry is None:
        return None
    return {**{key: value for key, value in asdict(entry).items() if value not in (None, ())}, "source": source,
            **({"joined_alias": alias} if alias else {})}


def unit_for(sport: str, dataset: str, field: str) -> str | None:
    entry = describe(sport, dataset, field)
    return entry.get("unit") if entry else None


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for", "from", "had", "has", "have", "he",
    "her", "his", "how", "in", "is", "it", "its", "more", "most", "of", "on", "or", "over", "so", "than", "that", "the",
    "their", "them", "they", "this", "to", "was", "were", "what", "when", "which", "while", "who", "why", "with",
    "change", "changed", "compare", "between", "season", "seasons", "team", "get", "got", "better", "worse",
}


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _words(text: str) -> set[str]:
    return {_stem(word) for word in re.split(r"[^a-z0-9]+", text.lower()) if len(word) > 1 and word not in STOPWORDS}


def search(manifests: dict, concept: str, limit: int = 20) -> list[dict]:
    """Rank recorded fields across authorized datasets by how well they match a concept."""
    terms = _words(concept)
    phrase = concept.lower().strip()
    if not terms:
        raise ValueError("Describe the concept in words, for example 'third down' or 'pass rush pressure'")
    scored = {}
    for dataset_id, manifest in manifests.items():
        for column in manifest.columns:
            entry = describe(manifest.sport, manifest.dataset, column) or {}
            name_words = _words(column.replace("_", " "))
            text_words = _words(entry.get("description", "")) | {w for a in entry.get("aliases", ()) for w in _words(a)}
            score = 3 * len(terms & name_words) + len(terms & text_words)
            if phrase and (phrase in column.lower() or any(phrase in a for a in entry.get("aliases", ()))):
                score += 4
            if score:
                key = (manifest.dataset, column)
                best = scored.get(key)
                hit = {"dataset": manifest.dataset, "field": column, "score": score,
                       "dataset_ids": [dataset_id], "seasons": [manifest.season],
                       **{k: entry[k] for k in ("description", "unit", "timing", "values", "source") if k in entry}}
                if best:
                    best["dataset_ids"].append(dataset_id)
                    best["seasons"].append(manifest.season)
                else:
                    scored[key] = hit
    ranked = sorted(scored.values(), key=lambda item: (-item["score"], item["dataset"], item["field"]))
    for item in ranked:
        item["seasons"] = sorted(set(item["seasons"]))
    return ranked[:max(1, min(limit, 40))]


def profile(frame: pl.DataFrame, field: str, top: int = 12) -> dict:
    """Describe recorded values of one column without returning raw rows."""
    series = frame.get_column(field)
    non_null = series.drop_nulls()
    result = {"field": field, "dtype": str(series.dtype), "rows": frame.height, "non_null": non_null.len(),
              "null_rate": round(1 - non_null.len() / frame.height, 4) if frame.height else None,
              "n_unique": non_null.n_unique()}
    if series.dtype.is_numeric() and non_null.len():
        numeric = non_null.cast(pl.Float64)
        result.update(min=numeric.min(), max=numeric.max(), mean=round(numeric.mean(), 6))
    if non_null.len() and (not series.dtype.is_numeric() or result["n_unique"] <= 25):
        counts = non_null.cast(pl.String).value_counts(sort=True).head(max(1, min(top, 25)))
        result["top_values"] = [{"value": row[field], "rows": row["count"]} for row in counts.iter_rows(named=True)]
    return result
