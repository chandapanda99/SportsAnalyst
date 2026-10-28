"""Present registered measurements at their recorded grain, with readable labels."""
import json
import math

from sports_analyst.models import ChartArtifact, stable_id
from sports_analyst.presentation.charts import metric_row_comparison_spec


def _field_label(field):
    field = field.rsplit("__", 1)[-1]
    return {"game_id": "Game ID", "event_id": "Event ID", "possession_pct": "Possession",
            "home_score": "Home Score", "away_score": "Away Score", "epa": "EPA",
            "xg": "Expected Goals", "cpoe": "CPOE"}.get(field, field.replace("_", " ").title())


def add_research_charts(result):
    if not hasattr(result, "charts"):
        return
    grouped = {}
    for item in result.aggregate_evidence:
        if item.metric in {"joined_aggregate", "soccer_monthly"} and type(item.value) in (int, float) and math.isfinite(item.value):
            objective = item.context.get("objective", item.label)
            grouped.setdefault(objective, []).append(item)
    for objective, items in list(grouped.items())[:8]:
        rows, observations = [], {}
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
            window = {"baseline": "Reference Period", "comparison": "Comparison Period"}.get(
                item.context.get("window"), item.context.get("window", "Recorded Data"))
            key = json.dumps([window, item.context.get("plan_id"), group], sort_keys=True, default=str)
            context = " · ".join(f"{_field_label(str(k))}: {v}" for k, v in group.items())
            observation = observations.setdefault(key, " · ".join(filter(None, [window, context])))
            label = _field_label(measure["field"])
            if measure["op"] == "count":
                label = f"Recorded {label} Count" if label else "Recorded Observations"
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
            rows.append({"metric": label, "observation": observation, "window": window,
                         "value": item.value,
                         "unit": "percent_points" if measure["field"].endswith("possession_pct")
                         and measure["op"] in {"mean", "min", "max"} else item.unit,
                         "context_label": " · ".join([window, *(f"{_field_label(str(k))}: {v}" for k, v in group.items())]),
                         "season": str(next(iter(group.values()))) if len(group) == 1
                         and next(iter(group)).rsplit("__", 1)[-1] == "season" else None,
                         "month": str(group["month"]) if item.context.get("time_bucket") and group.get("month") else None,
                         "sample_size": item.sample_size, "evidence_id": item.evidence_id})
        if not rows:
            continue
        field = "observation" if grouped_observations else "window"
        kind = "grouped-observations" if grouped_observations else "period-comparison"
        if (all(row["season"] and row["season"].isdigit() for row in rows)
                and len({(row["metric"], row["season"]) for row in rows}) == len(rows)):
            field, kind = "season", "season-trend"
        if all(row["month"] for row in rows):
            # Preserve each window/stratum rather than collapsing coincident calendar months.
            field, kind = "observation", "monthly-trend"
            rows.sort(key=lambda row: (row["month"], row["observation"]))
            for row in rows:
                row["observation"] = f"{row['month']} · {row['window']}" if all(
                    set(i.context.get("group", {})) == {"month"} for i in items) else row["observation"]
        order = list(dict.fromkeys(row[field] for row in rows))
        if field == "season":
            order.sort(key=int)
        spec = metric_row_comparison_spec(rows, series_field=field,
            series_order=order, comparison_kind=kind, color_field="window" if kind == "monthly-trend" else None)
        if kind == "grouped-observations":
            spec["usermeta"]["description"] = (
                "Each point is a recorded data group, not necessarily a single match. "
                "Groups are not ordered in time. Open exact values for the recorded context and sample sizes.")
        elif kind == "monthly-trend":
            spec["usermeta"]["description"] = (
                "Calendar-month measurements from recorded match dates, ordered chronologically. "
                "Windows and strata remain separate; empty months are not zero. "
                "Exact values show qualifying samples; rates use summed compatible counters.")
        identifier = stable_id("chart", {"objective": objective, "evidence": [i.evidence_id for i in items]})
        chart = ChartArtifact(chart_id=identifier, title=f"Additional Measurements: {objective}",
                              specification=spec, evidence_ids=[i.evidence_id for i in items])
        existing = next((index for index, item in enumerate(result.charts) if item.chart_id == identifier), None)
        if existing is None:
            result.charts.append(chart)
        else:
            result.charts[existing] = chart


def refresh_chart_presentation(bundle):
    """Repair saved chart presentation without changing stored evidence."""
    research = any(item.metric in {"joined_aggregate", "soccer_monthly"} for item in bundle.aggregate_evidence)
    legacy = any(chart.specification.get("usermeta", {}).get("chartKind") == "metric-rows"
                 and chart.specification["usermeta"].get("presentationVersion", 0) < 2 for chart in bundle.charts)
    if not research and not legacy:
        return bundle
    refreshed = bundle.model_copy(deep=True)
    if research:
        add_research_charts(refreshed)
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
    return refreshed
