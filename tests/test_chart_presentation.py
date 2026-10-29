"""Crucial chart contracts: correct grain, saved-result repair, and renderable trends."""
from copy import deepcopy
from types import SimpleNamespace

from sports_analyst.analysis.research.presentation import add_research_charts, refresh_chart_presentation
from sports_analyst.models import AggregateEvidence, AnalysisRequest, DatasetManifest
from sports_analyst.presentation.charts import metric_row_comparison_spec
from sports_analyst.presentation.reports import _themed_chart_specification


def test_soccer_scoped_tables_deduplicate_and_label_scores_from_selected_team_perspective():
    request = AnalysisRequest(sport="soccer", question="Compare scoring", analysis_domain="results",
        subject={"type": "team", "id": "132"}, scope={"team": "132", "competition": "uefa.champions",
        "comparison_design": "full_seasons", "baseline": {"season": 2024}, "comparison": {"season": 2026}})
    result = SimpleNamespace(charts=[], aggregate_evidence=[], executions=[])
    for attempt in (1, 2):
        plan_id = f"same-calculation-{attempt}"
        result.executions.append(SimpleNamespace(parameters={"plan_id": plan_id, "plan": {
            "dataset_id": "schedule", "grain": "game", "filters": [
                {"field": "home_team_id", "op": "eq", "value": "132"},
                {"field": "home_score", "op": "is_not_null"}]}}))
        for field, value in (("home_score", 19), ("away_score", 6)):
            result.aggregate_evidence.append(AggregateEvidence(evidence_id=f"{attempt}-{field}", metric="joined_aggregate",
                label="Raw score", value=value, unit="recorded column units", sample_size=7, row_set_sha256="same-observations",
                dataset_manifest_ids=["schedule"], tool_execution_id=plan_id, context={"objective": f"Scoring attempt {attempt}",
                    "plan_id": plan_id, "window": "baseline", "measure": {"op": "sum", "field": field}}))
    add_research_charts(result, request=request)
    assert len(result.charts) == 1
    chart = result.charts[0]
    assert chart.title == "Filtered sample comparison · Home matches"
    assert "recorded" not in chart.title
    assert {row["metric"] for row in chart.specification["data"]["values"]} == {"Goals scored (total)", "Goals conceded (total)"}
    assert {row["display_value"] for row in chart.specification["data"]["values"]} == {"19", "6"}
    assert len(chart.evidence_ids) == 4
    assert chart.specification["usermeta"]["reportSection"] == "supplemental"
    assert len(result.aggregate_evidence) == 4


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
    assert len(result.charts) == 1 and not chart.specification["vconcat"]
    assert chart.specification["usermeta"]["displayMode"] == "matrix"
    assert {row["metric"] for row in chart.specification["usermeta"]["comparisonSummary"]} == {"Possession"}
    assert {row["value"] for row in chart.specification["data"]["values"]} == {51.6, 60.4, 40.8}
    assert all(row["display_value"].endswith("%") for row in chart.specification["data"]["values"])
    assert set(chart.evidence_ids) == {item.evidence_id for item in evidence}
    assert "Home Score: 2" in chart.specification["data"]["values"][0]["context_label"]
    assert all(not label.startswith("Group ") for label in chart.specification["usermeta"]["seriesLabels"])
    # Simulate a persisted legacy plot and verify repair is idempotent, leaving evidence intact.
    chart.specification["vconcat"] = [{"title": {"text": "mean possession_pct {'raw': 'dictionary'}"}}]
    repaired = refresh_chart_presentation(result)
    assert repaired.charts[0].chart_id == chart.chart_id
    assert not repaired.charts[0].specification["vconcat"]
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
    assert spec["usermeta"]["colorLabels"] == ["Earlier period", "Later period"]
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


def test_research_categories_resolve_names_separate_populations_and_survive_saved_repair(tmp_path):
    import polars as pl
    import vl_convert as vlc

    from sports_analyst.datasets.nfl import sha256_file

    request = AnalysisRequest(sport="soccer", question="Compare home and away possession", analysis_domain="control",
        subject={"type": "team", "id": "132"}, scope={"team": "132", "competition": "ger.1",
        "comparison_design": "full_seasons", "baseline": {"season": 2024}, "comparison": {"season": 2026}})
    source = pl.DataFrame({"home_team_id": ["132", "359"], "home_team": ["Bayern Munich", "Recorded Opponent"]})
    path = tmp_path / "schedule.parquet"
    source.write_parquet(path)
    manifest = DatasetManifest(manifest_id="schedule", sport="soccer", competition="ger.1", season=2024,
        dataset="play_by_play", columns=source.columns, local_path=str(path), sha256=sha256_file(path),
        source_url="synthetic-test", row_count=2, package_version="test")

    class SavedResult(SimpleNamespace):
        def model_copy(self, **kwargs):
            return deepcopy(self)

    result = SavedResult(run=request, charts=[], aggregate_evidence=[], executions=[], dataset_manifests=[manifest])

    def record(plan_id, window, group, field, op, value, filters=None):
        alias = {"baseline": "game", "season:2025": "schedule", "comparison": "fixture"}[window]
        group = {f"{alias}__{key.rsplit('__', 1)[-1]}": value for key, value in group.items()}
        steps = [{"alias": alias, "relationship_id": "schedule-context"}] if group else []
        plan = {"dataset_id": "schedule", "grain": "team_game", "steps": steps, "filters": filters or []}
        result.executions.append(SimpleNamespace(parameters={"plan_id": plan_id, "plan": plan,
            "relationship_contracts": [{"relationship_id": "schedule-context", "right_dataset_id": "schedule"}]}))
        result.aggregate_evidence.append(AggregateEvidence(evidence_id=f"{plan_id}-{field}-{group}", metric="joined_aggregate",
            label="Source measurement", value=value, unit="recorded column units", sample_size=int(value) if op == "count" else 6,
            row_set_sha256="a" * 64, dataset_manifest_ids=["schedule"], tool_execution_id=plan_id,
            context={"objective": "Possession context", "window": window, "group": group, "plan_id": plan_id,
                     "measure": {"op": op, "field": field}}))

    for window in ("baseline", "season:2025", "comparison"):
        for identity, value in (("132", 60.), ("359", 48.)):
            record(f"teams-{window}", window, {"game__home_team_id": identity}, "possession_pct", "mean", value)
            record(f"teams-{window}", window, {"game__home_team_id": identity}, "game_id", "count", 6 if identity == "132" else 1)
    record("all", "baseline", {}, "game_id", "count", 12)
    record("home", "baseline", {}, "game_id", "count", 6, [{"field": "is_home", "op": "eq", "value": True}])
    record("away", "baseline", {}, "game_id", "count", 6, [{"field": "is_home", "op": "eq", "value": False}])
    original_evidence = deepcopy(result.aggregate_evidence)
    add_research_charts(result)
    assert len(result.charts) == 4
    assert any("Home matches" in chart.title for chart in result.charts)
    assert any("Away matches" in chart.title for chart in result.charts)
    chart = next(chart for chart in result.charts if chart.specification["usermeta"]["comparisonKind"] == "grouped-observations")
    spec = chart.specification
    assert spec["usermeta"]["seriesLabels"] == ["Bayern Munich", "Recorded Opponent"]
    assert spec["usermeta"]["colorLabels"] == ["2023–24", "2024–25", "2025–26"]
    assert all(row["category"] in {"Bayern Munich", "Recorded Opponent"} for row in spec["data"]["values"])
    assert spec["vconcat"][0]["layer"][0]["encoding"]["y"]["field"] == "category"
    assert {row["value"] for row in spec["data"]["values"] if row["metric"] == "Possession"} == {48., 60.}
    svg = vlc.vegalite_to_svg(_themed_chart_specification(spec, "132", "soccer"))
    assert all(text in svg for text in ("Bayern Munich", "Recorded Opponent", "2024–25", "60.0%"))
    assert "Reference Period" not in svg and "season:2025" not in svg and "Home Team Id" not in svg
    # Missing calculations must leave the complete selected range visible, not silently shorten the legend/table.
    partial = result.model_copy(deep=True)
    partial.aggregate_evidence = [item for item in partial.aggregate_evidence if item.context["window"] != "comparison"]
    add_research_charts(partial)
    partial_spec = next(c.specification for c in partial.charts
                        if c.specification["usermeta"]["comparisonKind"] == "grouped-observations")
    assert partial_spec["usermeta"]["expectedPeriods"] == ["2023–24", "2024–25", "2025–26"]
    assert partial_spec["usermeta"]["missingPeriods"] == ["2025–26"]
    assert all(not row["cells"][-1]["entries"] for row in partial_spec["usermeta"]["comparisonSummary"])
    # Portable saved reports retain display names even after downloaded data is cleared.
    path.unlink()
    repaired = refresh_chart_presentation(result)
    assert repaired.aggregate_evidence == original_evidence
    assert len(repaired.charts) == 4
    assert next(c for c in repaired.charts if c.chart_id == chart.chart_id).specification["usermeta"]["seriesLabels"] == [
        "Bayern Munich", "Recorded Opponent"]
