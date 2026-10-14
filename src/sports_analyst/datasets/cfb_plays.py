"""Recorded ESPN play context without name-only joins or tracking assumptions."""

from __future__ import annotations

import math
import re
from urllib.parse import urlparse


def source_id(value, kind):
    value = value or {}
    identity = str(value.get("id") or "")
    if identity.isdigit():
        return identity
    match = re.search(rf"/{kind}/(\d+)(?:[/?]|$)", value.get("$ref", ""))
    return match.group(1) if match else None


def finite(value):
    try:
        result = float(value) if value is not None else None
        return result if result is not None and math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def teams_and_athletes(summary):
    teams, athletes = {}, {}
    for entry in (summary.get("header", {}).get("competitions") or [{}])[0].get("competitors") or []:
        team = entry.get("team") or {}
        identity = source_id(team, "teams")
        if not identity:
            continue
        color = str(team.get("color") or "")
        alternate = str(team.get("alternateColor") or "")
        logos = team.get("logos") or []
        logo = team.get("logo") or (logos[0].get("href") if logos else None)
        if logo and (urlparse(logo).scheme != "https" or urlparse(logo).hostname != "a.espncdn.com"):
            logo = None
        teams[identity] = {
            "id": identity,
            "name": team.get("displayName") or identity,
            "abbreviation": team.get("abbreviation"),
            "side": entry.get("homeAway"),
            "color": f"#{color}" if re.fullmatch(r"[\da-fA-F]{6}", color) else "#28516a",
            "alternate_color": f"#{alternate}" if re.fullmatch(r"[\da-fA-F]{6}", alternate) else "#eef6fa",
            "logo": logo,
        }
    for entry in (summary.get("boxscore") or {}).get("players") or []:
        team_id = source_id(entry.get("team"), "teams")
        for category in entry.get("statistics") or []:
            for item in category.get("athletes") or []:
                athlete = item.get("athlete") or {}
                identity = source_id(athlete, "athletes")
                if identity:
                    athletes[identity] = {
                        "name": athlete.get("displayName"),
                        "position": (athlete.get("position") or {}).get("abbreviation"),
                        "team_id": team_id if team_id in teams else None,
                    }
    return teams, athletes


def recorded_play(play, summary, directory=None):
    teams, athletes = directory or teams_and_athletes(summary)
    start, end = play.get("start") or {}, play.get("end") or {}
    possession = source_id(start.get("team"), "teams")
    end_team = source_id(end.get("team"), "teams")
    participants = []
    seen = set()
    for entry in play.get("participants") or []:
        identity = source_id(entry.get("athlete"), "athletes")
        role = str(entry.get("type") or "participant")
        if not identity or (identity, role) in seen:
            continue
        seen.add((identity, role))
        known = athletes.get(identity, {})
        match = re.search(r"/competitors/(\d+)/roster/", (entry.get("statistics") or {}).get("$ref", ""))
        attributed_team = match.group(1) if match and match.group(1) in teams else known.get("team_id")
        participants.append(
            {
                "athlete_id": identity,
                "role": role,
                "name": known.get("name") or (entry.get("athlete") or {}).get("displayName"),
                "position": known.get("position"),
                "team_id": attributed_team,
                "position_id": source_id(entry.get("position"), "positions"),
                "identity_source": "ESPN structured participant",
            }
        )
    text = str(play.get("text") or "")
    kind = str((play.get("type") or {}).get("text") or "").lower()
    formation = re.search(r"\b(No Huddle[- ]Shotgun|Shotgun|Wildcat|Pistol|I-Formation)\b", text, re.I)
    no_play = kind == "penalty" or bool(re.search(r"\bno play\b|play nullified", text, re.I))
    roles = {entry["role"] for entry in participants}
    is_pass = bool(roles & {"passer", "receiver"}) or any(token in kind for token in ("pass", "sack", "interception"))
    is_rush = "rusher" in roles or "rush" in kind or kind == "run"
    return {
        "id": str(play.get("id") or ""),
        "text": play.get("text"),
        "quarter": (play.get("period") or {}).get("number"),
        "clock": (play.get("clock") or {}).get("displayValue"),
        "down": start.get("down"),
        "distance": finite(start.get("distance")),
        "yards_to_goal": finite(start.get("yardsToEndzone")),
        "end_yards_to_goal": finite(end.get("yardsToEndzone")),
        "team_id": possession if possession in teams else None,
        "end_team_id": end_team if end_team in teams else None,
        "home_score": finite(play.get("homeScore")),
        "away_score": finite(play.get("awayScore")),
        "yards_gained": finite(play.get("statYardage")),
        "play_type": (play.get("type") or {}).get("text"),
        "participants": participants,
        "scoring_play": play.get("scoringPlay"),
        "pass": is_pass, "rush": is_rush,
        "scrimmage": (is_pass or is_rush) and not no_play,
        "no_play": no_play,
        "complete": ("pass reception" in kind or "pass completion" in kind or "passing touchdown" in kind
                     or bool(re.search(r"\bcomplete(?:d)? to\b", text, re.I)))
                    and not bool(re.search(r"\bincomplete\b|intercept", text, re.I)),
        "interception": "intercept" in kind or bool(re.search(r"\bintercepted\b", text, re.I)),
        "turnover": play.get("isTurnover"),
        "touchdown": bool(play.get("scoringPlay") and play.get("scoreValue") == 6),
        "formation": formation.group(1) if formation else None,
        "formation_source": "Recorded play narrative" if formation else None,
        "source_url": play.get("$ref"),
        "alignment_source": "Illustrative actor placement; formation labels do not supply tracking coordinates",
    }
