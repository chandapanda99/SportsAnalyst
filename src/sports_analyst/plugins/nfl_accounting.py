"""Exclusive, reconciled EPA accounting on the same qualifying offense sample."""
from __future__ import annotations

import math
from datetime import UTC, datetime

import polars as pl

from sports_analyst.analysis.calculations import digest
from sports_analyst.models import AggregateEvidence, ChartArtifact, ToolExecutionRecord, stable_id

CATEGORIES = ("Passing (non-turnover, non-sack)", "Rushing (non-turnover)", "Sacks (non-turnover)", "Turnovers", "Other")


def classified(frame):
    return frame.with_columns(
        pl.when((pl.col("interception") == 1) | (pl.col("fumble_lost") == 1)).then(pl.lit(CATEGORIES[3]))
        .when(pl.col("sack") == 1).then(pl.lit(CATEGORIES[2]))
        .when(pl.col("play_type") == "pass").then(pl.lit(CATEGORIES[0]))
        .when(pl.col("play_type") == "run").then(pl.lit(CATEGORIES[1]))
        .otherwise(pl.lit(CATEGORIES[4])).alias("phase"))


def phase_accounting(baseline, comparison, manifests):
    required = {"_epa", "play_type", "sack", "interception", "fumble_lost"}
    windows = []
    for frame in (baseline, comparison):
        if not required <= set(frame.columns):
            return [], None, None, "EPA phase accounting was not calculated: required recorded classification fields are absent."
        if frame.select(pl.any_horizontal(pl.col(name).is_null() for name in required).any()).item():
            return [], None, None, "EPA phase accounting was not calculated: classification or EPA values are missing; missing is not zero."
        if not frame["_epa"].is_finite().all() or not frame.height:
            return [], None, None, "EPA phase accounting requires finite EPA and a nonempty sample in both windows."
        for flag in ("sack", "interception", "fumble_lost"):
            if not frame[flag].is_in([0, 1]).all():
                return [], None, None, "EPA phase accounting has invalid recorded classification flags."
        grouped = classified(frame)
        groups = {row["phase"]: {"plays": row["plays"], "epa_total": row["epa_total"]}
            for row in grouped.group_by("phase").agg(pl.len().alias("plays"), pl.col("_epa").sum().alias("epa_total")).to_dicts()}
        windows.append({"plays": frame.height, "epa_mean": frame["_epa"].mean(), "groups": groups})
    parameters = {"method": "exclusive_epa_accounting_v1", "windows": windows,
        "precedence": ["interception or lost fumble", "sack", "pass-coded", "run-coded", "other"],
        "formula": "comparison_category_epa / comparison_plays - baseline_category_epa / baseline_plays"}
    execution_id = stable_id("execution", {**parameters, "manifests": [item.manifest_id for item in manifests]})
    evidence = []
    for category in CATEGORIES:
        contributions = [window["groups"].get(category, {"epa_total": 0})["epa_total"] / window["plays"] for window in windows]
        payload = {**parameters, "category": category}
        evidence.append(AggregateEvidence(evidence_id=stable_id("evidence", {"execution": execution_id, "category": category}),
            metric="epa_phase_contribution", label=category, value=contributions[1] - contributions[0],
            baseline_value=contributions[0], comparison_value=contributions[1], unit="EPA per qualifying offensive play",
            sample_size=windows[1]["plays"], row_set_sha256=digest(payload),
            dataset_manifest_ids=[item.manifest_id for item in manifests],
            tool_execution_id=execution_id, context={"method": parameters["method"], "category": category, "windows": windows,
                "role": "accounting_contribution", "validation": "exclusive_partition_and_reconciled"},
            caveats=["Descriptive accounting, not causal attribution. Turnovers take priority over sacks, passing and rushing; "
                     "categories do not overlap. Passing/rushing are recorded play-type categories; scrambles remain run-coded. "
                     "Category values use the whole-offense denominator, not category efficiency."]))
    delta = windows[1]["epa_mean"] - windows[0]["epa_mean"]
    if not math.isclose(sum(item.value for item in evidence), delta, abs_tol=1e-9):
        raise ValueError("EPA accounting failed reconciliation")
    execution = ToolExecutionRecord(execution_id=execution_id, tool="account_offensive_epa_change", parameters=parameters,
        started_at=datetime.now(UTC), duration_ms=0, result_sha256=digest([item.model_dump() for item in evidence]),
        dataset_manifest_ids=[item.manifest_id for item in manifests])
    rows = [{"phase": item.label, "contribution": item.value} for item in evidence]
    chart = ChartArtifact(chart_id=stable_id("chart", execution_id), title="Where the EPA/play change came from",
        evidence_ids=[item.evidence_id for item in evidence], specification={"$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "data": {"values": rows}, "mark": "bar", "height": 180, "width": "container",
            "encoding": {"y": {"field": "phase", "type": "nominal", "sort": "-x", "title": None},
                "x": {"field": "contribution", "type": "quantitative", "title": "Contribution to EPA/play change", "scale": {"zero": True}},
                "tooltip": [{"field": "phase"}, {"field": "contribution", "format": "+.4f"}]}})
    return evidence, execution, chart, None
