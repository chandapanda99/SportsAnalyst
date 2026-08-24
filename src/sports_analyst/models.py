from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"
ANALYTICS_VERSION = "1.0"
NFLVERSE_LICENSE = "CC-BY-4.0"
NFLVERSE_ATTRIBUTION = "Data provided by nflverse and its contributors."


class ClaimType(StrEnum):
    MEASURED = "measured"
    INTERPRETATION = "interpretation"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DatasetManifest(BaseModel):
    model_config = ConfigDict(frozen=True)
    manifest_id: str
    sport: str = "nfl"
    dataset: str = "play_by_play"
    season: int = Field(ge=1999, le=2100)
    source_url: str
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sha256: str
    row_count: int = Field(ge=0)
    columns: list[str]
    schema_version: str = SCHEMA_VERSION
    package_version: str
    license: str = NFLVERSE_LICENSE
    attribution: str = NFLVERSE_ATTRIBUTION
    local_path: str


class AnalysisWindow(BaseModel):
    model_config = ConfigDict(frozen=True)
    season: int = Field(ge=1999, le=2100)
    weeks: tuple[int, int] = (1, 22)

    @field_validator("weeks", mode="before")
    @classmethod
    def normalize_weeks(cls, value: object) -> object:
        if value is None:
            return (1, 22)
        return value

    @model_validator(mode="after")
    def validate_weeks(self) -> AnalysisWindow:
        start, end = self.weeks
        if not 1 <= start <= end <= 22:
            raise ValueError("weeks must be an inclusive range between 1 and 22")
        return self


class AnalysisScope(BaseModel):
    model_config = ConfigDict(frozen=True)
    team: str = Field(min_length=2, max_length=64)
    baseline: AnalysisWindow
    comparison: AnalysisWindow
    season_type: Literal["REG", "POST", "ALL"] = "REG"
    comparison_design: Literal["full_seasons", "week_ranges", "before_after"] = "week_ranges"

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_seasons(cls, value: object) -> object:
        if not isinstance(value, dict) or "baseline" in value or "comparison" in value:
            return value
        migrated = dict(value)
        baseline_season = migrated.pop("baseline_season", None)
        comparison_season = migrated.pop("comparison_season", None)
        if baseline_season is not None:
            migrated["baseline"] = {"season": baseline_season, "weeks": [1, 22]}
        if comparison_season is not None:
            migrated["comparison"] = {"season": comparison_season, "weeks": [1, 22]}
        return migrated

    @field_validator("team", mode="before")
    @classmethod
    def normalize_team(cls, value: object) -> str:
        return str(value).strip().upper()

    @property
    def baseline_season(self) -> int:
        return self.baseline.season

    @property
    def comparison_season(self) -> int:
        return self.comparison.season

    @property
    def included_seasons(self) -> list[int]:
        if self.comparison_design == "full_seasons":
            return list(range(self.baseline.season, self.comparison.season + 1))
        return list(dict.fromkeys((self.baseline.season, self.comparison.season)))

    @model_validator(mode="after")
    def validate_windows(self) -> AnalysisScope:
        if self.baseline == self.comparison:
            raise ValueError("comparison windows must differ")
        if self.comparison_design == "full_seasons":
            if self.baseline.weeks != (1, 22) or self.comparison.weeks != (1, 22):
                raise ValueError("full-season ranges must use complete seasons")
            if self.baseline.season >= self.comparison.season:
                raise ValueError("full-season range end must be later than its start")
        if self.comparison_design == "before_after" and self.baseline.season != self.comparison.season:
            raise ValueError("before-and-after windows must use the same season")
        return self


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)
    scope: AnalysisScope
    metrics: list[str] = Field(default_factory=list)
    splits: list[str] = Field(default_factory=list)
    parent_investigation_id: str | None = None

    @field_validator("metrics", "splits")
    @classmethod
    def normalize_metrics(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip().lower() for item in value if item.strip()))


class TeamOption(BaseModel):
    value: str
    label: str


class MetricOption(BaseModel):
    value: str
    label: str
    category: str
    description: str
    available_seasons: list[int] = Field(default_factory=list)


class MetricDefinition(BaseModel):
    value: str
    label: str
    category: str
    description: str
    formula: str
    qualifying_plays: str
    interpretation: str
    higher_is_better: bool | None = None
    limitations: list[str] = Field(default_factory=list)


class PlayerOption(BaseModel):
    player_id: str
    name: str
    teams: list[str] = Field(default_factory=list)
    positions: list[str] = Field(default_factory=list)
    seasons: list[int] = Field(default_factory=list)


class SplitDimensionOption(BaseModel):
    value: str
    label: str
    description: str
    available_seasons: list[int] = Field(default_factory=list)


class ComparisonWindowOption(BaseModel):
    value: str
    label: str
    description: str


class AnalysisOptions(BaseModel):
    sport: str
    teams: list[TeamOption]
    available_seasons: list[int]
    syncable_seasons: list[int]
    metrics: list[MetricOption]
    default_metrics: list[str]
    split_dimensions: list[SplitDimensionOption]
    comparison_windows: list[ComparisonWindowOption]
    week_values: list[int] = Field(default_factory=lambda: list(range(1, 23)))
    syncable_datasets: list[str] = Field(default_factory=list)


class PlannedToolCall(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str


class AnalysisPlan(BaseModel):
    plan_id: str
    question: str
    scope: AnalysisScope
    calls: list[PlannedToolCall]
    limitations: list[str] = Field(default_factory=list)


class ToolDefinition(BaseModel):
    name: str
    description: str
    version: str = ANALYTICS_VERSION
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionRecord(BaseModel):
    execution_id: str
    tool: str
    version: str = ANALYTICS_VERSION
    parameters: dict[str, Any]
    started_at: datetime
    duration_ms: int = Field(ge=0)
    result_sha256: str
    dataset_manifest_ids: list[str]
    sql: str | None = None


class AggregateEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_id: str
    metric: str
    label: str
    value: float | int | str | None
    baseline_value: float | int | None = None
    comparison_value: float | int | None = None
    unit: str | None = None
    sample_size: int = Field(ge=0)
    confidence_low: float | None = None
    confidence_high: float | None = None
    row_set_sha256: str
    dataset_manifest_ids: list[str]
    tool_execution_id: str
    caveats: list[str] = Field(default_factory=list)


class PlayEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_id: str
    season: int
    game_id: str
    play_id: int
    team: str
    description: str
    epa: float | None = None
    supporting: bool = True
    dataset_manifest_id: str
    tool_execution_id: str | None = None


class Claim(BaseModel):
    model_config = ConfigDict(frozen=True)
    claim_id: str
    claim_type: ClaimType
    statement: str = Field(min_length=1, max_length=1_500)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Literal["low", "medium", "high"] = "medium"

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class ChartArtifact(BaseModel):
    chart_id: str
    title: str
    specification: dict[str, Any]
    evidence_ids: list[str]


class InvestigationRun(BaseModel):
    investigation_id: str
    parent_investigation_id: str | None = None
    question: str
    scope: AnalysisScope
    metrics: list[str] = Field(default_factory=list)
    splits: list[str] = Field(default_factory=list)
    status: RunStatus = RunStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    error: str | None = None


class InvestigationBundle(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run: InvestigationRun
    plan: AnalysisPlan
    summary: str
    claims: list[Claim]
    aggregate_evidence: list[AggregateEvidence]
    play_evidence: list[PlayEvidence]
    charts: list[ChartArtifact]
    executions: list[ToolExecutionRecord]
    dataset_manifests: list[DatasetManifest]
    methodological_caveats: list[str]
    model_id: str | None = None
    fallback_used: bool = False

    @model_validator(mode="after")
    def validate_citations(self) -> InvestigationBundle:
        known = {item.evidence_id for item in self.aggregate_evidence} | {item.evidence_id for item in self.play_evidence}
        for claim in self.claims:
            missing = set(claim.evidence_ids) - known
            if missing:
                raise ValueError(f"claim {claim.claim_id} cites unknown evidence: {sorted(missing)}")
        return self


class ProviderConfiguration(BaseModel):
    provider: str
    model: str
    endpoint: str | None = None
    reasoning_effort: str | None = None


class RuntimeCapabilities(BaseModel):
    providers: list[str]
    configured_provider: str
    model_configured: bool
    custom_analysis: bool = False
    sports: list[str] = Field(default_factory=lambda: ["nfl"])
    export_formats: list[str] = Field(default_factory=lambda: ["html", "markdown"])


class CustomAnalysisRequest(BaseModel):
    code: str
    input_manifest_ids: list[str]


class CustomAnalysisResult(BaseModel):
    supported: bool = False
    message: str


@runtime_checkable
class CustomAnalysisRunner(Protocol):
    def execute(self, request: CustomAnalysisRequest) -> CustomAnalysisResult: ...


class DisabledCustomAnalysisRunner:
    def execute(self, request: CustomAnalysisRequest) -> CustomAnalysisResult:
        del request
        return CustomAnalysisResult(message="Custom code execution is not available in v1; add a tested plugin tool instead.")


def stable_id(prefix: str, payload: Any, length: int = 16) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:length]}"
