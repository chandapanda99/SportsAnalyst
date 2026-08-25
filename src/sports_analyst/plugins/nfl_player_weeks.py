from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from sports_analyst.models import AnalysisWindow

TEAM_ALIASES = {"JAC": "JAX", "LAR": "LA", "OAK": "LV", "SD": "LAC", "STL": "LA"}
UNAVAILABLE_PATTERNS = ("OUT", "DOUBTFUL", "INACTIVE", "RESERVE", "INJURED RESERVE", "PUP", "IR")
POSITION_GROUPS = {
    "QB": "QB",
    "RB": "RB",
    "FB": "RB",
    "HB": "RB",
    "WR": "WR",
    "TE": "TE",
    "C": "OL",
    "G": "OL",
    "OG": "OL",
    "T": "OL",
    "OT": "OL",
    "OL": "OL",
    "LT": "OL",
    "RT": "OL",
    "LG": "OL",
    "RG": "OL",
    "DE": "DL",
    "DT": "DL",
    "DL": "DL",
    "NT": "DL",
    "EDGE": "DL",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "CB": "DB",
    "DB": "DB",
    "S": "DB",
    "FS": "DB",
    "SS": "DB",
    "K": "ST",
    "P": "ST",
    "LS": "ST",
}


@dataclass
class PlayerWeekLayer:
    frame: pl.DataFrame
    caveats: list[str] = field(default_factory=list)
    source_rows: dict[str, int] = field(default_factory=dict)


def _first(row: dict[str, Any], *names: str) -> Any:
    return next((row[name] for name in names if name in row and row[name] is not None), None)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().upper() in {"1", "TRUE", "T", "YES", "Y"}
    return bool(value)


def _list_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[,;|]", str(value)) if item.strip()]


def _team(value: Any) -> str | None:
    normalized = _text(value)
    if not normalized:
        return None
    upper = normalized.upper()
    return TEAM_ALIASES.get(upper, upper)


def _name_key(value: Any) -> str | None:
    normalized = _text(value)
    if not normalized:
        return None
    return re.sub(r"[^A-Z0-9]", "", normalized.upper()) or None


def _position(value: Any) -> tuple[str | None, str]:
    normalized = (_text(value) or "").upper()
    return (normalized or None), POSITION_GROUPS.get(normalized, normalized or "UNKNOWN")


def _status_severity(value: Any) -> int:
    status = (_text(value) or "").upper()
    if status in {"INA", "PUP", "RES", "RSN", "SUS"}:
        return 3
    if any(pattern in status for pattern in ("RESERVE", "INJURED RESERVE", "PUP", "INACTIVE", "OUT", " IR")):
        return 3
    if "DOUBTFUL" in status:
        return 2
    if "QUESTIONABLE" in status or "LIMITED" in status:
        return 1
    return 0


def _window_weeks(windows: list[AnalysisWindow]) -> dict[int, set[int]]:
    selected: dict[int, set[int]] = defaultdict(set)
    for window in windows:
        selected[window.season].update(range(window.weeks[0], window.weeks[1] + 1))
    return selected


def _selected_rows(frame: pl.DataFrame, columns: tuple[str, ...]):
    selected = [column for column in dict.fromkeys(columns) if column in frame.columns]
    if selected:
        yield from frame.select(selected).iter_rows(named=True)


def normalize_player_weeks(
    team: str,
    windows: list[AnalysisWindow],
    play_by_play: dict[int, pl.DataFrame],
    rosters: dict[int, pl.DataFrame] | None = None,
    injuries: dict[int, pl.DataFrame] | None = None,
    snap_counts: dict[int, pl.DataFrame] | None = None,
    season_type: str = "REG",
    weekly_rosters: dict[int, pl.DataFrame] | None = None,
    participation: dict[int, pl.DataFrame] | None = None,
    depth_charts: dict[int, pl.DataFrame] | None = None,
    player_directory: pl.DataFrame | None = None,
) -> PlayerWeekLayer:
    """Normalize nflverse player context to one row per team, season, week, and player."""
    rosters, injuries, snap_counts = rosters or {}, injuries or {}, snap_counts or {}
    weekly_rosters, participation, depth_charts = weekly_rosters or {}, participation or {}, depth_charts or {}
    selected_weeks = _window_weeks(windows)
    observations: list[dict[str, Any]] = []
    source_rows = {
        "play_by_play": 0,
        "rosters": 0,
        "weekly_rosters": 0,
        "injuries": 0,
        "snap_counts": 0,
        "participation": 0,
        "depth_charts": 0,
        "players": 0,
    }
    played_weeks: dict[int, set[int]] = defaultdict(set)

    def add(
        *,
        source: str,
        season: int,
        week: int,
        player_id: Any = None,
        player_name: Any = None,
        position: Any = None,
        roster_status: Any = None,
        injury_status: Any = None,
        offense_snaps: float = 0,
        defense_snaps: float = 0,
        special_teams_snaps: float = 0,
        targets: int = 0,
        carries: int = 0,
        dropbacks: int = 0,
        opportunities: int = 0,
        opportunity_epa: float = 0,
        participation_offense_snaps: int = 0,
        participation_defense_snaps: int = 0,
        depth_rank: float | None = None,
    ) -> None:
        if week not in selected_weeks.get(season, set()):
            return
        normalized_name = _text(player_name)
        normalized_id = _text(player_id)
        if not normalized_name and not normalized_id:
            return
        raw_position, position_group = _position(position)
        observations.append(
            {
                "source": source,
                "season": season,
                "week": week,
                "player_id": normalized_id,
                "player_name": normalized_name,
                "name_key": _name_key(normalized_name),
                "position": raw_position,
                "position_group": position_group,
                "roster_status": _text(roster_status),
                "injury_status": _text(injury_status),
                "injury_severity": _status_severity(injury_status),
                "offense_snaps": offense_snaps,
                "defense_snaps": defense_snaps,
                "special_teams_snaps": special_teams_snaps,
                "targets": targets,
                "carries": carries,
                "dropbacks": dropbacks,
                "opportunities": opportunities,
                "opportunity_epa": opportunity_epa,
                "participation_offense_snaps": participation_offense_snaps,
                "participation_defense_snaps": participation_defense_snaps,
                "depth_rank": depth_rank,
            }
        )

    for season, frame in play_by_play.items():
        if season not in selected_weeks:
            continue
        for row in _selected_rows(
            frame,
            (
                "posteam",
                "offense_team",
                "team",
                "season_type",
                "week",
                "week_number",
                "epa",
                "receiver_player_name",
                "receiver_name",
                "receiver_player_id",
                "receiver_id",
                "rusher_player_name",
                "rusher_name",
                "rusher_player_id",
                "rusher_id",
                "rush_attempt",
                "play_type",
                "qb_kneel",
                "qb_spike",
                "passer_player_name",
                "passer_name",
                "passer_player_id",
                "passer_id",
                "qb_dropback",
            ),
        ):
            if _team(_first(row, "posteam", "offense_team", "team")) != team:
                continue
            if season_type != "ALL" and _text(row.get("season_type")) not in {None, season_type}:
                continue
            week = int(_number(_first(row, "week", "week_number")))
            if week not in selected_weeks[season]:
                continue
            played_weeks[season].add(week)
            source_rows["play_by_play"] += 1
            epa = _number(row.get("epa"))
            receiver_name = _first(row, "receiver_player_name", "receiver_name")
            receiver_id = _first(row, "receiver_player_id", "receiver_id")
            if receiver_name or receiver_id:
                add(
                    source="play_by_play",
                    season=season,
                    week=week,
                    player_id=receiver_id,
                    player_name=receiver_name,
                    targets=1,
                    opportunities=1,
                    opportunity_epa=epa,
                )
            rusher_name = _first(row, "rusher_player_name", "rusher_name")
            rusher_id = _first(row, "rusher_player_id", "rusher_id")
            rush_attempt = _truthy(row.get("rush_attempt")) or _text(row.get("play_type")) == "run"
            if rush_attempt and not _truthy(row.get("qb_kneel")) and not _truthy(row.get("qb_spike")):
                add(
                    source="play_by_play",
                    season=season,
                    week=week,
                    player_id=rusher_id,
                    player_name=rusher_name,
                    carries=1,
                    opportunities=1,
                    opportunity_epa=epa,
                )
            passer_name = _first(row, "passer_player_name", "passer_name")
            passer_id = _first(row, "passer_player_id", "passer_id")
            dropback = _truthy(row.get("qb_dropback")) or _text(row.get("play_type")) == "pass"
            if dropback:
                add(
                    source="play_by_play",
                    season=season,
                    week=week,
                    player_id=passer_id,
                    player_name=passer_name,
                    position="QB",
                    dropbacks=1,
                )

    for season, frame in participation.items():
        if season not in selected_weeks:
            continue
        for row in _selected_rows(
            frame,
            (
                "nflverse_game_id",
                "game_id",
                "week",
                "possession_team",
                "offense_players",
                "offense_names",
                "offense_positions",
                "defense_players",
                "defense_names",
                "defense_positions",
            ),
        ):
            week = int(_number(row.get("week")))
            if week not in selected_weeks[season]:
                continue
            possession = _team(row.get("possession_team"))
            game_id = str(_first(row, "nflverse_game_id", "game_id") or "")
            is_offense = possession == team
            is_defense = not is_offense and team in game_id.split("_")
            if not is_offense and not is_defense:
                continue
            side = "offense" if is_offense else "defense"
            ids = _list_values(row.get(f"{side}_players"))
            names = _list_values(row.get(f"{side}_names"))
            positions = _list_values(row.get(f"{side}_positions"))
            source_rows["participation"] += 1
            played_weeks[season].add(week)
            for index, player_id in enumerate(ids):
                add(
                    source="participation",
                    season=season,
                    week=week,
                    player_id=player_id,
                    player_name=names[index] if index < len(names) else None,
                    position=positions[index] if index < len(positions) else None,
                    participation_offense_snaps=1 if is_offense else 0,
                    participation_defense_snaps=1 if is_defense else 0,
                )

    for season, frame in snap_counts.items():
        if season not in selected_weeks:
            continue
        for row in _selected_rows(
            frame,
            (
                "team",
                "team_abbr",
                "recent_team",
                "week",
                "week_number",
                "gsis_id",
                "player_id",
                "nfl_id",
                "pfr_player_id",
                "player_name",
                "player",
                "full_name",
                "player_display_name",
                "position",
                "position_group",
                "offense_snaps",
                "offensive_snaps",
                "offense_snap_count",
                "defense_snaps",
                "defensive_snaps",
                "defense_snap_count",
                "st_snaps",
                "special_teams_snaps",
                "special_teams_snap_count",
            ),
        ):
            if _team(_first(row, "team", "team_abbr", "recent_team")) != team:
                continue
            week = int(_number(_first(row, "week", "week_number")))
            if week not in selected_weeks[season]:
                continue
            played_weeks[season].add(week)
            source_rows["snap_counts"] += 1
            add(
                source="snap_counts",
                season=season,
                week=week,
                player_id=_first(row, "gsis_id", "player_id", "nfl_id", "pfr_player_id"),
                player_name=_first(row, "player_name", "player", "full_name", "player_display_name"),
                position=_first(row, "position", "position_group"),
                offense_snaps=_number(_first(row, "offense_snaps", "offensive_snaps", "offense_snap_count")),
                defense_snaps=_number(_first(row, "defense_snaps", "defensive_snaps", "defense_snap_count")),
                special_teams_snaps=_number(_first(row, "st_snaps", "special_teams_snaps", "special_teams_snap_count")),
            )

    for season, frame in injuries.items():
        if season not in selected_weeks:
            continue
        for row in _selected_rows(
            frame,
            (
                "team",
                "team_abbr",
                "recent_team",
                "week",
                "week_number",
                "gsis_id",
                "player_id",
                "nfl_id",
                "full_name",
                "player_name",
                "player_display_name",
                "player",
                "position",
                "position_group",
                "report_status",
                "game_status",
                "practice_status",
                "status",
            ),
        ):
            if _team(_first(row, "team", "team_abbr", "recent_team")) != team:
                continue
            week = int(_number(_first(row, "week", "week_number")))
            if week not in selected_weeks[season]:
                continue
            source_rows["injuries"] += 1
            add(
                source="injuries",
                season=season,
                week=week,
                player_id=_first(row, "gsis_id", "player_id", "nfl_id"),
                player_name=_first(row, "full_name", "player_name", "player_display_name", "player"),
                position=_first(row, "position", "position_group"),
                injury_status=_first(row, "report_status", "game_status", "practice_status", "status"),
            )

    for season, frame in weekly_rosters.items():
        if season not in selected_weeks:
            continue
        for row in _selected_rows(
            frame,
            (
                "team",
                "team_abbr",
                "recent_team",
                "week",
                "week_number",
                "gsis_id",
                "player_id",
                "nfl_id",
                "full_name",
                "player_name",
                "player_display_name",
                "position",
                "position_group",
                "status",
                "roster_status",
            ),
        ):
            if _team(_first(row, "team", "team_abbr", "recent_team")) != team:
                continue
            week = int(_number(_first(row, "week", "week_number")))
            if week not in selected_weeks[season]:
                continue
            status = _first(row, "status", "roster_status")
            source_rows["weekly_rosters"] += 1
            add(
                source="weekly_rosters",
                season=season,
                week=week,
                player_id=_first(row, "gsis_id", "player_id", "nfl_id"),
                player_name=_first(row, "full_name", "player_name", "player_display_name"),
                position=_first(row, "position", "position_group"),
                roster_status=status,
                injury_status=status if _status_severity(status) else None,
            )

    for season, frame in depth_charts.items():
        if season not in selected_weeks:
            continue
        for row in _selected_rows(
            frame,
            (
                "team",
                "team_abbr",
                "week",
                "week_number",
                "gsis_id",
                "player_id",
                "player_name",
                "full_name",
                "position",
                "pos_abb",
                "pos_grp",
                "pos_rank",
                "depth_team",
            ),
        ):
            if _team(_first(row, "team", "team_abbr")) != team:
                continue
            recorded_week = _first(row, "week", "week_number")
            weeks = [int(_number(recorded_week))] if recorded_week else sorted(selected_weeks[season])
            for week in (item for item in weeks if item in selected_weeks[season]):
                source_rows["depth_charts"] += 1
                add(
                    source="depth_charts",
                    season=season,
                    week=week,
                    player_id=_first(row, "gsis_id", "player_id"),
                    player_name=_first(row, "player_name", "full_name"),
                    position=_first(row, "position", "pos_abb", "pos_grp"),
                    depth_rank=_number(_first(row, "pos_rank", "depth_team")) or None,
                )

    weekly_roster_seasons = {season for season, frame in weekly_rosters.items() if not frame.is_empty()}
    roster_rows: list[tuple[int, dict[str, Any]]] = []
    for season, frame in rosters.items():
        if season not in selected_weeks:
            continue
        for row in _selected_rows(
            frame,
            (
                "team",
                "team_abbr",
                "recent_team",
                "full_name",
                "player_name",
                "player_display_name",
                "player",
                "gsis_id",
                "player_id",
                "nfl_id",
                "pfr_player_id",
                "position",
                "position_group",
                "depth_chart_position",
                "status",
                "roster_status",
            ),
        ):
            if _team(_first(row, "team", "team_abbr", "recent_team")) != team:
                continue
            roster_rows.append((season, row))
            source_rows["rosters"] += 1

    canonical_ids: dict[str, str] = {}
    directory_names: dict[str, str] = {}
    if player_directory is not None and not player_directory.is_empty():
        for row in _selected_rows(
            player_directory,
            (
                "gsis_id",
                "pfr_id",
                "pfr_player_id",
                "espn_id",
                "sportradar_id",
                "display_name",
                "full_name",
            ),
        ):
            gsis_id = _text(row.get("gsis_id"))
            if not gsis_id:
                continue
            source_rows["players"] += 1
            for source_id in (_first(row, "gsis_id"), _first(row, "pfr_id", "pfr_player_id"), row.get("espn_id"), row.get("sportradar_id")):
                normalized = _text(source_id)
                if normalized:
                    canonical_ids[normalized] = gsis_id
            name_key = _name_key(_first(row, "display_name", "full_name"))
            if name_key:
                directory_names[name_key] = gsis_id

    identity_ids: dict[tuple[int, str], set[str]] = defaultdict(set)
    for observation in observations:
        if observation["name_key"] and observation["player_id"]:
            identity_ids[(observation["season"], observation["name_key"])].add(observation["player_id"])
    for season, row in roster_rows:
        name = _first(row, "full_name", "player_name", "player_display_name", "player")
        player_id = _text(_first(row, "gsis_id", "player_id", "nfl_id", "pfr_player_id"))
        name_key = _name_key(name)
        if name_key and player_id:
            identity_ids[(season, name_key)].add(player_id)

    def preferred_id(season: int, name_key: str | None, source_id: str | None) -> str:
        if source_id and source_id in canonical_ids:
            return canonical_ids[source_id]
        if name_key and name_key in directory_names:
            return directory_names[name_key]
        candidates = identity_ids.get((season, name_key or ""), set())
        gsis = sorted(candidate for candidate in candidates if candidate.startswith("00-"))
        return (gsis or sorted(candidates) or ([source_id] if source_id else []) or [f"NAME:{name_key}"])[0]

    roster_metadata: dict[tuple[int, str], dict[str, Any]] = {}
    for season, row in roster_rows:
        name = _first(row, "full_name", "player_name", "player_display_name", "player")
        name_key = _name_key(name)
        player_id = preferred_id(season, name_key, _text(_first(row, "gsis_id", "player_id", "nfl_id", "pfr_player_id")))
        raw_position, position_group = _position(_first(row, "position", "position_group", "depth_chart_position"))
        roster_metadata[(season, player_id)] = {
            "player_name": _text(name),
            "position": raw_position,
            "position_group": position_group,
            "roster_status": _text(_first(row, "status", "roster_status")),
        }
        for week in ([] if season in weekly_roster_seasons else sorted(played_weeks.get(season) or selected_weeks[season])):
            add(
                source="rosters",
                season=season,
                week=week,
                player_id=player_id,
                player_name=name,
                position=raw_position,
                roster_status=_first(row, "status", "roster_status"),
            )

    records: dict[tuple[int, int, str], dict[str, Any]] = {}
    for observation in observations:
        player_id = preferred_id(
            observation["season"], observation["name_key"], observation["player_id"]
        )
        key = (observation["season"], observation["week"], player_id)
        metadata = roster_metadata.get((observation["season"], player_id), {})
        record = records.setdefault(
            key,
            {
                "season": observation["season"],
                "week": observation["week"],
                "team": team,
                "player_id": player_id,
                "player_name": metadata.get("player_name") or observation["player_name"] or player_id,
                "position": metadata.get("position") or observation["position"],
                "position_group": metadata.get("position_group") or observation["position_group"],
                "roster_status": metadata.get("roster_status") or observation["roster_status"],
                "injury_status": None,
                "injury_severity": 0,
                "unavailable": False,
                "offense_snaps": 0.0,
                "defense_snaps": 0.0,
                "special_teams_snaps": 0.0,
                "participation_offense_snaps": 0,
                "participation_defense_snaps": 0,
                "depth_rank": None,
                "targets": 0,
                "carries": 0,
                "dropbacks": 0,
                "opportunities": 0,
                "opportunity_epa": 0.0,
                "opportunity_epa_plays": 0,
                "sources": set(),
            },
        )
        record["sources"].add(observation["source"])
        for field_name in ("offense_snaps", "defense_snaps", "special_teams_snaps"):
            record[field_name] = max(record[field_name], observation[field_name])
        for field_name in ("targets", "carries", "dropbacks", "opportunities"):
            record[field_name] += observation[field_name]
        for field_name in ("participation_offense_snaps", "participation_defense_snaps"):
            record[field_name] += observation[field_name]
        if observation["depth_rank"] is not None:
            record["depth_rank"] = min(record["depth_rank"] or observation["depth_rank"], observation["depth_rank"])
        if observation["roster_status"]:
            record["roster_status"] = observation["roster_status"]
        if observation["opportunities"]:
            record["opportunity_epa"] += observation["opportunity_epa"]
            record["opportunity_epa_plays"] += observation["opportunities"]
        if observation["injury_severity"] >= record["injury_severity"]:
            record["injury_status"] = observation["injury_status"]
            record["injury_severity"] = observation["injury_severity"]
            record["unavailable"] = observation["injury_severity"] >= 2
        if record["position_group"] == "UNKNOWN" and observation["position_group"] != "UNKNOWN":
            record["position"], record["position_group"] = observation["position"], observation["position_group"]

    rows = []
    for record in records.values():
        if record["participation_offense_snaps"]:
            record["offense_snaps"] = float(record["participation_offense_snaps"])
        if record["participation_defense_snaps"]:
            record["defense_snaps"] = float(record["participation_defense_snaps"])
        record["total_snaps"] = record["offense_snaps"] + record["defense_snaps"] + record["special_teams_snaps"]
        record["sources"] = ",".join(sorted(record["sources"]))
        rows.append(record)
    frame = pl.DataFrame(rows, infer_schema_length=None).sort("season", "week", "player_id") if rows else pl.DataFrame()
    caveats = [
        "Season-level roster membership is projected only when weekly roster records are unavailable.",
        "Player identities prefer GSIS IDs and otherwise use cross-source name matching; unresolved names may remain separate players.",
        "Play-by-play identifies primary participants; synced participation data supplies recorded on-field players when available.",
    ]
    if not source_rows["snap_counts"] and not source_rows["participation"]:
        caveats.append("Weighted availability and lineup continuity require synced snap counts or participation data.")
    if not source_rows["injuries"]:
        caveats.append("Position-group availability requires synced injury reports.")
    if not source_rows["participation"]:
        caveats.append("Exact play-level lineup participation requires synced participation data.")
    if not source_rows["depth_charts"]:
        caveats.append("Starter and reserve roles require synced depth charts.")
    if not source_rows["players"]:
        caveats.append("Cross-source identity mapping is strongest when the shared player directory is synced.")
    return PlayerWeekLayer(frame=frame, caveats=caveats, source_rows=source_rows)


def _scoped(frame: pl.DataFrame, window: AnalysisWindow) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    return frame.filter(
        (pl.col("season") == window.season)
        & pl.col("week").is_between(window.weeks[0], window.weeks[1], closed="both")
    )


def summarize_player_usage(frame: pl.DataFrame, window: AnalysisWindow) -> dict[str, dict[str, Any]]:
    scoped = _scoped(frame, window)
    if scoped.is_empty():
        return {}
    grouped = scoped.group_by("player_id").agg(
        pl.first("player_name").alias("player_name"),
        pl.first("position").alias("position"),
        pl.first("position_group").alias("position_group"),
        pl.col("targets").sum(),
        pl.col("carries").sum(),
        pl.col("dropbacks").sum(),
        pl.col("opportunities").sum(),
        pl.col("opportunity_epa").sum(),
        pl.col("opportunity_epa_plays").sum(),
        pl.col("offense_snaps").sum(),
        pl.col("defense_snaps").sum(),
        pl.col("special_teams_snaps").sum(),
        pl.col("week").n_unique().alias("weeks"),
    )
    totals = {
        "targets": float(grouped["targets"].sum()),
        "carries": float(grouped["carries"].sum()),
        "dropbacks": float(grouped["dropbacks"].sum()),
        "opportunities": float(grouped["opportunities"].sum()),
    }
    result: dict[str, dict[str, Any]] = {}
    for row in grouped.iter_rows(named=True):
        relevant_snaps = (
            row["offense_snaps"]
            if row["position_group"] in {"QB", "RB", "WR", "TE", "OL"}
            else row["defense_snaps"]
            if row["position_group"] in {"DL", "LB", "DB"}
            else row["special_teams_snaps"]
        )
        result[str(row["player_id"])] = {
            **row,
            "target_share": row["targets"] / totals["targets"] if totals["targets"] else 0.0,
            "carry_share": row["carries"] / totals["carries"] if totals["carries"] else 0.0,
            "dropback_share": row["dropbacks"] / totals["dropbacks"] if totals["dropbacks"] else 0.0,
            "opportunity_share": row["opportunities"] / totals["opportunities"] if totals["opportunities"] else 0.0,
            "opportunities_per_100_snaps": row["opportunities"] / relevant_snaps * 100 if relevant_snaps else None,
            "epa_per_opportunity": (
                row["opportunity_epa"] / row["opportunity_epa_plays"] if row["opportunity_epa_plays"] else None
            ),
            "relevant_snaps": relevant_snaps,
        }
    return result


def summarize_position_availability(frame: pl.DataFrame, window: AnalysisWindow) -> dict[str, dict[str, Any]]:
    scoped = _scoped(frame, window)
    if scoped.is_empty():
        return {}
    weeks = sorted(scoped["week"].unique().to_list())
    groups: dict[str, dict[str, float | int | str]] = defaultdict(
        lambda: {"expected": 0.0, "unavailable": 0.0, "player_weeks": 0, "players": 0, "method": "snap_weighted"}
    )
    for player in scoped.partition_by("player_id", as_dict=False):
        group = str(player["position_group"][0])
        if group == "UNKNOWN":
            continue
        if group in {"QB", "RB", "WR", "TE", "OL"}:
            snap_column = "offense_snaps"
        elif group in {"DL", "LB", "DB"}:
            snap_column = "defense_snaps"
        else:
            snap_column = "special_teams_snaps"
        positive_snaps = [float(value) for value in player[snap_column].to_list() if value and float(value) > 0]
        expected = float(pl.Series(positive_snaps).median()) if positive_snaps else 1.0
        method = "snap_weighted" if positive_snaps else "player_week"
        unavailable_weeks = {int(row["week"]) for row in player.filter(pl.col("unavailable")).iter_rows(named=True)}
        player_weeks = len(weeks)
        groups[group]["expected"] = float(groups[group]["expected"]) + expected * player_weeks
        groups[group]["unavailable"] = float(groups[group]["unavailable"]) + expected * len(unavailable_weeks)
        groups[group]["player_weeks"] = int(groups[group]["player_weeks"]) + player_weeks
        groups[group]["players"] = int(groups[group]["players"]) + 1
        if method == "player_week":
            groups[group]["method"] = "mixed_or_unweighted"
    result: dict[str, dict[str, Any]] = {}
    for group, values in groups.items():
        expected = float(values["expected"])
        unavailable = float(values["unavailable"])
        result[group] = {
            **values,
            "availability_rate": 1 - unavailable / expected if expected else None,
            "unavailable_expected_snaps": unavailable,
        }
    return result


def summarize_lineup_continuity(
    frame: pl.DataFrame,
    baseline: AnalysisWindow,
    comparison: AnalysisWindow,
) -> dict[str, Any]:
    def player_snaps(window: AnalysisWindow) -> dict[str, dict[str, Any]]:
        usage = summarize_player_usage(frame, window)
        return {
            player_id: values
            for player_id, values in usage.items()
            if values["relevant_snaps"] is not None and float(values["relevant_snaps"]) > 0
        }

    base, comp = player_snaps(baseline), player_snaps(comparison)

    def continuity(base_group: dict[str, dict[str, Any]], comp_group: dict[str, dict[str, Any]]) -> dict[str, float | int]:
        base_total = sum(float(value["relevant_snaps"]) for value in base_group.values())
        comp_total = sum(float(value["relevant_snaps"]) for value in comp_group.values())
        returning = set(base_group) & set(comp_group)
        retained = sum(float(comp_group[player]["relevant_snaps"]) for player in returning)
        distributions = set(base_group) | set(comp_group)
        minimum = sum(
            min(
                float(base_group.get(player, {}).get("relevant_snaps", 0)) / base_total if base_total else 0,
                float(comp_group.get(player, {}).get("relevant_snaps", 0)) / comp_total if comp_total else 0,
            )
            for player in distributions
        )
        maximum = sum(
            max(
                float(base_group.get(player, {}).get("relevant_snaps", 0)) / base_total if base_total else 0,
                float(comp_group.get(player, {}).get("relevant_snaps", 0)) / comp_total if comp_total else 0,
            )
            for player in distributions
        )
        return {
            "returning_snap_share": retained / comp_total if comp_total else 0.0,
            "weighted_jaccard": minimum / maximum if maximum else 0.0,
            "baseline_players": len(base_group),
            "comparison_players": len(comp_group),
            "comparison_snaps": int(comp_total),
        }

    overall = continuity(base, comp)
    groups: dict[str, dict[str, float | int]] = {}
    turnover: dict[str, float] = {}
    all_comparison_snaps = sum(float(value["relevant_snaps"]) for value in comp.values())
    position_groups = {str(value["position_group"]) for value in base.values()} | {
        str(value["position_group"]) for value in comp.values()
    }
    for group in sorted(position_groups):
        base_group = {key: value for key, value in base.items() if value["position_group"] == group}
        comp_group = {key: value for key, value in comp.items() if value["position_group"] == group}
        groups[group] = continuity(base_group, comp_group)
        new_player_snaps = sum(
            float(value["relevant_snaps"]) for key, value in comp_group.items() if key not in base_group
        )
        turnover[group] = new_player_snaps / all_comparison_snaps if all_comparison_snaps else 0.0
    return {"overall": overall, "groups": groups, "turnover_contributions": turnover}
