"""Recorded ESPN play context without name-only joins or tracking assumptions."""

from __future__ import annotations

import json
import math
import re
from urllib.parse import urlparse

IDENTITY_VERSION = 4
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
RETURNER_ROLES = {"returner", "kick_returner", "punt_returner", "kickoff_returner"}
TACKLE_ROLES = {"tackler", "assisted_by", "tackle_assist"}
INTERCEPTION_ROLES = {"pass_defender", "interceptor", "interception"}
OFFENSE_ROLES = {"passer", "receiver", "rusher"}
DEFENSE_ROLES = {"tackler", "assisted_by", "tackle_assist", "sacker", "sacked_by",
                 "sack_assist", "interceptor", "interception", "pass_defender", "forced_by"}


def role_key(value):
    """ESPN sends camelCase roles (passDefender, sackedBy, assistedBy, forcedBy); compare them as snake_case."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value or "")).lower().replace("-", "_").replace(" ", "_")


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


def leading_count(value):
    match = re.match(r"\s*(\d+)", str(value or ""))
    return int(match.group(1)) if match else 0


def surname(name):
    parts = [part for part in re.sub(r"[.,]", " ", str(name or "")).lower().split() if part not in NAME_SUFFIXES]
    return parts[-1] if parts else ""


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
            labels = category.get("labels") or []
            for item in category.get("athletes") or []:
                athlete = item.get("athlete") or {}
                identity = source_id(athlete, "athletes")
                if not identity:
                    continue
                position = (athlete.get("position") or {}).get("abbreviation")
                known = athletes.setdefault(identity, {
                    "name": athlete.get("displayName"),
                    "position": position,
                    "team_id": team_id if team_id in teams else None,
                    "team_source": "ESPN game box score",
                    "name_source": "ESPN box score",
                    "position_source": "ESPN box score position" if position else None,
                    # A box-score line proves the athlete played in this game, not that they were on the field for any snap.
                    "played_in_game": True,
                    "box_score_activity": 0,
                })
                stats = item.get("stats") or []
                known["box_score_activity"] += leading_count(stats[0] if stats else None)
                if category.get("name") == "interceptions":
                    values = dict(zip(labels, stats, strict=False))
                    known["interceptions"] = leading_count(values.get("INT"))
                    known["interception_yards"] = int(finite(values.get("YDS")) or 0)
    return teams, athletes


def box_score_interceptor(athletes, defense, recorded_name, return_yards):
    """The defender the game box score credits with an interception the play record attributes to the offense."""
    candidates = [(identity, known) for identity, known in athletes.items()
                  if known.get("team_id") == defense and known.get("interceptions")]
    if len(candidates) == 1:
        return candidates[0], "the only interceptor credited to the defense in the ESPN game box score"
    named = [item for item in candidates if surname(item[1].get("name")) == surname(recorded_name)]
    if len(named) == 1:
        return named[0], "the only box-score interceptor on the defense with the surname in the play record"
    if return_yards is not None:
        matched = [item for item in (named or candidates)
                   if item[1].get("interceptions") == 1 and item[1].get("interception_yards") == return_yards]
        if len(matched) == 1:
            return matched[0], "the only box-score interceptor on the defense with a matching return distance"
    return None, "the ESPN game box score does not identify a single interceptor on the defense"


def recorded_play(play, summary, directory=None):
    directory = directory or teams_and_athletes(summary)
    teams, athletes = directory[:2]
    positions = directory[2] if len(directory) > 2 else {}
    start, end = play.get("start") or {}, play.get("end") or {}
    possession = source_id(start.get("team"), "teams")
    end_team = source_id(end.get("team"), "teams")
    text = str(play.get("text") or "")
    kind = str((play.get("type") or {}).get("text") or "").lower()
    intercepted = "intercept" in kind or bool(re.search(r"\bintercepted\b", text, re.I))

    def opponent(team):
        return next((identity for identity in teams if identity != team), None) if team in teams and len(teams) == 2 else None

    # On any return the listed tackler brought down the returner, so the tackler is on the other team.
    # The returner's own athlete ID can be wrong (see interception conflicts), so the returning team is
    # taken from the change of possession, not from that ID.
    returner_team = None
    if any(role_key(entry.get("type")) in RETURNER_ROLES for entry in play.get("participants") or []):
        returner_team = opponent(possession) if intercepted else end_team if end_team in teams else opponent(possession)
    participants = []
    seen = set()
    for entry in play.get("participants") or []:
        identity = source_id(entry.get("athlete"), "athletes")
        role = str(entry.get("type") or "participant")
        if not identity or (identity, role) in seen:
            continue
        seen.add((identity, role))
        known = athletes.get(identity, {})
        # ESPN can rewrite a historical participant's statistics $ref to their
        # CURRENT school. Even a season-scoped athlete URL is not proof of a stint.
        # Snap possession/role and the game's box score take precedence instead.
        normalized_role = role_key(role)
        attributed_team, team_source = known.get("team_id"), known.get("team_source")
        # The game's box score or roster is game-scoped. For defensive credits it beats the "not in possession"
        # guess, which is wrong on every punt, kickoff and turnover return. The guess only fills gaps.
        game_team = attributed_team if attributed_team in teams else None
        if possession in teams and normalized_role in OFFENSE_ROLES:
            attributed_team, team_source = possession, "Recorded play possession and offensive role"
        elif not game_team and returner_team and opponent(returner_team) and normalized_role in TACKLE_ROLES:
            attributed_team, team_source = opponent(returner_team), "Recorded return: the tackler opposes the returner"
        elif not game_team and opponent(possession) and normalized_role in DEFENSE_ROLES:
            attributed_team, team_source = opponent(possession), "Recorded play possession and defensive role"
        position_id = source_id(entry.get("position"), "positions")
        position = positions.get(position_id) or (entry.get("position") or {}).get("abbreviation")
        participants.append(
            {
                "athlete_id": identity,
                "role": role,
                "name": known.get("name") or (entry.get("athlete") or {}).get("displayName"),
                "position": position or known.get("position"),
                "team_id": attributed_team,
                "team_source": team_source,
                "position_id": position_id,
                "position_source": "ESPN participant position" if position else known.get("position_source"),
                "name_source": known.get("name_source") or ("ESPN box score" if known.get("name") else "ESPN structured participant"),
                "identity_source": "ESPN structured participant",
            }
        )
    conflicts = []
    defense = opponent(possession)
    if intercepted and defense:
        returned = re.search(r"\breturn(?:ed)? for (-?\d+) y", text, re.I)
        return_yards = int(returned.group(1)) if returned else 0 if re.search(r"\breturn(?:ed)? for no gain", text, re.I) else None
        for actor in participants:
            game_team = athletes.get(actor["athlete_id"], {}).get("team_id")
            if role_key(actor["role"]) not in INTERCEPTION_ROLES or possession not in {game_team, actor["team_id"]}:
                continue
            # ESPN credited an athlete on the offense. Flag it with the box-score credit; never rewrite the recorded ID.
            match, basis = box_score_interceptor(athletes, defense, actor["name"], return_yards)
            conflicts.append({
                "role": "Interception", "source": "ESPN game box score", "basis": basis,
                "recorded_athlete_id": actor["athlete_id"], "recorded_name": actor["name"], "recorded_team_id": possession,
                "box_score_athlete_id": match[0] if match else None, "box_score_name": match[1].get("name") if match else None,
                "box_score_team_id": defense,
            })
            break
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
        "end_down": end.get("down"),
        "end_distance": finite(end.get("distance")),
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
        "attribution_conflicts_json": json.dumps(conflicts, sort_keys=True) if conflicts else None,
        **({"identity_context_version": IDENTITY_VERSION} if len(directory) > 2 else {}),
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
