"""Readable research labels from recorded scopes and exact source identities."""
import json
from datetime import date
from pathlib import Path

import polars as pl

from sports_analyst.datasets.nfl import sha256_file
from sports_analyst.datasets.soccer.connector import soccer_season_label


def field_label(field):
    field = field.rsplit("__", 1)[-1]
    return {"game_id": "Match", "event_id": "Match", "possession_pct": "Possession",
            "home_score": "Home Score", "away_score": "Away Score", "epa": "EPA", "xg": "Expected Goals", "cpoe": "CPOE",
            "home_team_id": "Home team", "away_team_id": "Away team", "home_id": "Home team", "away_id": "Away team",
            "team_id": "Team", "total_shots": "Shots", "shots_on_target": "Shots on Target", "won_corners": "Corners Won",
            "is_home": "Venue", "home": "Venue"}.get(field, field.replace("_", " ").title())


class ResearchLabels:
    def __init__(self, result, request=None, access=None, store=None):
        self.request = request or getattr(result, "run", None)
        self.access, self.store = access, store
        self.plans = {e.parameters["plan_id"]: e.parameters for e in getattr(result, "executions", [])
                      if e.parameters.get("plan_id") and e.parameters.get("plan")}
        self.manifests = {m.manifest_id: m for m in getattr(result, "dataset_manifests", [])}
        if access:
            self.manifests.update(access.manifests)
        self.cached = {row["evidence_id"]: row for chart in result.charts
                       for row in chart.specification.get("data", {}).get("values", [])
                       if row.get("evidence_id") and row.get("group_display") is not None}
        self.lookups = {}

    def payload(self, item):
        return self.plans.get(item.context.get("plan_id"), {})

    def scope(self, item):
        return self.request.scope.model_dump(mode="json") if self.request else self.payload(item).get("scope", {})

    def season_label(self, item, year):
        scope = self.scope(item)
        sport = getattr(self.request, "sport", None) or self.payload(item).get("sport")
        try:
            return soccer_season_label(scope.get("competition"), int(year)) if sport == "soccer" and scope.get("competition") else str(year)
        except (ValueError, TypeError):
            return str(year)

    def period(self, item):
        if item.context.get("window_label"):
            return item.context["window_label"]
        window = item.context.get("window", "")
        scope = self.scope(item)
        if window.startswith("season:"):
            return self.season_label(item, window.split(":", 1)[1])
        period = scope.get(window, {})
        if period.get("season"):
            label = self.season_label(item, period["season"])
            if period.get("start_date") and period.get("end_date"):
                dates = [date.fromisoformat(period[key][:10]).strftime("%b %d, %Y") for key in ("start_date", "end_date")]
                return " – ".join(dates)
            if scope.get("comparison_design") != "full_seasons" and period.get("weeks"):
                return f"{label} · Weeks {period['weeks'][0]}–{period['weeks'][1]}"
            return label
        return {"baseline": "Earlier period", "comparison": "Later period"}.get(window, "Recorded sample")

    def source(self, item, field):
        payload = self.payload(item)
        plan = payload.get("plan", {})
        alias, _, _ = field.rpartition("__")
        source_id = plan.get("dataset_id")
        if alias:
            step = next((s for s in plan.get("steps", []) if s["alias"] == alias), None)
            relation = next((r for r in payload.get("relationship_contracts", [])
                             if step and r["relationship_id"] == step["relationship_id"]), None)
            source_id = relation["right_dataset_id"] if relation else None
        return self.manifests.get(source_id)

    def team_name(self, item, field, value):
        column = field.rsplit("__", 1)[-1]
        source = self.source(item, field)
        sources = [source] if source else [m for key, m in self.manifests.items() if key in item.dataset_manifest_ids]
        if not source:
            from sports_analyst.analysis.research.contracts import contract

            if len({contract(m).namespace for m in sources if column in m.columns}) > 1:
                return "Team name unavailable"
        names = set()
        for manifest in sources:
            expected = self.payload(item).get("inputs", {}).get(manifest.manifest_id)
            if expected and expected != manifest.sha256:
                continue
            if column not in manifest.columns:
                continue
            stem = column.removesuffix("_id")
            candidates = [stem + "_name", stem + "_display_name", stem]
            if stem in {"home", "away"}:
                candidates = [stem + "_team_name", stem + "_team", *candidates]
            name_field = next((name for name in candidates if name in manifest.columns and name != column), None)
            if not name_field:
                continue
            cache_key = (manifest.manifest_id, column, name_field)
            if cache_key not in self.lookups:
                try:
                    if self.access:
                        frame = self.access.executor.scan(manifest, [column, name_field])
                    else:
                        local = self.store.materialize_manifest(manifest) if self.store else manifest
                        path = Path(local.local_path)
                        if not path.exists() or sha256_file(path) != manifest.sha256:
                            continue
                        frame = pl.scan_parquet(path).select(column, name_field)
                    # A bounded identity dictionary, using source-native keys; no fuzzy/name joins.
                    values = frame.select(pl.col(column).cast(pl.String), pl.col(name_field).cast(pl.String)).unique().limit(5001).collect()
                    self.lookups[cache_key] = values.to_dicts() if values.height <= 5000 else []
                except (OSError, ValueError, RuntimeError, pl.exceptions.PolarsError):
                    self.lookups[cache_key] = []
            names.update(row[name_field].strip() for row in self.lookups[cache_key]
                         if str(row[column]) == str(value) and row[name_field] and row[name_field].strip() != str(value))
        return next(iter(names)) if len(names) == 1 else "Team name unavailable"

    def value(self, item, field, value):
        column = field.rsplit("__", 1)[-1]
        if column in {"home_team_id", "away_team_id", "team_id", "home_id", "away_id"}:
            return self.team_name(item, field, value)
        if column == "season" and value is not None:
            return self.season_label(item, value)
        if column in {"home", "is_home"} and type(value) is bool:
            return "Home" if value else "Away"
        return "Not recorded" if value is None else str(value)

    def group(self, item):
        cached = self.cached.get(item.evidence_id, {}).get("group_display", {})
        return {field: (cached.get(field) if cached.get(field) != "Team name unavailable" else None) or self.value(item, field, value)
                for field, value in item.context.get("group", {}).items()}

    def filters(self, item):
        if self.cached.get(item.evidence_id, {}).get("filter_display") and not any(
                "Team name unavailable" in text for text in self.cached[item.evidence_id]["filter_display"]):
            return self.cached[item.evidence_id]["filter_display"]
        filters = self.payload(item).get("plan", {}).get("filters", [])
        if not filters:
            return self.cached.get(item.evidence_id, {}).get("filter_display", [])
        operators = {"eq": "", "ne": "excluding", "gt": "above", "ge": "at least", "lt": "below", "le": "at most"}
        return [f"{field_label(f['field'])}: recorded" if f["op"] == "is_not_null" else
                " ".join(filter(None, [field_label(f["field"]) + ":", operators.get(f["op"], f["op"]),
                                       self.value(item, f["field"], f.get("value"))])) for f in filters]

    def venue(self, item):
        scope = self.scope(item)
        selected = str(scope.get("team", ""))
        filters = self.payload(item).get("plan", {}).get("filters", [])
        for value in filters:
            field = value["field"].rsplit("__", 1)[-1]
            if value["op"] == "eq" and field in {"home_team_id", "away_team_id"} and str(value.get("value")) == selected:
                return "Home" if field == "home_team_id" else "Away"
            if value["op"] == "eq" and field in {"home", "is_home"} and type(value.get("value")) is bool:
                return "Home" if value["value"] else "Away"
        return None

    def partition(self, item):
        from sports_analyst.analysis.research.contracts import contract

        payload = self.payload(item)
        plan = payload.get("plan", {})
        source = self.source(item, "")
        def identity(manifest):
            if not manifest:
                return None
            return [manifest.dataset, contract(manifest).namespace, manifest.provider_id,
                    manifest.processing_version, manifest.package_version, manifest.resolution_version, manifest.partition_key]

        def field(name):
            return [identity(self.source(item, name)), name.rsplit("__", 1)[-1]]

        def filters(values, child=False):
            return sorted([{"field": f["field"] if child else field(f["field"]), "op": f["op"], "value": f.get("value")}
                           for f in values], key=lambda f: json.dumps(f, sort_keys=True, default=str))

        steps = []
        for step in plan.get("steps", []):
            relation = next((r for r in payload.get("relationship_contracts", [])
                             if r["relationship_id"] == step["relationship_id"]), {})
            steps.append({"source": identity(self.source(item, step["alias"] + "__")),
                          "left_keys": relation.get("left_keys"), "right_keys": relation.get("right_keys"),
                          "kind": relation.get("kind"), "role": relation.get("context_role"),
                          "filters": filters(step.get("filters", []), child=True), "mode": step.get("mode", "enrich"),
                          "measures": step.get("measures", [])})
        # Different populations or grouping dimensions are different charts, not adjacent observations.
        # Missing legacy scope metadata cannot justify combining unrelated executions.
        return json.dumps({"group": sorted([field(f) for f in item.context.get("group", {})], key=str),
                           "filters": filters(plan.get("filters", [])), "steps": steps, "missing": plan.get("missing"),
                           "grain": plan.get("grain"), "dataset": identity(source),
                           "legacy_plan": item.context.get("plan_id") if not payload else None}, sort_keys=True, default=str)

    def expected_periods(self, item):
        scope = self.scope(item)
        if scope.get("comparison_design") == "full_seasons":
            return [self.season_label(item, year) for year in range(scope["baseline"]["season"], scope["comparison"]["season"] + 1)]
        if scope.get("baseline") and scope.get("comparison"):
            return list(dict.fromkeys(self.period(item.model_copy(update={"context": {**item.context, "window": window,
                "window_label": None}})) for window in ("baseline", "comparison")))
        return []
