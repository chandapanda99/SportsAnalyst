"""Versioned feature contracts, field definitions and demand-driven acquisition."""
import json

POLICY_VERSION = "cfb-features-1"
FEATURES = {
    "analysis": {"source": "espn", "rule": "Consistent recorded definitions across comparison windows"},
    "advanced": {"source": "current_model", "rule": "One identical content-hashed model bundle across windows"},
    "rendering": {"source": "field_policy", "rule": "Exact cited play facts stay primary; corroborated context may supplement"},
    "historical_sample": {"source": "separate_scope_only", "rule": "No automatic substitution into existing comparison samples"},
    "source_review": {"source": "enabled_providers", "rule": "Explicit source audit, not feature-driven acquisition"},
}
FIELDS = {"formation": "formation", "run_direction": "rush_direction", "pass_direction": "pass_direction",
          "pass_depth": "pass_depth", "out_of_bounds": "out_of_bounds"}
# These fields were observed and validated in the NCAA captures. The CFBD
# adapter currently establishes crosschecks, not additional rendering fields.
PROVIDER_FIELDS = {"ncaa": frozenset(FIELDS.values()), "cfbd": frozenset()}


def valid(field, value):
    if field in {"rush_direction", "pass_direction"}:
        return value in ("left", "middle", "right")
    if field == "pass_depth":
        return value in ("short", "deep")
    if field == "out_of_bounds":
        return isinstance(value, bool)
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= 100
            and value.strip().lower() not in {"unknown", "not recorded", "not available", "none", "—"})


def refinement(field, original, candidate):
    # A documented semantic refinement, not a string-length/column-count score.
    return (field == "formation" and str(original).strip().lower() == "shotgun"
            and str(candidate).strip().lower() in {"no huddle-shotgun", "no huddle shotgun"})


def demand(rows):
    missing = set()
    for row in rows:
        kind = str(row.get("play_type") or "").lower()
        if row.get("no_play") or any(word in kind for word in ("kick", "punt", "timeout", "penalty")):
            continue
        fields = {"formation"}
        if row.get("pass") or "pass" in kind:
            fields |= {"pass_direction", "pass_depth"}
        if row.get("rush") or "rush" in kind or kind == "run":
            fields.add("rush_direction")
        missing.update(field for field in fields if not valid(field, row.get(field)))
        metadata = json.loads(row.get("source_provenance_json") or "{}").get("provenance", {}).get("formation", {})
        if str(row.get("formation") or "").strip().lower() == "shotgun" and metadata.get("method") != "recorded":
            missing.add("formation")  # Optional no-huddle context has a verified definition.
    return missing


def acquisition_plan(rows, feature, enabled):
    if feature not in FEATURES:
        raise ValueError("Unsupported CFB source-policy feature")
    needed = demand(rows) if feature == "rendering" else set()
    providers = [provider for provider in enabled if feature == "source_review"
                 or (feature == "rendering" and needed & PROVIDER_FIELDS.get(provider, frozenset()))]
    return {"version": POLICY_VERSION, "feature": feature, "needed_fields": sorted(needed), "providers": providers,
            "skipped": {provider: "No verified fields needed for this feature" for provider in enabled if provider not in providers}}


def resolve_observations(values, feature, existing_provenance):
    from sports_analyst.datasets.providers import resolve_fields

    output = {"values": {}, "provenance": {}, "conflicts": {}, "rejected": {}, "decisions": {}}
    for field in sorted({item.field for item in values}):
        candidates = [item for item in values if item.field == field]
        eligible = [item for item in candidates if valid(field, item.value)]
        primary = next((item for item in eligible if item.provider_id == "espn"), None)
        method = existing_provenance.get(field, {}).get("method")
        richer = next((item for item in eligible if primary and item.provider_id == "ncaa"
                       and method != "recorded" and refinement(field, primary.value, item.value)), None)
        priority = ("ncaa", "espn", "cfbd") if richer else ("espn", "ncaa", "cfbd")
        resolved = resolve_fields(eligible, priority)
        for section in output.keys() - {"decisions"}:
            output[section].update(resolved[section])
        if any(item.value != candidates[0].value for item in candidates):
            output["conflicts"][field] = [item.model_dump(mode="json") for item in candidates]
        invalid = [item.model_dump(mode="json") for item in candidates if item not in eligible]
        if invalid:
            output["rejected"][field] = invalid
        output["decisions"][field] = {"feature": feature, "policy_version": POLICY_VERSION,
            "definition": "Narrative formation label, not exact alignment" if field == "formation" else "Parsed play context",
            "selected_provider": resolved["provenance"].get(field, {}).get("provider_id"),
            "reason": "Compatible no-huddle refinement" if richer else
                      "Valid primary context retained" if primary else "Validated corroborated supplementation"}
    return output
