"""Host-owned definitions and comparison signatures; unknown units stay explicit."""
from sports_analyst.analysis.research.contracts import VERSION, contract

# Exact recorded counter pairs, not arbitrary arithmetic supplied by a model.
RATE_PAIRS = {
    ("completions", "attempts"): ("completion_rate", "proportion"),
    ("passing_completions", "passing_attempts"): ("completion_rate", "proportion"),
    ("passing_yards", "passing_attempts"): ("passing_yards_per_attempt", "yards/attempt"),
    ("rushing_yards", "rushing_attempts"): ("rushing_yards_per_attempt", "yards/attempt"),
    ("receiving_yards", "receptions"): ("yards_per_reception", "yards/reception"),
    ("third_down_conversions", "third_down_attempts"): ("third_down_conversion_rate", "proportion"),
    ("fourth_down_conversions", "fourth_down_attempts"): ("fourth_down_conversion_rate", "proportion"),
    ("field_goals_made", "field_goals_attempted"): ("field_goal_rate", "proportion"),
    ("three_point_field_goals_made", "three_point_field_goals_attempted"): ("three_point_rate", "proportion"),
    ("three_pointers_made", "three_pointers_attempted"): ("three_point_rate", "proportion"),
    ("free_throws_made", "free_throws_attempted"): ("free_throw_rate", "proportion"),
    ("goals", "shots"): ("goals_per_shot", "proportion"),
    ("shots_on_target", "shots"): ("shots_on_target_rate", "proportion"),
    ("total_goals", "total_shots"): ("goals_per_shot", "proportion"),
    ("shots_on_target", "total_shots"): ("shots_on_target_rate", "proportion"),
}


def measure_fields(measures):
    return {field for m in measures for field in (m.field, m.denominator) if field}


def rate_definition(measure):
    # Paired eligibility requires both counters from the SAME observation/source.
    prefix, _, numerator = measure.field.rpartition("__")
    other_prefix, _, denominator = measure.denominator.rpartition("__")
    if prefix != other_prefix or (numerator, denominator) not in RATE_PAIRS:
        raise ValueError("Unsupported rate counter pair or different source aliases; use compatible recorded counters from one table")
    return RATE_PAIRS[(numerator, denominator)]


def definitions(plan, manifests, relationships):
    aliases = {"base": plan.dataset_id}
    aliases.update({step.alias: next(r.right_dataset_id for r in relationships
                                   if r.relationship_id == step.relationship_id) for step in plan.steps})
    result = {}
    for m in plan.measures:
        alias, _, field = m.field.rpartition("__")
        source = manifests[aliases.get(alias or "base", plan.dataset_id)]
        c = contract(source)
        unit = ("observations" if m.op in {"count", "n_unique"} else
                "yards" if field.endswith("yards") or field == "yards" else
                "points" if field in {"points", "points_scored", "points_allowed"} else
                "goals" if field in {"goals", "goals_for", "goals_against"} else
                "expected_goals" if field in {"xg", "expected_goals", "non_penalty_xg"} else
                "expected_points" if field == "epa" else "recorded column units")
        definition = field
        if m.op == "rate":
            definition, unit = rate_definition(m)
        result[m.name] = {"registry_version": VERSION, "sport": source.sport, "competition": source.competition,
                          "namespace": c.namespace, "provider": source.provider_id,
                          "dataset": c.dataset, "field": field, "op": m.op,
                          "definition": definition, "unit": unit, "grain": plan.grain,
                          "processing_version": source.processing_version,
                          "package_version": source.package_version,
                          "population": {"filters": [f.model_dump(mode="json") for f in plan.filters],
                              "missing": plan.missing, "steps": [{"dataset": manifests[aliases[s.alias]].dataset
                                  if s.alias in aliases else "existence", "mode": s.mode,
                                  "filters": [f.model_dump(mode="json") for f in s.filters]} for s in plan.steps]},
                          "definition_status": "counter_pair_verified" if m.op == "rate" else "source_specific_recorded_field",
                          "eligibility": "both finite nonnegative counters on the same observations" if m.op == "rate" else "finite non-null recorded values"}
    return result


def assert_comparable(existing, payload, measure, group):
    """Reject incompatible same-objective/window comparisons before registration."""
    definition = payload["measurement_definitions"][measure["name"]]
    for evidence in existing:
        context = evidence.context
        if (context.get("objective") == payload["plan"]["objective"] and context.get("group") == group
                and context.get("measure", {}).get("name") == measure["name"]
                and context.get("window") != payload["plan"]["window"]):
            if context.get("measurement_definition") != definition:
                raise ValueError("Comparison uses incompatible definitions, units, populations or provider processing; measure both windows consistently")
            if context.get("model_identities", []) != payload.get("model_identities", []):
                raise ValueError("Comparison windows use incompatible modeled samples")
