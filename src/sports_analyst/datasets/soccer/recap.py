"""Native ESPN event context; never cross providers by clock or player name."""
from __future__ import annotations

import json

from sports_analyst.datasets.soccer.statistics import number

CONTEXT_FIELDS = ("id", "provider", "team_id", "athlete_id", "athlete_name", "period",
                  "field_position_x", "field_position_y", "coordinate_system")


def native_context(event, commentary):
    identifier = str(event.get("id") or "")
    candidates = [item.get("play") or {} for item in commentary
                  if identifier and str((item.get("play") or {}).get("id") or "") == identifier]
    # Duplicate broadcasts are not an identity crosswalk. Only use a unique
    # native event reference, corroborating team/period whenever both supply it.
    linked = candidates[0] if len(candidates) == 1 else {}
    team = str((event.get("team") or {}).get("id") or "")
    other_team = str((linked.get("team") or {}).get("id") or "")
    period = number((event.get("period") or {}).get("number"))
    other_period = number((linked.get("period") or {}).get("number"))
    if (team and other_team and team != other_team) or (period is not None and other_period is not None and period != other_period):
        linked = {}
    fx = fy = None
    for item in (event, linked):
        x, y = number(item.get("fieldPositionX")), number(item.get("fieldPositionY"))
        if x is not None and y is not None and 0 <= x <= 2 and 0 <= y <= 1 and (x != 0 or y != 0):
            fx, fy = x, y
            break
    return {"id": identifier, "provider": "espn", "period": period if period is not None else other_period if linked else None,
            "field_position_x": fx, "field_position_y": fy,
            "coordinate_system": "ESPN attacked-goal-relative fractions: half-pitch length and full-pitch width"}


def cached_timeline(connector, competition, season, game_id, timeline):
    """Enrich old saved evidence from its cached summary; no source requests."""
    from sports_analyst.datasets.soccer.connector import SOCCER_COMPETITIONS

    if competition not in SOCCER_COMPETITIONS or not str(game_id).isdigit():
        return timeline
    raw = None
    checkpoint = connector.data_dir / competition / str(season) / "events" / f"{game_id}.json"
    try:
        if checkpoint.exists() and checkpoint.stat().st_size <= 16 * 1024**2:
            raw = json.loads(checkpoint.read_text(encoding="utf-8"))
        elif connector.source_cache:
            raw = connector.source_cache._cached(f"{competition}/{season}/shared-events/{game_id}.json", float("inf"))
    except (OSError, ValueError):
        return timeline
    if not isinstance(raw, dict) or str((raw.get("header") or {}).get("id") or "") != str(game_id):
        return timeline
    try:
        events = connector._parse_summary(raw, "key_events").to_dicts()
    except (ValueError, TypeError, KeyError, AttributeError):
        return timeline
    output = []
    for saved in timeline:
        if saved.get("id"):
            matches = [event for event in events if str(event.get("id")) == str(saved["id"])]
        else:
            # Legacy reports omitted IDs. Require exact native text, clock, type
            # and, where retained, source sequence; never just a nearby minute.
            matches = [event for event in events if all(str(event.get(k) or "") == str(saved.get(k) or "")
                       for k in ("text", "clock", "type")) and (
                           saved.get("sequence") is None or str(event.get("event_sequence")) == str(saved["sequence"]))]
        if len(matches) == 1:
            output.append({**saved, **{key: matches[0].get(key) for key in CONTEXT_FIELDS
                                      if saved.get(key) is None or saved.get(key) == ""}})
        else:
            output.append(saved)
    return output
