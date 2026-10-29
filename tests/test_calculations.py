"""Major analytical composition, accounting, and isolation contracts."""
from types import SimpleNamespace

import polars as pl
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from test_nfl_plugin import manifest

from sports_analyst.analysis.agents import _fallback_synthesis
from sports_analyst.analysis.calculations import checked_arithmetic, complete_calculations
from sports_analyst.application.service import AnalystApplication
from sports_analyst.config import Settings
from sports_analyst.models import AnalysisRequest, AnalysisScope, AnalysisWindow
from sports_analyst.plugins.nfl_accounting import phase_accounting


def accounting_sample():
    frame = pl.DataFrame({"_epa": [1., 2., -2., -3., 0.5], "play_type": ["pass", "run", "pass", "pass", "other"],
        "sack": [0, 0, 1, 1, 0], "interception": [0, 0, 0, 1, 0], "fumble_lost": [0] * 5})
    comparison = pl.concat([frame.with_columns((pl.col("_epa") + 1).alias("_epa")), frame])
    return frame, comparison


def test_epa_accounting_reconciles_unequal_samples_and_preserves_missingness():
    baseline, comparison = accounting_sample()
    sources = [manifest(2024, baseline.columns), manifest(2025, comparison.columns)]
    evidence, execution, chart, gap = phase_accounting(baseline, comparison, sources)
    assert gap is None and len(evidence) == 5
    assert sum(item.value for item in evidence) == pytest.approx(comparison["_epa"].mean() - baseline["_epa"].mean())
    assert sum(group["plays"] for group in execution.parameters["windows"][0]["groups"].values()) == baseline.height
    assert execution.parameters["windows"][0]["groups"]["Sacks (non-turnover)"]["plays"] == 1
    assert execution.parameters["windows"][0]["groups"]["Turnovers"]["plays"] == 1
    assert chart.evidence_ids == [item.evidence_id for item in evidence]
    # Zero recorded events differ from an unavailable classification field.
    for incomplete in (comparison.drop("sack"), comparison.with_columns(pl.lit(None).alias("sack"))):
        absent, _, _, reason = phase_accounting(baseline, incomplete, sources)
        assert not absent and reason
    # The offline report answers the accounting question too.
    primary = evidence[0].model_copy(update={"metric": "epa_per_play", "value": .5})
    draft = _fallback_synthesis("Which phase contributed?", "CHI", AnalysisWindow(season=2024), AnalysisWindow(season=2025),
                                [primary, *evidence], analysis_domain="offense")
    assert "accounting contribution" in draft.summary


def test_interpreter_composes_scoped_evidence_and_registers_only_checked_results(monkeypatch):
    baseline, comparison = accounting_sample()
    evidence, _, _, _ = phase_accounting(baseline, comparison, [manifest(2024, baseline.columns)])
    first = evidence[0]
    code = '''const index = JSON.parse(await tools.inspectCalculationInputs({}));
if (!index.metric_index.some(x => x.metric === "epa_phase_contribution")) throw Error("Hidden accounting family");
const data = JSON.parse(await tools.inspectCalculationInputs({metric: "epa_phase_contribution"}));
const e = data.evidence[0];
await tools.recordAnalysisPlan({objectives:["Compare contributions"],existing_evidence_ids:[e.evidence_id],
required_data:[],calculations:["Double the contribution"],limitations:[]});
if (typeof fetch !== "undefined" || typeof process !== "undefined") throw Error("Host capability exposed");
let rejected = false;
try { await tools.registerArithmetic({label:"Bad", expression:"a * 2",
inputs:{a:{evidence_id:e.evidence_id,field:"value"}},proposed_value:999,unit:e.unit}); }
catch (error) { rejected = true; }
// Invalid calls are returned as correctable errors; no evidence is registered.
const registered = JSON.parse(await tools.registerArithmetic({label:"Contribution doubled", expression:"a * 2",
inputs:{a:{evidence_id:e.evidence_id,field:"value"}},proposed_value:e.value * 2,unit:e.unit}));
await tools.finishQuestionReview({evidence_by_objective:{"0":[e.evidence_id,registered.evidence_id]},unresolved:{}});
"done";'''

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    # This response repeats forever unless the host stops after the valid review.
    model = Model(responses=[AIMessage(content="", tool_calls=[{"name": "eval", "id": "calc", "args": {"code": code}}])])
    monkeypatch.setattr("sports_analyst.providers.get_provider", lambda name: SimpleNamespace(
        build=lambda settings: SimpleNamespace(chat_model=model, model_id="offline-calculation-model")))
    noise = [first.model_copy(update={"evidence_id": f"noise-{i}", "metric": "unrelated_metric"}) for i in range(100)]
    result = SimpleNamespace(aggregate_evidence=[*noise, *evidence], executions=[], caveats=[])
    complete_calculations(Settings(_env_file=None, model_provider="ollama"), "Compare the contributions", result, {"team": "CHI"})
    assert not result.caveats
    derived = [item for item in result.aggregate_evidence if item.metric == "derived_arithmetic"]
    assert len(derived) == 1 and derived[0].value == pytest.approx(first.value * 2)
    assert derived[0].context["validation"] == "arithmetic_only"
    assert any(item.tool == "complete_calculations" and item.parameters["messages"] for item in result.executions)
    assert result.executions[-1].parameters["planning_turns"][0]["stop_reason"] == "review_complete"
    assert result.executions[-1].parameters["planning_turns"][0]["model_calls"] == 1
    for expression in ("__import__('os')", "a.__class__", "a ** 10000", "1 / 0"):
        with pytest.raises((ValueError, ZeroDivisionError)):
            checked_arithmetic(expression, {"a": 2.})
    # A prematurely finished live-model stage remains a persisted execution
    # failure, not an ordinary source-coverage gap.
    model.responses = [AIMessage(content="Cannot proceed")]
    broken = SimpleNamespace(aggregate_evidence=list(evidence), executions=[], caveats=[])
    complete_calculations(Settings(_env_file=None, model_provider="ollama"), "Compare contributions", broken, {})
    assert broken.executions[-1].tool == "complete_calculations_failed"
    assert broken.executions[-1].parameters["error_type"] == "ValueError"
    assert "execution failure" in broken.caveats[0]


@pytest.mark.parametrize("exhausted", [False, True])
def test_interpreter_bounds_planning_and_preserves_measurements(monkeypatch, exhausted):
    baseline, comparison = accounting_sample()
    evidence, _, _, _ = phase_accounting(baseline, comparison, [manifest(2024, baseline.columns)])
    first = evidence[0]
    start = '''const e=JSON.parse(await tools.inspectCalculationInputs({})).evidence[0];
await tools.recordAnalysisPlan({objectives:["Compare contributions"],existing_evidence_ids:[e.evidence_id],
required_data:[],calculations:["Double contribution"],limitations:[]});
await tools.registerArithmetic({label:"Doubled",expression:"a*2",inputs:{a:{evidence_id:e.evidence_id,field:"value"}},
proposed_value:e.value*2,unit:e.unit}); "registered";'''
    finish = f'''await tools.finishQuestionReview({{evidence_by_objective:{{"0":["{first.evidence_id}"]}},unresolved:{{}}}}); "finished";'''

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    def evaluation(code, call_id):
        return AIMessage(content="", tool_calls=[{"name": "eval", "id": call_id, "args": {"code": code}}])

    # Thirteen model/tool exchanges exceed the former 32 graph-step guard.
    responses = [evaluation(start, "start")]
    if exhausted:
        responses.extend(evaluation('await tools.inspectCalculationInputs({offset:-1});', f"invalid-{i}") for i in range(3))
    else:
        responses.extend(evaluation(f'await tools.inspectCalculationInputs({{offset:{i}}});', f"page-{i}") for i in range(11))
        responses.append(evaluation(finish, "review"))
    model = Model(responses=responses)
    monkeypatch.setattr("sports_analyst.providers.get_provider", lambda _: SimpleNamespace(
        build=lambda settings: SimpleNamespace(chat_model=model, model_id="offline-bounded-planner")))
    result = SimpleNamespace(aggregate_evidence=list(evidence), executions=[], caveats=[])
    complete_calculations(Settings(_env_file=None, model_provider="ollama", calculation_model_call_limit=4 if exhausted else 24),
                          "Compare contributions", result, {})
    assert len([e for e in result.aggregate_evidence if e.metric == "derived_arithmetic"]) == 1
    execution = next(e for e in result.executions if e.tool.startswith("complete_calculations"))
    turn = execution.parameters["planning_turns"][0]
    assert turn["model_calls"] == (4 if exhausted else 13)
    assert turn["stop_reason"] == ("model_call_limit" if exhausted else "review_complete")
    if exhausted:
        assert execution.tool == "complete_calculations_failed"
        assert execution.parameters["retained_evidence_ids"]
        assert execution.parameters["tool_audit"][-1]["tool"] == "inspect_calculation_inputs"
        assert "execution failure" in result.caveats[0]
    else:
        assert execution.tool == "complete_calculations" and not result.caveats


def test_controlled_game_join_and_scoped_acquisition(tmp_path, monkeypatch):
    from contextlib import nullcontext

    from sports_analyst.analysis.scoped_data import ScopedData
    from sports_analyst.datasets.nfl import sha256_file

    left_path, right_path = tmp_path / "plays.parquet", tmp_path / "schedule.parquet"
    left = pl.DataFrame({"team_id": ["1", "1", "9"], "game_id": ["g1", "g1", "g2"],
                         "play_id": ["p1", "p2", "p3"], "yards": [5., 10., 999.]})
    right = pl.DataFrame({"game_id": ["g1", "g2"], "venue": ["home", "away"]})
    left.write_parquet(left_path)
    right.write_parquet(right_path)
    sources = [manifest(2025, frame.columns, dataset).model_copy(update={"sport": "cfb", "partition_key": "team:1",
        "local_path": str(path), "sha256": sha256_file(path)})
        for frame, path, dataset in [(left, left_path, "recorded_plays"), (right, right_path, "schedules")]]
    persisted = []
    store = SimpleNamespace(manifests=lambda **kwargs: sources, materialize_manifest=lambda item: item,
                            save_manifest=lambda item: persisted.append(item))
    fetched = []

    def sync(seasons, datasets, **kwargs):
        fetched.append((seasons, datasets, kwargs["team_ids"]))
        item = sources[0].model_copy(update={"dataset": "team_stats", "manifest_id": "prepared-stats"})
        kwargs["manifest_callback"](item)
        return [item]

    from sports_analyst.storage.persistence import LocalPersistenceBackend

    store.persistence = LocalPersistenceBackend()
    app = SimpleNamespace(settings=Settings(_env_file=None, data_dir=tmp_path), store=store,
                          connectors={"cfb": SimpleNamespace(sync=sync)})
    monkeypatch.setattr("sports_analyst.application.preparation.coordinator", lambda app: SimpleNamespace(lease=lambda *a, **k: nullcontext()))
    request = AnalysisRequest(sport="cfb", question="Compare yardage by venue", scope={"team": "1", "season_type": "ALL",
        "comparison_design": "full_seasons", "baseline": {"season": 2024}, "comparison": {"season": 2025}})
    access = ScopedData(app, request, "team:1")
    result = access.aggregate(sources[0].manifest_id, "comparison", ["game__venue"], [{"op": "sum", "field": "yards"}], [],
                              sources[1].manifest_id, ["venue"])
    assert result["rows"][0]["m0"] == 15 and result["qualifying_rows"] == 2
    assert result["joined_sha256"] == sources[1].sha256
    assert access.prepare_dataset("team_stats", 2025)[0]["dataset_id"] == "prepared-stats"
    assert fetched == [([2025], ["team_stats"], ["1"])] and persisted
    with pytest.raises(ValueError):
        access.prepare_dataset("team_stats", 2025)
    right = pl.concat([right, right.head(1)])
    right.write_parquet(right_path)
    duplicate = sources[1].model_copy(update={"sha256": sha256_file(right_path)})
    access.manifests[duplicate.manifest_id] = duplicate
    with pytest.raises(ValueError, match="duplicated"):
        access.aggregate(sources[0].manifest_id, "comparison", ["game__venue"], [{"op": "count"}], [],
                         duplicate.manifest_id, ["venue"])


def test_nfl_phase_request_persists_accounting_chart_and_play_examples(tmp_path, pbp_pair):
    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, foundry_endpoint=""))
    for season, frame in pbp_pair.items():
        frame = frame.with_columns(pl.lit(0).alias("fumble_lost"))
        path = tmp_path / f"fixture-{season}.parquet"
        frame.write_parquet(path)
        app.store.save_manifest(app.connector.register_local(path, season))
    request = AnalysisRequest(question="Which phase contributed to the change in EPA?", analysis_domain="offense",
        metrics=["epa_per_play"], scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025))
    bundle = app.investigate(request)
    accounting = [item for item in bundle.aggregate_evidence if item.metric == "epa_phase_contribution"]
    assert len(accounting) == 5
    assert any(item.tool == "account_offensive_epa_change" for item in bundle.executions)
    assert any(chart.title == "Where the EPA/play change came from" for chart in bundle.charts)
    assert "accounting contribution" in bundle.summary
    saved = app.store.get_investigation(bundle.run.investigation_id)
    assert all(app.evidence(saved.run.investigation_id, item.evidence_id) for item in accounting)
    assert saved.play_evidence and all(play.play_id for play in saved.play_evidence)
    # Simulate a report saved before phase accounting existed. A follow-up must
    # prepare the missing calculation, not repeat the old evidence gap.
    legacy_id = "legacy-" + saved.run.investigation_id
    removed = {item.evidence_id for item in accounting}
    app.store.save_investigation(saved.model_copy(update={"run": saved.run.model_copy(update={"investigation_id": legacy_id}),
        "claims": [claim for claim in saved.claims if not removed.intersection(claim.evidence_ids)],
        "charts": [chart for chart in saved.charts if not removed.intersection(chart.evidence_ids)],
        "aggregate_evidence": [
        item for item in saved.aggregate_evidence if item.metric != "epa_phase_contribution"]}))
    child = app.follow_up(legacy_id, "Which phase accounted for the EPA change?")
    assert child.run.parent_investigation_id == legacy_id
    assert any(item.metric == "epa_phase_contribution" for item in child.aggregate_evidence)


@pytest.mark.parametrize("sport,identity", [("nfl", "posteam"), ("nba", "team_abbreviation"),
                                          ("soccer", "team_id"), ("cfb", "team_id")])
def test_scoped_discovery_aggregation_and_isolation(tmp_path, monkeypatch, sport, identity):
    from sports_analyst.analysis.scoped_data import ScopedData
    from sports_analyst.datasets.nfl import sha256_file

    path = tmp_path / "source.parquet"
    frame = pl.DataFrame({identity: ["A", "A", "OTHER"], "game_date": ["2025-01-01", "2025-01-02", "2025-01-01"],
                          "yards": [10., None, 999.], "week": [1, 2, 1]})
    frame.write_parquet(path)
    source = manifest(2025, frame.columns).model_copy(update={"sport": sport, "local_path": str(path),
        "sha256": sha256_file(path), "competition": "eng.1" if sport == "soccer" else None})
    from sports_analyst.storage.persistence import LocalPersistenceBackend

    app = SimpleNamespace(settings=Settings(_env_file=None, data_dir=tmp_path),
        store=SimpleNamespace(manifests=lambda **kwargs: [source], materialize_manifest=lambda item: item,
                              persistence=LocalPersistenceBackend()))
    request = AnalysisRequest(sport=sport, question="How is recorded yardage distributed across weeks?", scope={"team": "A",
        "season_type": "ALL", "comparison_design": "full_seasons", "baseline": {"season": 2024}, "comparison": {"season": 2025}})
    access = ScopedData(app, request, None)
    assert access.catalog()[0]["columns"] == frame.columns and "local_path" not in access.catalog()[0]
    payload = access.aggregate(source.manifest_id, "comparison", ["week"], [{"op": "sum", "field": "yards"}], [])
    assert payload["qualifying_rows"] == 2
    assert payload["rows"][0]["m0"] == 10 and payload["rows"][1]["m0"] is None
    with pytest.raises(ValueError, match="authorized dataset IDs"):
        access.aggregate("outside-catalog", "comparison", [], [{"op": "count"}], [])
    with pytest.raises(ValueError):
        access.aggregate(source.manifest_id, "comparison", [], [{"op": "sum", "field": "__import__('os')"}], [])
    outside = access.aggregate(source.manifest_id, "comparison", [], [{"op": "count"}],
                               [{"field": identity, "op": "eq", "value": "OTHER"}])
    assert outside["qualifying_rows"] == 0
    with pytest.raises(ValueError):
        access.aggregate(source.manifest_id, "wrong-window", [], [{"op": "count"}], [])
    if sport == "nfl":
        class Model(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        code = '''await tools.recordAnalysisPlan({objectives:["Distribute recorded yardage by week", "Explain coverage assignments"],
existing_evidence_ids:[],required_data:["yards", "week", "coverage_assignments"],calculations:["Sum yards by week"],limitations:[]});
const catalog = JSON.parse(await tools.inspectScopedDatasets({}));
const measured = JSON.parse(await tools.aggregateScopedData({dataset_id:catalog.datasets[0].dataset_id, window:"comparison",
group_by:["week"],measures:[{op:"sum",field:"yards"}],filters:[]}));
await tools.finishQuestionReview({evidence_by_objective:{"0":measured.evidence.map(e=>e.evidence_id)},
unresolved:{"1":"Coverage assignments are not recorded in the scoped catalog."}});
"done";'''
        model = Model(responses=[AIMessage(content="", tool_calls=[{"name": "eval", "id": "q", "args": {"code": code}}]),
                                 AIMessage(content="Review complete")])
        monkeypatch.setattr("sports_analyst.providers.get_provider", lambda name: SimpleNamespace(
            build=lambda settings: SimpleNamespace(chat_model=model, model_id="offline-planner")))
        result = SimpleNamespace(aggregate_evidence=[], executions=[], caveats=[])
        complete_calculations(Settings(_env_file=None, model_provider="ollama"), request.question, result, {}, access)
        assert len(result.aggregate_evidence) == 1 and result.aggregate_evidence[0].value == 10
        assert result.executions[-1].parameters["plan"]["required_data"] == ["yards", "week", "coverage_assignments"]
        assert any("Coverage assignments" in caveat for caveat in result.caveats)
