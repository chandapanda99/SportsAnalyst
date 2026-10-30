"""Bounded, observation-preserving joins over catalog snapshots."""
from __future__ import annotations

import json
import operator
import re
from copy import copy
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl

from sports_analyst.analysis.research.contracts import VERSION, JoinPlan, contract, relationships
from sports_analyst.analysis.research.semantics import definitions, measure_fields, rate_definition
from sports_analyst.datasets.snapshots import sha256_file
from sports_analyst.models import AnalysisWindow, stable_id

MODELED = {"epa", "wpa", "cpoe", "cp", "xpass", "pass_oe"}


def key_strings(frame, keys):
    """Normalize exact integral physical floats, never round imprecise IDs or strip leading zeros."""
    schema = frame.collect_schema() if isinstance(frame, pl.LazyFrame) else frame.schema
    expr = []
    for key in keys:
        value, dtype = pl.col(key), schema[key]
        if dtype.is_float():
            valid = value.is_finite() & (value == value.floor()) & (value.abs() <= 2**53)
            value = pl.when(valid).then(value.cast(pl.Int64, strict=False)).otherwise(None)
        expr.append(value.cast(pl.String).alias(key))
    return frame.with_columns(expr)


def predicate(filters, columns):
    result = pl.lit(True)
    for item in filters:
        if item.field not in columns:
            raise ValueError(f"Unknown field {item.field!r}; supported columns: {sorted(columns)}")
        col, value = pl.col(item.field), item.value
        if item.op == "is_not_null":
            expression = col.is_not_null()
        elif value is None:
            if item.op == "eq":
                expression = col.is_null()
            elif item.op == "ne":
                expression = col.is_not_null()
            else:
                raise ValueError(f"Filter field={item.field!r}, op={item.op!r} requires a non-null value; "
                                 "use eq/null for missing values or is_not_null for recorded values")
        else:
            expression = getattr(operator, item.op)(col, value)
        result &= expression
    return result


def expressions(measures, columns):
    result = []
    names = [m.name for m in measures]
    reserved = {name + suffix for name in names for suffix in ("_non_null", "_numerator", "_denominator")}
    if len(names) != len(set(names)) or any(n in columns or n in reserved or n == "qualifying_rows" for n in names):
        raise ValueError("Measure names must be unique and not collide with fields or audit columns")
    for m in measures:
        if m.op == "count":
            result.extend([pl.len().alias(m.name), pl.len().alias(m.name + "_non_null")])
            continue
        if m.field not in columns:
            raise ValueError(f"Unknown measure field {m.field!r}; supported columns: {sorted(columns)}")
        if m.op == "rate":
            _, unit = rate_definition(m)
            if m.denominator not in columns:
                raise ValueError(f"Unknown rate denominator {m.denominator!r}; supported columns: {sorted(columns)}")
            numerator = pl.col(m.field).cast(pl.Float64, strict=False)
            denominator = pl.col(m.denominator).cast(pl.Float64, strict=False)
            usable = (numerator.is_finite() & denominator.is_finite() & (numerator >= 0) & (denominator >= 0)).fill_null(False)
            if unit == "proportion":
                usable &= numerator <= denominator
            n = pl.when(usable).then(numerator).otherwise(None).sum()
            d = pl.when(usable).then(denominator).otherwise(None).sum()
            result.extend([pl.when(d > 0).then(n / d).otherwise(None).alias(m.name),
                           usable.sum().alias(m.name + "_non_null"),
                           pl.when(usable.any()).then(n).otherwise(None).alias(m.name + "_numerator"),
                           pl.when(usable.any()).then(d).otherwise(None).alias(m.name + "_denominator")])
            continue
        value = pl.col(m.field)
        if m.op in {"sum", "mean", "min", "max"}:
            value = value.cast(pl.Float64, strict=False)
            value = pl.when(value.is_finite()).then(value).otherwise(None)
        expr = value.drop_nulls().n_unique() if m.op == "n_unique" else getattr(value, m.op)()
        if m.op == "sum":
            expr = pl.when(value.count() > 0).then(expr).otherwise(None)
        result.extend([expr.alias(m.name), value.count().alias(m.name + "_non_null")])
    return result


class JoinExecutor:
    def __init__(self, access):
        self.access = access
        self.plans = {}
        self._verified = {}
        self._graph_key, self._graph = None, []

    @staticmethod
    def identity_spec(manifest):
        c = contract(manifest)
        if manifest.sport == "nba" and c.namespace == "nba_stats":
            return "player_crosswalk", "espn_athlete_id", "nba_player_id"
        if manifest.sport == "nfl" and c.player_namespace == "pfr":
            return "players", "gsis_id", "pfr_id"
        return None

    def graph(self):
        key = tuple((m.manifest_id, m.sha256, tuple(m.columns), m.package_version, m.processing_version,
                     m.provider_id, m.competition, m.season, m.resolution_version)
                    for m in self.access.manifests.values())
        if key != self._graph_key:
            self._graph = relationships(self.access.manifests)
            self._graph_key = key
        return self._graph

    def calendars(self, manifest):
        c = contract(manifest)
        return [m for m in self.access.manifests.values() if m.season == manifest.season
                and m.competition == manifest.competition and contract(m).grain == "game"
                and contract(m).namespace == c.namespace]

    def scoped_games(self, manifest, period):
        """Reuse sport-specific temporal semantics; context must not widen the base sample."""
        request = self.access.request
        candidates = self.calendars(manifest)
        if not candidates:
            return None
        games, usable, facts = set(), False, {}
        needed = (request.scope.season_type != "ALL" or period.start_date or period.end_date
                  or request.scope.comparison_design != "full_seasons" or contract(manifest).grain == "game")
        for calendar in candidates:
            fields = [k for k in calendar.columns if k in {"game_id", "event_id", "completed", "season_type", "week",
                      "date", "game_date", "game_date_time", "notes_headline", "status", "season",
                      "status_type_completed", "status_completed"}]
            frame = self.scan(calendar, fields).limit(10001).collect()
            if frame.height > 10000:
                raise ValueError("Schedule attribution exceeds its bound")
            game_key = contract(calendar).game
            for row in frame.iter_rows(named=True):
                previous = facts.setdefault(str(row[game_key]), {})
                for field in ("season_type", "week", "date", "game_date", "completed", "status_type_completed"):
                    if row.get(field) is not None:
                        value = str(row[field])[:10] if field in {"date", "game_date"} else str(row[field])
                        if field in previous and previous[field] != value:
                            raise ValueError("Conflicting schedule scope facts across partitions; no silent union permitted")
                        previous[field] = value
            if request.sport == "cfb":
                from sports_analyst.plugins.cfb import CFBPlugin

                if not {"completed", "season_type", "date", "week", "game_id"} <= set(frame.columns):
                    if needed:
                        raise ValueError("CFB schedule cannot verify the requested temporal scope")
                    continue
                usable = True
                frame = CFBPlugin.window(frame, period, request)
                games.update(frame["game_id"].cast(pl.String).to_list())
            elif request.sport == "nba":
                from sports_analyst.datasets.nba import normalize_season_phase
                from sports_analyst.plugins.nba_segments import segment_game_ids

                frame = normalize_season_phase(frame)
                segment = period.segment or {"REG": "regular_season", "POST": "playoffs", "ALL": "full_season"}[request.scope.season_type]
                completion = next((k for k in ("completed", "status_type_completed", "status_completed") if k in frame.columns), None)
                if completion:
                    frame = frame.filter(pl.col(completion) == True)  # noqa: E712
                elif contract(manifest).grain == "game":
                    raise ValueError("NBA fixture counting requires recorded completion status; use recorded game statistics instead")
                if "season_type" not in frame.columns:
                    if needed:
                        raise ValueError("NBA schedule cannot verify this segment scope")
                    continue
                if segment in {"regular_season", "playoffs", "full_season"}:
                    phases = {"regular_season": ["2"], "playoffs": ["3"], "full_season": ["2", "3"]}[segment]
                    ids = frame.filter(pl.col("season_type").cast(pl.String).is_in(phases))["game_id"].cast(pl.String).to_list()
                else:
                    ids = segment_game_ids(frame, period.season, segment)
                usable = True
                frame = frame.filter(pl.col("game_id").cast(pl.String).is_in(sorted(ids)))
                date = "game_date" if "game_date" in frame.columns else "game_date_time"
                if (period.start_date or period.end_date) and date not in frame.columns:
                    raise ValueError("NBA schedule has no date attribution")
                if period.start_date:
                    frame = frame.filter(pl.col(date).cast(pl.String).str.slice(0, 10) >= period.start_date)
                if period.end_date:
                    frame = frame.filter(pl.col(date).cast(pl.String).str.slice(0, 10) <= period.end_date)
                games.update(frame["game_id"].cast(pl.String).to_list())
            elif request.sport == "soccer":
                from sports_analyst.plugins.soccer import _match_window

                if request.scope.season_type == "POST":
                    raise ValueError("Soccer stage selection requires a recorded competition-stage filter, not NFL POST semantics")
                if not {"status", "date", "event_id"} <= set(frame.columns):
                    if needed:
                        raise ValueError("Soccer fixtures cannot verify completion/date scope")
                    continue
                usable = True
                frame = frame.filter(pl.col("status").cast(pl.String).str.to_lowercase().is_in(["status_final", "status_full_time", "final"]))
                frame = _match_window(frame, period.start_date, period.end_date)
                games.update(frame["event_id"].cast(pl.String).to_list())
        return sorted(games) if usable else None

    def discover(self, offset=0, limit=30):
        rows = [r.model_dump(mode="json") for r in self.graph()]
        start, size = max(0, offset), min(50, max(1, limit))
        return {"relationships": rows[start:start + size], "total": len(rows),
                "next_offset": start + size if start + size < len(rows) else None,
                "unsupported": ["Unverified lineup intervals and ambiguous crosswalks are not joinable",
                                "A column or loader alone is not historical coverage"]}

    def validate(self, raw):
        plan = JoinPlan.model_validate(raw)
        if plan.dataset_id not in self.access.manifests:
            raise ValueError("Base dataset is outside the authorized catalog")
        base = self.access.manifests[plan.dataset_id]
        if base.sport == "nba" and contract(base).namespace == "nba_stats" and "source_season" not in base.columns:
            raise ValueError("Native NBA base has no preserved END-year stamp; queue this package with prepare_analysis_data before research")
        if plan.grain != contract(base).grain or plan.grain in {"unverified", "season_summary", "identity_reference", "interval_candidate"}:
            raise ValueError("Base grain is unverified or does not match its contract")
        if plan.interpretation == "pregame":
            raise ValueError("Pregame joins require verified publication timestamps; use retrospective context instead")
        graph = {r.relationship_id: r for r in self.graph()}
        aliases, columns, inputs = {"base": base.manifest_id}, set(base.columns), {base.manifest_id: base.sha256}
        if base.sport != "nfl":
            inputs.update({m.manifest_id: m.sha256 for m in self.calendars(base)})
        subject = self.access.request.subject
        identity = self.identity_spec(base)
        if subject and subject.type == "player" and identity:
            mappings = [m for m in self.access.manifests.values() if m.dataset == identity[0] and m.season in {0, base.season}]
            if not mappings:
                raise ValueError(f"Player analysis requires verified {identity[0]} identity metadata; no numeric/name substitution")
            inputs.update({m.manifest_id: m.sha256 for m in mappings})
        for step in plan.steps:
            relation = graph.get(step.relationship_id)
            if not relation or aliases.get(step.left_alias) != relation.left_dataset_id:
                raise ValueError("Unknown relationship or left_alias; discover relationships for these exact snapshots")
            if relation.kind == "crosswalk" and (step.filters or step.mode != "enrich"):
                raise ValueError("Crosswalk ambiguity cannot be hidden by filtering or preaggregation; use an unfiltered identity enrichment")
            if step.alias in aliases or step.alias == "base":
                raise ValueError("Join aliases must be unique")
            right = self.access.manifests[relation.right_dataset_id]
            if relation.bridge_dataset_id:
                if step.left_alias != "base":
                    raise ValueError("Opponent ownership must come from primary observations")
                bridge = self.access.manifests[relation.bridge_dataset_id]
                inputs[bridge.manifest_id] = bridge.sha256
            if relation.point:
                left = self.access.manifests[relation.left_dataset_id]
                if left.package_version != right.package_version or left.processing_version != right.processing_version:
                    raise ValueError("Temporal ordering pipelines are not version-compatible")
                if relation.kind == "interval" and step.mode == "preaggregate":
                    raise ValueError("Interval membership cannot be preaggregated before event matching")
            if contract(right).grain == "identity_reference":
                membership = {"latest_team", "team", "team_id", "position", "nba_position", "espn_position", "status"}
                used = set(step.fields) | {f.field for f in step.filters}
                if used & membership:
                    raise ValueError("Identity reference cannot establish historical membership/position/status; use a dated or game roster")
            if not set(step.fields) <= set(right.columns):
                raise ValueError(f"Unsupported right fields; allowed: {right.columns}")
            predicate(step.filters, right.columns)
            if step.mode == "preaggregate" and not step.measures:
                raise ValueError("Preaggregate requires explicit child measures")
            if step.mode != "preaggregate" and step.measures:
                raise ValueError("Child measures require preaggregate mode")
            if step.mode in {"exists", "not_exists"} and step.fields:
                raise ValueError("Existence filters do not project child fields")
            if step.mode == "preaggregate":
                if step.fields:
                    raise ValueError("Preaggregate exposes only joining keys and aggregate measures")
                expressions(step.measures, right.columns)
            if step.mode not in {"exists", "not_exists"}:
                aliases[step.alias] = right.manifest_id
            names = [m.name for m in step.measures] if step.mode == "preaggregate" else step.fields
            if step.mode not in {"exists", "not_exists"}:
                names = list(set(names) | set(relation.right_keys))
                columns.update(f"{step.alias}__{name}" for name in names)
            inputs[right.manifest_id] = right.sha256
        if plan.time_bucket:
            date_field = plan.time_bucket.field
            if date_field not in columns or date_field.rsplit("__", 1)[-1] not in {"date", "game_date", "gameday", "start_date"}:
                raise ValueError("Monthly grouping requires a projected recorded match/game date field")
            if "month" in columns or "month" not in plan.group_by:
                raise ValueError("Use derived group_by=['month', ...]; month must not shadow a source column")
            columns.add("month")
        if not set(plan.group_by) <= columns:
            raise ValueError(f"Unsupported grouping fields; allowed: {sorted(columns)}")
        predicate(plan.filters, columns)
        expressions(plan.measures, columns)
        payload = {"version": VERSION, "plan": plan.model_dump(mode="json"), "inputs": inputs,
                   "input_contracts": {key: {"contract": contract(self.access.manifests[key]).model_dump(mode="json"),
                       "provider": self.access.manifests[key].provider_id,
                       "package_version": self.access.manifests[key].package_version,
                       "processing_version": self.access.manifests[key].processing_version,
                       "resolution_version": self.access.manifests[key].resolution_version} for key in inputs},
                   "relationship_contracts": [graph[step.relationship_id].model_dump(mode="json") for step in plan.steps],
                   "measurement_definitions": definitions(plan, self.access.manifests, self.graph()),
                   "sport": self.access.request.sport, "scope": self.access.request.scope.model_dump(mode="json"),
                   "subject": self.access.request.subject.model_dump(mode="json") if self.access.request.subject else None}
        identifier = stable_id("join-plan", payload)
        self.plans[identifier] = payload
        self.access.acquisition.state.write(identifier, payload)
        return {"plan_id": identifier, **payload, "status": "validated; execution will recheck snapshots and cardinality"}

    def scan(self, manifest, fields):
        if not set(fields) <= set(manifest.columns) or len(fields) > 64:
            raise ValueError("Unsupported projection or column budget exceeded")
        path = Path(self.access.app.store.materialize_manifest(manifest).local_path)
        stat = path.stat()
        stamp = (manifest.sha256, stat.st_size, stat.st_mtime_ns)
        if self._verified.get(manifest.manifest_id) != stamp:
            if sha256_file(path) != manifest.sha256:
                raise ValueError("Source checksum changed; rediscover and validate the plan again")
            self._verified[manifest.manifest_id] = stamp
        return pl.scan_parquet(path).select(sorted(set(fields)))

    def base(self, manifest, fields, window):
        request, c = self.access.request, contract(manifest)
        period = (AnalysisWindow(season=int(window.split(":", 1)[1]))
                  if window.startswith("season:") and request.scope.comparison_design == "full_seasons"
                  else getattr(request.scope, window, None) if window in {"baseline", "comparison"} else None)
        if period is None or period.season not in request.scope.included_seasons or manifest.season != period.season:
            raise ValueError("Window/dataset season outside investigation")
        subject = request.subject
        if subject and subject.type == "player" and c.player_namespace in {"fotmob", "understat"}:
            raise ValueError(f"{c.player_namespace} player scope requires a verified ESPN athlete crosswalk; "
                             "name/numeric-ID guesses are not allowed")
        identifier = str(subject.id if subject else request.scope.team)
        identity = self.identity_spec(manifest)
        if subject and subject.type == "player" and identity:
            candidates = set()
            for mapping in self.access.manifests.values():
                if mapping.dataset != identity[0] or mapping.season not in {0, manifest.season}:
                    continue
                required = list(identity[1:])
                if not set(required) <= set(mapping.columns):
                    continue
                identities = key_strings(self.scan(mapping, required), required).filter(
                    (pl.col(required[0]) == identifier) | (pl.col(required[1]) == identifier)).unique().limit(3).collect()
                candidates.update(identities.iter_rows())
            if len(candidates) != 1 or any(v is None for pair in candidates for v in pair):
                raise ValueError("Selected athlete has missing/ambiguous provider identity; no name or numeric-ID substitution permitted")
            identifier = next(iter(candidates))[1]
        cols = set(manifest.columns)
        if subject and subject.type == "player":
            ids = [key for key in (c.player, "passer_player_id", "rusher_player_id", "receiver_player_id",
                                  "passer_id", "rusher_id", "receiver_id") if key and key in cols]
        elif c.grain == "game":
            ids = [key for key in ("home_team_id", "away_team_id", "home_team", "away_team",
                                  "home_team_abbrev", "away_team_abbrev") if key in cols]
        else:
            ids = [c.team] if c.team else []
        if not ids:
            raise ValueError("No verified base subject attribution; acquire an attributed table")
        allowed = pl.any_horizontal([pl.col(key).cast(pl.String) == identifier for key in ids])
        fields.update(ids)
        if "season" in cols:
            fields.add("season")
            allowed &= pl.col("season") == period.season
        if "source_season" in cols and request.sport == "nba":
            fields.add("source_season")
            allowed &= pl.col("source_season") == period.season
        attributed = self.scoped_games(manifest, period) if request.sport != "nfl" and c.game else None
        if attributed is not None:
            fields.add(c.game)
            allowed &= pl.col(c.game).cast(pl.String).is_in(attributed)
        if request.scope.season_type != "ALL" and attributed is None:
            field = next((k for k in ("season_type", "game_type") if k in cols), None)
            if field is None:
                raise ValueError("Requested season-type attribution is not verified for this table; no scope expansion")
            fields.add(field)
            value = {"REG": "2", "POST": "3"}[request.scope.season_type] if request.sport == "nba" else request.scope.season_type
            allowed &= pl.col(field).cast(pl.String) == value
        if (period.start_date or period.end_date) and attributed is None:
            field = next((k for k in ("game_date", "date", "gameday", "game_date_time") if k in cols), None)
            if not field:
                raise ValueError("No date attribution for requested window")
            fields.add(field)
            day = pl.col(field).cast(pl.String).str.slice(0, 10)
            if period.start_date:
                allowed &= day >= period.start_date
            if period.end_date:
                allowed &= day <= period.end_date
        elif request.scope.comparison_design != "full_seasons" and attributed is None:
            if "week" not in cols or period.segment:
                raise ValueError("Window requires verified week/segment attribution")
            fields.add("week")
            allowed &= pl.col("week").is_between(*period.weeks)
        if c.grain == "player_week":
            fields.add("week")
            allowed &= pl.col("week") > 0
        if "completed" in cols:
            fields.add("completed")
            allowed &= pl.col("completed") == True  # noqa: E712
        if request.sport == "soccer" and c.grain == "game":
            fields.add("status")
            allowed &= pl.col("status").cast(pl.String).str.to_lowercase().is_in(["status_final", "status_full_time", "final"])
        return self.scan(manifest, fields).filter(allowed)

    def execute(self, identifier):
        self.access.calls += 1
        if self.access.calls > 16:
            raise ValueError("Scoped data query budget exhausted")
        self._verified.clear()
        if not re.fullmatch(r"join-plan-[a-f0-9]{16,64}", identifier):
            raise ValueError("Invalid validated plan identifier")
        state = self.access.acquisition.state
        if identifier not in self.plans:
            stored = state.read(identifier)
            if stored is None or stable_id("join-plan", stored) != identifier:
                raise ValueError("Unknown or invalid persisted join plan")
            checked = self.revalidate(stored).plans[identifier]
            if stable_id("join-plan", checked) != identifier:
                raise ValueError("Persisted plan inputs changed")
            self.plans[identifier] = checked
        payload = self.plans[identifier]
        subject = self.access.request.subject.model_dump(mode="json") if self.access.request.subject else None
        if payload["scope"] != self.access.request.scope.model_dump(mode="json") or payload["subject"] != subject:
            raise ValueError("Investigation scope changed; validate a new plan")
        for key, checksum in payload["inputs"].items():
            manifest = self.access.manifests.get(key)
            if manifest is None or manifest.sha256 != checksum:
                raise ValueError("Plan source checksum identity changed")
            self.scan(manifest, [])  # Materialize and verify even on cache hits.
        # Rebuild approval identity even on an in-process cache hit. Byte checksums
        # alone do not detect changed contracts, crosswalk versions or provenance.
        exact = self.revalidate(payload)
        cache_key = stable_id("join-result", payload)
        cached = state.read(cache_key)
        if cached is not None:
            return cached
        with TemporaryDirectory(prefix="sports-research-", dir=state.root) as directory:
            result = exact._execute(identifier, Path(directory))
        state.write(cache_key, result)
        return result

    def revalidate(self, payload):
        """Pin the full execution to approved inputs, excluding later enrichment."""
        access = copy(self.access)
        access.manifests = {key: self.access.manifests[key] for key in payload["inputs"]}
        exact = JoinExecutor(access)
        checked = exact.validate(payload["plan"])
        approval = {key: payload[key] for key in ("version", "plan", "inputs", "input_contracts", "relationship_contracts",
                                                 "measurement_definitions", "sport", "scope", "subject")}
        identifier = stable_id("join-plan", approval)
        if payload.get("plan_id", identifier) != identifier:
            raise ValueError("Execution receipt does not match its approved plan")
        if checked["plan_id"] != identifier:
            raise ValueError("Plan contract/provenance changed; validate again")
        return exact

    def _execute(self, identifier, directory):
        if identifier not in self.plans:
            raise ValueError("Unknown validated plan_id")
        payload = self.plans[identifier]
        plan = JoinPlan.model_validate(payload["plan"])
        manifests = self.access.manifests
        if any(key not in manifests or manifests[key].sha256 != sha for key, sha in payload["inputs"].items()):
            raise ValueError("Plan inputs changed; validate again")
        graph = {r.relationship_id: r for r in self.graph()}
        base = manifests[plan.dataset_id]
        fields = set(plan.group_by) | {f.field for f in plan.filters} | measure_fields(plan.measures)
        if plan.time_bucket:
            fields.discard("month")
            fields.add(plan.time_bucket.field)
        fields = {f for f in fields if "__" not in f}
        for step in plan.steps:
            relation = graph[step.relationship_id]
            if step.left_alias == "base":
                fields.update(relation.left_keys)
                if relation.owner_team:
                    fields.add(relation.owner_team)
                if relation.point:
                    fields.add(relation.point)
        fields.update(contract(base).keys)
        if contract(base).game:
            fields.add(contract(base).game)
        query = self.base(base, fields, plan.window)
        base_filters = [f for f in plan.filters if "__" not in f.field and not (plan.time_bucket and f.field == "month")]
        if base_filters:
            query = query.filter(predicate(base_filters, fields))
        # Slice by game when possible, avoiding partial results for a large season.
        game = contract(base).game
        games = query.select(game).unique().sort(game).collect()[game].to_list() if game else [None]
        if game and None in games:
            raise ValueError("Null base game identifiers; observations cannot be partitioned safely")
        if len(games) > 3000:
            raise ValueError("Game partition budget exceeded; narrow investigation")
        chunks, audits, models, working_bytes, base_rows = [], [], set(), 0, 0
        if contract(base).dataset == "enriched_plays" and any(m.field in MODELED for m in plan.measures):
            if "model_identity" not in base.columns:
                raise ValueError("Modeled measurement has no verified model identity")
            fields.add("model_identity")
            query = self.base(base, fields, plan.window)
            if base_filters:
                query = query.filter(predicate(base_filters, fields))
        for game_id in games:
            frame = (query.filter(pl.col(game) == game_id) if game else query).limit(200_001).collect()
            if frame.height > 200_000:
                raise ValueError("Partition exceeds 200000 observations; no truncated result returned")
            base_rows += frame.height
            if "model_identity" in frame.columns:
                if frame["model_identity"].null_count():
                    raise ValueError("Missing modeled sample identity")
                models.update(frame["model_identity"].unique().to_list())
                if len(models) > 1:
                    raise ValueError("Mixed model identities within the measurement")
            keys = list(contract(base).keys)
            if keys and (any(frame[k].null_count() for k in keys) or frame.select(keys).unique().height != frame.height):
                raise ValueError("Base observation keys are null/duplicated; resolve grain before measuring")
            frame = frame.with_row_index("_observation")
            eligible = pl.lit(True)
            for step in plan.steps:
                relation, before = graph[step.relationship_id], frame.height
                right = manifests[relation.right_dataset_id]
                lk = [f"{step.left_alias}__{k}" if step.left_alias != "base" else k for k in relation.left_keys]
                rk = list(relation.right_keys)
                if not set(lk) <= set(frame.columns):
                    raise ValueError("Chained relationship needs its left keys projected by the previous step")
                needed = set(rk) | set(step.fields) | {f.field for f in step.filters} | measure_fields(step.measures)
                if relation.target_team:
                    needed.add(relation.target_team)
                coarse = contract(right).grain in {"game", "team_game", "player_week", "membership_snapshot"}
                if coarse and frame.select(lk).unique().height < frame.height and any(
                        (m.op == "sum" and m.field.startswith(step.alias + "__")) or
                        (m.op == "rate" and any(f.startswith(step.alias + "__") for f in (m.field, m.denominator))) for m in plan.measures):
                    raise ValueError("Cannot sum repeated game/week context at a finer observation grain")
                if relation.kind == "interval":
                    needed.update((relation.start, relation.end))
                modeled = contract(right).dataset == "enriched_plays" and (
                    set(step.fields) & MODELED or any(m.field in MODELED for m in step.measures))
                if modeled:
                    if "model_identity" not in right.columns:
                        raise ValueError("Context model identity unavailable")
                    needed.add("model_identity")
                child = self.scan(right, needed).filter(predicate(step.filters, right.columns))
                # Cast IDs as strings on both sides, preserving source namespace.
                frame = key_strings(frame, lk)
                child = key_strings(child, rk)
                # Composite key semijoin bounds context to these exact base records.
                lookup = frame.select(lk).rename(dict(zip(lk, rk))).unique()
                for key in rk:
                    child = child.filter(pl.col(key).is_in(lookup[key].to_list()))
                data = child.join(lookup.lazy(), on=rk, how="semi").limit(200_001).collect()
                if relation.bridge_dataset_id:
                    bridge = manifests[relation.bridge_dataset_id]
                    bg = contract(bridge).game
                    sides = key_strings(self.scan(bridge, [bg, relation.home_team, relation.away_team]),
                                        [bg, relation.home_team, relation.away_team]).filter(
                        pl.col(bg).is_in(frame[lk[0]].to_list())).unique().collect()
                    if sides[bg].n_unique() != sides.height:
                        raise ValueError("Conflicting opponent schedule identity")
                    owners = frame.select(pl.col(lk[0]).alias("_game"),
                                          pl.col(relation.owner_team).cast(pl.String).alias("_owner")).unique()
                    owners = owners.join(sides, left_on="_game", right_on=bg, how="left", validate="m:1")
                    home, away = pl.col(relation.home_team), pl.col(relation.away_team)
                    valid = ((pl.col("_owner") == home) | (pl.col("_owner") == away)).fill_null(False)
                    if owners.filter(~valid).height:
                        raise ValueError("Primary owner is not a verified side of this game")
                    owners = owners.with_columns(pl.when(pl.col("_owner") == home).then(away).otherwise(home).alias("_opponent"))
                    desired = owners.select(pl.col("_game").alias(rk[0]), pl.col("_opponent").alias(relation.target_team)).unique()
                    data = key_strings(data, [relation.target_team]).join(desired, on=[rk[0], relation.target_team], how="semi")
                if data.height > 200_000:
                    raise ValueError("Context partition exceeds row budget")
                if any(data[k].null_count() for k in rk):
                    raise ValueError("Null relationship key")
                child_rows = data.height
                if modeled and data.height:
                    if data["model_identity"].null_count():
                        raise ValueError("Context modeled sample has missing identity")
                    models.update(data["model_identity"].unique().to_list())
                    if len(models) > 1:
                        raise ValueError("Incompatible context model identities")
                if relation.kind == "interval":
                    start, end = relation.start, relation.end
                    data = data.with_columns(pl.col(k).cast(pl.Float64, strict=False) for k in (start, end)).sort([*rk, start])
                    invalid = data.filter(pl.any_horizontal([pl.col(k).is_null() | ~pl.col(k).is_finite() for k in (start, end)])
                                          | (pl.col(start) > pl.col(end)))
                    overlap = data.with_columns(pl.col(end).shift(1).over(rk).alias("_previous_end")).filter(
                        pl.col(start) <= pl.col("_previous_end"))
                    if invalid.height or overlap.height:
                        raise ValueError("Invalid or overlapping closed temporal intervals; ambiguous event membership")
                elif step.mode == "preaggregate":
                    data = data.group_by(rk).agg(*expressions(step.measures, data.columns))
                elif step.mode in {"exists", "not_exists"}:
                    data = data.select(rk).unique()
                elif data.select(rk).unique().height != data.height:
                    raise ValueError("Duplicate context keys: duplicated/ambiguous mappings; use preaggregate or an existence filter")
                marker = f"{step.alias}___matched"
                data = data.with_columns(pl.lit(True).alias(marker))
                rename = {name: f"{step.alias}__{name}" for name in data.columns if name != marker}
                data = data.rename(rename)
                if relation.kind == "interval":
                    point = f"{step.left_alias}__{relation.point}" if step.left_alias != "base" else relation.point
                    frame = frame.with_columns(pl.col(point).cast(pl.Float64, strict=False))
                    if frame[point].null_count() or not frame[point].is_finite().all():
                        raise ValueError("Event ordering is missing/nonfinite")
                    frame = frame.sort([*lk, point]).join_asof(data.sort(rename[relation.start]),
                        left_on=point, right_on=rename[relation.start], by_left=lk, by_right=[rename[k] for k in rk],
                        strategy="backward", check_sortedness=False, coalesce=False)
                    # Polars coalesces by-keys independently of the as-of key.
                    # Re-expose the verified equal keys, then null them on nonmatches.
                    frame = frame.with_columns(pl.col(left_key).alias(rename[right_key])
                        for left_key, right_key in zip(lk, rk) if rename[right_key] not in frame.columns)
                    valid = (pl.col(marker).fill_null(False) & (pl.col(point) <= pl.col(rename[relation.end]))).fill_null(False)
                    frame = frame.with_columns([pl.when(valid).then(pl.col(k)).otherwise(None).alias(k)
                                                for k in rename.values()] + [valid.alias(marker)])
                else:
                    frame = frame.join(data, left_on=lk, right_on=[rename[k] for k in rk], how="left", validate="m:1", coalesce=False)
                matched = frame[marker].fill_null(False)
                missing_fields = sum(frame[f"{step.alias}__{f}"].null_count() for f in step.fields)
                audits.append({"alias": step.alias, "game": str(game_id), "base_rows": before,
                    "matched": matched.sum(), "unmatched": before - matched.sum(), "child_rows": child_rows,
                    "output_rows": frame.height, "missing_field_cells": missing_fields, "mode": step.mode})
                if frame.height != before:
                    raise ValueError("Join multiplied observations")
                if step.mode in {"exists", "not_exists"}:
                    frame = frame.filter(pl.col(marker).fill_null(False) == (step.mode == "exists"))
                elif plan.missing == "strict" and (not matched.all() or missing_fields):
                    raise ValueError("Strict join has unmatched records or missing requested context")
                elif plan.missing == "matched":
                    eligible &= pl.col(marker).fill_null(False)
                    for f in step.fields:
                        eligible &= pl.col(f"{step.alias}__{f}").is_not_null()
            frame = frame.filter(eligible)
            if plan.time_bucket:
                frame = frame.with_columns(pl.col(plan.time_bucket.field).cast(pl.String).str.slice(0, 10)
                    .str.to_date("%Y-%m-%d", strict=False).dt.strftime("%Y-%m").alias("month"))
                if frame["month"].null_count():
                    raise ValueError("Monthly measurement has missing/invalid recorded dates; repair date coverage before aggregating")
            frame = frame.filter(predicate(plan.filters, frame.columns))
            retained = sorted({*plan.group_by, *measure_fields(plan.measures), "_observation"})
            frame = frame.select(retained)
            working_bytes += frame.estimated_size()
            if working_bytes > self.access.app.settings.research_working_bytes:
                raise ValueError("Joined working-data budget exceeded; narrow filters/windows; no partial result returned")
            path = directory / f"{len(chunks)}.parquet"
            frame.write_parquet(path)
            chunks.append(pl.scan_parquet(path))
        # Aggregation stays lazy; means/distinct counts are computed over observations,
        # not means-of-means or sums of partition-level distinct counts.
        if not chunks:
            raise ValueError("No qualifying primary observations")
        all_rows = pl.concat(chunks, how="diagonal_relaxed")
        expr = [pl.len().alias("qualifying_rows"), *expressions(plan.measures, all_rows.collect_schema().names())]
        final = (all_rows.group_by(plan.group_by).agg(*expr) if plan.group_by else all_rows.select(*expr)).limit(101).collect(engine="streaming")
        if final.height > 100:
            raise ValueError("More than 100 output groups; narrow grouping")
        rows = final.sort(plan.group_by).to_dicts() if plan.group_by else final.to_dicts()
        result = {**payload, "plan_id": identifier, "audits": audits, "rows": rows,
                  "model_identities": sorted(models),
                  "base_rows": base_rows,
                  "qualifying_rows": sum(row["qualifying_rows"] for row in rows),
                  "definition": "Recorded scoped base observations; matched context is not a causal estimate. "
                                "Counts are at the declared base grain; each numeric measure records its non-null denominator."
                                + (" Soccer follows primary competition/date semantics; the legacy NFL REG selector is not a stage filter."
                                   if base.sport == "soccer" else "")}
        # Validate JSON finiteness and use the complete plan/input identity for replay.
        json.dumps(result, allow_nan=False)
        return result
