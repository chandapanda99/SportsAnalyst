"""Normalize independently recorded situations, retaining unknowns and raw fields."""
import re

from sports_analyst.datasets.cfb_crosswalk import field_spot, game_crosswalk, normalized_clock, yards_to_goal
from sports_analyst.datasets.cfb_plays import source_id


def event_family(value):
    text = str(value or "").lower()
    if any(word in text for word in ("penalty", "no play", "timeout", "coin toss")):
        return None
    if "pass" in text and "intercept" not in text:
        return "pass"
    if "rush" in text or text == "run":
        return "rush"
    return None


def normalized_pair(ncaa, summary, source_plays, game, season):
    crosswalk = game_crosswalk(ncaa, summary, game, season)
    drives = {row.get("drive_number"): row for row in ncaa.get("drives") or []}
    aliases, names = crosswalk["aliases"], crosswalk["team_names"]
    checkpoints, previous, expected_drive = {}, (0, 0), 1
    for row in sorted(ncaa.get("drive_titles") or [], key=lambda item: item.get("drive_number", 0)):
        current = (row.get("score_home"), row.get("score_away"))
        if (row.get("drive_number") != expected_drive
                or any(not isinstance(value, int) or value < 0 for value in current) or previous is None):
            previous = None
            continue
        if any(a < b for a, b in zip(current, previous, strict=True)):
            previous = None
            continue
        checkpoints[row["drive_number"]] = previous
        previous = current
        expected_drive += 1
    secondary = []
    for row in ncaa.get("pbp") or []:
        owner = names.get(row.get("offense"))
        drive = drives.get(row.get("drive_number"), {})
        start_period = drive.get("start_period", drive.get("period"))
        end_period = drive.get("end_period", drive.get("period"))
        spot = field_spot(row.get("end_yard_line"))
        is_score = row.get("is_touchdown") or row.get("is_safety")
        score = checkpoints.get(row.get("drive_number")) if not is_score else None
        secondary.append({"id": f"{ncaa.get('contest_id')}:{row.get('drive_number')}:{row.get('play_number')}",
            "quarter": start_period if start_period == end_period else None,
            "clock": normalized_clock(row.get("clock")), "team_id": owner,
            "down": row.get("down"), "distance": row.get("distance"),
            "yards_to_goal": yards_to_goal(aliases.get(str(row.get("yard_line_side") or "").casefold()),
                                             row.get("yard_line_number"), owner),
            "end_yards_to_goal": yards_to_goal(aliases.get(spot[0]), spot[1], owner) if spot else None,
            "play_type": event_family(row.get("play_type")), "yards_gained": row.get("yards_gained"),
            "no_play": bool(row.get("no_play")), "penalty": bool(row.get("penalty_flag")),
            "drive_key": crosswalk["drives"].get(row.get("drive_number")),
            "home_score": score[0] if score else None, "away_score": score[1] if score else None,
            "raw": row})
    primary = []
    for row in source_plays:
        start, end = row.get("start") or {}, row.get("end") or {}
        drive = re.search(r"/drives/(\d+)", (row.get("drive") or {}).get("$ref", ""))
        primary.append({"id": str(row.get("id")), "quarter": (row.get("period") or {}).get("number"),
            "clock": normalized_clock((row.get("clock") or {}).get("displayValue")),
            "team_id": source_id(start.get("team"), "teams"), "down": start.get("down"),
            "distance": start.get("distance"), "yards_to_goal": start.get("yardsToEndzone"),
            "end_yards_to_goal": end.get("yardsToEndzone"), "play_type": event_family((row.get("type") or {}).get("text")),
            "yards_gained": row.get("statYardage"), "home_score": row.get("homeScore"), "away_score": row.get("awayScore"),
            "no_play": bool(row.get("noPlay") or re.search(r"\bno play\b|play nullified", row.get("text") or "", re.I)),
            "penalty": bool(row.get("isPenalty") or re.search(r"\bpenalty\b", row.get("text") or "", re.I)),
            "drive_key": drive[1] if drive else None})
    return crosswalk, primary, secondary
