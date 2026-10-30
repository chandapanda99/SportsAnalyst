from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any

import polars as pl

from sports_analyst.application.runtime import LazyRegistry, sport_registries
from sports_analyst.config import Settings, get_settings
from sports_analyst.models import (
    AnalysisOptions,
    AnalysisPlan,
    AnalysisRequest,
    DatasetManifest,
    InvestigationBundle,
    InvestigationRun,
    MetricDefinition,
    PlannedToolCall,
    PlayerOption,
    RunStatus,
    RuntimeCapabilities,
    SportOption,
    TeamOption,
    ToolDefinition,
    stable_id,
)
from sports_analyst.observability.logging import configure_logging
from sports_analyst.storage.local import EventRegistry, LocalStore
from sports_analyst.storage.persistence import PersistenceBackend

logger = logging.getLogger("sports_analyst.service")


class _DisabledTelemetry:
    @staticmethod
    def span(*_args, **_kwargs):
        return nullcontext(None)

    @staticmethod
    def add_outputs(*_args, **_kwargs) -> None:
        return None


class AnalystApplication:
    def __init__(
        self,
        settings: Settings | None = None,
        persistence: PersistenceBackend | None = None,
        *,
        restore_durable_index: bool = True,
        analysis_runtime: bool = True,
        startup_progress: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        configure_logging(self.settings.log_level)
        if startup_progress:
            startup_progress("Loading your saved sports data...")
        self.store = LocalStore(self.settings, persistence, restore_durable_index=restore_durable_index)
        self.connectors, self.plugins = sport_registries(self.settings, self.store.persistence)
        self._runtime_lock = RLock()
        self._analysis_enabled = analysis_runtime
        self._agent = None
        self._telemetry = None
        self.events = EventRegistry()
        self.jobs = None
        if self.settings.job_backend == "sqlite":
            from sports_analyst.jobs.local import SQLiteJobStore

            self.jobs = SQLiteJobStore(self.settings.job_database_path)
        elif self.settings.job_backend == "object":
            from sports_analyst.jobs.object_store import ObjectJobStore

            polling = self.settings.job_progress_transport == "poll"
            self.jobs = ObjectJobStore(
                self.store.persistence,
                record_events=not polling,
                status_min_interval=0.5 if polling else 0,
            )

    @property
    def connector(self):
        """Compatibility alias; replacing it updates the active NFL registry."""
        return self.connectors["nfl"]

    @connector.setter
    def connector(self, value):
        self.connectors["nfl"] = value

    @property
    def plugin(self):
        return self.plugins["nfl"]

    @plugin.setter
    def plugin(self, value):
        self.plugins["nfl"] = value

    @property
    def agent(self):
        with self._runtime_lock:
            if self._analysis_enabled and self._agent is None:
                from sports_analyst.analysis.agents import EvidenceBoundAgent
                self._agent = EvidenceBoundAgent(self.settings)
            return self._agent

    @agent.setter
    def agent(self, value):
        self._agent = value

    @property
    def telemetry(self):
        with self._runtime_lock:
            if self._telemetry is None:
                if self._analysis_enabled and self.settings.langsmith_tracing:
                    from sports_analyst.observability.telemetry import LangSmithTelemetry
                    self._telemetry = LangSmithTelemetry(self.settings)
                else:
                    self._telemetry = _DisabledTelemetry()
            return self._telemetry

    @telemetry.setter
    def telemetry(self, value):
        self._telemetry = value

    def clear_caches(self) -> None:
        connectors = (self.connectors.initialized_values() if isinstance(self.connectors, LazyRegistry)
                      else tuple(self.connectors.values()))
        for connector in connectors:
            connector.clear_cache()

    def capabilities(self) -> RuntimeCapabilities:
        configured = self.settings.model_provider == "ollama" or bool(self.settings.foundry_endpoint)
        return RuntimeCapabilities(
            job_progress_transport=self.settings.job_progress_transport,
            providers=["azure_foundry", "ollama"],
            configured_provider=self.settings.model_provider,
            model_configured=configured,
            custom_analysis=False,
            sports=list(self.plugins),
        )

    def sport_options(self) -> list[SportOption]:
        from sports_analyst.datasets.nba import nba_live_transport_available
        live = nba_live_transport_available()
        return [
            SportOption(value="nfl", label="NFL", available=True),
            SportOption(
                value="nba",
                label="NBA",
                available=True,
                live_available=live,
                live_message=None if live else "Install the nba-live extra to enable live NBA Stats fallbacks.",
            ),
            SportOption(value="soccer", label="Soccer", available=True),
            SportOption(value="cfb", label="College Football", available=True),
        ]

    def _sport(self, sport: str) -> tuple[Any, Any]:
        normalized = sport.strip().lower()
        if normalized not in self.plugins:
            raise ValueError(f"unsupported sport {sport!r}")
        return self.connectors[normalized], self.plugins[normalized]

    def _load_dataset(
        self,
        connector: Any,
        manifest: DatasetManifest,
        columns: set[str] | list[str] | tuple[str, ...] | None = None,
        predicate: pl.Expr | None = None,
    ) -> pl.DataFrame:
        materialized = self.store.materialize_manifest(manifest)
        if predicate is None:
            return connector.load(materialized, columns)
        return connector.load(materialized, columns, predicate=predicate)

    @staticmethod
    def _nfl_play_by_play_predicate(request: AnalysisRequest, manifest: DatasetManifest) -> pl.Expr:
        """Push broad analysis filters into Parquet scans to cap cloud memory use."""
        columns = set(manifest.columns)
        predicate = pl.col("posteam").is_not_null() if "posteam" in columns else pl.lit(True)
        if request.scope.season_type != "ALL" and "season_type" in columns:
            predicate &= pl.col("season_type") == request.scope.season_type
        matching_windows = [
            window for window in (request.scope.baseline, request.scope.comparison) if window.season == manifest.season
        ]
        if request.scope.comparison_design != "full_seasons" and matching_windows and "week" in columns:
            window_predicate = pl.lit(False)
            for window in matching_windows:
                window_predicate |= pl.col("week").is_between(window.weeks[0], window.weeks[1], closed="both")
            predicate &= window_predicate
        dropback = pl.col("qb_dropback") == 1 if "qb_dropback" in columns else pl.col("play_type") == "pass"
        rush = pl.col("rush_attempt") == 1 if "rush_attempt" in columns else pl.col("play_type") == "run"
        if request.analysis_domain == "passing":
            predicate &= dropback
        elif request.analysis_domain == "rushing":
            predicate &= rush
            if "qb_kneel" in columns:
                predicate &= pl.col("qb_kneel").fill_null(0) != 1
            if "qb_spike" in columns:
                predicate &= pl.col("qb_spike").fill_null(0) != 1
        elif request.analysis_domain == "offense":
            predicate &= dropback | rush
            if "qb_kneel" in columns:
                predicate &= pl.col("qb_kneel").fill_null(0) != 1
            if "qb_spike" in columns:
                predicate &= pl.col("qb_spike").fill_null(0) != 1
        return predicate

    def analysis_options(self, sport: str = "nfl", competition: str | None = None) -> AnalysisOptions:
        connector, plugin = self._sport(sport)
        manifests = [item for item in self.store.manifests(sport=sport,
            **({"provider_id": None, "processing_version": None} if sport == "soccer" else {})) if item.row_count > 0]
        if sport == "cfb":
            return plugin.analysis_options(manifests)
        if sport == "soccer":
            competition = competition or "eng.1"
            fields = {"status", "home_team_id", "home_team", "away_team_id", "away_team"}
            schedules = {item.season: self._load_dataset(connector, item, fields) for item in manifests
                         if item.dataset == "play_by_play" and item.competition == competition}
            options = plugin.analysis_options(manifests, {"competition": competition, "schedules": schedules})
            if not options.teams:
                options = options.model_copy(update={"teams": [TeamOption.model_validate(team) for team in connector.team_directory(competition)]})
            return self._preparation_options(options)
        if sport == "nfl":
            team_manifests = [item for item in manifests if item.dataset == "teams"]
            context = self._load_dataset(connector, team_manifests[0]) if team_manifests else None
        else:
            fields = {"game_id", "game_date", "game_date_time", "season_type", "season_type_id", "notes_headline"}
            schedule_frames = {item.season: self._load_dataset(connector, item, fields)
                               for item in manifests if item.dataset == "schedules"}
            context = {"schedules": schedule_frames}
        return self._preparation_options(plugin.analysis_options(manifests, context))

    @staticmethod
    def _preparation_options(options):
        from sports_analyst.datasets.nba import NBA_DATASETS
        years = options.syncable_seasons
        if options.sport == "nba":
            years = [year for year in years if year in NBA_DATASETS["play_by_play"].available_seasons]
        metrics = []
        for metric in options.metrics:
            eligible = years
            if options.sport == "nba" and metric.value.startswith("lineup_"):
                eligible = [year for year in years if year in NBA_DATASETS["lineups"].available_seasons]
            metrics.append(metric.model_copy(update={"preparable_seasons": list(eligible)}))
        setup = options.data_setup.model_copy(update={"description": "Missing required investigation data prepares automatically. "
                                                       "Explicit downloads are still available for offline use; source coverage is checked before analysis."})
        return options.model_copy(update={"automatic_preparation": True, "preparable_seasons": list(years), "metrics": metrics, "data_setup": setup})

    def explain_metric(self, metric: str, sport: str = "nfl") -> MetricDefinition:
        return self._sport(sport)[1].explain_metric(metric)

    def tool_definitions(self, sport: str = "nfl") -> list[ToolDefinition]:
        return self._sport(sport)[1].tools()

    def resolve_players(self, query: str, sport: str = "nfl", competition: str | None = None,
                        team_id: str | None = None, season: int | None = None) -> list[PlayerOption]:
        from sports_analyst.application.discovery import player_sources

        connector, plugin = self._sport(sport)
        if sport == "cfb":
            from sports_analyst.datasets.cfb import CFBCoverageUnavailable
            if not team_id or not season:
                raise ValueError("Select a college-football school and roster season")
            try:
                return connector.players(team_id, season, query)
            except CFBCoverageUnavailable:
                # Only previously downloaded, attributed participants are used.
                manifests = [item for item in self.store.manifests("player_stats", "cfb")
                             if item.season == season and item.partition_key == f"team:{team_id}" and item.row_count]
                players = {}
                for manifest in manifests:
                    data = self._load_dataset(connector, manifest, {"athlete_id", "name", "team_id"})
                    for row in data.select("athlete_id", "name", "team_id").unique().iter_rows(named=True):
                        if row["team_id"] == team_id and row["name"]:
                            players[row["athlete_id"]] = PlayerOption(
                                player_id=row["athlete_id"], name=row["name"], teams=[team_id], seasons=[season],
                                discovery_source="recorded_game_participants")
                if not players:
                    raise ValueError(
                        "Roster unavailable for this season. Sync selected-school player statistics to discover "
                        "recorded game participants; this is not a complete roster."
                    ) from None
                return sorted(
                    (player for player in players.values() if query.casefold() in player.name.casefold()),
                    key=lambda player: player.name,
                )[:25]
        if sport == "soccer":
            manifests = [item for item in self.store.manifests("lineups", sport, competition) if item.row_count > 0]
            sources = player_sources(self, connector, manifests, sport)
            return plugin.resolve_players(query, sources)
        allowed = (
            {"play_by_play", "rosters", "weekly_rosters", "player_stats", "players"}
            if sport == "nfl"
            else {
                "player_boxscores",
                "stats_player_boxscores",
                "rosters",
                "stats_rosters",
                "game_rosters",
                "stats_game_rosters",
                "player_crosswalk",
                "player_core",
                "play_by_play",
            }
        )
        manifests = [manifest for manifest in self.store.manifests(sport=sport) if manifest.dataset in allowed and manifest.row_count > 0]
        sources = player_sources(self, connector, manifests, sport)
        return plugin.resolve_players(query, sources)

    def sync(
            self, seasons: list[int], job_id: str | None = None, datasets: list[str] | None = None, sport: str = "nfl", competition: str | None = None,
            *, team_ids: list[str] | None = None, conference_id: str | None = None, division_id: str | None = None,
    ) -> list[DatasetManifest]:
        from sports_analyst.application.sync import run_dataset_sync

        return run_dataset_sync(self, seasons, job_id, datasets, sport, competition,
                                team_ids=team_ids, conference_id=conference_id, division_id=division_id)

    def dataset_sync_timeout_seconds(
            self, seasons: list[int], datasets: list[str] | None = None, sport: str = "nfl"
    ) -> int:
        """Size the inactivity timeout to the selected bulk-download workload."""
        baseline = self.settings.event_stream_timeout_seconds
        if sport in {"soccer", "cfb"}:
            return max(baseline, 3600)
        if sport != "nba":
            return baseline
        from sports_analyst.datasets.nba import NBA_DATASETS
        selected = list(dict.fromkeys(datasets or ["play_by_play", "schedules", "team_boxscores", "player_boxscores"]))
        weights = {
            "play_by_play": 5,
            "stats_play_by_play": 5,
            "shots": 3,
            "stats_shots": 3,
            "lineups": 3,
            "team_boxscores": 2,
            "player_boxscores": 2,
            "stats_team_boxscores": 2,
            "stats_player_boxscores": 2,
            "stats_player_game_logs": 2,
        }
        workload = sum(
            weights.get(dataset, 1)
            for season in set(seasons)
            for dataset in selected
            if dataset in NBA_DATASETS and season in NBA_DATASETS[dataset].available_seasons
        )
        return min(3_600, max(baseline, baseline + 20 * workload))

    def _thread_id(self, parent_id: str | None, default: str) -> str:
        if not parent_id:
            return default
        try:
            root = self.store.get_investigation(parent_id)
            while root.run.parent_investigation_id:
                root = self.store.get_investigation(root.run.parent_investigation_id)
            return root.run.investigation_id
        except KeyError:
            return parent_id

    def _prepare_cfb(self, request: AnalysisRequest, identifier: str):
        from sports_analyst.datasets.cfb import CFB_DATASETS
        from sports_analyst.plugins.cfb import ADVANCED as CFB_ADVANCED_METRICS
        connector = self.connectors["cfb"]
        subject = request.subject
        if not subject:
            raise ValueError("Select a college-football team or player")
        partition = f"{subject.type}:{connector.validate_id(subject.id)}"
        self.store.invalidate_reset_cache("cfb")
        seasons = request.scope.included_seasons
        if subject.type == "player":
            history = connector.player_seasons(subject.id)
            if not {request.scope.baseline_season, request.scope.comparison_season} <= set(history):
                raise ValueError("A comparison endpoint is absent from the player's verified history")
            seasons = [season for season in seasons if season in history]
        for season in seasons:
            self.store.refresh_durable_datasets("cfb", [season], CFB_DATASETS, partition_key=partition)
            installed = {item.dataset: item for item in self.store.manifests(sport="cfb", partition_key=partition)
                         if item.season == season}
            complete = all(dataset in installed and installed[dataset].coverage.get("expected_matches", 0) > 0
                           and installed[dataset].coverage.get("completed_matches", 0) >= installed[dataset].coverage.get("expected_matches", 0)
                           for dataset in {"schedules", "team_stats", "player_stats", "scoring_events"})

            def progress(phase, dataset, year, completed, total, fraction=None, detail=None, force=False):
                self.events.emit(identifier, "preparing", f"Preparing {partition} · {year} · {detail or dataset}", 0.15,
                                 season=year, partition_key=partition, dataset=dataset)

            if not (complete and season < datetime.now(UTC).year):
                connector.prepare(season, team_id=subject.id if subject.type == "team" else None,
                                  athlete_id=subject.id if subject.type == "player" else None,
                                  progress=progress, manifest_callback=self.store.save_manifest)
            if season in {request.scope.baseline_season, request.scope.comparison_season}:
                schedule_manifest = self.store.manifest_for_season(season, "schedules", "cfb", partition_key=partition)
                schedule = self._load_dataset(connector, schedule_manifest)
                window = request.scope.baseline if season == request.scope.baseline_season else request.scope.comparison
                selected_schedule = self.plugins["cfb"].window(schedule, window, request)
                if request.scope.baseline_season == request.scope.comparison_season:
                    selected_schedule = pl.concat([selected_schedule, self.plugins["cfb"].window(schedule, request.scope.comparison, request)]).unique(subset=["game_id"])
                connector.prepare_recorded(season, partition, selected_schedule, self.store.save_manifest, progress)
            if set(request.metrics) & CFB_ADVANCED_METRICS.keys() and season in {request.scope.baseline_season, request.scope.comparison_season}:
                def model_progress(game, index, total):
                    self.events.emit(identifier, "preparing", f"Modeling college-football plays · {season} · game {game} · {index + 1}/{total}", 0.18,
                                     season=season, partition_key=partition, dataset="enriched_plays")
                connector.prepare_enriched(season, partition, selected_schedule, self.store.save_manifest, model_progress)
        return partition, seasons

    def _investigation_metadata(self, request: AnalysisRequest, identifier: str, thread_id: str) -> dict[str, Any]:
        subject = request.subject
        return {
            "investigation_id": identifier,
            "thread_id": thread_id,
            "parent_investigation_id": request.parent_investigation_id or "",
            "sport": request.sport,
            "subject_type": subject.type if subject else "team",
            "subject_id": subject.id if subject else request.scope.team,
            "analysis_domain": request.analysis_domain,
            "comparison_design": request.scope.comparison_design,
            "included_seasons": request.scope.included_seasons,
            "metric_count": len(request.metrics),
            "split_count": len(request.splits),
            "provider": self.settings.model_provider,
        }

    def investigate(self, request: AnalysisRequest, investigation_id: str | None = None) -> InvestigationBundle:
        identifier = investigation_id or stable_id("investigation", {"request": request.model_dump(), "time": datetime.now(UTC).isoformat()})
        thread_id = self._thread_id(request.parent_investigation_id, identifier)
        metadata = self._investigation_metadata(request, identifier, thread_id)
        tags = ["open-sports-analyst", f"sport:{request.sport}", f"domain:{request.analysis_domain}"]
        with self.telemetry.span(
                "sports-analyst.investigation",
                inputs={"question": request.question, "scope": request.scope.model_dump(mode="json")},
                metadata=metadata,
                tags=tags,
        ) as root_span:
            bundle = self._investigate(request, identifier, metadata, root_span)
            self.telemetry.add_outputs(
                root_span,
                {
                    "status": bundle.run.status.value,
                    "claim_count": len(bundle.claims),
                    "evidence_count": len(bundle.aggregate_evidence) + len(bundle.play_evidence),
                    "chart_count": len(bundle.charts),
                    "model_id": bundle.model_id or "deterministic",
                    "fallback_used": bundle.fallback_used,
                },
            )
            return bundle

    def _investigate(
            self,
            request: AnalysisRequest,
            identifier: str,
            trace_metadata: dict[str, Any],
            root_span: Any,
    ) -> InvestigationBundle:
        from sports_analyst.analysis.instructions import evidence_brief

        connector, plugin = self._sport(request.sport)
        started_at = perf_counter()
        logger.info(
            "investigation_started investigation_id=%s team=%s domain=%s design=%s seasons=%s "
            "baseline=%s:%s-%s comparison=%s:%s-%s metrics=%d splits=%d",
            identifier,
            request.subject.id if request.subject else request.scope.team,
            request.analysis_domain,
            request.scope.comparison_design,
            ",".join(str(season) for season in request.scope.included_seasons),
            request.scope.baseline_season,
            request.scope.baseline.weeks[0],
            request.scope.baseline.weeks[1],
            request.scope.comparison_season,
            request.scope.comparison.weeks[0],
            request.scope.comparison.weeks[1],
            len(request.metrics),
            len(request.splits),
        )
        self.events.emit(identifier, "planning", "Resolving scope and analytical tools", 0.1)
        with self.telemetry.span("sports-analyst.plan-analysis", metadata=trace_metadata, parent=root_span, run_type="tool") as plan_span:
            plan = plugin.default_plan(request)
            self.telemetry.add_outputs(plan_span, {"planned_tool_count": len(plan.calls)})
        with self.telemetry.span("sports-analyst.load-datasets", metadata=trace_metadata, parent=root_span, run_type="tool") as load_span:
            from sports_analyst.application.investigation_data import load_investigation_data
            partition, manifests, datasets, supplemental_manifests, supplemental = load_investigation_data(
                self, request, identifier, connector, plugin,
            )
            self.telemetry.add_outputs(
                load_span,
                {
                    "play_by_play_seasons": sorted(manifests),
                    "supplemental_dataset_count": len(supplemental_manifests),
                    "manifest_count": len(manifests) + sum(len(items) for items in supplemental_manifests.values()),
                },
            )
        self.events.emit(identifier, "analyzing", "Comparing efficiency and situational splits", 0.4)
        analysis_started_at = perf_counter()
        with self.telemetry.span(
                "sports-analyst.execute-deterministic-analysis",
                metadata=trace_metadata,
                parent=root_span,
                run_type="tool",
        ) as analysis_span:
            result = plugin.analyze(request, datasets, manifests, supplemental, supplemental_manifests)
            from sports_analyst.analysis.calculations import complete_calculations
            from sports_analyst.analysis.scoped_data import ScopedData

            self.events.emit(identifier, "analyzing", "Checking the question against measured evidence", 0.57)
            scoped_data = ScopedData(self, request, partition, identifier)
            scoped_data.progress = lambda message: self.events.emit(identifier, "preparing", message, 0.57)
            complete_calculations(self.settings, request.question, result, {
                "sport": request.sport, "subject": request.subject.model_dump(mode="json") if request.subject else None,
                "domain": request.analysis_domain, "scope": request.scope.model_dump(mode="json"),
            }, data_access=scoped_data)
            from sports_analyst.analysis.research.presentation import add_research_charts

            add_research_charts(result, request=request, data_access=scoped_data)
            if request.sport == "soccer":
                from sports_analyst.datasets.soccer.understat import attach_tablets

                attach_tablets(result.play_evidence, scoped_data)
            queried_ids = {key for item in result.aggregate_evidence for key in item.dataset_manifest_ids}
            if request.sport == "cfb":
                for index, evidence in enumerate(result.play_evidence):
                    if not evidence.play_id or not evidence.visualization:
                        continue
                    self.events.emit(identifier, "analyzing", f"Checking selected-play personnel · {index + 1}/{len(result.play_evidence)}", 0.55)
                    context = dict(evidence.visualization.cfb_statistics)
                    selected_play = dict(context.get("selected_play") or {})
                    try:
                        selected_play = connector.selected_play_context(selected_play, evidence.game_id, evidence.season)
                    except Exception:
                        logger.warning("cfb_selected_context_unavailable game_id=%s", evidence.game_id)
                    context["source_provenance"] = json.loads(selected_play.get("source_provenance_json") or "{}")
                    selected_play["personnel_context"] = connector.play_personnel(evidence.game_id, evidence.season, evidence.play_id)
                    context["selected_play"] = selected_play
                    visualization = evidence.visualization.model_copy(update={"cfb_statistics": context,
                        "formation": selected_play.get("formation", evidence.visualization.formation),
                        "pass_location": selected_play.get("pass_direction", evidence.visualization.pass_location),
                        "run_location": selected_play.get("rush_direction", evidence.visualization.run_location),
                        "pass_length": selected_play.get("pass_depth", evidence.visualization.pass_length)})
                    result.play_evidence[index] = evidence.model_copy(update={"visualization": visualization})
            self.telemetry.add_outputs(
                analysis_span,
                {
                    "aggregate_evidence_count": len(result.aggregate_evidence),
                    "play_evidence_count": len(result.play_evidence),
                    "execution_count": len(result.executions),
                    "chart_count": len(result.charts),
                },
            )
        logger.info(
            "analysis_completed investigation_id=%s aggregates=%d plays=%d executions=%d charts=%d duration_ms=%d",
            identifier,
            len(result.aggregate_evidence),
            len(result.play_evidence),
            len(result.executions),
            len(result.charts),
            round((perf_counter() - analysis_started_at) * 1000),
        )
        self.events.emit(identifier, "synthesizing", "Reviewing evidence and drafting findings", 0.75)
        synthesis_started_at = perf_counter()
        with self.telemetry.span("sports-analyst.synthesize-report", metadata=trace_metadata, parent=root_span) as synthesis_span:
            conversation_context = None
            if request.parent_investigation_id:
                conversation_context = [
                    {"question": item.run.question, "summary": item.summary}
                    for item in self.store.investigation_thread(request.parent_investigation_id)
                ]
            definitions = []
            for metric in sorted({item.metric for item in result.aggregate_evidence}):
                try:
                    definitions.append(self.explain_metric(metric, request.sport))
                except (ValueError, KeyError):
                    # Derived split/trend evidence may not have a registered metric definition.
                    pass
            source_manifests = {item.manifest_id: item for item in manifests.values()}
            for packages in supplemental_manifests.values():
                source_manifests.update({item.manifest_id: item for item in packages.values()})
            source_manifests.update({key: item for key, item in scoped_data.manifests.items() if key in queried_ids})
            analytical_context = evidence_brief(
                result.aggregate_evidence, definitions, list(source_manifests.values()),
                {"sport": request.sport, "domain": request.analysis_domain,
                 "subject": request.subject.model_dump(mode="json") if request.subject else {"type": "team", "id": request.scope.team},
                 "comparison": request.scope.model_dump(mode="json"), "as_of": datetime.now(UTC).isoformat()})
            analytical_context["question_coverage_reviews"] = [
                {"plan": item.parameters.get("plan"), "review": item.parameters.get("question_review")}
                for item in result.executions if item.tool == "complete_calculations"]
            analytical_context["calculation_stage_status"] = (
                "failed" if any(item.tool == "complete_calculations_failed" for item in result.executions) else "complete_or_not_requested")
            analytical_context["calculation_failure_types"] = [item.parameters["error_type"] for item in result.executions
                                                               if item.tool == "complete_calculations_failed"]
            draft, model_id, fallback = self.agent.synthesize(
                request.question,
                request.subject.id if request.subject else request.scope.team,
                request.scope.baseline,
                request.scope.comparison,
                result.aggregate_evidence,
                result.play_evidence,
                request.scope.included_seasons if request.scope.comparison_design == "full_seasons" else None,
                conversation_context,
                request.analysis_domain,
                request.sport,
                progress_callback=lambda message, progress: self.events.emit(identifier, "synthesizing", message, progress),
                trace_metadata=trace_metadata,
                competition=request.scope.competition,
                analytical_context=analytical_context,
            )
            if analytical_context["calculation_stage_status"] == "failed":
                draft = draft.model_copy(update={"summary": (
                    "Partial analysis: the additional calculation stage failed. "
                    "The findings below use existing evidence; this failure does not establish that source data are missing.\n\n"
                    + draft.summary)[:2500]})
            self.telemetry.add_outputs(
                synthesis_span,
                {"claim_count": len(draft.claims), "model_id": model_id or "deterministic", "fallback_used": fallback},
            )
        logger.info(
            "synthesis_completed investigation_id=%s model_id=%s fallback=%s claims=%d duration_ms=%d",
            identifier,
            model_id or "deterministic",
            str(fallback).lower(),
            len(draft.claims),
            round((perf_counter() - synthesis_started_at) * 1000),
        )
        with self.telemetry.span(
                "sports-analyst.validate-and-persist", metadata=trace_metadata, parent=root_span, run_type="tool"
        ) as persist_span:
            subject = request.subject
            if subject is not None and subject.type == "team" and not subject.display_name:
                options = self.analysis_options(request.sport, request.scope.competition)
                team_name = next((team.label for team in options.teams if team.value == subject.id), None)
                if team_name:
                    subject = subject.model_copy(update={"display_name": team_name})
            run = InvestigationRun(
                sport=request.sport,
                subject=subject,
                investigation_id=identifier,
                parent_investigation_id=request.parent_investigation_id,
                question=request.question,
                scope=request.scope,
                analysis_domain=request.analysis_domain,
                metrics=request.metrics,
                splits=request.splits,
                status=RunStatus.COMPLETED,
                completed_at=datetime.now(UTC),
            )
            bundle = InvestigationBundle(
                run=run,
                plan=plan,
                summary=draft.summary,
                claims=draft.claims,
                aggregate_evidence=result.aggregate_evidence,
                play_evidence=result.play_evidence,
                charts=result.charts,
                executions=result.executions,
                dataset_manifests=list(source_manifests.values()),
                methodological_caveats=result.caveats,
                model_id=model_id,
                fallback_used=fallback,
            )
            self.store.save_investigation(bundle)
            self.telemetry.add_outputs(persist_span, {"investigation_id": identifier, "saved": True})
        self.events.emit(identifier, "complete", "Investigation ready", 1.0, investigation_id=identifier)
        logger.info(
            "investigation_completed investigation_id=%s duration_ms=%d",
            identifier,
            round((perf_counter() - started_at) * 1000),
        )
        return bundle

    def follow_up(self, parent_id: str, question: str, investigation_id: str | None = None) -> InvestigationBundle:
        source = self.store.get_investigation(parent_id)
        root = source
        while root.run.parent_investigation_id:
            root = self.store.get_investigation(root.run.parent_investigation_id)
        identifier = investigation_id or stable_id(
            "investigation", {"parent": root.run.investigation_id, "question": question, "time": datetime.now(UTC).isoformat()}
        )
        metadata = {
            "investigation_id": identifier,
            "thread_id": root.run.investigation_id,
            "parent_investigation_id": root.run.investigation_id,
            "sport": root.run.sport,
            "subject_type": root.run.subject.type if root.run.subject else "team",
            "subject_id": root.run.subject.id if root.run.subject else root.run.scope.team,
            "analysis_domain": root.run.analysis_domain,
            "comparison_design": root.run.scope.comparison_design,
            "included_seasons": root.run.scope.included_seasons,
            "metric_count": len(root.run.metrics),
            "split_count": len(root.run.splits),
            "provider": self.settings.model_provider,
            "follow_up": True,
        }
        tags = ["open-sports-analyst", "follow-up", f"sport:{root.run.sport}", f"domain:{root.run.analysis_domain}"]
        with self.telemetry.span(
                "sports-analyst.follow-up",
                inputs={"question": question, "parent_investigation_id": root.run.investigation_id},
                metadata=metadata,
                tags=tags,
        ) as root_span:
            bundle = self._follow_up(root, question, identifier, metadata, root_span)
            self.telemetry.add_outputs(
                root_span,
                {
                    "status": bundle.run.status.value,
                    "claim_count": len(bundle.claims),
                    "evidence_count": len(bundle.aggregate_evidence) + len(bundle.play_evidence),
                    "model_id": bundle.model_id or "deterministic",
                    "fallback_used": bundle.fallback_used,
                },
            )
            return bundle

    def _follow_up(
            self,
            root: InvestigationBundle,
            question: str,
            identifier: str,
            trace_metadata: dict[str, Any],
            root_span: Any,
    ) -> InvestigationBundle:
        started_at = perf_counter()
        logger.info("follow_up_started investigation_id=%s parent_id=%s mode=reuse", identifier, root.run.investigation_id)
        from sports_analyst.analysis.calculations import needs_phase_accounting

        if (root.run.sport == "nfl" and root.run.analysis_domain == "offense" and needs_phase_accounting(question)
                and ("epa" in question.lower() or "epa_per_play" in root.run.metrics)
                and not any(item.metric == "epa_phase_contribution" for item in root.aggregate_evidence)):
            # Older reports may lack a now-supported calculation. Re-enter the
            # normal preparation/evidence pipeline instead of rewording a gap.
            return self._investigate(AnalysisRequest(sport=root.run.sport, subject=root.run.subject, question=question,
                scope=root.run.scope, analysis_domain=root.run.analysis_domain,
                metrics=list(dict.fromkeys(["epa_per_play", *root.run.metrics])),
                splits=root.run.splits, parent_investigation_id=root.run.investigation_id), identifier, trace_metadata, root_span)
        with self.telemetry.span(
                "sports-analyst.reuse-parent-evidence", metadata=trace_metadata, parent=root_span, run_type="tool"
        ) as reuse_span:
            self.events.emit(identifier, "planning", "Reviewing the existing investigation", 0.1)
            self.events.emit(identifier, "analyzing", "Reusing validated evidence from the parent investigation", 0.55)
            conversation_context = [
                {"question": item.run.question, "summary": item.summary} for item in
                self.store.investigation_thread(root.run.investigation_id)
            ]
            self.telemetry.add_outputs(
                reuse_span,
                {
                    "conversation_turn_count": len(conversation_context),
                    "aggregate_evidence_count": len(root.aggregate_evidence),
                    "play_evidence_count": len(root.play_evidence),
                },
            )
        self.events.emit(identifier, "synthesizing", "Answering the follow-up from validated evidence", 0.75)
        from types import SimpleNamespace

        from sports_analyst.analysis.calculations import complete_calculations
        from sports_analyst.analysis.research.presentation import add_research_charts
        from sports_analyst.analysis.scoped_data import ScopedData

        request = AnalysisRequest(sport=root.run.sport, subject=root.run.subject, question=question,
            scope=root.run.scope, analysis_domain=root.run.analysis_domain, metrics=root.run.metrics,
            splits=root.run.splits, parent_investigation_id=root.run.investigation_id)
        partition = None
        if request.sport == "cfb" and request.subject:
            partition = f"{request.subject.type}:{request.subject.id}"
        elif request.sport == "soccer" and request.subject and request.subject.type == "team":
            partition = f"team:{request.subject.id}"
        scoped = ScopedData(self, request, partition, identifier)
        scoped.progress = lambda message: self.events.emit(identifier, "preparing", message, 0.6)
        work = SimpleNamespace(aggregate_evidence=list(root.aggregate_evidence), executions=[],
                               caveats=[], charts=list(root.charts))
        complete_calculations(self.settings, question, work, request.scope.model_dump(mode="json"), scoped)
        add_research_charts(work, request=request, data_access=scoped)
        source_manifests = {m.manifest_id: m for m in root.dataset_manifests}
        used = {key for e in work.aggregate_evidence for key in e.dataset_manifest_ids}
        source_manifests.update({key: m for key, m in scoped.manifests.items() if key in used})
        from sports_analyst.analysis.instructions import evidence_brief
        context = evidence_brief(work.aggregate_evidence, [], list(source_manifests.values()),
                                 {"sport": request.sport, "comparison": request.scope.model_dump(mode="json")})
        context["question_coverage_reviews"] = [{"plan": e.parameters.get("plan"), "review": e.parameters.get("question_review")}
                                                for e in work.executions if e.tool == "complete_calculations"]
        failed = any(e.tool == "complete_calculations_failed" for e in work.executions)
        context["calculation_stage_status"] = "failed" if failed else "complete_or_not_requested"
        with self.telemetry.span("sports-analyst.synthesize-follow-up", metadata=trace_metadata, parent=root_span) as synthesis_span:
            draft, model_id, fallback = self.agent.synthesize(
                question,
                root.run.subject.id if root.run.subject else root.run.scope.team,
                root.run.scope.baseline,
                root.run.scope.comparison,
                work.aggregate_evidence,
                root.play_evidence,
                root.run.scope.included_seasons if root.run.scope.comparison_design == "full_seasons" else None,
                conversation_context,
                root.run.analysis_domain,
                root.run.sport,
                progress_callback=lambda message, progress: self.events.emit(identifier, "synthesizing", message, progress),
                trace_metadata=trace_metadata,
                competition=root.run.scope.competition,
                analytical_context=context,
            )
            if failed:
                draft = draft.model_copy(update={"summary": ("Partial analysis: additional research failed; independently validated evidence remains usable.\n\n" + draft.summary)[:2500]})
            self.telemetry.add_outputs(
                synthesis_span,
                {"claim_count": len(draft.claims), "model_id": model_id or "deterministic", "fallback_used": fallback},
            )
        with self.telemetry.span(
                "sports-analyst.persist-follow-up", metadata=trace_metadata, parent=root_span, run_type="tool"
        ) as persist_span:
            plan_payload = {
                "question": question,
                "parent": root.run.investigation_id,
                "evidence": [item.evidence_id for item in [*root.aggregate_evidence, *root.play_evidence]],
            }
            plan = AnalysisPlan(
                plan_id=stable_id("plan", plan_payload),
                question=question,
                scope=root.run.scope,
                calls=[
                    PlannedToolCall(
                        tool="reuse_parent_evidence",
                        arguments={"parent_investigation_id": root.run.investigation_id},
                        purpose="Answer the follow-up without repeating unchanged deterministic analysis.",
                    )
                ],
            )
            run = InvestigationRun(
                sport=root.run.sport,
                subject=root.run.subject,
                investigation_id=identifier,
                parent_investigation_id=root.run.investigation_id,
                question=question,
                scope=root.run.scope,
                analysis_domain=root.run.analysis_domain,
                metrics=root.run.metrics,
                splits=root.run.splits,
                status=RunStatus.COMPLETED,
                completed_at=datetime.now(UTC),
            )
            bundle = InvestigationBundle(
                run=run,
                plan=plan,
                summary=draft.summary,
                claims=draft.claims,
                aggregate_evidence=work.aggregate_evidence,
                play_evidence=root.play_evidence,
                charts=work.charts,
                executions=[*root.executions, *work.executions],
                dataset_manifests=list(source_manifests.values()),
                methodological_caveats=[
                    *root.methodological_caveats,
                    *work.caveats,
                    "This follow-up reused parent evidence; additional host-validated research was permitted for unanswered objectives.",
                ],
                model_id=model_id,
                fallback_used=fallback,
            )
            self.store.save_investigation(bundle)
            self.telemetry.add_outputs(persist_span, {"investigation_id": identifier, "saved": True})
        self.events.emit(identifier, "complete", "Follow-up ready", 1.0, investigation_id=identifier)
        logger.info(
            "follow_up_completed investigation_id=%s parent_id=%s duration_ms=%d",
            identifier,
            root.run.investigation_id,
            round((perf_counter() - started_at) * 1000),
        )
        return bundle

    def evidence(self, investigation_id: str, evidence_id: str) -> Any:
        bundle = self.store.get_investigation(investigation_id)
        matches = [item for item in [*bundle.aggregate_evidence, *bundle.play_evidence] if item.evidence_id == evidence_id]
        if not matches:
            raise KeyError(f"evidence not found: {evidence_id}")
        return self._soccer_recap_context(bundle, matches[0])

    def _soccer_recap_context(self, bundle, evidence):
        if evidence not in bundle.play_evidence or evidence.sport != "soccer" or not evidence.visualization:
            return evidence
        from sports_analyst.datasets.soccer.recap import cached_timeline

        timeline = cached_timeline(self.connectors["soccer"], bundle.run.scope.competition,
            evidence.season, evidence.game_id, evidence.visualization.soccer_timeline)
        from sports_analyst.datasets.soccer.whoscored import cached_recap

        visual = evidence.visualization.model_copy(update={"soccer_timeline": timeline})
        try:
            visual = cached_recap(self.connectors["soccer"], bundle.run.scope.competition, evidence.season, evidence.game_id, visual)
        except (OSError, ValueError, TypeError, KeyError) as error:
            logger.warning("soccer_recap_enrichment_unavailable game_id=%s error_type=%s", evidence.game_id, type(error).__name__)
        from sports_analyst.datasets.soccer.shot_recap import hydrate_shots, match_shots

        try:
            visual = hydrate_shots(self.store, evidence, bundle.run.scope.competition, visual)
            visual = match_shots(visual, evidence.game_id)
        except (OSError, ValueError, TypeError, KeyError, pl.exceptions.PolarsError) as error:
            logger.warning("soccer_shot_context_unavailable game_id=%s error_type=%s", evidence.game_id, type(error).__name__)
        return evidence.model_copy(update={"visualization": visual})

    def evidence_many(self, investigation_id: str, evidence_ids: list[str]) -> list[Any]:
        bundle = self.store.get_investigation(investigation_id)
        lookup = {item.evidence_id: item for item in [*bundle.aggregate_evidence, *bundle.play_evidence]}
        missing = [identifier for identifier in evidence_ids if identifier not in lookup]
        if missing:
            raise KeyError(f"evidence not found: {missing}")
        return [self._soccer_recap_context(bundle, lookup[identifier]) for identifier in evidence_ids]

    def query_sql(self, sql: str, sport: str = "nfl", partition_key: str | None = None) -> list[dict[str, Any]]:
        if sport == "cfb" and not partition_key:
            raise ValueError("College-football SQL requires an explicit selected-subject partition")
        manifests = self.store.manifests(sport=sport, partition_key=partition_key)
        if not manifests:
            raise ValueError("no datasets are registered")
        from sports_analyst.storage.sql import execute_read_only_sql
        rows, _duration = execute_read_only_sql(
            sql,
            {(item.dataset, item.season): Path(item.local_path) for item in manifests},
            self.settings.sql_row_limit,
        )
        return rows
