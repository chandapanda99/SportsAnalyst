"""Read-only analytical operations on catalog-authorized subject/window slices.

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
from sports_analyst.models import AnalysisWindow


class ScopedData:
    def __init__(self, app, request, partition):
        self.app, self.request = app, request
        seasons = {request.scope.baseline.season, request.scope.comparison.season}
        if request.scope.comparison_design == "full_seasons":
            seasons.update(request.scope.included_seasons)
        self.manifests = {item.manifest_id: item for item in app.store.manifests(
            sport=request.sport, competition=request.scope.competition)
            if item.season in seasons and item.row_count and item.availability != "source_unavailable"
            and item.partition_key in {None, partition}}
        self.calls = 0
        self.verified = set()

    def catalog(self):
        return [{"dataset_id": key, "dataset": item.dataset, "season": item.season,
                 "columns": item.columns, "coverage": item.coverage, "availability": item.availability,
                 "attribution": item.attribution, "scope_note": "Subject/time attribution checked on query; not every table is compatible."}
                for key, item in list(self.manifests.items())[:120]]

    def aggregate(self, dataset_id, window, group_by, measures, filters):
        self.calls += 1
        if self.calls > 16:
            raise ValueError("Scoped data query budget exhausted")
        manifest = self.manifests[dataset_id]
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
        for field in group_by:
            if field not in columns:
                raise ValueError(f"Unknown grouping field: {field}")
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
        required = set(group_by) | set(identity)
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
        for condition in filters:
            field, op, value = condition["field"], condition["op"], condition.get("value")
            if field not in columns or op not in {"eq", "ne", "gt", "ge", "lt", "le", "is_not_null"}:
                raise ValueError("Unsupported filter")
            required.add(field)
            col = pl.col(field)
            if op == "is_not_null":
                predicate &= col.is_not_null()
            else:
                # Values are literals; never evaluated as expressions or paths.
                predicate &= {"eq": col == value, "ne": col != value, "gt": col > value,
                              "ge": col >= value, "lt": col < value, "le": col <= value}[op]
        expressions, definitions = [], []
        for index, measure in enumerate(measures):
            field, op = measure.get("field", ""), measure["op"]
            if op not in {"count", "sum", "mean", "min", "max", "n_unique"} or (op != "count" and field not in columns):
                raise ValueError("Unsupported measure or unknown column")
            alias = f"m{index}"
            if op == "count":
                expression = pl.len()
            else:
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
                   "scope": self.request.scope.model_dump(mode="json"), "subject": identifier,
                   "group_by": group_by, "measures": definitions, "filters": filters,
                   "qualifying_rows": frame.height, "rows": rows,
                   "definition": "Raw recorded attributed rows, not the default metric qualifying sample. "
                                 "Counts are rows, not necessarily games."}
        return {**payload, "result_sha256": digest(payload)}
