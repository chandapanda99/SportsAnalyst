"""Present newly registered measurements without mixing unrelated units/scales."""
from sports_analyst.models import ChartArtifact, stable_id
from sports_analyst.presentation.charts import metric_row_comparison_spec


def add_research_charts(result):
    if not hasattr(result, "charts"):
        return
    grouped = {}
    for item in result.aggregate_evidence:
        if item.metric == "joined_aggregate" and type(item.value) in (int, float):
            objective = item.context.get("objective", item.label)
            grouped.setdefault(objective, []).append(item)
    for objective, items in list(grouped.items())[:8]:
        rows = []
        for item in items:
            measure = item.context["measure"]
            group = item.context.get("group", {})
            rows.append({"metric": f"{measure['op']} {measure['field']} {group}",
                         "window": item.context["window"], "value": item.value, "unit": item.unit})
        identifier = stable_id("chart", {"objective": objective, "evidence": [i.evidence_id for i in items]})
        if identifier not in {c.chart_id for c in result.charts}:
            result.charts.append(ChartArtifact(chart_id=identifier, title=f"Additional measurements: {objective}",
                specification=metric_row_comparison_spec(rows, series_field="window",
                    series_order=list(dict.fromkeys(row["window"] for row in rows))),
                evidence_ids=[i.evidence_id for i in items]))
