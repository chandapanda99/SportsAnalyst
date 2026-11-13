"""Five-player lineups rebuilt from ESPN play-by-play substitutions, for any date-bounded segment.

Period 1 starts with the box-score starters. A later period's starting five is the players who are
subbed out, or credited with an event, before being subbed in; any remaining places are filled from
the previous period's closing five only when exactly enough candidates remain. A period whose
lineup cannot be resolved, or whose substitutions contradict the tracked lineup, is excluded and
counted in the coverage; nothing is guessed.

Possessions use the box-score estimate (FGA − player ORB + TOV + 0.44 × FTA) from the events each
five was on court for; team and dead-ball rebounds are not offensive rebounds.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import polars as pl

from sports_analyst.plugins.nba_context import FREE_THROW, canonical_column, identifier

SOURCE = "play_by_play_reconstruction_v1"
_FREE_THROW = re.compile(FREE_THROW)
_PERIOD_SECONDS = {True: 720.0, False: 300.0}  # regulation quarter, overtime


def _seconds(clock: Any) -> float | None:
    text = str(clock or "").strip()
    if not text:
        return None
    try:
        if ":" in text:
            minutes, seconds = text.split(":", 1)
            return int(minutes) * 60 + float(seconds)
        return float(text)
    except ValueError:
        return None


def _roster(player_box: pl.DataFrame) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], list[str]], dict[str, str]]:
    """(game, player) → team, (game, team) → starters, player → name, all from recorded box-score rows."""
    id_column = next((name for name in ("player_id", "athlete_id") if name in player_box.columns), None)
    if player_box.is_empty() or id_column is None or "starter" not in player_box.columns:
        return {}, {}, {}
    frame = canonical_column(player_box, "team_abbreviation", "_team").filter(pl.col("_team").is_not_null())
    name_column = next((name for name in ("player_name", "athlete_display_name") if name in frame.columns), None)
    team_of: dict[tuple[str, str], str] = {}
    starters: dict[tuple[str, str], list[str]] = defaultdict(list)
    names: dict[str, str] = {}
    columns = ["game_id", id_column, "_team", "starter", *([name_column] if name_column else [])]
    for row in frame.select(columns).iter_rows(named=True):
        game, player = str(row["game_id"]), identifier(row[id_column])
        team_of[(game, player)] = row["_team"]
        if row["starter"] is True:
            starters[(game, row["_team"])].append(player)
        if name_column and row.get(name_column):
            names.setdefault(player, str(row[name_column]))
    return team_of, dict(starters), names


def _credited(row: dict[str, Any]) -> list[str]:
    kind = str(row.get("type_text") or "").casefold()
    if "technical" in kind or "ejection" in kind:
        return []  # bench players and coaches can be charged with these
    return [player for index in (1, 2, 3) if (player := identifier(row.get(f"athlete_id_{index}")))]


def _is_substitution(row: dict[str, Any]) -> bool:
    return "substitution" in str(row.get("type_text") or "").casefold() or " enters the game for " in str(
        row.get("description") or row.get("text") or "")


def _period_start(events: list[dict[str, Any]], team: str, game: str, team_of: dict, previous: set[str] | None) -> set[str] | None:
    entered: set[str] = set()
    start: set[str] = set()
    for row in events:
        if _is_substitution(row):
            entering, leaving = identifier(row.get("athlete_id_1")), identifier(row.get("athlete_id_2"))
            if team_of.get((game, entering)) != team and team_of.get((game, leaving)) != team:
                continue
            if leaving and leaving not in entered:
                start.add(leaving)
            entered.add(entering)
        else:
            for player in _credited(row):
                if team_of.get((game, player)) == team and player not in entered:
                    start.add(player)
    if len(start) < 5 and previous:
        candidates = sorted(previous - start - entered)
        if len(candidates) == 5 - len(start):
            start |= set(candidates)
    return start if len(start) == 5 else None


def reconstruct_lineups(pbp: pl.DataFrame, player_box: pl.DataFrame, game_ids: set[str] | None = None) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Aggregate on-court five-player units per team with points, possessions and minutes."""
    team_of, starters, names = _roster(player_box)
    coverage = {"games": 0, "periods": 0, "resolved_periods": 0, "unresolved_games": 0, "source": SOURCE}
    empty = pl.DataFrame(schema={"team_abbreviation": pl.String, "group_id": pl.String, "group_name": pl.String, "min": pl.Float64,
                                 "poss": pl.Float64, "off_rating": pl.Float64, "def_rating": pl.Float64, "net_rating": pl.Float64})
    if pbp.is_empty() or not team_of or "game_id" not in pbp.columns:
        return empty, coverage
    frame = pbp.filter(pl.col("game_id").cast(pl.String).is_in(sorted(game_ids))) if game_ids else pbp
    frame = canonical_column(canonical_column(canonical_column(frame, "home_team_abbrev", "_home"), "away_team_abbrev", "_away"),
                             "team_abbreviation", "_event_team")
    order = [name for name in ("period", "play_id") if name in frame.columns]
    frame = frame.with_columns(pl.col("play_id").cast(pl.Int64, strict=False).alias("_order") if "play_id" in frame.columns
                               else pl.int_range(pl.len()).alias("_order"))
    totals: dict[tuple[str, tuple[str, ...]], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for game_frame in frame.sort(["game_id", *order[:1], "_order"]).partition_by("game_id", maintain_order=True):
        rows = game_frame.to_dicts()
        game = str(rows[0]["game_id"])
        home, away = rows[0].get("_home"), rows[0].get("_away")
        coverage["games"] += 1
        on_court = {team: set(starters.get((game, team), [])) for team in (home, away)}
        if not home or not away or any(len(players) != 5 for players in on_court.values()):
            coverage["unresolved_games"] += 1
            continue
        previous: dict[str, set[str] | None] = {team: set(players) for team, players in on_court.items()}
        scores = {"home": 0.0, "away": 0.0}
        for period in sorted({int(row.get("period") or 0) for row in rows}):
            events = [row for row in rows if int(row.get("period") or 0) == period]
            coverage["periods"] += 1
            if period > 1:
                on_court = {team: _period_start(events, team, game, team_of, previous[team]) for team in (home, away)}
            resolved = all(players is not None and len(players) == 5 for players in on_court.values())
            clock = _PERIOD_SECONDS[period <= 4]
            period_totals: dict[tuple[str, tuple[str, ...]], dict[str, float]] = defaultdict(lambda: defaultdict(float))
            for row in events:
                home_score, away_score = float(row.get("home_score") or scores["home"]), float(row.get("away_score") or scores["away"])
                scored = {home: home_score - scores["home"], away: away_score - scores["away"]}
                scores = {"home": home_score, "away": away_score}
                now = _seconds(row.get("clock"))
                elapsed = max(0.0, clock - now) if now is not None and now <= clock else 0.0
                clock = now if now is not None and now <= clock else clock
                if not resolved:
                    continue
                units = {team: tuple(sorted(on_court[team])) for team in (home, away)}
                for team, other in ((home, away), (away, home)):
                    unit = period_totals[(team, units[team])]
                    unit["seconds"] += elapsed
                    unit["points_for"] += scored[team]
                    unit["points_against"] += scored[other]
                event_team = row.get("_event_team")
                if event_team in (home, away) and not _is_substitution(row):
                    kind, text = str(row.get("type_text") or ""), str(row.get("description") or row.get("text") or "")
                    free_throw = bool(_FREE_THROW.search(kind) or _FREE_THROW.search(text))
                    parts = {
                        "fga": float(bool(row.get("shooting_play")) and not free_throw),
                        "fta": float(free_throw),
                        "orb": float("offensive rebound" in kind.casefold() and bool(identifier(row.get("athlete_id_1")))),
                        "tov": float("turnover" in kind.casefold() and "no turnover" not in kind.casefold()),
                    }
                    other = away if event_team == home else home
                    for name, value in parts.items():
                        period_totals[(event_team, units[event_team])][f"own_{name}"] += value
                        period_totals[(other, units[other])][f"opp_{name}"] += value
                if _is_substitution(row):
                    entering, leaving = identifier(row.get("athlete_id_1")), identifier(row.get("athlete_id_2"))
                    team = team_of.get((game, entering)) or team_of.get((game, leaving))
                    if team not in on_court or leaving not in on_court[team] or entering in on_court[team]:
                        resolved = False  # the recorded substitution contradicts the tracked five
                        continue
                    on_court[team] = (on_court[team] - {leaving}) | {entering}
            if resolved:
                coverage["resolved_periods"] += 1
                for key, values in period_totals.items():
                    for name, value in values.items():
                        totals[key][name] += value
            previous = {team: set(players) if resolved and players else None for team, players in on_court.items()}
    rows = []
    for (team, unit), values in totals.items():
        own = values["own_fga"] - values["own_orb"] + values["own_tov"] + 0.44 * values["own_fta"]
        opp = values["opp_fga"] - values["opp_orb"] + values["opp_tov"] + 0.44 * values["opp_fta"]
        if own <= 0 or opp <= 0:
            continue
        offense, defense = 100 * values["points_for"] / own, 100 * values["points_against"] / opp
        rows.append({"team_abbreviation": team, "group_id": "-".join(unit),
                     "group_name": " - ".join(names.get(player, player) for player in unit),
                     "min": values["seconds"] / 60, "poss": (own + opp) / 2, "off_rating": offense, "def_rating": defense,
                     "net_rating": offense - defense, "points_for": values["points_for"], "points_against": values["points_against"]})
    coverage["resolved_share"] = round(coverage["resolved_periods"] / coverage["periods"], 4) if coverage["periods"] else 0.0
    return (pl.DataFrame(rows) if rows else empty), coverage
