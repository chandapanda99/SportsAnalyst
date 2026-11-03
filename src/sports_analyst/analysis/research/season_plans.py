"""Replay compatible research plans over installed seasons, or for a head-to-head's second subject."""
from copy import deepcopy

RELATIONSHIP_FIELDS = ("left_keys", "right_keys", "kind", "context_role", "point", "start", "end", "boundaries",
                       "owner_team", "target_team", "home_team", "away_team")
SNAPSHOT_FIELDS = ("sport", "competition", "dataset", "provider_id", "package_version", "processing_version", "resolution_version")


def _remap_steps(access, payload, plan, resolve):
    graph = access.executor.graph()
    relationships = {r["relationship_id"]: r for r in payload["relationship_contracts"]}
    for step in plan.get("steps", []):
        old = relationships[step["relationship_id"]]
        candidates = [r for r in graph if r.left_dataset_id == resolve(old["left_dataset_id"])
                      and r.right_dataset_id == resolve(old["right_dataset_id"]) and all(
                          getattr(r, field) == (tuple(old[field]) if isinstance(old.get(field), list) else old.get(field))
                          for field in RELATIONSHIP_FIELDS)
                      and r.bridge_dataset_id == resolve(old.get("bridge_dataset_id"))]
        if len(candidates) != 1:
            raise ValueError("No unique verified relationship for this season")
        step["relationship_id"] = candidates[0].relationship_id


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
            getattr(m, field) == getattr(source, field) for field in ("partition_key", *SNAPSHOT_FIELDS))]
        if len(candidates) != 1:
            raise ValueError(f"No unique compatible installed {source.dataset} snapshot for season {year}")
        mapping[identifier] = candidates[0].manifest_id
    _remap_steps(access, payload, plan, mapping.get)
    plan.update(dataset_id=mapping[plan["dataset_id"]], window=f"season:{year}")
    return plan


def assert_subject_neutral(filters, subject):
    """A filter on the first subject's own identity would silently empty or distort the second subject's replay."""
    names = {str(value).casefold() for value in (subject.id, subject.team_id, subject.display_name) if value} if subject else set()
    if any(str(item.get("value", "")).casefold() in names for item in filters):
        raise ValueError("A filter names the first subject directly, so it cannot be repeated for the second subject; "
                         "the host already limits each subject's data")


def subject_dataset(source, target, identifier):
    """The second subject's snapshot matching the first's: shared league data, or the same package in its own partition."""
    if not identifier:
        return None
    if identifier in target.manifests:
        return identifier
    origin = source.manifests[identifier]
    candidates = [m for m in target.manifests.values() if m.season == origin.season
                  and all(getattr(m, field) == getattr(origin, field) for field in SNAPSHOT_FIELDS)]
    if len(candidates) != 1:
        raise ValueError(f"No unique compatible {origin.dataset} snapshot for the second subject in {origin.season}")
    return candidates[0].manifest_id


def subject_plan(source, target, payload):
    """Repeat a validated plan for a head-to-head's second subject: same windows, fields and filters."""
    plan = deepcopy(payload["plan"])
    assert_subject_neutral([*plan.get("filters", []), *(f for s in plan.get("steps", []) for f in s.get("filters", []))],
                           source.request.subject)

    def resolve(identifier):
        return subject_dataset(source, target, identifier)

    _remap_steps(target, payload, plan, resolve)
    plan["dataset_id"] = resolve(plan["dataset_id"])
    return plan
