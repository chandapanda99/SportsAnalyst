"""Game-scoped NCAA/ESPN identity and field aliases from corroborated drives.

No global abbreviation substitutions, player-name joins or clock fabrication.
"""
from __future__ import annotations

import re
from collections import defaultdict

from sports_analyst.datasets.cfb_plays import source_id


def normalized_clock(value):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or ""))
    if not match or int(match[2]) >= 60:
        return None
    return f"{int(match[1])}:{match[2]}"


def field_spot(value):
    match = re.fullmatch(r"([A-Za-z&. -]+)\s*(\d{1,2})", str(value or "").strip())
    if not match or int(match[2]) > 50:
        return None
    return match[1].strip().casefold(), int(match[2])


def yards_to_goal(side, number, possession):
    if number == 50:
        return 50
    if not side or not possession or number is None or not 0 <= number <= 50:
        return None
    return 100 - number if side == possession else number


def _score(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    try:
        result = int(str(value))
        return result if result >= 0 else None
    except (TypeError, ValueError):
        return None


def game_crosswalk(ncaa, summary, game, season):
    header = summary.get("header") or {}
    competitors = (header.get("competitions") or [{}])[0].get("competitors") or []
    teams = ncaa.get("teams") or []
    links, team_evidence = {}, {}
    for row in teams:
        supplied = row.get("espn_team_id")
        candidates = [entry for entry in competitors
                      if entry.get("homeAway") == row.get("home_away")
                      and _score(entry.get("score")) == _score(row.get("final"))
                      and (str((entry.get("team") or {}).get("id")) == str(supplied) if supplied is not None else
                           str(row.get("team") or "").casefold() in {
                               str((entry.get("team") or {}).get(field) or "").casefold()
                               for field in ("displayName", "shortDisplayName", "location", "name")})]
        if len(candidates) == 1 and row.get("team"):
            links[row["team"]] = str(candidates[0]["team"]["id"])
            team_evidence[row["team"]] = "explicit ESPN ID" if supplied is not None else "game/season, exact name, home/away and final score"
    verified = (str(ncaa.get("espn_game_id")) == str(game) and str(header.get("id")) == str(game)
                and ncaa.get("season") == season and ncaa.get("academic_year") == season + 1
                and (header.get("season") or {}).get("year") == season
                and len(teams) == len(competitors) == 2
                and {row.get("home_away") for row in teams} == {"home", "away"}
                and all(str((row.get("team") or {}).get("id") or "").isdigit() for row in competitors)
                and len(links) == len(set(links.values())) == 2
                and set(links.values()) == {str(row["team"]["id"]) for row in competitors})
    by_id = {str(row["team"]["id"]): row for row in competitors}
    if verified:
        verified = all(_score(row.get("final")) is not None
                       and _score(row.get("final")) == _score(by_id[links[row["team"]]].get("score"))
                       and row.get("home_away") in {"home", "away"}
                       and row.get("home_away") == by_id[links[row["team"]]].get("homeAway") for row in teams)
    names = links if verified else {}
    aliases, evidence = defaultdict(set), defaultdict(list)
    for entry in competitors if verified else []:
        alias = entry["team"].get("abbreviation")
        if alias:
            aliases[alias.casefold()].add(str(entry["team"]["id"]))
            evidence[alias.casefold()].append({"method": "ESPN team metadata"})
    espn_aliases = {alias: set(owners) for alias, owners in aliases.items()}

    def drive_signature(row, native):
        if native:
            values = (names.get(row.get("team")), row.get("start_period", row.get("period")),
                      normalized_clock(row.get("start_clock")), row.get("end_period", row.get("period")),
                      normalized_clock(row.get("end_clock")), row.get("n_plays"), row.get("yards"), row.get("end_how"))
        else:
            start, end = row.get("start") or {}, row.get("end") or {}
            values = (source_id(row.get("team"), "teams"), (start.get("period") or {}).get("number"),
                      normalized_clock((start.get("clock") or {}).get("displayValue")), (end.get("period") or {}).get("number"),
                      normalized_clock((end.get("clock") or {}).get("displayValue")), row.get("offensivePlays"),
                      row.get("yards"), row.get("result"))
        return values if all(value is not None for value in values) else None

    source_drives = (summary.get("drives") or {}).get("previous") or []
    current = (summary.get("drives") or {}).get("current")
    if current and not any(str(row.get("id")) == str(current.get("id")) for row in source_drives):
        source_drives = [*source_drives, current]
    indexed = []
    for rows, native in ((ncaa.get("drives") or [], True), (source_drives, False)):
        index = defaultdict(list)
        for row in rows:
            signature = drive_signature(row, native)
            if signature is not None:
                index[signature].append(row)
        indexed.append(index)
    drives = {}
    for signature, left in indexed[0].items():
        right = indexed[1].get(signature, [])
        if not verified or len(left) != 1 or len(right) != 1:
            continue
        native, espn = left[0], right[0]
        native_start = field_spot(native.get("start_yard_line"))
        espn_start = field_spot((espn.get("start") or {}).get("text"))
        if not native_start or not espn_start or native_start[1] != espn_start[1]:
            continue
        owner = espn_aliases.get(espn_start[0], set())
        if len(owner) != 1:
            continue
        drives[native["drive_number"]] = str(espn["id"])
        for phase in ("start", "end"):
            ncaa_spot = field_spot(native.get(f"{phase}_yard_line"))
            espn_spot = field_spot((espn.get(phase) or {}).get("text"))
            if not ncaa_spot or not espn_spot or ncaa_spot[1] != espn_spot[1]:
                continue
            owners = espn_aliases.get(espn_spot[0], set())
            if len(owners) == 1:
                aliases[ncaa_spot[0]].update(owners)
                evidence[ncaa_spot[0]].append({"method": "verified drive boundary", "native_drive": native["drive_number"],
                                             "espn_drive": str(espn["id"]), "boundary": phase})
    conflicts = {alias: sorted(owners) for alias, owners in aliases.items() if len(owners) != 1}
    resolved = {alias: next(iter(owners)) for alias, owners in aliases.items() if len(owners) == 1}
    return {"verified": verified, "team_names": names, "team_identity_evidence": team_evidence if verified else {},
            "aliases": resolved, "alias_evidence": dict(evidence),
            "alias_conflicts": conflicts, "drives": drives}
