"""Calendar-month context from the same recorded match measurements as comparisons."""
import hashlib
import json
from datetime import date
from types import SimpleNamespace

import polars as pl

from sports_analyst.datasets.soccer.catalog import soccer_season_label
from sports_analyst.datasets.soccer.expected_goals import numeric
from sports_analyst.datasets.soccer.statistics import EVENT_METRICS, MATCH_METRICS, event_value, measured_value
from sports_analyst.models import AggregateEvidence, ChartArtifact, stable_id
from sports_analyst.presentation.charts import metric_row_comparison_spec


def metric_value(plugin, request, supplemental, metrics, name, season, rows, reference_rows):
    """Reuse recorded metric definitions for each season or month, never average window averages."""
    def get(dataset):
        return supplemental.get(dataset, {}).get(season, pl.DataFrame())

    if metrics[name][1] == "season_statistics":
        field = name.removeprefix(f"season_{request.subject.type}_")
        frame = get("season_statistics")
        if not {field, "subject_id", "subject_type", "appearances"} <= set(frame.columns):
            return None, 0
        frame = frame.filter((pl.col("subject_id") == str(request.subject.id)) & (pl.col("subject_type") == request.subject.type))
        numbers = [numeric(value) for value in frame[field].to_list()]
        appearances = frame["appearances"].sum()
        return ((sum(numbers), int(appearances)) if numbers and all(value is not None for value in numbers)
                and appearances else (None, 0))
    if not rows:
        return None, 0
    if name in MATCH_METRICS:
        return measured_value(name, rows, get(MATCH_METRICS[name][1]), str(request.subject.id))
    if name in EVENT_METRICS:
        if name == "open_xt_per_match":
            signatures = []
            for year, sample in ((season, rows), (request.scope.baseline.season, reference_rows)):
                raw = supplemental.get("open_events", {}).get(year, pl.DataFrame())
                scoped = raw.filter(pl.col("game_id").cast(pl.String).is_in([r["game_id"] for r in sample])) if (
                    {"game_id", "xt_model_sha256"} <= set(raw.columns)) else pl.DataFrame()
                signatures.append(set(scoped["xt_model_sha256"].drop_nulls().to_list()) if "xt_model_sha256" in scoped.columns else set())
            if len(signatures[0]) != 1 or signatures[0] != signatures[1]:
                raise ValueError("Expected threat trend has missing or incompatible model hashes")
        return event_value(name, rows, get("open_events"), str(request.subject.id))
    return plugin._value(name, rows, get("team_stats"), get("lineups"), get("key_events"),
                         str(request.subject.id), get("player_game_logs"), get("expected_goals"), get("player_expected_goals"))


def seasonal_evidence(plugin, request, frames, supplemental, aggregates, metrics, execution_id, manifest_ids):
    if request.scope.comparison_design != "full_seasons":
        return [], None, []
    output, rows, limitations = [], [], []
    missing_metrics = set()
    labels = [soccer_season_label(request.scope.competition, year) for year in request.scope.included_seasons]
    sources = list(aggregates)
    # The scorecard uses the same recorded observations and metric definitions
    # as the monthly view, not the agent's incidental research-plan coverage.
    if request.subject.type == "team":
        for name in ("goals_for_per_match", "goals_against_per_match", "shots_per_match", "pass_completion_rate", "possession_pct"):
            if name not in metrics or any(source.metric == name for source in sources):
                continue
            try:
                values = [metric_value(plugin, request, supplemental, metrics, name, frames[key][0].season,
                    frames[key][1], frames["baseline"][1]) for key in ("baseline", "comparison")]
            except ValueError:
                continue
            if all(value is not None and count for value, count in values):
                sources.append(SimpleNamespace(metric=name, label=metrics[name][0], unit=metrics[name][4], caveats=[],
                    baseline_value=values[0][0], comparison_value=values[1][0],
                    context={"baseline_sample": values[0][1], "comparison_sample": values[1][1]}))
    for source in sources:
        for window_name, (window, sample) in frames.items():
            season_label = soccer_season_label(request.scope.competition, window.season)
            value, count = None, 0
            if window_name in {"baseline", "comparison"}:
                value = source.baseline_value if window_name == "baseline" else source.comparison_value
                count = source.context[f"{window_name}_sample"]
            else:
                try:
                    value, count = metric_value(plugin, request, supplemental, metrics, source.metric,
                                                window.season, sample, frames["baseline"][1])
                except ValueError as error:
                    limitations.append(f"{season_label} · {source.label}: trend validation failed: {error}")
            if value is None or not count:
                missing_metrics.add(source.label)
                limitations.append(f"{season_label} · {source.label}: no usable recorded coverage; season retained as a gap, not zero.")
                continue
            identity = {"execution": execution_id, "metric": source.metric, "season": window.season,
                        "value": round(value, 4), "games": sorted(r["game_id"] for r in sample), "manifests": sorted(manifest_ids)}
            item = AggregateEvidence(evidence_id=stable_id("evidence", identity), metric=f"seasonal_{source.metric}",
                label=f"{season_label} · {source.label}", value=round(value, 4), unit=source.unit, sample_size=count,
                row_set_sha256=hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
                dataset_manifest_ids=manifest_ids, tool_execution_id=execution_id,
                caveats=[f"{season_label}: {count} metric-specific qualifying observations.",
                         "Recorded per-season measurement; the endpoint delta does not establish a steady year-to-year trend.",
                         *([c for c in source.caveats if "model" in c.lower() or "provider" in c.lower()])],
                context={"season": window.season, "season_label": season_label, "metric": source.metric,
                         "definition": metrics[source.metric][5], "game_ids": identity["games"],
                         "source_dataset": metrics[source.metric][1], "qualifying_rows": len(sample)})
            output.append(item)
            rows.append({"metric": source.label, "season": season_label, "value": item.value, "unit": item.unit,
                         "sample_size": count, "evidence_id": item.evidence_id,
                         "context_label": f"{season_label}: {count} qualifying observations"})
    if request.subject.type == "team":
        for _, (window, sample) in frames.items():
            if not sample:
                continue
            season_label = soccer_season_label(request.scope.competition, window.season)
            for metric, label, value in (("matches", "Completed matches", len(sample)),
                ("goals_scored", "Goals scored", sum(row["goals_for"] for row in sample)),
                ("goals_conceded", "Goals conceded", sum(row["goals_against"] for row in sample))):
                identity = {"execution": execution_id, "metric": metric, "season": window.season,
                    "games": sorted(row["game_id"] for row in sample), "value": value, "manifests": sorted(manifest_ids)}
                item = AggregateEvidence(evidence_id=stable_id("evidence", identity), metric=f"seasonal_{metric}",
                    label=f"{season_label} · {label}", value=float(value), unit="count", sample_size=len(sample),
                    row_set_sha256=hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
                    dataset_manifest_ids=manifest_ids, tool_execution_id=execution_id,
                    caveats=["Recorded completed matches for the selected team, home and away; not the entire competition."],
                    context={"season": window.season, "metric": metric, "season_label": season_label,
                        "game_ids": identity["games"], "source_dataset": "play_by_play", "qualifying_rows": len(sample)})
                output.append(item)
                rows.append({"metric": label, "season": season_label, "value": value, "unit": "count", "sample_size": len(sample),
                    "evidence_id": item.evidence_id, "context_label": f"{season_label}: {len(sample)} completed matches, home and away"})
    spec = metric_row_comparison_spec(rows, series_field="season", series_order=labels)
    season_matrix(spec, labels)
    spec["usermeta"]["description"] = (
        "Selected team, home and away, within the chosen competition. Totals use recorded completed matches; rates use each metric's qualifying matches. "
        "Each selected season is shown. Missing optional statistics remain gaps, not zero."
        + (" Missing coverage: " + "; ".join(limitations) if limitations else ""))
    for plot in spec["vconcat"]:
        for layer in plot["layer"]:
            layer["encoding"]["x"]["scale"] = {"domain": labels}
        if plot["title"]["text"] in missing_metrics:
            plot["layer"] = [layer for layer in plot["layer"] if layer["mark"]["type"] != "line"]
    chart = ChartArtifact(chart_id=stable_id("chart", {"execution": execution_id, "view": "inclusive-season-trend"}),
                          title="Season summary · recorded match performance", specification=spec,
                          evidence_ids=[item.evidence_id for item in output])
    return output, chart, limitations


def season_matrix(spec, labels):
    values = spec.get("data", {}).get("values", [])
    summaries = []
    for metric in dict.fromkeys(row["metric"] for row in values):
        cells = [{"period": label, "status": "recorded", "entries": [
            {"value": row["display_value"], "sample": row.get("sample_size"), "evidence_id": row.get("evidence_id"),
             "context": row.get("context_label", "")} for row in values if row["metric"] == metric and row["season"] == label]}
            for label in labels]
        summaries.append({"metric": metric, "category": "", "availablePeriods": sum(bool(c["entries"]) for c in cells), "cells": cells})
    priorities = {"Completed matches": 0, "Goals scored": 1, "Goals conceded": 2}
    summaries.sort(key=lambda row: priorities.get(row["metric"], 3))
    spec["usermeta"].update(displayMode="matrix", comparisonSummary=summaries, expectedPeriods=labels,
        missingPeriods=[label for label in labels if not any(row["season"] == label for row in values)],
        sampleLabel="Qualifying matches", reportSection="primary")


def monthly_evidence(plugin, request, frames, supplemental, aggregates, metrics, execution_id, manifest_ids):
    # Reuse already-comparable metrics; add small, relevant context from installed data only.
    candidates = [a.metric for a in aggregates if a.metric in metrics and metrics[a.metric][1] != "season_statistics"]
    if request.subject.type == "team":
        candidates += ["fotmob_expected_goals_per_match", "fotmob_expected_goals_on_target_per_match", "pass_completion_rate",
                       "goals_for_per_match", "goals_against_per_match", "shots_per_match", "possession_pct"]

    def calculate(name, season, rows):
        return metric_value(plugin, request, supplemental, metrics, name, season, rows, frames["baseline"][1])

    output, limitations, months = [], [], {}
    for window_name, (_, rows) in frames.items():
        buckets = {}
        for row in rows:
            try:
                month = date.fromisoformat(str(row["date"])[:10]).strftime("%Y-%m")
            except (ValueError, KeyError):
                limitations.append(f"Monthly {window_name} context unavailable: missing or invalid recorded match dates.")
                buckets = {}
                break
            buckets.setdefault(month, []).append(row)
        months[window_name] = buckets
    included = 0
    for name in dict.fromkeys(candidates):
        if included >= 6:
            break
        try:
            unavailable = any(calculate(name, frames[label][0].season, frames[label][1])[0] is None
                              for label in ("baseline", "comparison"))
        except ValueError as error:
            limitations.append(f"Monthly {metrics[name][0]} context failed validation: {error}")
            continue
        if unavailable:
            continue
        included += 1
        source = next((a for a in aggregates if a.metric == name), None)
        for window_name, (window, _rows) in frames.items():
            try:
                value, count = calculate(name, window.season, _rows)
            except ValueError as error:
                limitations.append(f"Monthly {window.season} · {metrics[name][0]} context failed validation: {error}")
                continue
            if value is None or not count:
                limitations.append(f"Monthly {window.season} · {metrics[name][0]} coverage unavailable; no zero or interpolation substituted.")
                continue
            for month, sample in sorted(months[window_name].items()):
                try:
                    value, count = calculate(name, window.season, sample)
                except ValueError as error:
                    limitations.append(f"{month} · {metrics[name][0]} context failed validation: {error}")
                    continue
                if value is None or not count:
                    continue
                identity = {"execution": execution_id, "metric": name, "window": window_name,
                            "month": month, "games": sorted(r["game_id"] for r in sample), "value": value,
                            "manifests": sorted(manifest_ids)}
                output.append(AggregateEvidence(evidence_id=stable_id("evidence", identity), metric="soccer_monthly",
                    label=f"{metrics[name][0]} · {month} · {window_name}", value=value, unit=metrics[name][4], sample_size=count,
                    row_set_sha256=hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
                    dataset_manifest_ids=manifest_ids, tool_execution_id=execution_id,
                    caveats=[*(source.caveats if source else []),
                             *(["FotMob-reported values; upstream model version undisclosed, stability across seasons unverified. "
                                "Missing matches are not filled from another provider."] if metrics[name][1] == "match_analytics" else []),
                             f"Calendar month {month}: {count}/{len(sample)} qualifying matches. Missing values are not zero.",
                             "Monthly context is descriptive; unlike metrics can have different covered-match samples."],
                    context={"objective": "Monthly soccer performance", "window": window_name, "group": {"month": month},
                             "window_label": soccer_season_label(request.scope.competition, window.season)
                                 if request.scope.comparison_design == "full_seasons" else
                                 "Reference Period" if window_name == "baseline" else "Comparison Period",
                             "season": window.season,
                             "time_bucket": {"field": "date", "interval": "month"}, "metric_label": metrics[name][0],
                             "measure": {"op": "defined_metric", "field": name}, "qualifying_rows": len(sample),
                             "definition": metrics[name][5], "aggregation": "recomputed from recorded match observations",
                             "game_ids": sorted(r["game_id"] for r in sample),
                             "source_dataset": metrics[name][1]}))
    return output, limitations
