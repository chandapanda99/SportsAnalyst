from __future__ import annotations

from typing import Any, Protocol

from sports_analyst.models import AnalysisPlan, AnalysisRequest, ToolDefinition


class SportPlugin(Protocol):
    sport_id: str
    display_name: str

    def tools(self) -> list[ToolDefinition]: ...

    def resolve_team(self, team: str) -> str: ...

    def default_plan(self, request: AnalysisRequest) -> AnalysisPlan: ...

    def analyze(self, request: AnalysisRequest, datasets: dict[int, Any], manifests: dict[int, Any]) -> Any: ...
