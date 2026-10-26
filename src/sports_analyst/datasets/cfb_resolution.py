"""Resolve only corroborated play fields, preserving primary facts and conflicts."""
from __future__ import annotations

import json
import math

from sports_analyst.datasets.cfb_alignment import align_sequences
from sports_analyst.datasets.cfb_normalization import event_family, normalized_pair
from sports_analyst.datasets.cfb_policy import FEATURES, FIELDS, resolve_observations
from sports_analyst.datasets.providers import FieldObservation

RESOLUTION_VERSION = "cfb-resolved-2"


def cfbd_pair(payload, summary, source_plays, game, season):
    competitors = ((summary.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or []
    teams = {row.get("homeAway"): str((row.get("team") or {}).get("id")) for row in competitors}
    records = payload.get("rows") or []
    verified = (str(payload.get("game_id")) == game and payload.get("season") == season
                and set(teams) == {"home", "away"} and len(set(teams.values())) == 2
                and bool(records) and all(str(row.get("game_id")) == game and row.get("season") == season
                    and str(row.get("home_team_id")) == teams["home"]
                    and str(row.get("away_team_id")) == teams["away"] for row in records))
    _, primary, _ = normalized_pair({}, summary, source_plays, game, season)
    secondary = []
    for index, row in enumerate(records):
        offense = row.get("offense_play")
        side = "home" if offense and offense == row.get("home") else "away" if offense and offense == row.get("away") else None
        scoring_side = ("home" if row.get("pos_team") == row.get("home") else
                        "away" if row.get("pos_team") == row.get("away") else None)
        # offense_score_play/defense_score_play are scoring-event indicators,
        # NOT the scoreboard. Compare cumulative possession-team scores only.
        home = row.get("pos_team_score") if scoring_side == "home" else row.get("def_pos_team_score") if scoring_side else None
        away = row.get("def_pos_team_score") if scoring_side == "home" else row.get("pos_team_score") if scoring_side else None
        minutes, seconds = row.get("clock_minutes"), row.get("clock_seconds")
        clock = (f"{int(minutes)}:{int(seconds):02d}" if isinstance(minutes, (int, float)) and isinstance(seconds, (int, float))
                 and math.isfinite(minutes) and math.isfinite(seconds) and minutes >= 0 and 0 <= seconds < 60
                 and int(minutes) == minutes and int(seconds) == seconds else None)
        # id_play may be float64 and have lost digits. Never round it into an ID.
        suffix = row.get("new_id")
        exact_id = (game + str(int(suffix)) if isinstance(suffix, (int, float)) and math.isfinite(suffix)
                    and 0 <= suffix <= 2**53 and int(suffix) == suffix else None)
        secondary.append({"id": f"{game}:row:{index}", "espn_id": exact_id, "quarter": row.get("period"),
            "clock": clock, "team_id": teams.get(side), "down": row.get("down"), "distance": row.get("distance"),
            "yards_to_goal": row.get("yards_to_goal"), "end_yards_to_goal": row.get("yards_to_goal_end"),
            "yards_gained": row.get("yards_gained"), "play_type": event_family(row.get("play_type")),
            "home_score": home, "away_score": away, "penalty": bool(row.get("penalty_flag")),
            "no_play": bool(row.get("penalty_no_play")), "raw": row})
    return verified, primary, secondary


def resolve_game(rows, source_plays, summary, game, season, inputs, statuses=None, primary_input=None, policy=None):
    """Inputs are already acquired/verified receipts. Never copy secondary models."""
    feature = (policy or {}).get("feature", "rendering")
    if feature not in FEATURES:
        raise ValueError("Unsupported CFB source-policy feature")
    if feature not in {"rendering", "source_review"}:
        return rows
    observations, alignments, receipts = {}, {}, [primary_input] if primary_input else []
    for provider, (payload, receipt) in inputs.items():
        if provider == "ncaa":
            crosswalk, primary, secondary = normalized_pair(payload, summary, source_plays, game, season)
            verified = crosswalk["verified"]
        else:
            verified, primary, secondary = cfbd_pair(payload, summary, source_plays, game, season)
        aligned = align_sequences(primary, secondary, game_verified=verified)
        by_id = {row["id"]: row for row in secondary}
        primary_by_id = {row["id"]: row for row in primary}
        approved = {}
        for identity, native_id in aligned["matches"].items():
            native, context = by_id[native_id], aligned["evidence"][identity]
            if provider == "ncaa" and not context["verified_drive"]:
                continue
            if provider == "cfbd":
                original = primary_by_id[identity]
                # A lossless reconstructed ID is only corroboration, not permission
                # to ignore scores, situation, end position or sequence validation.
                if native["espn_id"] != identity or any(
                    original.get(field) is None or native.get(field) != original[field]
                    for field in ("end_yards_to_goal", "home_score", "away_score")
                ):
                    continue
            approved[identity] = {"record_id": native_id, **context}
            raw = native["raw"]
            for source, target in FIELDS.items():
                value = raw.get(source)
                if target in {"rush_direction", "pass_direction"}:
                    value = str(value or "").lower()
                    if value not in {"left", "middle", "right"}:
                        continue
                elif ((target == "pass_depth" and value not in {"short", "deep"})
                      or (target == "formation" and (not isinstance(value, str) or not value.strip() or len(value) > 100))
                      or (target == "out_of_bounds" and not isinstance(value, bool))):
                    continue
                if value is not None:
                    observations.setdefault(identity, []).append(FieldObservation(
                        provider_id=provider, source_record_id=native_id, source_url=receipt["source_url"],
                        processing_version=receipt["processing_version"], field=target, value=value, method="text_parsed"))
        alignments[provider] = {"verified_game": verified, "matches": approved,
            "ambiguous": aligned["ambiguous_primary"], "unmatched": len(primary) - len(approved),
            "primary_overtime_plays": sum((row.get("quarter") or 0) > 4 for row in primary),
            "matched_overtime_plays": sum((primary_by_id[key].get("quarter") or 0) > 4 for key in approved),
            "overtime_policy": "Retain all primary ESPN plays; never infer a missing secondary overtime period or possession",
            "model_policy": "Secondary EPA/WPA retained in inputs only; current ESPN model pipeline owns advanced values"}
        receipts.append(receipt)
    result = []
    for row in rows:
        identity = str(row.get("play_id") or row.get("id"))
        provenance = json.loads(row.get("source_provenance_json") or "{}")
        values = observations.get(identity, [])
        for field in {item.field for item in values}:
            if row.get(field) is not None:
                original_source = provenance.get("provenance", {}).get(field, {})
                values.append(FieldObservation(provider_id="espn", source_record_id=identity, source_url=row.get("source_url") or "https://www.espn.com",
                    processing_version="recorded-primary", field=field, value=row[field],
                    method=original_source.get("method", "text_parsed")))
        resolved = resolve_observations(values, (policy or {}).get("feature", "rendering"), provenance.get("provenance", {}))
        for section in ("provenance", "conflicts", "rejected"):
            added = resolved[section]
            if section == "provenance":
                added = {field: {key: value for key, value in metadata.items() if key not in {"value", "field"}}
                         for field, metadata in added.items()}
            provenance[section] = {**provenance.get(section, {}), **added}
        provenance["secondary_status"] = statuses or {}
        provenance["source_policy"] = {**(policy or {}), "decisions": resolved["decisions"]}
        provenance["alignment"] = {provider: report["matches"][identity] for provider, report in alignments.items()
                                   if identity in report["matches"]}
        coverage = {provider: {**{key: value for key, value in report.items() if key not in {"matches", "ambiguous"}},
                              "matched_plays": len(report["matches"]), "ambiguous_plays": len(report["ambiguous"])}
                    for provider, report in alignments.items()}
        labels = {f"{field}_source": f"SportsDataverse {metadata['provider_id']} parsing of published play text"
                  for field, metadata in resolved["provenance"].items() if metadata["provider_id"] != "espn"}
        result.append({**row, **resolved["values"], **labels, "resolution_version": RESOLUTION_VERSION,
                       "source_provenance_json": json.dumps(provenance, sort_keys=True),
                       "source_inputs_json": json.dumps(receipts, sort_keys=True),
                       "secondary_coverage_json": json.dumps(coverage, sort_keys=True)})
    return result
