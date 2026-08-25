from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from sports_analyst.agents import EvidenceBoundAgent
from sports_analyst.config import Settings, get_settings
from sports_analyst.data import NFLVerseConnector
from sports_analyst.log_config import configure_logging
from sports_analyst.models import (
    AnalysisOptions,
    AnalysisRequest,
    DatasetManifest,
    InvestigationBundle,
    InvestigationRun,
    MetricDefinition,
    PlayerOption,
    RunStatus,
    RuntimeCapabilities,
    ToolDefinition,
    stable_id,
)
from sports_analyst.plugins import NFLPlugin
from sports_analyst.providers import provider_ids
from sports_analyst.sql import execute_read_only_sql
from sports_analyst.storage import EventRegistry, LocalStore

logger = logging.getLogger("sports_analyst.service")


class AnalystApplication:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        configure_logging(self.settings.log_level)
        self.store = LocalStore(self.settings)
        self.connector = NFLVerseConnector(self.settings)
        self.plugin = NFLPlugin()
        self.agent = EvidenceBoundAgent(self.settings)
        self.events = EventRegistry()

    def capabilities(self) -> RuntimeCapabilities:
        configured = self.settings.model_provider == "ollama" or bool(self.settings.foundry_endpoint)
        return RuntimeCapabilities(
            providers=provider_ids(), configured_provider=self.settings.model_provider, model_configured=configured, custom_analysis=False
        )

    def analysis_options(self) -> AnalysisOptions:
        team_manifests = self.store.manifests("teams")
        teams = self.connector.load(team_manifests[0]) if team_manifests else None
        return self.plugin.analysis_options(self.store.manifests("play_by_play"), teams)

    def explain_metric(self, metric: str) -> MetricDefinition:
        return self.plugin.explain_metric(metric)

    def tool_definitions(self) -> list[ToolDefinition]:
        return self.plugin.tools()

    def resolve_players(self, query: str) -> list[PlayerOption]:
        manifests = [
            manifest
            for manifest in self.store.manifests()
            if manifest.dataset in {"play_by_play", "rosters", "weekly_rosters", "player_stats", "players"}
        ]
        sources = [(manifest.season, self.connector.load(manifest)) for manifest in manifests]
        return self.plugin.resolve_players(query, sources)

    def sync(self, seasons: list[int], job_id: str | None = None, datasets: list[str] | None = None) -> list[DatasetManifest]:
        selected_datasets = datasets or ["play_by_play"]
        key = job_id or stable_id("sync", {"seasons": sorted(seasons), "datasets": selected_datasets, "time": datetime.now(UTC)})
        started_at = perf_counter()
        logger.info(
            "dataset_sync_started job_id=%s seasons=%s datasets=%s",
            key,
            ",".join(str(season) for season in sorted(seasons)),
            ",".join(selected_datasets),
        )
        self.events.emit(key, "starting", "Downloading selected nflverse seasons", 0.05)
        manifests = self.connector.sync(seasons, selected_datasets)
        for index, manifest in enumerate(manifests, start=1):
            self.store.save_manifest(manifest)
            self.events.emit(
                key,
                "registering",
                f"Registered {manifest.dataset} {manifest.season}",
                0.1 + 0.8 * index / len(manifests),
            )
        self.events.emit(key, "complete", "Dataset sync complete", 1.0, manifest_ids=[item.manifest_id for item in manifests])
        logger.info(
            "dataset_sync_completed job_id=%s manifests=%d duration_ms=%d",
            key,
            len(manifests),
            round((perf_counter() - started_at) * 1000),
        )
        return manifests

    def investigate(self, request: AnalysisRequest, investigation_id: str | None = None) -> InvestigationBundle:
        started_at = perf_counter()
        identifier = investigation_id or stable_id(
            "investigation", {"request": request.model_dump(), "time": datetime.now(UTC).isoformat()}
        )
        logger.info(
            "investigation_started investigation_id=%s team=%s domain=%s design=%s seasons=%s "
            "baseline=%s:%s-%s comparison=%s:%s-%s metrics=%d splits=%d",
            identifier,
            request.scope.team,
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
        plan = self.plugin.default_plan(request)
        manifests = {season: self.store.manifest_for_season(season, "play_by_play") for season in request.scope.included_seasons}
        datasets = {season: self.connector.load(manifest) for season, manifest in manifests.items()}
        supplemental_manifests: dict[str, dict[int, DatasetManifest]] = {}
        for manifest in self.store.manifests():
            if manifest.dataset in {"play_by_play", "teams"}:
                continue
            if manifest.dataset != "players" and manifest.season not in manifests:
                continue
            supplemental_manifests.setdefault(manifest.dataset, {})[manifest.season] = manifest
        supplemental = {
            dataset: {season: self.connector.load(manifest) for season, manifest in season_manifests.items()}
            for dataset, season_manifests in supplemental_manifests.items()
        }
        self.events.emit(identifier, "analyzing", "Comparing efficiency and situational splits", 0.4)
        analysis_started_at = perf_counter()
        result = self.plugin.analyze(request, datasets, manifests, supplemental, supplemental_manifests)
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
        conversation_context = None
        if request.parent_investigation_id:
            conversation_context = [
                {"question": item.run.question, "summary": item.summary}
                for item in self.store.investigation_thread(request.parent_investigation_id)
            ]
        draft, model_id, fallback = self.agent.synthesize(
            request.question,
            request.scope.team,
            request.scope.baseline,
            request.scope.comparison,
            result.aggregate_evidence,
            result.play_evidence,
            request.scope.included_seasons if request.scope.comparison_design == "full_seasons" else None,
            conversation_context,
            request.analysis_domain,
            progress_callback=lambda message, progress: self.events.emit(
                identifier, "synthesizing", message, progress
            ),
        )
        logger.info(
            "synthesis_completed investigation_id=%s model_id=%s fallback=%s claims=%d duration_ms=%d",
            identifier,
            model_id or "deterministic",
            str(fallback).lower(),
            len(draft.claims),
            round((perf_counter() - synthesis_started_at) * 1000),
        )
        run = InvestigationRun(
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
        return self.investigate(
            AnalysisRequest(
                question=question,
                scope=root.run.scope,
                analysis_domain=root.run.analysis_domain,
                metrics=root.run.metrics,
                splits=root.run.splits,
                parent_investigation_id=root.run.investigation_id,
            ),
            investigation_id,
        )

    def evidence(self, investigation_id: str, evidence_id: str) -> Any:
        bundle = self.store.get_investigation(investigation_id)
        matches = [item for item in [*bundle.aggregate_evidence, *bundle.play_evidence] if item.evidence_id == evidence_id]
        if not matches:
            raise KeyError(f"evidence not found: {evidence_id}")
        return matches[0]

    def query_sql(self, sql: str) -> list[dict[str, Any]]:
        manifests = self.store.manifests()
        if not manifests:
            raise ValueError("no datasets are registered")
        rows, _duration = execute_read_only_sql(
            sql, {item.season: Path(item.local_path) for item in manifests}, self.settings.sql_row_limit
        )
        return rows
