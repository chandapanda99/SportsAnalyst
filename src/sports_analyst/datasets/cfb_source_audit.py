"""Read-only, bounded matched-game audit; never enables a provider automatically.

Run with ``python -m sports_analyst.datasets.cfb_source_audit --output report.json``.
No API keys, model calls or optional provider imports. A CFBD season-asset
download is opt-in through --cfbd-cache and is checksum/size bounded.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from sports_analyst.datasets.cfb_alignment import align_sequences
from sports_analyst.datasets.cfb_normalization import normalized_pair
from sports_analyst.datasets.providers import align_plays

SAMPLES = (("6405615", 2025, "FBS", "401754374"), ("129920", 2017, "FCS", "400951055"),
           ("5362277", 2024, "FBS", "401628439"), ("5835679", 2024, "FCS", "401680057"))
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


def audit_game(contest, season, subdivision, game, fetch=public_json):
    if not str(contest).isdigit() or not str(game).isdigit():
        raise ValueError("Audit identifiers must be numeric")
    ncaa_url = f"{ROOT}/{contest}.json.gz"
    summary_url = f"{SITE}/summary?event={game}"
    ncaa, summary = fetch(ncaa_url), fetch(summary_url)
    if str(ncaa.get("contest_id")) != str(contest):
        raise ValueError("NCAA response has the wrong contest identity")
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
    crosswalk, primary, secondary = normalized_pair(ncaa, summary, source_plays, game, season)
    verified = crosswalk["verified"]
    strict = align_plays(primary, secondary, game_verified=verified)
    aligned = align_sequences(primary, secondary, game_verified=verified)
    by_id = {row["id"]: row for row in secondary}
    eligible = {}
    for identity, native_id in aligned["matches"].items():
        context = aligned["evidence"][identity]
        # An audit-approved link is not a production enablement switch.
        if not context["verified_drive"]:
            continue
        fields = [field for field in FIELDS if by_id[native_id]["raw"].get(field) is not None and field != "clock"]
        if fields:
            eligible[identity] = {"native_id": native_id, "fields": fields, "alignment": context}
    return {"contest_id": contest, "espn_game_id": game, "season": season, "subdivision": subdivision,
            "game_team_identity_verified": verified, "ncaa_url": ncaa_url, "espn_url": summary_url,
            "source_sha256": {"ncaa": hashlib.sha256(json.dumps(ncaa, sort_keys=True).encode()).hexdigest(),
                              "espn_summary": hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest(),
                              "espn": hashlib.sha256(json.dumps(source_plays, sort_keys=True).encode()).hexdigest()},
            "ncaa_rows": len(secondary), "espn_rows": len(primary),
            "ncaa_unresolved_field_position": sum(row["yards_to_goal"] is None for row in secondary),
            "ncaa_unresolved_period": sum(row["quarter"] is None or row["quarter"] < 1 for row in secondary),
            "matched_overtime_plays": sum(row["quarter"] > 4 and row["id"] in aligned["matches"] for row in primary),
            "excluded_penalty_or_no_play_rows": {
                "ncaa": sum(row["penalty"] or row["no_play"] for row in secondary),
                "espn": sum(row["penalty"] or row["no_play"] for row in primary)},
            "espn_unresolved_possession": sum(row["team_id"] is None for row in primary),
            "ncaa_populated_fields": {field: sum(row.get(field) is not None for row in ncaa.get("pbp") or []) for field in FIELDS},
            "conservative_context_matches": len(aligned["matches"]),
            "strict_clock_context_matches": len(strict["matches"]),
            "missing_clock_matches": sum(not row["clock_recorded_both"] for row in aligned["evidence"].values()),
            "clock_disagreement_matches": sum(row["clock_disagreement"] for row in aligned["evidence"].values()),
            "verified_drives": len(crosswalk["drives"]),
            "team_identity_evidence": crosswalk["team_identity_evidence"],
            "field_aliases": crosswalk["aliases"], "alias_evidence": crosswalk["alias_evidence"],
            "alias_conflicts": crosswalk["alias_conflicts"], "ambiguous_espn": aligned["ambiguous_primary"],
            "validated_enrichment_candidates": eligible,
            "alignment_reason": aligned.get("reason"),
            "unmatched_espn": len(aligned["unmatched_primary"]), "unmatched_ncaa": len(aligned["unmatched_secondary"]),
            "automatic_merge_approved": False,
            "limitations": ["Row counts include different administrative event representations; differences are not missing-play counts.",
                            "Formation and direction fields are text-parsed, not tracking.",
                            "Unknown or conflicting field-side aliases remain unresolved; aliases are game-scoped.",
                            "Only unambiguous sequence links in verified drives qualify as enrichment candidates, not production writes.",
                            "Penalties, scoring plays without score agreement, and quarter-spanning drives may remain unmatched.",
                            "NCAA player names are not joined to ESPN athlete IDs."]}


def run_audit(fetch=public_json, *, cfbd_cache=None):
    report = {"audited_at": datetime.now(UTC).isoformat(), "adapter_version": "2", "games": [], "failures": []}
    for sample in SAMPLES:
        try:
            report["games"].append(audit_game(*sample, fetch=fetch))
        except Exception as error:
            report["failures"].append({"contest_id": sample[0], "error_type": type(error).__name__})
    report["cfbd"] = {"status": "not_sampled", "automatic_merge_approved": False,
                      "reason": "A scoped CFBD sample and model-version compatibility check remain required; "
                                "no national play asset was downloaded."}
    if cfbd_cache is not None:
        from sports_analyst.datasets.cfbd_audit import audit_season

        try:
            report["cfbd"] = audit_season(2025, ["401754374"], cfbd_cache, fetch=fetch)
        except Exception as error:
            report["cfbd"] = {"status": "failed", "error_type": type(error).__name__, "automatic_merge_approved": False}
    report["decision"] = ("Game-scoped alias and sequence links are reported individually. "
                          "Production acquisition/resolution remains separate; "
                          "no universal provider approval or model compatibility is inferred.")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cfbd-cache", type=Path, help="Opt in to one bounded, checksum-verified public season-asset download")
    args = parser.parse_args()
    payload = json.dumps(run_audit(cfbd_cache=args.cfbd_cache), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)
