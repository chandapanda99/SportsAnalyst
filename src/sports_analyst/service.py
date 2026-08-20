from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sports_analyst.agents import EvidenceBoundAgent
from sports_analyst.config import Settings, get_settings
from sports_analyst.data import NFLVerseConnector
from sports_analyst.models import (
    AnalysisRequest,
    DatasetManifest,
    InvestigationBundle,
    InvestigationRun,
    RunStatus,
    RuntimeCapabilities,
    stable_id,
)
from sports_analyst.plugins import NFLPlugin
from sports_analyst.providers import provider_ids
from sports_analyst.sql import execute_read_only_sql
from sports_analyst.storage import EventRegistry, LocalStore


class AnalystApplication:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
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

    def sync(self, seasons: list[int], job_id: str | None = None) -> list[DatasetManifest]:
        key = job_id or stable_id("sync", {"seasons": sorted(seasons), "time": datetime.now(UTC)})
        self.events.emit(key, "starting", "Downloading selected nflverse seasons", 0.05)
        manifests = self.connector.sync(seasons)
        for index, manifest in enumerate(manifests, start=1):
            self.store.save_manifest(manifest)
            self.events.emit(key, "registering", f"Registered {manifest.season}", 0.1 + 0.8 * index / len(manifests))
        self.events.emit(key, "complete", "Dataset sync complete", 1.0, manifest_ids=[item.manifest_id for item in manifests])
        return manifests

    def investigate(self, request: AnalysisRequest, investigation_id: str | None = None) -> InvestigationBundle:
        identifier = investigation_id or stable_id(
            "investigation", {"request": request.model_dump(), "time": datetime.now(UTC).isoformat()}
        )
        self.events.emit(identifier, "planning", "Resolving scope and analytical tools", 0.1)
        plan = self.plugin.default_plan(request)
        manifests = {
            season: self.store.manifest_for_season(season)
            for season in (request.scope.baseline_season, request.scope.comparison_season)
        }
        datasets = {season: self.connector.load(manifest) for season, manifest in manifests.items()}
        self.events.emit(identifier, "analyzing", "Comparing efficiency and situational splits", 0.4)
        result = self.plugin.analyze(request, datasets, manifests)
        self.events.emit(identifier, "synthesizing", "Reviewing evidence and drafting findings", 0.75)
        draft, model_id, fallback = self.agent.synthesize(
            request.scope.team,
            request.scope.baseline_season,
            request.scope.comparison_season,
            result.aggregate_evidence,
            result.play_evidence,
        )
        run = InvestigationRun(
            investigation_id=identifier,
            parent_investigation_id=request.parent_investigation_id,
            question=request.question,
            scope=request.scope,
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
            dataset_manifests=list(manifests.values()),
            methodological_caveats=result.caveats,
            model_id=model_id,
            fallback_used=fallback,
        )
        self.store.save_investigation(bundle)
        self.events.emit(identifier, "complete", "Investigation ready", 1.0, investigation_id=identifier)
        return bundle

    def follow_up(self, parent_id: str, question: str) -> InvestigationBundle:
        parent = self.store.get_investigation(parent_id)
        return self.investigate(AnalysisRequest(question=question, scope=parent.run.scope, parent_investigation_id=parent_id))

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
        rows, _duration = execute_read_only_sql(sql, {item.season: Path(item.local_path) for item in manifests}, self.settings.sql_row_limit)
        return rows
