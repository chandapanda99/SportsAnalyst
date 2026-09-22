from __future__ import annotations

import logging
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import polars as pl

from sports_analyst.config import Settings, get_settings
from sports_analyst.data import NFLVerseConnector
from sports_analyst.log_config import configure_logging
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
    ToolDefinition,
    stable_id,
)
from sports_analyst.nba_data import NBA_DATASETS, SportsDataverseNBAConnector, nba_live_transport_available
from sports_analyst.persistence import PersistenceBackend
from sports_analyst.plugins import NBAPlugin, NFLPlugin
from sports_analyst.sql import execute_read_only_sql
from sports_analyst.storage import EventRegistry, LocalStore

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
    ) -> None:
        self.settings = settings or get_settings()
        configure_logging(self.settings.log_level)
        self.store = LocalStore(self.settings, persistence, restore_durable_index=restore_durable_index)
        nfl_connector = NFLVerseConnector(self.settings)
        nfl_plugin = NFLPlugin()
        self.connectors: dict[str, Any] = {
            "nfl": nfl_connector,
            "nba": SportsDataverseNBAConnector(self.settings),
        }
        self.plugins: dict[str, Any] = {"nfl": nfl_plugin, "nba": NBAPlugin()}
        # Compatibility aliases for integrations that still customize the NFL
        # application through these public attributes.
        self.connector = nfl_connector
        self.plugin = nfl_plugin
        if analysis_runtime:
            from sports_analyst.agents import EvidenceBoundAgent
            from sports_analyst.telemetry import LangSmithTelemetry

            self.agent = EvidenceBoundAgent(self.settings)
            self.telemetry = LangSmithTelemetry(self.settings)
        else:
            self.agent = None
            self.telemetry = _DisabledTelemetry()
        self.events = EventRegistry()
        self.jobs = None
        if self.settings.job_backend == "sqlite":
            from sports_analyst.jobs import SQLiteJobStore

            self.jobs = SQLiteJobStore(self.settings.job_database_path)
        elif self.settings.job_backend == "object":
            from sports_analyst.object_jobs import ObjectJobStore

            polling = self.settings.job_progress_transport == "poll"
            self.jobs = ObjectJobStore(
                self.store.persistence,
                record_events=not polling,
                status_min_interval=0.5 if polling else 0,
            )

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

    def analysis_options(self, sport: str = "nfl") -> AnalysisOptions:
        connector, plugin = self._sport(sport)
        manifests = self.store.manifests(sport=sport)
        if sport == "nfl":
            team_manifests = self.store.manifests("teams", sport)
            context = self._load_dataset(connector, team_manifests[0]) if team_manifests else None
        else:
            team_frames = [self._load_dataset(connector, item) for item in self.store.manifests("team_boxscores", sport)]
            schedule_frames = {item.season: self._load_dataset(connector, item) for item in self.store.manifests("schedules", sport)}
            context = {
                "teams": pl.concat(team_frames, how="diagonal_relaxed") if team_frames else pl.DataFrame(),
                "schedules": schedule_frames,
            }
        return plugin.analysis_options(manifests, context)

    def explain_metric(self, metric: str, sport: str = "nfl") -> MetricDefinition:
        return self._sport(sport)[1].explain_metric(metric)

    def tool_definitions(self, sport: str = "nfl") -> list[ToolDefinition]:
        return self._sport(sport)[1].tools()

    def resolve_players(self, query: str, sport: str = "nfl") -> list[PlayerOption]:
        connector, plugin = self._sport(sport)
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
        manifests = [manifest for manifest in self.store.manifests(sport=sport) if manifest.dataset in allowed]
        sources = [(manifest.season, self._load_dataset(connector, manifest)) for manifest in manifests]
        return plugin.resolve_players(query, sources)

    def sync(
            self, seasons: list[int], job_id: str | None = None, datasets: list[str] | None = None, sport: str = "nfl"
    ) -> list[DatasetManifest]:
        from sports_analyst.sync_service import run_dataset_sync

        return run_dataset_sync(self, seasons, job_id, datasets, sport)

    def dataset_sync_timeout_seconds(
            self, seasons: list[int], datasets: list[str] | None = None, sport: str = "nfl"
    ) -> int:
        """Size the inactivity timeout to the selected bulk-download workload."""
        baseline = self.settings.event_stream_timeout_seconds
        if sport != "nba":
            return baseline
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
            manifests = {
                season: self.store.manifest_for_season(season, "play_by_play", request.sport) for season in request.scope.included_seasons
            }
            pbp_columns = plugin.required_play_by_play_columns(request)
            datasets = {
                season: self._load_dataset(
                    connector,
                    manifest,
                    pbp_columns,
                    self._nfl_play_by_play_predicate(request, manifest) if request.sport == "nfl" else None,
                )
                for season, manifest in manifests.items()
            }
            required_supplemental = plugin.required_supplemental_datasets(request)
            endpoint_seasons = {request.scope.baseline_season, request.scope.comparison_season}
            supplemental_manifests: dict[str, dict[int, DatasetManifest]] = {}
            for manifest in self.store.manifests(sport=request.sport):
                if manifest.dataset in {"play_by_play", "teams"}:
                    continue
                if manifest.dataset not in required_supplemental:
                    continue
                if manifest.dataset != "players" and manifest.season not in endpoint_seasons:
                    continue
                supplemental_manifests.setdefault(manifest.dataset, {})[manifest.season] = manifest
            supplemental = {
                dataset: {season: self._load_dataset(connector, manifest) for season, manifest in season_manifests.items()}
                for dataset, season_manifests in supplemental_manifests.items()
            }
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
            )
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
            run = InvestigationRun(
                sport=request.sport,
                subject=request.subject,
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
                dataset_manifests=[
                    *manifests.values(),
                    *(manifest for season_manifests in supplemental_manifests.values() for manifest in season_manifests.values()),
                ],
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
        with self.telemetry.span("sports-analyst.synthesize-follow-up", metadata=trace_metadata, parent=root_span) as synthesis_span:
            draft, model_id, fallback = self.agent.synthesize(
                question,
                root.run.subject.id if root.run.subject else root.run.scope.team,
                root.run.scope.baseline,
                root.run.scope.comparison,
                root.aggregate_evidence,
                root.play_evidence,
                root.run.scope.included_seasons if root.run.scope.comparison_design == "full_seasons" else None,
                conversation_context,
                root.run.analysis_domain,
                root.run.sport,
                progress_callback=lambda message, progress: self.events.emit(identifier, "synthesizing", message, progress),
                trace_metadata=trace_metadata,
            )
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
                aggregate_evidence=root.aggregate_evidence,
                play_evidence=root.play_evidence,
                charts=root.charts,
                executions=root.executions,
                dataset_manifests=root.dataset_manifests,
                methodological_caveats=[
                    *root.methodological_caveats,
                    "This follow-up reused the parent investigation's immutable evidence; no deterministic tools were rerun.",
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
        return matches[0]

    def evidence_many(self, investigation_id: str, evidence_ids: list[str]) -> list[Any]:
        bundle = self.store.get_investigation(investigation_id)
        lookup = {item.evidence_id: item for item in [*bundle.aggregate_evidence, *bundle.play_evidence]}
        missing = [identifier for identifier in evidence_ids if identifier not in lookup]
        if missing:
            raise KeyError(f"evidence not found: {missing}")
        return [lookup[identifier] for identifier in evidence_ids]

    def query_sql(self, sql: str, sport: str = "nfl") -> list[dict[str, Any]]:
        manifests = self.store.manifests(sport=sport)
        if not manifests:
            raise ValueError("no datasets are registered")
        rows, _duration = execute_read_only_sql(
            sql,
            {(item.dataset, item.season): Path(item.local_path) for item in manifests},
            self.settings.sql_row_limit,
        )
        return rows
