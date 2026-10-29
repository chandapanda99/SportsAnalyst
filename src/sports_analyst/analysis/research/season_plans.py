"""Replay compatible research plans over installed seasons, without new source downloads."""
from copy import deepcopy


def season_plan(access, payload, year):
    plan = deepcopy(payload["plan"])
    # Fixed games, dates and explicit season predicates require a separate analytical decision.
    fixed = {"season", "source_season", "date", "game_date", "gameday", "game_id", "event_id"}
    predicates = [*plan.get("filters", []), *(f for s in plan.get("steps", []) for f in s.get("filters", []))]
    if any(f["field"].rsplit("__", 1)[-1] in fixed for f in predicates):
        raise ValueError("Fixed season/date/game filters require an explicit plan for this season")
    mapping = {}
    for identifier in payload["inputs"]:
        source = access.manifests[identifier]
        if source.season == 0:
            mapping[identifier] = identifier
            continue
        candidates = [m for m in access.manifests.values() if m.season == year and all(
            getattr(m, field) == getattr(source, field) for field in (
                "sport", "competition", "dataset", "partition_key", "provider_id", "package_version",
                "processing_version", "resolution_version"))]
        if len(candidates) != 1:
            raise ValueError(f"No unique compatible installed {source.dataset} snapshot for season {year}")
        mapping[identifier] = candidates[0].manifest_id
    graph = access.executor.graph()
    relationships = {r["relationship_id"]: r for r in payload["relationship_contracts"]}
    for step in plan.get("steps", []):
        old = relationships[step["relationship_id"]]
        candidates = [r for r in graph if r.left_dataset_id == mapping[old["left_dataset_id"]]
                      and r.right_dataset_id == mapping[old["right_dataset_id"]] and all(
                          getattr(r, field) == (tuple(old[field]) if isinstance(old.get(field), list) else old.get(field))
                          for field in ("left_keys", "right_keys", "kind", "context_role", "point", "start", "end", "boundaries",
                                        "owner_team", "target_team", "home_team", "away_team"))
                      and r.bridge_dataset_id == mapping.get(old.get("bridge_dataset_id"))]
        if len(candidates) != 1:
            raise ValueError("No unique verified relationship for this season")
        step["relationship_id"] = candidates[0].relationship_id
    plan.update(dataset_id=mapping[plan["dataset_id"]], window=f"season:{year}")
    return plan
