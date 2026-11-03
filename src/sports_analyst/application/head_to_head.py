"""Compare two subjects over one period by reusing each subject's validated single-subject analysis."""
from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sports_analyst.models import (
    AggregateEvidence,
    AnalysisRequest,
    AnalysisSubject,
    ChartArtifact,
    DatasetManifest,
    InvestigationBundle,
    InvestigationRun,
    PlayEvidence,
    RunStatus,
    ToolExecutionRecord,
    stable_id,
)
from sports_analyst.presentation.charts import metric_row_comparison_spec

SUPPORTED_SPORTS = {"nfl"}
PLAYS_PER_SUBJECT = 4
# Samples further apart than this make totals misleading, so the report says to compare rates.
UNEQUAL_SAMPLE_RATIO = 1.5


@dataclass
class Side:
    subject: AnalysisSubject
    label: str
    aggregate: dict[str, AggregateEvidence]
    plays: list[PlayEvidence]
    executions: list[ToolExecutionRecord]
    manifests: list[DatasetManifest]


def _sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def subject_label(subject: AnalysisSubject) -> str:
    return subject.display_name or subject.id


def _side_request(request: AnalysisRequest, subject: AnalysisSubject) -> AnalysisRequest:
    team = subject.id if subject.type == "team" else subject.team_id or request.sport.upper()
    # Each side is an ordinary single-subject request over the shared period; model_copy keeps it unvalidated.
    return request.model_copy(update={"subject": subject, "comparison_subject": None,
                                      "scope": request.scope.model_copy(update={"team": team.upper()})})


def _named(app, request: AnalysisRequest, subject: AnalysisSubject) -> AnalysisSubject:
    if subject.type != "team" or subject.display_name:
        return subject
    teams = app.analysis_options(request.sport, request.scope.competition).teams
    name = next((team.label for team in teams if team.value == subject.id), None)
    return subject.model_copy(update={"display_name": name}) if name else subject


def _measure(app, request: AnalysisRequest, subject: AnalysisSubject, identifier: str, position: int) -> Side:
    from sports_analyst.application.investigation_data import load_investigation_data

    connector, plugin = app._sport(request.sport)
    label = subject_label(subject)
    side = _side_request(request, subject)
    app.events.emit(identifier, "loading", f"Loading recorded data for {label}", 0.15 + 0.15 * position)
    _, manifests, datasets, supplemental_manifests, supplemental = load_investigation_data(app, side, identifier, connector, plugin)
    app.events.emit(identifier, "analyzing", f"Measuring {label}", 0.25 + 0.15 * position)
    result = plugin.analyze(side, datasets, manifests, supplemental, supplemental_manifests)
    # Keep only the subject's own measurements; change-based tools are meaningless for one period.
    aggregate = {item.metric: item for item in result.aggregate_evidence
                 if item.metric in request.metrics and item.comparison_value is not None}
    used = {item.tool_execution_id for item in aggregate.values()}
    window = "baseline" if position == 0 else "comparison"
    plays: dict[str, PlayEvidence] = {}
    for play in result.play_evidence:
        if play.evidence_role in {None, "typical", "metric_example"} and play.evidence_id not in plays:
            kind = "metric example" if play.evidence_role == "metric_example" else "typical"
            plays[play.evidence_id] = play.model_copy(update={
                "window": window, "supporting": True, "selection_reason": f"A {kind} {label} play from {play.season}."})
    all_manifests = [*manifests.values(), *(item for group in supplemental_manifests.values() for item in group.values())]
    return Side(subject, label, aggregate, list(plays.values())[:PLAYS_PER_SUBJECT],
                [item for item in result.executions if item.execution_id in used], all_manifests)


def _level(item: AggregateEvidence) -> tuple[float, int]:
    sample = item.context.get("comparison_sample")
    return float(item.comparison_value), int(sample if isinstance(sample, int) else item.sample_size)


def compare_sides(first: Side, second: Side, metrics: list[str], execution_id: str) -> tuple[list[AggregateEvidence], list[str]]:
    """Pair each metric's two measurements; the difference is second minus first, never a change over time."""
    evidence, gaps = [], []
    for metric in metrics:
        a, b = first.aggregate.get(metric), second.aggregate.get(metric)
        if a is None or b is None:
            gaps.append(metric)
            continue
        (a_value, a_sample), (b_value, b_sample) = _level(a), _level(b)
        caveats = list(dict.fromkeys([*a.caveats, *b.caveats]))
        if min(a_sample, b_sample) and max(a_sample, b_sample) / min(a_sample, b_sample) > UNEQUAL_SAMPLE_RATIO:
            caveats.append(f"{first.label} has {a_sample:,} qualifying observations and {second.label} has {b_sample:,}; "
                           "compare rates, not totals.")
        payload = {"head_to_head": [a.evidence_id, b.evidence_id]}
        evidence.append(AggregateEvidence(
            evidence_id=stable_id("evidence", payload),
            metric=metric,
            label=a.label,
            value=round(b_value - a_value, 6),
            baseline_value=round(a_value, 6),
            comparison_value=round(b_value, 6),
            unit=a.unit,
            sample_size=min(a_sample, b_sample),
            context={"comparison_kind": "head_to_head", "subjects": [first.label, second.label],
                     "baseline_sample": a_sample, "comparison_sample": b_sample,
                     "source_evidence_ids": [a.evidence_id, b.evidence_id],
                     "difference_definition": f"{second.label} minus {first.label}"},
            row_set_sha256=_sha([a.row_set_sha256, b.row_set_sha256]),
            dataset_manifest_ids=list(dict.fromkeys([*a.dataset_manifest_ids, *b.dataset_manifest_ids])),
            tool_execution_id=execution_id,
            caveats=caveats,
        ))
    return evidence, gaps


def comparison_chart(evidence: list[AggregateEvidence], labels: list[str], period: str) -> ChartArtifact:
    rows = [{"metric": item.label, "subject": label, "value": value, "unit": item.unit, "sample_size": sample}
            for item in evidence
            for label, value, sample in zip(labels, (item.baseline_value, item.comparison_value),
                                            (item.context["baseline_sample"], item.context["comparison_sample"]), strict=True)]
    return ChartArtifact(
        chart_id=stable_id("chart", {"type": "head-to-head", "evidence": [item.evidence_id for item in evidence]}),
        title=f"{labels[0]} vs {labels[1]} · {period}",
        specification=metric_row_comparison_spec(rows, series_field="subject", series_order=labels, comparison_kind="subject-comparison"),
        evidence_ids=[item.evidence_id for item in evidence],
    )


def investigate_head_to_head(app, request: AnalysisRequest, identifier: str, trace_metadata: dict[str, Any]) -> InvestigationBundle:
    from sports_analyst.analysis.instructions import evidence_brief

    if request.sport not in SUPPORTED_SPORTS:
        raise ValueError("Head-to-head comparisons are currently available for the NFL only.")
    if request.subject is None or request.comparison_subject is None:
        raise ValueError("Choose two subjects to compare head-to-head.")
    if not request.metrics:
        raise ValueError("Choose at least one metric to compare.")
    started_at, started = datetime.now(UTC), perf_counter()
    subjects = [_named(app, request, request.subject), _named(app, request, request.comparison_subject)]
    request = request.model_copy(update={"subject": subjects[0], "comparison_subject": subjects[1]})
    app.events.emit(identifier, "planning", "Setting up the head-to-head comparison", 0.1)
    first, second = (_measure(app, request, subject, identifier, index) for index, subject in enumerate(subjects))
    labels = [first.label, second.label]
    period = str(request.scope.baseline.season)
    execution_id = stable_id("execution", {"tool": "compare_subjects", "subjects": labels, "period": request.scope.baseline.model_dump(),
                                            "metrics": request.metrics})
    evidence, gaps = compare_sides(first, second, request.metrics, execution_id)
    if not evidence:
        raise ValueError(f"None of the selected metrics could be measured for both {labels[0]} and {labels[1]} in {period}.")
    manifests = {item.manifest_id: item for item in [*first.manifests, *second.manifests]}
    executions = [*first.executions, *second.executions, ToolExecutionRecord(
        execution_id=execution_id, tool="compare_subjects",
        parameters={"subjects": labels, "period": request.scope.baseline.model_dump(), "metrics": request.metrics, "unmeasured": gaps},
        started_at=started_at, duration_ms=round((perf_counter() - started) * 1000),
        result_sha256=_sha([item.evidence_id for item in evidence]),
        dataset_manifest_ids=list(dict.fromkeys(key for item in evidence for key in item.dataset_manifest_ids)))]
    plays = [*first.plays, *second.plays]
    caveats = [
        f"Head-to-head: each value is that subject's own {period} measurement. Differences are {labels[1]} minus {labels[0]}, "
        "not changes over time.",
        "Team context, teammates, opponents and playing time differ between the subjects; the measurements describe outcomes, "
        "not isolated individual ability.",
        "Change-based tools, situational breakdowns and additional research calculations are not run for head-to-head reports.",
        *([f"Not measured for both subjects: {', '.join(gaps)}."] if gaps else []),
    ]
    definitions = []
    for metric in request.metrics:
        with suppress(KeyError, ValueError):
            definitions.append(app.explain_metric(metric, request.sport))
    context = evidence_brief(evidence, definitions, list(manifests.values()), {
        "sport": request.sport, "domain": request.analysis_domain, "comparison_kind": "head_to_head",
        "subjects": [subject.model_dump(mode="json") for subject in subjects],
        "period": request.scope.baseline.model_dump(mode="json"), "as_of": datetime.now(UTC).isoformat()})
    app.events.emit(identifier, "synthesizing", "Comparing the two subjects and drafting findings", 0.75)
    draft, model_id, fallback = app.agent.synthesize(
        request.question, f"{labels[0]} vs {labels[1]}", request.scope.baseline, request.scope.comparison, evidence, plays,
        None, None, request.analysis_domain, request.sport,
        progress_callback=lambda message, progress: app.events.emit(identifier, "synthesizing", message, progress),
        trace_metadata=trace_metadata, competition=request.scope.competition, analytical_context=context, subjects=(labels[0], labels[1]),
    )
    _, plugin = app._sport(request.sport)
    run = InvestigationRun(
        sport=request.sport, subject=subjects[0], comparison_subject=subjects[1], investigation_id=identifier,
        parent_investigation_id=request.parent_investigation_id, question=request.question, scope=request.scope,
        analysis_domain=request.analysis_domain, metrics=request.metrics, splits=request.splits,
        status=RunStatus.COMPLETED, completed_at=datetime.now(UTC),
    )
    bundle = InvestigationBundle(
        run=run, plan=plugin.default_plan(_side_request(request, subjects[0])), summary=draft.summary, claims=draft.claims,
        aggregate_evidence=evidence, play_evidence=plays, charts=[comparison_chart(evidence, labels, period)],
        executions=executions, dataset_manifests=list(manifests.values()), methodological_caveats=caveats,
        model_id=model_id, fallback_used=fallback,
    )
    # Doubles as the last cancellation check before anything is saved.
    app.events.emit(identifier, "saving", "Saving your report", 0.97)
    app.store.save_investigation(bundle)
    app.events.emit(identifier, "complete", "Investigation ready", 1.0, investigation_id=identifier)
    return bundle
