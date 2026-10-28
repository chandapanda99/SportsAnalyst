"""Crucial chart contracts: correct grain, saved-result repair, and renderable trends."""
from copy import deepcopy
from types import SimpleNamespace

from sports_analyst.analysis.research.presentation import add_research_charts, refresh_chart_presentation
from sports_analyst.models import AggregateEvidence
from sports_analyst.presentation.charts import metric_row_comparison_spec
from sports_analyst.presentation.reports import _themed_chart_specification


def test_grouped_research_charts_preserve_measurements_and_repair_saved_results():
    evidence = []
    for index, possession in enumerate((51.6, 60.4, 40.8)):
        for op, field, value in (("count", "game_id", 1), ("mean", "possession_pct", possession)):
            evidence.append(AggregateEvidence(evidence_id=f"e{index}-{op}", metric="joined_aggregate", label="Raw result",
                value=value, unit="observations" if op == "count" else "recorded column units", sample_size=1,
                row_set_sha256="a" * 64, dataset_manifest_ids=["m1"], tool_execution_id="t1",
                context={"objective": "Away Possession 2025", "window": "comparison",
                    "measure": {"op": op, "field": field},
                    "group": {"possession_pct": str(possession), "game__home_score": "2", "game__away_score": "3"}}))
    class SavedResult(SimpleNamespace):
        def model_copy(self, **kwargs):
            return deepcopy(self)

    result = SavedResult(aggregate_evidence=evidence, charts=[])
    add_research_charts(result)
    chart = result.charts[0]
    assert len(result.charts) == 1 and len(chart.specification["vconcat"]) == 1
    assert chart.specification["vconcat"][0]["title"]["text"] == "Possession"
    assert {row["value"] for row in chart.specification["data"]["values"]} == {51.6, 60.4, 40.8}
    assert all(row["display_value"].endswith("%") for row in chart.specification["data"]["values"])
    assert all(layer["mark"]["type"] != "line" for layer in chart.specification["vconcat"][0]["layer"])
    assert set(chart.evidence_ids) == {item.evidence_id for item in evidence}
    assert "Home Score: 2" in chart.specification["data"]["values"][0]["context_label"]
    assert all(not label.startswith("Group ") for label in chart.specification["usermeta"]["seriesLabels"])
    # Simulate a persisted legacy plot and verify repair is idempotent, leaving evidence intact.
    chart.specification["vconcat"][0]["title"]["text"] = "mean possession_pct {'raw': 'dictionary'}"
    repaired = refresh_chart_presentation(result)
    assert repaired.charts[0].chart_id == chart.chart_id
    assert repaired.charts[0].specification["vconcat"][0]["title"]["text"] == "Possession"
    assert result.charts[0].specification["vconcat"][0]["title"]["text"].startswith("mean possession_pct {")
    assert repaired.aggregate_evidence == evidence
    assert len(refresh_chart_presentation(repaired).charts) == 1
    seasonal = SavedResult(charts=[], aggregate_evidence=[item.model_copy(update={
        "context": {**item.context, "group": {"season": 2025 - index // 2}}}) for index, item in enumerate(evidence)])
    add_research_charts(seasonal)
    assert seasonal.charts[0].specification["usermeta"]["comparisonKind"] == "season-trend"
    assert seasonal.charts[0].specification["usermeta"]["seriesLabels"] == ["2023", "2024", "2025"]


def test_monthly_charts_order_actual_months_keep_windows_and_metric_samples():
    import vl_convert as vlc

    evidence = [AggregateEvidence(evidence_id=f"month-{i}-{metric}", metric="soccer_monthly", label=metric,
        value=value, unit=unit, sample_size=3, row_set_sha256="a" * 64,
        dataset_manifest_ids=["m1"], tool_execution_id="t1",
        context={"objective": "Monthly performance", "window": window, "group": {"month": month},
                 "time_bucket": {"field": "date", "interval": "month"}, "metric_label": metric,
                 "measure": {"op": "defined_metric", "field": metric}})
        for i, (month, window) in enumerate([("2025-03", "comparison"), ("2024-09", "baseline")])
        for metric, value, unit in [("Possession", .6, "percentage"), ("Goals per match", 2., "goals")]]
    result = SimpleNamespace(aggregate_evidence=evidence, charts=[])
    add_research_charts(result)
    spec = result.charts[0].specification
    assert spec["usermeta"]["comparisonKind"] == "monthly-trend"
    assert spec["usermeta"]["seriesLabels"][0].startswith("2024-09")
    assert spec["usermeta"]["colorLabels"] == ["Reference Period", "Comparison Period"]
    assert len(spec["vconcat"]) == 2
    assert all(row["sample_size"] == 3 for row in spec["data"]["values"])
    svg = vlc.vegalite_to_svg(_themed_chart_specification(spec, "132", "soccer"))
    assert "2024-09" in svg and "60.0%" in svg and "NaN" not in svg


def test_season_trend_chart_renders_labels_scales_and_export_legend():
    import vl_convert as vlc

    rows = [{"metric": metric, "season": str(2023 + i), "value": value, "unit": unit}
            for metric, unit, values in (("EPA/play", "EPA/play", (-.049, -.082, .079)),
                                        ("Turnover Rate", "rate", (.022, .013, .010)),
                                        ("CPOE", "rate", (-.102, -4.002, 1.2)))
            for i, value in enumerate(values)]
    spec = metric_row_comparison_spec(rows, series_field="season", series_order=["2023", "2024", "2025"])
    assert spec["usermeta"]["comparisonKind"] == "season-trend"
    assert spec["vconcat"][1]["layer"][0]["encoding"]["y"]["axis"]["format"] == ".1%"
    themed = _themed_chart_specification(spec, "CHI")
    scale = themed["vconcat"][0]["layer"][1]["encoding"]["color"]["scale"]
    assert scale["domain"] == ["2023", "2024", "2025"] and len(set(scale["range"])) == 3
    svg = vlc.vegalite_to_svg(themed)
    assert all(label in svg for label in ("Seasons", "2023", "2024", "2025", "2.2%", "1.3%", "0.079"))
    assert "+0.079" not in svg and "NaN" not in svg
    assert "-0.10 pp" in svg and "-4.00 pp" in svg and "-10.2%" not in svg
