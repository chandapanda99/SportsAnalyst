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
    AnalysisWindow,
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

SUPPORTED_SPORTS = {"nfl", "nba", "soccer", "cfb"}
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


def side_request(request: AnalysisRequest, subject: AnalysisSubject, season: int | None = None) -> AnalysisRequest:
    """One subject's ordinary request over the shared period, or over one season of a range."""
    team = subject.id if subject.type == "team" else subject.team_id or request.sport.upper()
    scope: dict[str, Any] = {"team": team.upper()}
    if season is not None:
        scope.update(baseline=AnalysisWindow(season=season), comparison=AnalysisWindow(season=season))
    # model_copy keeps the side unvalidated, so it stays a head-to-head scope with equal windows.
    return request.model_copy(update={"subject": subject, "comparison_subject": None,
                                      "scope": request.scope.model_copy(update=scope)})


def season_label(request: AnalysisRequest, season: int) -> str:
    if request.sport == "soccer" and request.scope.competition:
        from sports_analyst.datasets.soccer.catalog import soccer_season_label

        return soccer_season_label(request.scope.competition, season)
    return str(season)


def period_label(request: AnalysisRequest) -> str:
    seasons = request.scope.included_seasons
    first, last = season_label(request, seasons[0]), season_label(request, seasons[-1])
    return first if first == last else f"{first}–{last}"


def _named(app, request: AnalysisRequest, subject: AnalysisSubject) -> AnalysisSubject:
    if subject.type != "team" or subject.display_name:
        return subject
    teams = app.analysis_options(request.sport, request.scope.competition).teams
    name = next((team.label for team in teams if team.value == subject.id), None)
    return subject.model_copy(update={"display_name": name}) if name else subject


def _measure(app, request: AnalysisRequest, subject: AnalysisSubject, identifier: str, position: int,
             season: int | None = None, progress: float = 0.0) -> Side:
    from sports_analyst.application.investigation_data import load_investigation_data

    connector, plugin = app._sport(request.sport)
    label = subject_label(subject)
    side = side_request(request, subject, season)
    suffix = f" · {season_label(request, season)}" if season is not None else ""
    app.events.emit(identifier, "loading", f"Loading recorded data for {label}{suffix}", 0.15 + progress + 0.15 * position)
    _, manifests, datasets, supplemental_manifests, supplemental = load_investigation_data(app, side, identifier, connector, plugin)
    app.events.emit(identifier, "analyzing", f"Measuring {label}{suffix}", 0.25 + progress + 0.15 * position)
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


def compare_sides(first: Side, second: Side, metrics: list[str], execution_id: str,
                  season: int | None = None, season_name: str | None = None) -> tuple[list[AggregateEvidence], list[str]]:
    """Pair each metric's two measurements; the difference is second minus first, never a change over time.

    Within a season range each season is paired on its own: no pooled multi-season value is formed,
    because weighting season values by sample is only valid for some metrics.
    """
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
            label=f"{a.label} · {season_name}" if season_name else a.label,
            value=round(b_value - a_value, 6),
            baseline_value=round(a_value, 6),
            comparison_value=round(b_value, 6),
            unit=a.unit,
            sample_size=min(a_sample, b_sample),
            context={"comparison_kind": "head_to_head", "subjects": [first.label, second.label],
                     "baseline_sample": a_sample, "comparison_sample": b_sample,
                     "source_evidence_ids": [a.evidence_id, b.evidence_id],
                     "difference_definition": f"{second.label} minus {first.label}",
                     **({"season": season, "season_label": season_name, "metric_label": a.label} if season_name else {})},
            row_set_sha256=_sha([a.row_set_sha256, b.row_set_sha256]),
            dataset_manifest_ids=list(dict.fromkeys([*a.dataset_manifest_ids, *b.dataset_manifest_ids])),
            tool_execution_id=execution_id,
            caveats=caveats,
        ))
    return evidence, gaps


def comparison_chart(evidence: list[AggregateEvidence], labels: list[str], period: str) -> ChartArtifact:
    # Season-range rows are already labelled "Metric · Season": one row of the two subjects per season.
    rows = [{"metric": item.label, "subject": label, "value": value, "unit": item.unit, "sample_size": sample}
            for item in sorted(evidence, key=lambda item: (item.metric, item.context.get("season", 0)))
            for label, value, sample in zip(labels, (item.baseline_value, item.comparison_value),
                                            (item.context["baseline_sample"], item.context["comparison_sample"]), strict=True)]
    return ChartArtifact(
        chart_id=stable_id("chart", {"type": "head-to-head", "evidence": [item.evidence_id for item in evidence]}),
        title=f"{labels[0]} vs {labels[1]} · {period}",
        specification=metric_row_comparison_spec(rows, series_field="subject", series_order=labels, comparison_kind="subject-comparison"),
        evidence_ids=[item.evidence_id for item in evidence],
    )


def _season_sides(app, request: AnalysisRequest, subjects: list[AnalysisSubject], identifier: str):
    """Measure both subjects once per season; within a range, a season either subject lacks becomes a gap."""
    seasons = request.scope.included_seasons
    if len(seasons) == 1:
        yield None, [_measure(app, request, subject, identifier, index) for index, subject in enumerate(subjects)], None
        return
    for step, season in enumerate(seasons):
        progress = 0.4 * step / len(seasons)
        try:
            yield season, [_measure(app, request, subject, identifier, index, season, progress)
                           for index, subject in enumerate(subjects)], None
        except ValueError as error:
            yield season, None, str(error)[:300]


def _gap_caveats(gaps: dict[str, list[str]], unmeasured_seasons: list[str], season_range: bool) -> list[str]:
    caveats = []
    if gaps:
        names = [f"{metric} ({', '.join(where)})" if season_range else metric for metric, where in gaps.items()]
        caveats.append(f"Not measured for both subjects: {', '.join(names)}.")
    if unmeasured_seasons:
        caveats.append(f"Seasons not measured for both subjects: {'; '.join(unmeasured_seasons)}.")
    return caveats


def investigate_head_to_head(app, request: AnalysisRequest, identifier: str, trace_metadata: dict[str, Any]) -> InvestigationBundle:
    from sports_analyst.analysis.instructions import evidence_brief

    if request.sport not in SUPPORTED_SPORTS:
        raise ValueError("Head-to-head comparisons are available for the NFL, NBA, soccer and college football.")
    if request.subject is None or request.comparison_subject is None:
        raise ValueError("Choose two subjects to compare head-to-head.")
    if not request.metrics:
        raise ValueError("Choose at least one metric to compare.")
    started_at, started = datetime.now(UTC), perf_counter()
    subjects = [_named(app, request, request.subject), _named(app, request, request.comparison_subject)]
    request = request.model_copy(update={"subject": subjects[0], "comparison_subject": subjects[1]})
    labels = [subject_label(subject) for subject in subjects]
    period = period_label(request)
    season_range = request.scope.season_range
    app.events.emit(identifier, "planning", "Setting up the head-to-head comparison", 0.1)
    execution_id = stable_id("execution", {"tool": "compare_subjects", "subjects": labels, "period": request.scope.baseline.model_dump(),
                                            "seasons": request.scope.included_seasons, "metrics": request.metrics})
    evidence: list[AggregateEvidence] = []
    gaps: dict[str, list[str]] = {}
    unmeasured_seasons: list[str] = []
    measured: list[Side] = []
    for season, sides, failure in _season_sides(app, request, subjects, identifier):
        name = season_label(request, season) if season is not None else None
        if sides is None:
            unmeasured_seasons.append(f"{name}: {failure}")
            continue
        measured.extend(sides)
        paired, missing = compare_sides(*sides, request.metrics, execution_id, season, name)
        evidence.extend(paired)
        for metric in missing:
            gaps.setdefault(metric, []).append(name or period)
    if not evidence:
        raise ValueError(f"None of the selected metrics could be measured for both {labels[0]} and {labels[1]} in {period}.")
    manifests = {item.manifest_id: item for side in measured for item in side.manifests}
    executions = [*{item.execution_id: item for side in measured for item in side.executions}.values(), ToolExecutionRecord(
        execution_id=execution_id, tool="compare_subjects",
        parameters={"subjects": labels, "period": request.scope.baseline.model_dump(), "seasons": request.scope.included_seasons,
                    "metrics": request.metrics, "unmeasured": gaps, "unmeasured_seasons": unmeasured_seasons},
        started_at=started_at, duration_ms=round((perf_counter() - started) * 1000),
        result_sha256=_sha([item.evidence_id for item in evidence]),
        dataset_manifest_ids=list(dict.fromkeys(key for item in evidence for key in item.dataset_manifest_ids)))]
    # Sides alternate first, second per season; each subject keeps its latest seasons' plays.
    plays = [play for sides in (measured[0::2], measured[1::2])
             for play in sorted((play for side in sides for play in side.plays), key=lambda play: -play.season)[:PLAYS_PER_SUBJECT]]
    caveats = [
        f"Head-to-head: each value is that subject's own {'single-season' if season_range else period} measurement. "
        f"Differences are {labels[1]} minus {labels[0]}, not changes over time.",
        *([f"Seasons {period} are compared one at a time. No combined multi-season value is calculated, because weighting "
           "season values by sample is not valid for every metric."] if season_range else []),
        "Team context, teammates, opponents and playing time differ between the subjects; the measurements describe outcomes, "
        "not isolated individual ability.",
        "Change-based tools and situational breakdowns are not run for head-to-head reports. Follow-up questions can run additional "
        "research, repeated for both subjects.",
        *_gap_caveats(gaps, unmeasured_seasons, season_range),
    ]
    definitions = []
    for metric in request.metrics:
        with suppress(KeyError, ValueError):
            definitions.append(app.explain_metric(metric, request.sport))
    context = evidence_brief(evidence, definitions, list(manifests.values()), {
        "sport": request.sport, "domain": request.analysis_domain, "comparison_kind": "head_to_head",
        "subjects": [subject.model_dump(mode="json") for subject in subjects],
        "period": request.scope.baseline.model_dump(mode="json"), "seasons": request.scope.included_seasons,
        "as_of": datetime.now(UTC).isoformat()})
    app.events.emit(identifier, "synthesizing", "Comparing the two subjects and drafting findings", 0.75)
    draft, model_id, fallback = app.agent.synthesize(
        request.question, f"{labels[0]} vs {labels[1]}", request.scope.baseline, request.scope.comparison, evidence, plays,
        request.scope.included_seasons if season_range else None, None, request.analysis_domain, request.sport,
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
        run=run, plan=plugin.default_plan(side_request(request, subjects[0])), summary=draft.summary, claims=draft.claims,
        aggregate_evidence=evidence, play_evidence=plays, charts=[comparison_chart(evidence, labels, period)],
        executions=executions, dataset_manifests=list(manifests.values()), methodological_caveats=caveats,
        model_id=model_id, fallback_used=fallback,
    )
    # Doubles as the last cancellation check before anything is saved.
    app.events.emit(identifier, "saving", "Saving your report", 0.97)
    app.store.save_investigation(bundle)
    app.events.emit(identifier, "complete", "Report ready", 1.0, investigation_id=identifier)
    return bundle
