"""Present registered measurements at their recorded grain, with readable labels."""
import json
import math

from sports_analyst.analysis.research.labels import ResearchLabels
from sports_analyst.analysis.research.labels import field_label as _field_label
from sports_analyst.models import ChartArtifact, stable_id
from sports_analyst.presentation.charts import metric_row_comparison_spec


def _comparison_view(spec, labels, items, field, kind):
    """A missing measurement is a visible cell, never a fabricated zero or single-dot plot."""
    values = spec["data"]["values"]
    def period_key(row):
        return row["season"] if kind == "season-trend" else row["window"]

    expected = labels.expected_periods(items[0]) or (spec["usermeta"]["seriesLabels"] if kind == "season-trend" else
        list(dict.fromkeys(row["window"] for row in values)))
    if kind == "monthly-trend":
        spec["usermeta"].update(expectedPeriods=expected,
            missingPeriods=[p for p in expected if not any(row["window"] == p for row in values)])
        return spec
    grouped = kind == "grouped-observations"
    by_row = {}
    for row in values:
        category = row["category"] if grouped else ""
        by_row.setdefault((row["metric"], category), []).append(row)
    summaries, eligible = [], []
    for (metric, category), records in by_row.items():
        cells = []
        for period in expected:
            matches = [r for r in records if (r["season"] if kind == "season-trend" else r["window"]) == period]
            # Multiple recorded values are not averaged or silently selected.
            cells.append({"period": period, "entries": [{"value": r["display_value"], "sample": r.get("sample_size"),
                "evidence_id": r["evidence_id"], "context": r.get("context_label", "")} for r in matches],
                "status": "recorded" if matches else "No registered measurement"})
        comparable = sum(bool(cell["entries"]) for cell in cells)
        summaries.append({"metric": metric, "category": category, "cells": cells, "availablePeriods": comparable})
        if comparable >= 2 and all(len(cell["entries"]) <= 1 for cell in cells):
            eligible.extend(records)
    summaries.sort(key=lambda row: (-row["availablePeriods"], row["metric"], row["category"]))
    if eligible:
        plot = metric_row_comparison_spec(eligible, series_field=field,
            series_order=spec["usermeta"]["seriesLabels"] if grouped else expected,
            comparison_kind=kind, color_field="window" if grouped else None)
        spec["vconcat"] = plot["vconcat"]
        if not grouped:
            for subplot in spec["vconcat"]:
                for layer in subplot["layer"]:
                    layer["encoding"]["x"]["scale"] = {"domain": expected}
                if len({period_key(r) for r in subplot["data"]["values"]}) < len(expected):
                    subplot["layer"] = [layer for layer in subplot["layer"] if layer["mark"]["type"] != "line"]
    else:
        spec["vconcat"] = []
    meta = spec["usermeta"]
    meta.update(expectedPeriods=expected, comparisonSummary=summaries, displayMode="matrix",
                metricRowCount=len(spec["vconcat"]),
                missingPeriods=[p for p in expected if not any(period_key(row) == p for row in values)])
    if grouped:
        meta["colorLabels"] = expected
        meta["defaultMetric"] = next((row["metric"] for row in summaries
                                     if row["metric"] not in {"Matches", "Games", "Recorded observations"}), "")
    else:
        meta["seriesLabels"] = expected
    return spec


def add_research_charts(result, request=None, data_access=None, store=None):
    if not hasattr(result, "charts"):
        return
    grouped = {}
    labels = ResearchLabels(result, request, data_access, store)
    for item in result.aggregate_evidence:
        if item.metric in {"joined_aggregate", "soccer_monthly"} and type(item.value) in (int, float) and math.isfinite(item.value):
            objective = item.context.get("objective", item.label)
            # Plan objectives are prose, not a population identity. Equivalent
            # verified plans across years belong in one scoped comparison.
            key = "Scoped measurements" if labels.payload(item).get("plan") else objective
            grouped.setdefault((key, labels.partition(item)), []).append(item)
    # Remove only the old automatically generated research views; retain all stored evidence.
    objectives = {objective for objective, _ in grouped}
    result.charts[:] = [chart for chart in result.charts if not (
        chart.title in {f"Additional Measurements: {objective}" for objective in objectives}
        or chart.specification.get("usermeta", {}).get("researchObjective") is not None)]
    for (objective, _partition), items in grouped.items():
        rows, observations, measurements = [], {}, set()
        grouped_observations = any(item.context.get("group") for item in items)
        for item in items:
            measure = item.context["measure"]
            group = item.context.get("group", {})
            # A count of one per group is bookkeeping, not a useful subplot.
            # Retain its evidence and sample size; never average away the groups.
            peers = [peer for peer in items if peer.context["measure"] == measure]
            if (grouped_observations and measure["op"] in {"count", "n_unique"}
                    and all(peer.value == 1 for peer in peers)
                    and any(peer.context["measure"]["op"] not in {"count", "n_unique"} for peer in items)):
                continue
            window = labels.period(item)
            measurement = json.dumps([window, group, measure, item.context.get("measurement_definition"),
                item.context.get("metric_label"), item.value, item.unit, item.sample_size,
                item.row_set_sha256, sorted(item.dataset_manifest_ids)], sort_keys=True, default=str)
            if measurement in measurements:
                continue
            measurements.add(measurement)
            key = json.dumps([window, item.context.get("plan_id"), group], sort_keys=True, default=str)
            group_display = labels.group(item)
            filters = labels.filters(item)
            category = " · ".join(group_display.values()) or "All recorded observations"
            context = " · ".join([window, *filters, *(f"{_field_label(str(k))}: {v}" for k, v in group_display.items())])
            observation = observations.setdefault(key, " · ".join([category, window]))
            label = _field_label(measure["field"])
            if measure["op"] == "count":
                grain = labels.payload(item).get("plan", {}).get("grain")
                sport = getattr(labels.request, "sport", None) or labels.payload(item).get("sport")
                games = "Matches" if sport == "soccer" else "Games"
                label = {"game": games, "team_game": games, "player_game": "Player-game records",
                         "play": "Plays"}.get(grain, "Recorded observations")
            elif measure["op"] == "n_unique":
                label = {"game_id": "Distinct Games", "event_id": "Distinct Events"}.get(measure["field"], f"Distinct {label}")
            elif measure["op"] == "mean" and label != "Possession":
                label = f"Average {label}"
            elif measure["op"] == "sum":
                label = f"Total {label}"
            elif measure["op"] == "rate":
                label = item.context.get("measurement_definition", {}).get("definition") or label
            elif measure["op"] in {"min", "max"}:
                label = f"{'Minimum' if measure['op'] == 'min' else 'Maximum'} {label}"
            label = item.context.get("metric_label") or label
            venue = labels.venue(item)
            column = measure["field"].rsplit("__", 1)[-1]
            if venue and getattr(labels.request, "sport", None) == "soccer" and column in {"home_score", "away_score"}:
                scored = (venue == "Home") == (column == "home_score")
                label = ("Goals scored" if scored else "Goals conceded") + (" per match" if measure["op"] == "mean" else " (total)" if measure["op"] == "sum" else "")
            rows.append({"metric": label, "observation": observation, "category": category, "window": window,
                         "value": item.value,
                         "unit": "count" if column in {"home_score", "away_score"} and measure["op"] == "sum" else "percent_points" if measure["field"].endswith("possession_pct")
                         and measure["op"] in {"mean", "min", "max"} else item.unit,
                         "context_label": context, "group_display": group_display, "filter_display": filters,
                         "season": str(next(iter(group.values()))) if len(group) == 1
                         and next(iter(group)).rsplit("__", 1)[-1] == "season" else None,
                         "season_label": next(iter(group_display.values())) if len(group) == 1
                         and next(iter(group)).rsplit("__", 1)[-1] == "season" else None,
                         "month": str(group["month"]) if item.context.get("time_bucket") and group.get("month") else None,
                         "sample_size": item.sample_size, "evidence_id": item.evidence_id})
            rows[-1]["measurement_scope"] = {"rows": item.row_set_sha256, "inputs": sorted(item.dataset_manifest_ids)}
        if not rows:
            continue
        field = "observation" if grouped_observations else "window"
        kind = "grouped-observations" if grouped_observations else "period-comparison"
        if (all(row["season"] and row["season"].isdigit() for row in rows)
                and len({(row["metric"], row["season"]) for row in rows}) == len(rows)):
            field, kind = "season", "season-trend"
            rows.sort(key=lambda row: int(row["season"]))
            for row in rows:
                row["season"] = row["season_label"]
        if all(row["month"] for row in rows):
            # Preserve each window/stratum rather than collapsing coincident calendar months.
            field, kind = "observation", "monthly-trend"
            rows.sort(key=lambda row: (row["month"], row["observation"]))
            for row in rows:
                row["observation"] = f"{row['month']} · {row['window']}" if all(
                    set(i.context.get("group", {})) == {"month"} for i in items) else row["observation"]
        if kind == "grouped-observations":
            field = "category"
        order = list(dict.fromkeys(row[field] for row in rows))
        spec = metric_row_comparison_spec(rows, series_field=field,
            series_order=order, comparison_kind=kind, color_field="window" if kind in {"monthly-trend", "grouped-observations"} else None)
        spec["usermeta"]["researchObjective"] = objective
        spec["usermeta"]["colorTitle"] = "Seasons" if labels.scope(items[0]).get("comparison_design") == "full_seasons" else "Periods"
        scope_labels = labels.filters(items[0])
        dimensions = list(items[0].context.get("group", {}))
        title_filters = [text for text in scope_labels if not text.endswith(": recorded")]
        venue = labels.venue(items[0])
        if venue:
            title_filters = [f"{venue} matches"]
        suffix = " · ".join([*(f"By {_field_label(field)}" for field in dimensions if field != "month"), *title_filters])
        if not dimensions and not scope_labels:
            suffix = "Whole-period summary"
        if kind == "grouped-observations":
            spec["usermeta"]["description"] = (
                "Compare the named categories; colors identify the selected seasons or date windows. "
                "Each value summarizes its recorded sample. Category order does not imply a time trend. "
                "Whole-period totals and different filtered samples are shown separately.")
        elif kind == "monthly-trend":
            spec["usermeta"]["description"] = (
                "Calendar-month measurements from recorded match dates, ordered chronologically. "
                "Windows and strata remain separate; empty months are not zero. "
                "Exact values show qualifying samples; rates use summed compatible counters.")
        spec = _comparison_view(spec, labels, items, field, kind)
        spec["usermeta"]["eligibilityRules"] = scope_labels
        spec["usermeta"]["reportSection"] = "primary" if kind == "monthly-trend" else "supplemental"
        if kind == "monthly-trend":
            spec["usermeta"]["defaultMetric"] = rows[0]["metric"]
        if kind != "monthly-trend":
            spec["usermeta"]["description"] = (
                "Additional calculation for this specific filtered sample. Counts describe qualifying observations. "
                "An empty cell means this calculation was not produced for that period; consult the season summary for overall team performance.")
        identifier = stable_id("chart", {"objective": objective, "evidence": [i.evidence_id for i in items]})
        title = "Month-by-month performance" if kind == "monthly-trend" else "Filtered sample comparison"
        if kind == "grouped-observations":
            title = "Category comparison"
        chart = ChartArtifact(chart_id=identifier, title=title + (f" · {suffix}" if suffix else ""),
                              specification=spec, evidence_ids=[i.evidence_id for i in items])
        existing = next((index for index, item in enumerate(result.charts) if item.chart_id == identifier), None)
        if existing is None:
            result.charts.append(chart)
        else:
            result.charts[existing] = chart
    # Equivalent repeated tool calls should not produce repeated tables. Compare
    # the complete displayed measurements AND scope; never merge conflicting values.
    seen, charts = {}, []
    for chart in result.charts:
        meta = chart.specification.get("usermeta", {})
        if meta.get("researchObjective") is None:
            charts.append(chart)
            continue
        values = chart.specification.get("data", {}).get("values", [])
        identity = json.dumps({"kind": meta.get("comparisonKind"), "scope": sorted(meta.get("eligibilityRules", [])),
            "values": sorted([{k: v for k, v in row.items() if k not in {"evidence_id", "observation", "context_label", "series_order"}}
                for row in values], key=lambda row: json.dumps(row, sort_keys=True, default=str))}, sort_keys=True, default=str)
        if identity in seen:
            previous = seen[identity]
            previous.evidence_ids[:] = list(dict.fromkeys([*previous.evidence_ids, *chart.evidence_ids]))
        else:
            seen[identity] = chart
            charts.append(chart)
    result.charts[:] = charts


def refresh_chart_presentation(bundle, store=None):
    """Repair saved chart presentation without changing stored evidence."""
    research = any(item.metric in {"joined_aggregate", "soccer_monthly"} for item in bundle.aggregate_evidence)
    legacy = any(chart.specification.get("usermeta", {}).get("chartKind") == "metric-rows"
                 and chart.specification["usermeta"].get("presentationVersion", 0) < 2 for chart in bundle.charts)
    soccer_seasonal = getattr(getattr(bundle, "run", None), "sport", None) == "soccer" and any(
        item.metric.startswith("seasonal_") for item in bundle.aggregate_evidence)
    if not research and not legacy and not soccer_seasonal:
        return bundle
    refreshed = bundle.model_copy(deep=True)
    if research:
        add_research_charts(refreshed, store=store)
    for index, chart in enumerate(refreshed.charts):
        meta = chart.specification.get("usermeta", {})
        if meta.get("chartKind") != "metric-rows" or meta.get("presentationVersion", 0) >= 2:
            continue
        rows = chart.specification.get("data", {}).get("values", [])
        if not rows or not meta.get("seriesField"):
            continue
        for row in rows:
            if isinstance(row.get("display_value"), str):
                row["display_value"] = row["display_value"].removeprefix("+")
        spec = metric_row_comparison_spec(rows, series_field=meta["seriesField"], series_order=meta.get("seriesLabels", []))
        refreshed.charts[index] = chart.model_copy(update={"specification": spec})
    if getattr(getattr(refreshed, "run", None), "sport", None) == "soccer":
        from sports_analyst.plugins.soccer_trends import season_matrix

        seasonal_ids = {item.evidence_id for item in refreshed.aggregate_evidence if item.metric.startswith("seasonal_")}
        for chart in refreshed.charts:
            if seasonal_ids.intersection(chart.evidence_ids) and chart.specification.get("usermeta", {}).get("seriesField") == "season":
                season_matrix(chart.specification, chart.specification["usermeta"].get("seriesLabels", []))
                chart.title = "Season summary · recorded match performance"
    return refreshed
