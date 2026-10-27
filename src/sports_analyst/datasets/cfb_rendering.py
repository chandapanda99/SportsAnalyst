"""Preserve provider-derived play geometry without inventing tracking data."""

import json

from sports_analyst.datasets.cfb_plays import finite

RENDER_VERSION = 3
# Exclude injected betting inputs and model decision surfaces.
PROVIDER_FIELDS = (
    "air_yards", "yards_after_catch", "air_yardsToEndzone", "pass_direction", "rush_direction", "pass_depth",
    "qb_hurry", "sack", "completion", "int", "touchdown", "fumble_vec", "fumble_lost", "fumble_recovered",
    "yds_int_return", "yds_fumble_return", "interception_player_name", "fumble_recovered_player_name",
    "yds_punted", "yds_punt_return", "yds_fg", "yds_kickoff", "yds_kickoff_return",
    "punt_tb", "punt_oob", "punt_fair_catch", "punt_downed", "punt_blocked",
    "kickoff_tb", "kickoff_oob", "kickoff_fair_catch", "kickoff_downed", "kickoff_onside",
    "penalty_in_text", "penalty_enforcement", "penalty_negated_play", "penalty_yards_net", "penalty_side",
    "first_down_earned", "first_down_penalty", "goal_to_go", "kneel_down", "new_down", "new_distance",
    "EP_start", "EP_end", "EPA", "wpa_naive", "wp_before_naive", "wp_after_naive",
    "cp", "cp_game_state", "cp_model", "cpoe", "xpass", "pass_oe",
)
RENDER_FIELDS = (
    "air_yards", "yards_after_catch", "air_yards_to_endzone", "pass_direction", "rush_direction", "pass_depth",
    "air_yards_source", "yards_after_catch_source", "pass_direction_source", "rush_direction_source", "pass_depth_source",
    "render_context_version", "render_provider_version", "provider_context_json",
)


def is_nullified(row):
    if row.get("no_play"):
        return True
    try:
        context = json.loads(row.get("provider_context_json") or "{}")
        return context.get("penalty_negated_play") is True or context.get("penalty_enforcement") == "no_play"
    except (TypeError, ValueError, AttributeError):
        return False


def render_context(play, provider_version, recorded=None):
    result = {"render_context_version": RENDER_VERSION, "render_provider_version": provider_version}
    for target, source in (("air_yards", "air_yards"), ("yards_after_catch", "yards_after_catch"),
                           ("air_yards_to_endzone", "air_yardsToEndzone")):
        value = finite(play.get(source))
        if value is not None and (-100 <= value <= 100 if target != "air_yards_to_endzone" else 0 <= value <= 100):
            result[target] = value
            if target != "air_yards_to_endzone":
                result[f"{target}_source"] = "SportsDataverse derivation from ESPN catch/target spot text"
    for key, allowed in (("pass_direction", {"left", "middle", "right"}),
                         ("rush_direction", {"left", "middle", "right"}), ("pass_depth", {"short", "deep"})):
        value = str(play.get(key) or "").lower()
        if value in allowed:
            result[key] = value
            result[f"{key}_source"] = "SportsDataverse parsing of ESPN play text"
    # Older provider builds can carry a corrected/model-state yardage instead
    # of the source play's statYardage. Never render that discrepancy as YAC.
    if recorded is not None and "air_yards" in result:
        net = finite(recorded.get("yards_gained"))
        complete = recorded.get("complete") is True
        if complete and net is not None and not recorded.get("no_play"):
            yac = net - result["air_yards"]
            if -100 <= yac <= 100:
                result["yards_after_catch"] = yac
                result["yards_after_catch_source"] = "Recorded net yards minus SportsDataverse catch-spot-derived air yards"
        elif recorded.get("complete") is False or recorded.get("no_play"):
            result.pop("yards_after_catch", None)
            result.pop("yards_after_catch_source", None)
    context = {key: play[key] for key in PROVIDER_FIELDS
               if isinstance(play.get(key), (str, bool)) or finite(play.get(key)) is not None}
    # Prefer validated source-consistent geometry over stale provider yardage.
    for key in ("air_yards", "yards_after_catch"):
        context.pop(key, None)
        if key in result:
            context[key] = result[key]
    result["provider_context_json"] = json.dumps(context, sort_keys=True, allow_nan=False)
    return result


def hydrate_rows(rows, pipeline, provider_version):
    by_id = {str(play.get("id")): play for play in pipeline.get("plays") or []}
    return [{**row, **render_context(by_id.get(str(row.get("play_id") or row.get("id")), {}), provider_version, row)}
            for row in rows]


def with_render_context(saved, fresh):
    """Refresh geometry and recorded labels; never overwrite saved analysis/model values."""
    from sports_analyst.datasets.cfb_identity import with_identity_context
    from sports_analyst.datasets.cfb_policy import FIELDS, refinement, valid

    saved = with_identity_context(saved, fresh)
    result = {**saved, **{field: fresh[field] for field in RENDER_FIELDS
                         if saved.get(field) is None and fresh.get(field) is not None}}
    old_provenance = json.loads(saved.get("source_provenance_json") or "{}")
    new_provenance = json.loads(fresh.get("source_provenance_json") or "{}")
    copied = set()
    for field in FIELDS.values():
        existing = old_provenance.get("provenance", {}).get(field, {})
        if valid(field, fresh.get(field)) and (not valid(field, saved.get(field)) or
                (existing.get("method") != "recorded" and refinement(field, saved.get(field), fresh.get(field)))):
            result[field] = fresh[field]
            copied.add(field)
            if field + "_source" in fresh:
                result[field + "_source"] = fresh[field + "_source"]
            if field in new_provenance.get("provenance", {}):
                old_provenance.setdefault("provenance", {})[field] = new_provenance["provenance"][field]
    if new_provenance.get("source_policy"):
        for section in ("source_policy", "alignment", "secondary_status", "conflicts"):
            old_provenance[section] = {**old_provenance.get(section, {}), **new_provenance.get(section, {})}
        old_provenance["source_policy"]["decisions"] = {
            field: decision if field in copied or saved.get(field) == fresh.get(field) else {
                **decision, "selected_provider": old_provenance.get("provenance", {}).get(field, {}).get("provider_id", "saved_snapshot"),
                "reason": "Saved cited context retained; fresh context is not a compatible refinement"}
            for field, decision in old_provenance["source_policy"].get("decisions", {}).items()}
        result["source_provenance_json"] = json.dumps(old_provenance, sort_keys=True)
        for field in ("resolution_version", "source_inputs_json", "secondary_coverage_json"):
            if field in fresh:
                result[field] = fresh[field]
    if fresh.get("provider_context_json"):
        result["provider_context_json"] = json.dumps({**json.loads(fresh["provider_context_json"]),
                                                     **json.loads(saved.get("provider_context_json") or "{}")}, sort_keys=True)
        result["render_context_version"] = fresh.get("render_context_version", RENDER_VERSION)
    return result
