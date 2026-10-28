"""Scoped preparation and read-only analytics on authorized subject/window slices.

The model chooses columns, groupings and computations, never file paths or SQL.
Unknown attribution or time grain is rejected rather than expanding the scope.
"""
from __future__ import annotations

import math
from functools import reduce
from operator import or_
from pathlib import Path

import polars as pl

from sports_analyst.analysis.calculations import digest
from sports_analyst.analysis.research.contracts import Filter
from sports_analyst.analysis.research.executor import predicate as research_predicate
from sports_analyst.models import AnalysisWindow


class ScopedData:
    def __init__(self, app, request, partition, identifier=None):
        self.app, self.request = app, request
        self.identifier = identifier
        seasons = {request.scope.baseline.season, request.scope.comparison.season}
        if request.scope.comparison_design == "full_seasons":
            seasons.update(request.scope.included_seasons)
        self.manifests = {item.manifest_id: item for item in app.store.manifests(
            sport=request.sport, competition=request.scope.competition, provider_id=None, processing_version=None)
            if item.season in seasons | {0} and item.row_count and item.availability != "source_unavailable"
            and item.partition_key in {None, partition}}
        self.calls = 0
        self.verified = set()
        self.acquisitions = set()
        self._executor = None
        self._acquisition = None

    @property
    def executor(self):
        from sports_analyst.analysis.research.executor import JoinExecutor

        if self._executor is None:
            self._executor = JoinExecutor(self)
        return self._executor

    @property
    def acquisition(self):
        from uuid import uuid4

        from sports_analyst.analysis.research.acquisition import Acquisition

        if self._acquisition is None:
            self._acquisition = Acquisition(self, self.identifier or str(uuid4()))
        return self._acquisition

    def catalog_page(self, offset=0, limit=5, dataset="", capability_offset=0):
        from sports_analyst.analysis.research.acquisition import inventory

        rows = [r for r in self.catalog() if not dataset or dataset.lower() in r["dataset"].lower()]
        start, size = max(0, offset), min(5, max(1, limit))
        capabilities = [c for c in inventory(self.request.sport, self) if not dataset or dataset.lower() in c["dataset"].lower()]
        capability_start = max(0, capability_offset)
        page = [{**r, "columns": r["columns"][:24], "column_count": len(r["columns"])} for r in rows[start:start + size]]
        return {"datasets": page, "total": len(rows),
                "next_offset": start + size if start + size < len(rows) else None,
                "capabilities": capabilities[capability_start:capability_start + size],
                "capability_total": len(capabilities),
                "capability_next_offset": capability_start + size if capability_start + size < len(capabilities) else None,
                "schema_retrieval": "Column preview is not complete; use inspect_dataset_schema(dataset_id, offset, limit, query)",
                "acquisition_round": self.acquisition.round if hasattr(self.app, "settings") else 1}

    def prepare_dataset(self, dataset, season):
        """Only existing team-scoped acquisition adapters; never national loaders."""
        from sports_analyst.application.preparation import coordinator, current_season, reusable

        request = self.request
        allowed = ({"schedules", "team_stats", "player_stats", "rosters", "scoring_events", "recorded_plays"}
                   if request.sport == "cfb" else {"play_by_play", "team_stats", "lineups", "key_events", "expected_goals"})
        if request.sport not in {"cfb", "soccer"}:
            raise ValueError("This provider uses season-wide bulk downloads. Use Data Management to approve that download explicitly.")
        if dataset not in allowed or season not in request.scope.included_seasons:
            raise ValueError(f"Package/season outside approved acquisition scope. Allowed packages: {sorted(allowed)}")
        subject = request.subject
        team = (subject.id if subject and subject.type == "team" else subject.team_id if subject else request.scope.team)
        if not team or not str(team).isdigit():
            raise ValueError("A verified selected ESPN team ID is required; athlete IDs cannot substitute for team IDs")
        key = (dataset, season)
        if key in self.acquisitions or len(self.acquisitions) >= 2:
            raise ValueError("Scoped acquisition already attempted or the two-package budget is exhausted")
        self.acquisitions.add(key)
        partition = f"team:{team}"
        connector = self.app.connectors[request.sport]
        with coordinator(self.app).lease(f"prepare:{request.sport}:{request.scope.competition}:{partition}:{season}", seconds=1800):
            installed = self.app.store.manifests(sport=request.sport, competition=request.scope.competition,
                                               partition_key=partition)
            current = current_season(request.sport, request.scope.competition)
            ready = [item for item in installed if item.dataset == dataset and item.season == season
                     and item.row_count and reusable(item, current)
                     and (self.app.store.persistence.durable or Path(item.local_path).exists())]
            if ready:
                produced = ready
            else:
                options = ({"team_ids": [str(team)]} if request.sport == "cfb" else
                           {"competition": request.scope.competition, "team_id": str(team), "include_expected_goals": False,
                            "refresh_seasons": {season} if season == current else set()})
                def progress(*_args, **_kwargs):
                    if getattr(self, "progress", None):
                        self.progress(f"Preparing scoped {request.sport.upper()} {dataset} for {team} · {season}")

                progress()
                produced = connector.sync([season], [dataset], manifest_callback=self.app.store.save_manifest,
                                          progress_callback=progress, **options)
            for item in produced:
                if item.partition_key == partition and item.season == season and item.row_count:
                    self.manifests[item.manifest_id] = item
        return [{"dataset_id": item.manifest_id, "dataset": item.dataset, "coverage": item.coverage,
                 "availability": item.availability} for item in produced]

    def catalog(self):
        from sports_analyst.analysis.research.contracts import contract

        return [{"dataset_id": key, "dataset": item.dataset, "season": item.season,
                 "columns": item.columns, "coverage": item.coverage, "availability": item.availability,
                 "attribution": item.attribution, "contract": contract(item).model_dump(mode="json"),
                 "scope_note": "Declared contract; snapshot keys and coverage checked on execution."}
                for key, item in self.manifests.items()]

    def aggregate(self, dataset_id, window, group_by, measures, filters, game_dataset_id="", game_fields=None):
        self.calls += 1
        if self.calls > 16:
            raise ValueError("Scoped data query budget exhausted")
        if dataset_id not in self.manifests:
            raise ValueError(f"Unknown dataset_id={dataset_id!r}; inspect_scoped_datasets returns authorized dataset IDs")
        if game_dataset_id:
            from sports_analyst.analysis.research.contracts import contract, relationships

            right = self.manifests.get(game_dataset_id)
            if right is None or contract(right).grain != "game":
                raise ValueError("Only verified schedule context is supported by the legacy interface")
            relations = [r for r in relationships(self.manifests) if r.left_dataset_id == dataset_id
                         and r.right_dataset_id == game_dataset_id]
            if not relations or not game_fields or len(game_fields) > 6:
                raise ValueError("No compatible schedule relationship or invalid field budget")
            plan = {"objective": "Legacy scoped schedule context", "dataset_id": dataset_id, "window": window,
                    "grain": contract(self.manifests[dataset_id]).grain, "missing": "strict",
                    "steps": [{"relationship_id": relations[0].relationship_id, "alias": "game", "fields": game_fields}],
                    "group_by": group_by, "filters": filters,
                    "measures": [{**m, "name": f"m{i}"} for i, m in enumerate(measures)]}
            checked = self.executor.validate(plan)
            self.calls -= 1  # The executor owns the shared query counter.
            payload = self.executor.execute(checked["plan_id"])
            source = self.manifests[dataset_id]
            response = {"dataset_id": dataset_id, "source_sha256": source.sha256, "window": window,
                "joined_dataset_id": game_dataset_id, "joined_sha256": right.sha256, "game_fields": game_fields,
                "scope": self.request.scope.model_dump(mode="json"), "subject": self.request.scope.team,
                "group_by": group_by, "filters": filters, "definition": payload["definition"],
                "measures": [{"result": f"m{i}", "op": m["op"], "field": m.get("field", "")} for i, m in enumerate(measures)],
                "rows": payload["rows"], "qualifying_rows": payload["qualifying_rows"], "join_plan_id": checked["plan_id"]}
            return {**response, "result_sha256": digest(response)}
        manifest = self.manifests[dataset_id]
        fields = sorted(manifest.columns)
        if window.startswith("season:") and self.request.scope.comparison_design == "full_seasons":
            year = int(window.removeprefix("season:"))
            if year not in self.request.scope.included_seasons:
                raise ValueError("Season is outside the investigation scope")
            period = AnalysisWindow(season=year)
        elif window in {"baseline", "comparison"}:
            period = getattr(self.request.scope, window)
        else:
            raise ValueError("Select baseline or comparison")
        if period.season != manifest.season:
            raise ValueError("Dataset season does not match the selected window")
        if len(group_by) > 3 or not 1 <= len(measures) <= 8 or len(filters) > 8:
            raise ValueError("Query exceeds grouping/measurement/filter budget")
        columns = set(manifest.columns)
        original_columns = set(columns)
        fields = sorted(columns)
        for field in group_by:
            if field not in columns:
                raise ValueError(f"Unknown grouping field: {field!r}. Allowed fields={fields}")
        subject = self.request.subject
        identifier = str(subject.id if subject else self.request.scope.team)
        if subject and subject.type == "player":
            identity = [field for field in ("player_id", "athlete_id", "passer_player_id", "rusher_player_id", "receiver_player_id")
                        if field in columns]
        else:
            names = ("posteam",) if self.request.sport == "nfl" and manifest.dataset == "play_by_play" else (
                ("team_abbreviation", "team_abbrev", "team", "recent_team") if self.request.sport in {"nfl", "nba"} else ("team_id",))
            identity = [field for field in names if field in columns]
        if not identity:
            raise ValueError("Table has no supported subject-attribution field; use a compatible attributed table")
        predicate = reduce(or_, (pl.col(field).cast(pl.String) == identifier for field in identity))
        required = (set(group_by) & original_columns) | set(identity)
        if "season_type" in columns and self.request.sport == "nfl" and self.request.scope.season_type != "ALL":
            predicate &= pl.col("season_type") == self.request.scope.season_type
            required.add("season_type")
        elif self.request.scope.season_type != "ALL":
            raise ValueError("This table cannot verify the requested season type; "
                             "use existing sport-specific evidence or an ALL scope")
        if "completed" in columns:
            predicate &= pl.col("completed") == True  # noqa: E712
            required.add("completed")
        if period.start_date or period.end_date:
            date = next((name for name in ("game_date", "date", "game_date_time") if name in columns), None)
            if date is None:
                raise ValueError("Date window requires an attributed date column")
            required.add(date)
            if period.start_date:
                predicate &= pl.col(date).cast(pl.String).str.slice(0, 10) >= str(period.start_date)
            if period.end_date:
                predicate &= pl.col(date).cast(pl.String).str.slice(0, 10) <= str(period.end_date)
        elif self.request.scope.comparison_design != "full_seasons":
            if "week" not in columns:
                raise ValueError("This table cannot establish the requested week/season-segment window")
            if period.segment:
                raise ValueError("Named segments require sport-specific attribution; this generic tool cannot infer them")
            predicate &= pl.col("week").is_between(*period.weeks)
            required.add("week")
        extra_predicate = pl.lit(True)
        for condition in filters:
            field, op, value = condition["field"], condition["op"], condition.get("value")
            if field not in columns or op not in {"eq", "ne", "gt", "ge", "lt", "le", "is_not_null"}:
                raise ValueError(f"Invalid filter field={field!r}, op={op!r}. "
                                 f"Allowed fields={fields}; operators=eq,ne,gt,ge,lt,le,is_not_null. "
                                 "Subject/season filters are already enforced by the host; do not invent a team alias.")
            if field in original_columns:
                required.add(field)
            # Share literal/null semantics with validated joined calculations.
            extra_predicate &= research_predicate([Filter(field=field, op=op, value=value)], columns)
        expressions, definitions = [], []
        for index, measure in enumerate(measures):
            field, op = measure.get("field", ""), measure["op"]
            if op not in {"count", "sum", "mean", "min", "max", "n_unique"} or (op != "count" and field not in columns):
                raise ValueError(f"Invalid measure field={field!r}, op={op!r}. "
                                 f"Allowed fields={fields}; operations=count,sum,mean,min,max,n_unique")
            alias = f"m{index}"
            if op == "count":
                expression = pl.len()
            else:
                if field in original_columns:
                    required.add(field)
                value = pl.col(field)
                if op in {"sum", "mean", "min", "max"}:
                    value = value.cast(pl.Float64, strict=False)
                    value = pl.when(value.is_finite()).then(value).otherwise(None)
                # An all-missing numeric group is null, never a recorded zero.
                expression = value.drop_nulls().n_unique() if op == "n_unique" else getattr(value, op)()
                if op == "sum":
                    expression = pl.when(value.count() > 0).then(expression).otherwise(None)
                expressions.append(value.count().alias(f"{alias}_non_null"))
            expressions.append(expression.alias(alias))
            definitions.append({"result": alias, "op": op, "field": field})
        if len(required) > 24:
            raise ValueError("Query exceeds column budget")
        materialized = self.app.store.materialize_manifest(manifest)
        if dataset_id not in self.verified:
            from sports_analyst.datasets.nfl import sha256_file

            if sha256_file(Path(materialized.local_path)) != manifest.sha256:
                raise ValueError("Source snapshot checksum changed; prepare the investigation again")
            self.verified.add(dataset_id)
        # The file comes from the trusted catalog, not from an LLM path argument.
        query = pl.scan_parquet(materialized.local_path).select(sorted(required)).filter(predicate)
        frame = query.limit(200_001).collect()
        if frame.height > 200_000:
            raise ValueError("Subject slice exceeds 200000 rows; narrow the filters (no partial result returned)")
        frame = frame.filter(extra_predicate)
        result = (frame.group_by(group_by).agg(pl.len().alias("qualifying_rows"), *expressions)
                  if group_by else frame.select(pl.len().alias("qualifying_rows"), *expressions))
        if result.height > 100:
            raise ValueError("More than 100 groups; narrow grouping or filters (no partial result returned)")
        rows = result.sort(group_by).to_dicts() if group_by else result.to_dicts()
        for row in rows:
            for value in row.values():
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("Nonfinite result")
        payload = {"dataset_id": dataset_id, "source_sha256": manifest.sha256, "window": window,
                   "joined_dataset_id": None, "joined_sha256": None, "game_fields": [],
                   "scope": self.request.scope.model_dump(mode="json"), "subject": identifier,
                   "group_by": group_by, "measures": definitions, "filters": filters,
                   "qualifying_rows": frame.height, "rows": rows,
                   "definition": "Raw recorded attributed rows, not the default metric qualifying sample. "
                                 "Counts are rows, not necessarily games."}
        return {**payload, "result_sha256": digest(payload)}
