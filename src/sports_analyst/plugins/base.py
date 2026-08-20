from __future__ import annotations

from typing import Any, Protocol

from sports_analyst.models import AnalysisOptions, AnalysisPlan, AnalysisRequest, DatasetManifest, ToolDefinition


class SportPlugin(Protocol):
    sport_id: str
    display_name: str

    def tools(self) -> list[ToolDefinition]: ...

    def analysis_options(self, manifests: list[DatasetManifest]) -> AnalysisOptions: ...

    def resolve_team(self, team: str) -> str: ...

    def default_plan(self, request: AnalysisRequest) -> AnalysisPlan: ...

    def analyze(
        self,
        request: AnalysisRequest,
        datasets: dict[int, Any],
        manifests: dict[int, Any],
        supplemental: dict[str, dict[int, Any]] | None = None,
        supplemental_manifests: dict[str, dict[int, Any]] | None = None,
    ) -> Any: ...
