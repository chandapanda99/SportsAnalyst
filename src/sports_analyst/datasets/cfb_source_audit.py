"""Read-only, bounded matched-game audit; never enables a provider automatically.

Run with ``python -m sports_analyst.datasets.cfb_source_audit --output report.json``.
No API keys, model calls, national play files or optional provider imports.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from sports_analyst.datasets.cfb_plays import source_id
from sports_analyst.datasets.providers import align_plays

SAMPLES = (("6405615", 2025, "FBS", "401754374"), ("129920", 2017, "FCS", "400951055"))
FIELDS = ("formation", "clock", "run_direction", "pass_direction", "pass_depth", "tackler_1", "end_yard_line")
ROOT = "https://raw.githubusercontent.com/sportsdataverse/ncaa-mfb-football-raw/main/mfb/json"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"


def public_json(url):
    request = Request(url, headers={"User-Agent": "OpenSportsAnalyst-source-audit/1"})
    with urlopen(request, timeout=20) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Audit source exceeds the per-request byte bound")
    if url.endswith(".gz"):
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            data = stream.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("Expanded audit payload exceeds its bound")
    return json.loads(data)


def family(value):
    text = str(value or "").lower()
    if any(word in text for word in ("penalty", "no play", "timeout", "coin toss")):
        return None
    if "pass" in text and "intercept" not in text:
        return "pass"
    if "rush" in text or text == "run":
        return "rush"
    return None  # Special teams/turnovers need separately validated alignment rules.


def clock(value):
    if not re.fullmatch(r"\d{1,2}:\d{2}", str(value or "")):
        return None
    minutes, seconds = str(value).split(":")
    return f"{int(minutes)}:{seconds}" if int(seconds) < 60 else None


def audit_game(contest, season, subdivision, game, fetch=public_json):
    if not str(contest).isdigit() or not str(game).isdigit():
        raise ValueError("Audit identifiers must be numeric")
    ncaa_url = f"{ROOT}/{contest}.json.gz"
    summary_url = f"{SITE}/summary?event={game}"
    ncaa, summary = fetch(ncaa_url), fetch(summary_url)
    header = summary.get("header") or {}
    competitors = (header.get("competitions") or [{}])[0].get("competitors") or []
    teams = ncaa.get("teams") or []
    verified = (str(ncaa.get("contest_id")) == contest and str(ncaa.get("espn_game_id")) == game
                and ncaa.get("season") == season and ncaa.get("academic_year") == season + 1
                and str(header.get("id")) == game and (header.get("season") or {}).get("year") == season
                and len(teams) == len(competitors) == 2
                and {str(row.get("espn_team_id")) for row in teams}
                    == {str(row["team"]["id"]) for row in competitors})
    if verified:
        by_id = {str(row["team"]["id"]): row for row in competitors}
        verified = all(str(by_id[str(row["espn_team_id"])].get("score")) == str(row.get("final"))
                       and by_id[str(row["espn_team_id"])].get("homeAway") == row.get("home_away") for row in teams)
    source_plays = []
    for page in range(1, 11):
        data = fetch(f"{CORE}/events/{game}/competitions/{game}/plays?limit=1000&page={page}")
        source_plays.extend(data.get("items") or [])
        if len(source_plays) > 1000:
            raise ValueError("Audit game exceeds the play bound")
        if page >= int(data.get("pageCount", 1)):
            break
    else:
        raise ValueError("Audit pagination was truncated")
    names = {row.get("team"): str(row.get("espn_team_id")) for row in teams}
    aliases = {row["team"].get("abbreviation"): str(row["team"]["id"]) for row in competitors}
    periods = {row.get("drive_number"): row.get("period") for row in ncaa.get("drives") or []}
    secondary = []
    for row in ncaa.get("pbp") or []:
        owner = names.get(row.get("offense"))
        side = aliases.get(row.get("yard_line_side"))
        yard = row.get("yard_line_number")
        yardline = (100 - yard if owner == side else yard) if owner and side and yard is not None else None
        secondary.append({"id": f"{contest}:{row.get('drive_number')}:{row.get('play_number')}",
            "quarter": periods.get(row.get("drive_number")), "clock": clock(row.get("clock")), "team_id": owner,
            "down": row.get("down"), "distance": row.get("distance"), "yards_to_goal": yardline,
            "play_type": None if row.get("no_play") else family(row.get("play_type")), "yards_gained": row.get("yards_gained")})
    primary = []
    for row in source_plays:
        start = row.get("start") or {}
        primary.append({"id": str(row.get("id")), "quarter": (row.get("period") or {}).get("number"),
            "clock": clock((row.get("clock") or {}).get("displayValue")),
            "team_id": source_id(start.get("team"), "teams"),
            "down": start.get("down"), "distance": start.get("distance"), "yards_to_goal": start.get("yardsToEndzone"),
            "play_type": family((row.get("type") or {}).get("text")), "yards_gained": row.get("statYardage")})
    aligned = align_plays(primary, secondary, game_verified=verified)
    return {"contest_id": contest, "espn_game_id": game, "season": season, "subdivision": subdivision,
            "game_team_identity_verified": verified, "ncaa_url": ncaa_url, "espn_url": summary_url,
            "source_sha256": {"ncaa": hashlib.sha256(json.dumps(ncaa, sort_keys=True).encode()).hexdigest(),
                              "espn": hashlib.sha256(json.dumps(source_plays, sort_keys=True).encode()).hexdigest()},
            "ncaa_rows": len(secondary), "espn_rows": len(primary),
            "ncaa_unresolved_field_position": sum(row["yards_to_goal"] is None for row in secondary),
            "espn_unresolved_possession": sum(row["team_id"] is None for row in primary),
            "ncaa_populated_fields": {field: sum(row.get(field) is not None for row in ncaa.get("pbp") or []) for field in FIELDS},
            "conservative_context_matches": len(aligned["matches"]),
            "unmatched_espn": len(aligned["unmatched_primary"]), "unmatched_ncaa": len(aligned["unmatched_secondary"]),
            "automatic_merge_approved": False,
            "limitations": ["Row counts include different administrative event representations; differences are not missing-play counts.",
                            "Formation and direction fields are text-parsed, not tracking.",
                            "NCAA field-side abbreviations must be independently crosswalked; unknown aliases remain unknown.",
                            "Context matches require additional score/sequence validation before production enrichment.",
                            "NCAA player names are not joined to ESPN athlete IDs."]}


def run_audit(fetch=public_json):
    report = {"audited_at": datetime.now(UTC).isoformat(), "adapter_version": "1", "games": [], "failures": []}
    for sample in SAMPLES:
        try:
            report["games"].append(audit_game(*sample, fetch=fetch))
        except Exception as error:
            report["failures"].append({"contest_id": sample[0], "error_type": type(error).__name__})
    report["cfbd"] = {"status": "not_sampled", "automatic_merge_approved": False,
                      "reason": "A scoped CFBD sample and model-version compatibility check remain required; "
                                "no national play asset was downloaded."}
    report["decision"] = "Keep secondary providers audit-only; no universal coverage or automatic field merge is established."
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(run_audit(), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)
