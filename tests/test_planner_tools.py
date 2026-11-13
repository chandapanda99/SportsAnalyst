"""Planner guidance: data dictionary, field profiles, sport-analysis re-runs, sandbox tier and follow-up state."""
import json
from types import SimpleNamespace

import polars as pl
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from test_nfl_plugin import manifest

from sports_analyst.analysis.agents import _synthesis_mode
from sports_analyst.analysis.calculations import complete_calculations, conversation_brief, evidence_digest
from sports_analyst.analysis.research import dictionary, sandbox
from sports_analyst.analysis.scoped_data import ScopedData
from sports_analyst.analysis.sport_runs import SportRuns
from sports_analyst.config import Settings
from sports_analyst.models import (
    AggregateEvidence,
    AnalysisOptions,
    AnalysisRequest,
    MetricOption,
    PlayEvidence,
    SplitDimensionOption,
    ToolDefinition,
)


class Model(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def offline(monkeypatch, *codes):
    model = Model(responses=[AIMessage(content="", tool_calls=[{"name": "eval", "id": f"c{i}", "args": {"code": code}}])
                             for i, code in enumerate(codes)])
    monkeypatch.setattr("sports_analyst.providers.get_provider", lambda name: SimpleNamespace(
        build=lambda settings: SimpleNamespace(chat_model=model, model_id="offline-planner")))
    return model


def evidence(evidence_id, metric="epa_per_play", value=0.1):
    return AggregateEvidence(evidence_id=evidence_id, metric=metric, label=f"{metric} change", value=value,
                             baseline_value=0.0, comparison_value=value, unit="per play", sample_size=300,
                             row_set_sha256="x", dataset_manifest_ids=["m"], tool_execution_id="execution-root")


@pytest.fixture
def scoped(tmp_path):
    from sports_analyst.datasets.nfl import sha256_file
    from sports_analyst.storage.persistence import LocalPersistenceBackend

    path = tmp_path / "pbp.parquet"
    frame = pl.DataFrame({"posteam": ["CHI"] * 6 + ["GB"], "season_type": ["REG"] * 7, "week": [1, 1, 2, 2, 3, 3, 1],
                          "down": [1, 3, 3, 2, 3, None, 3], "play_type": ["pass", "run", "pass", "pass", "run", "punt", "pass"],
                          "yards_gained": [5., 2., 12., -3., 1., 0., 99.]})
    frame.write_parquet(path)
    source = manifest(2025, frame.columns).model_copy(update={"local_path": str(path), "sha256": sha256_file(path)})
    app = SimpleNamespace(settings=Settings(_env_file=None, data_dir=tmp_path),
        store=SimpleNamespace(manifests=lambda **kwargs: [source], materialize_manifest=lambda item: item,
                              persistence=LocalPersistenceBackend()))
    request = AnalysisRequest(sport="nfl", question="How did they do on third down?", analysis_domain="offense",
        scope={"team": "CHI", "comparison_design": "week_ranges", "baseline": {"season": 2024}, "comparison": {"season": 2025}})
    return ScopedData(app, request, None), source


def test_dictionary_curates_infers_and_searches(scoped):
    access, source = scoped
    down = dictionary.describe("nfl", "play_by_play", "down")
    assert down["source"] == "curated" and down["timing"] == "context"
    assert dictionary.describe("nfl", "play_by_play", "epa")["unit"] == "expected_points"
    assert dictionary.describe("cfb", "team_stats", "rushing_yards")["unit"] == "yards"
    assert dictionary.describe("nba", "box", "offensive_rebound_rate")["source"] == "inferred_from_name"
    assert dictionary.describe("nfl", "play_by_play", "unexplained_column") is None
    matches = dictionary.search(access.manifests, "third down")
    assert matches[0]["field"] == "down" and matches[0]["dataset_ids"] == [source.manifest_id]
    with pytest.raises(ValueError):
        dictionary.search(access.manifests, "  ")


def test_catalog_field_values_and_extract_stay_subject_scoped(scoped):
    access, source = scoped
    entry = access.catalog()[0]
    assert entry["subject_fields"] == ["posteam"] and entry["windows"] == ["comparison"]
    profile = access.field_values(source.manifest_id, "play_type", "comparison")
    assert profile["rows"] == 6 and {row["value"] for row in profile["top_values"]} == {"pass", "run", "punt"}
    assert profile["definition"]["source"] == "curated"
    extract = access.extract(source.manifest_id, "comparison", ["down", "yards_gained"],
                             [{"field": "play_type", "op": "ne", "value": "punt"}])
    assert len(extract["rows"]) == 5 and 99. not in [row["yards_gained"] for row in extract["rows"]]
    with pytest.raises(ValueError, match="season"):
        access.field_values(source.manifest_id, "down", "baseline")
    with pytest.raises(ValueError, match="1-12 distinct"):
        access.extract(source.manifest_id, "comparison", ["not_a_field"], [])


def test_sandbox_is_isolated_reproducible_and_checked():
    extract = {"rows": [{"y": 1}, {"y": 2}, {"y": 10}]}
    outputs = [{"name": "median_yards", "label": "Median yards", "unit": "yards"}]
    checked = sandbox.run("return {median_yards: median(values('y'))};", outputs, extract)
    assert checked["values"] == {"median_yards": 2} and checked["rows"] == 3 and len(checked["code_sha256"]) == 64
    refusals = {
        "return {other: 1};": "must match",
        "return {median_yards: 1 / 0};": "finite",
        "return {median_yards: Math.random()};": "reproducible",
        "while (true) {}": "failed",
        "return {median_yards: fetch('https://example.com')};": "failed",
        "return {median_yards: typeof require === 'undefined' ? null : 1};": "finite",
    }
    for code, message in refusals.items():
        with pytest.raises(ValueError, match=message):
            sandbox.run(code, outputs, extract, timeout=0.5)
    with pytest.raises(ValueError, match="snake_case"):
        sandbox.run("return {};", [{"name": "Bad Name", "label": "x", "unit": "y"}], extract)


def test_planner_orients_profiles_and_registers_labelled_sandbox_evidence(monkeypatch, scoped):
    access, source = scoped
    existing = [evidence("evidence-root", value=0.2), evidence("evidence-split", "decomposition_down")]
    code = f'''const plan = await tools.recordAnalysisPlan({{objectives:["Median third-down gain"],existing_evidence_ids:[],
required_data:["down","yards_gained"],calculations:["median"],limitations:[]}});
const found = JSON.parse(await tools.searchFields({{concept:"third down"}}));
if (found.matches[0].field !== "down") throw Error("search");
const values = JSON.parse(await tools.inspectFieldValues({{dataset_id:"{source.manifest_id}",field:"down",window:"comparison"}}));
if (!values.top_values.length) throw Error("profile");
const bad = JSON.parse(await tools.finishQuestionReview({{evidence_by_objective:{{"1":["evidence-root"]}},unresolved:{{}}}}));
if (!bad.error.includes("Missing: ['0']")) throw Error(bad.error);
const run = JSON.parse(await tools.computeOnExtract({{objective:"Median third-down gain",dataset_id:"{source.manifest_id}",
window:"comparison",fields:["yards_gained"],filters:[{{field:"down",op:"eq",value:3}}],
code:"return {{median_gain: median(values('yards_gained'))}};",
outputs:[{{name:"median_gain",label:"Median third-down gain",unit:"yards"}}]}}));
await tools.finishQuestionReview({{evidence_by_objective:{{"0":[run.evidence[0].evidence_id]}},unresolved:{{}}}});
"done";'''
    model = offline(monkeypatch, code)
    result = SimpleNamespace(aggregate_evidence=list(existing), executions=[], caveats=[])
    complete_calculations(Settings(_env_file=None, model_provider="ollama"), "Median third-down gain?", result, {}, access)
    computed = [item for item in result.aggregate_evidence if item.metric == "sandbox_computation"]
    assert len(computed) == 1 and computed[0].value == 2.  # third downs: 2, 12, 1 yards
    assert computed[0].context["validation"] == "sandbox_reexecuted" and "Sandbox-computed" in computed[0].caveats[0]
    assert any(item.tool == "compute_on_extract" for item in result.executions)
    content = next(m["content"] for m in result.executions[-1].parameters["messages"] if "Host orientation" in str(m["content"]))
    orientation = json.loads(content[content.index("{"):])
    assert model.responses
    assert {row["metric"] for row in orientation["existing_evidence"]} == {"epa_per_play", "decomposition_down"}
    assert orientation["data_map"]["tables"][0]["subject_fields"] == ["posteam"]


class FakeRuns:
    def __init__(self, outcome, scope_request=None):
        self.outcome, self.scope_request = outcome, scope_request
        self.runs = []
        self.request = SimpleNamespace(analysis_domain="offense")

    def describe(self):
        return {"analysis_domains": [{"value": "defense"}], "runs_remaining": 3 - len(self.runs)}

    def run(self, analysis_domain, metrics, splits):
        self.runs.append({"arguments": {"analysis_domain": analysis_domain, "metrics": metrics, "splits": splits}})
        return self.outcome

    def scope_change(self, *args):
        if self.scope_request is None:
            raise ValueError("Seasons [2019] are not installed")
        return self.scope_request


def test_planner_reuses_sport_analyses_and_their_plays(monkeypatch):
    play = PlayEvidence(evidence_id="play-new", season=2025, game_id="g1", play_id=1, team="CHI", description="Third-down sack",
                        dataset_manifest_id="m", evidence_role="supports_change", window="comparison")
    outcome = SimpleNamespace(aggregate_evidence=[evidence("evidence-root"), evidence("evidence-third", "decomposition_down", .3)],
                              play_evidence=[play], executions=[], caveats=["Small third-down sample."])
    code = '''await tools.recordAnalysisPlan({objectives:["Third-down change"],existing_evidence_ids:["evidence-root"],
required_data:["down split"],calculations:[],limitations:[]});
const options = JSON.parse(await tools.inspectSportAnalyses({}));
const run = JSON.parse(await tools.runSportAnalysis({analysis_domain:"offense",metrics:[],splits:["down"],purpose:"Third downs"}));
if (run.new_evidence !== 1 || run.new_plays[0].evidence_id !== "play-new") throw Error(JSON.stringify(run));
await tools.finishQuestionReview({evidence_by_objective:{"0":["evidence-third"]},unresolved:{}}); "done";'''
    offline(monkeypatch, code)
    runs = FakeRuns(outcome)
    result = SimpleNamespace(aggregate_evidence=[evidence("evidence-root")], play_evidence=[], executions=[], caveats=[])
    complete_calculations(Settings(_env_file=None, model_provider="ollama"), "Third downs?", result, {}, sport_runs=runs)
    added = next(item for item in result.aggregate_evidence if item.evidence_id == "evidence-third")
    assert added.context["sport_analysis_run"]["splits"] == ["down"]
    assert [item.evidence_id for item in result.aggregate_evidence].count("evidence-root") == 1
    assert result.play_evidence == [play] and any("third-down sample" in caveat for caveat in result.caveats)
    assert result.executions[-1].parameters["sport_analysis_runs"] == [runs.runs[0]["arguments"]]


def test_follow_up_scope_change_ends_planning_with_validated_request(monkeypatch):
    request = AnalysisRequest(sport="nfl", question="What about 2022?", analysis_domain="offense",
        scope={"team": "CHI", "comparison_design": "week_ranges", "baseline": {"season": 2022}, "comparison": {"season": 2025}})
    code = '''const refused = JSON.parse(await tools.proposeScopeChange({reason:"Needs 2019",baseline_season:2019}));
if (!refused.error.includes("not installed")) throw Error("expected refusal");
await tools.proposeScopeChange({reason:"The question asks about 2022",baseline_season:2022}); "rescoped";'''
    offline(monkeypatch, code, code)
    runs = FakeRuns(None)
    result = SimpleNamespace(aggregate_evidence=[evidence("evidence-root")], play_evidence=[], executions=[], caveats=[])
    complete_calculations(Settings(_env_file=None, model_provider="ollama"), "What about 2022?", result, {},
                          sport_runs=runs, allow_scope_change=True)
    assert result.executions[-1].tool == "complete_calculations_failed"  # refusal, then the model stopped without a review
    runs.scope_request = request
    check = 'if (!refused.error.includes("not installed")) throw Error("expected refusal");'
    offline(monkeypatch, code.replace("2019", "2022").replace(check, ""))
    result = SimpleNamespace(aggregate_evidence=[evidence("evidence-root")], play_evidence=[], executions=[], caveats=[], scope_change=None)
    complete_calculations(Settings(_env_file=None, model_provider="ollama"), "What about 2022?", result, {},
                          sport_runs=runs, allow_scope_change=True)
    assert result.scope_change["request"]["scope"]["baseline"]["season"] == 2022
    assert result.executions[-1].parameters["planning_turns"][0]["stop_reason"] == "scope_change"


def sport_app(available=(2023, 2024, 2025)):
    options = AnalysisOptions(sport="nfl", teams=[], available_seasons=list(available), syncable_seasons=[],
        metrics=[MetricOption(value="epa_per_play", label="EPA/play", category="efficiency", description="", analysis_domain="offense"),
                 MetricOption(value="epa_per_play_allowed", label="EPA/play allowed", category="efficiency", description="",
                              analysis_domain="defense")],
        default_metrics=[], analysis_domains=[{"value": "offense", "subject_type": "team"}, {"value": "defense", "subject_type": "team"},
                                              {"value": "quarterback", "subject_type": "player"}],
        split_dimensions=[SplitDimensionOption(value="down", label="Down", description="")], comparison_windows=[])
    calls = []
    plugin = SimpleNamespace(tools=lambda: [ToolDefinition(name="compare_time_windows", description="Compare windows")],
                             analyze=lambda request, *data: calls.append(request) or SimpleNamespace(aggregate_evidence=[]))
    app = SimpleNamespace(_sport=lambda sport: (None, plugin), analysis_options=lambda sport, competition: options)
    return app, calls


def test_sport_runs_validate_settings_and_scope_changes():
    app, calls = sport_app()
    request = AnalysisRequest(sport="nfl", question="How did the offense change?", analysis_domain="offense",
        scope={"team": "CHI", "comparison_design": "full_seasons", "baseline": {"season": 2024}, "comparison": {"season": 2025}})
    runs = SportRuns(app, request, "investigation-x", loaded={"datasets": {}, "manifests": {}, "supplemental": {},
                                                              "supplemental_manifests": {}})
    described = runs.describe()
    assert [d["value"] for d in described["analysis_domains"]] == ["offense", "defense"]
    runs._loaded["defense"] = runs._loaded["offense"]
    runs.run("defense", ["epa_per_play_allowed"], ["down"])
    assert calls[-1].analysis_domain == "defense" and calls[-1].scope == request.scope
    for arguments, message in ((("quarterback", [], []), "Unsupported analysis_domain"),
                               (("offense", ["epa_per_play_allowed"], []), "Unknown"),
                               (("offense", [], ["weather"]), "splits"),
                               (("defense", ["epa_per_play_allowed"], ["down"]), "already run"),
                               (("offense", [], []), "report's own")):
        with pytest.raises(ValueError, match=message):
            runs.run(*arguments)
    changed = runs.scope_change(baseline_season=2023, season_type="post")
    assert changed.scope.included_seasons == [2023, 2024, 2025] and changed.scope.season_type == "POST"
    assert runs.scope_change(analysis_domain="defense").analysis_domain == "defense"
    with pytest.raises(ValueError, match="not installed"):
        runs.scope_change(baseline_season=2019)
    with pytest.raises(ValueError, match="report's own"):
        runs.scope_change(baseline_season=2024)


def test_sport_runs_repeat_the_real_nfl_analysis_for_another_domain(tmp_path, pbp_pair):
    from sports_analyst.application.service import AnalystApplication

    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, foundry_endpoint=""))
    for season, frame in pbp_pair.items():
        path = tmp_path / f"fixture-{season}.parquet"
        frame.write_parquet(path)
        app.store.save_manifest(app.connector.register_local(path, season))
    request = AnalysisRequest(question="How did the passing game change?", analysis_domain="passing",
        scope={"team": "KC", "baseline": {"season": 2024}, "comparison": {"season": 2025}})
    runs = SportRuns(app, request, "investigation-runs")
    described = runs.describe()
    assert {d["value"] for d in described["analysis_domains"]} >= {"passing", "rushing", "defense"}
    assert "down" in {s["value"] for s in described["splits"]}
    # The fixture records dropbacks only, so the run varies the split and metrics, not the domain.
    outcome = runs.run("passing", ["epa_per_dropback", "success_rate"], ["down"])
    assert outcome.aggregate_evidence and any("down" in json.dumps(item.context) or "down" in item.metric
                                              for item in outcome.aggregate_evidence)
    with pytest.raises(ValueError, match="30 qualifying rushing"):
        runs.run("rushing", [], [])
    assert runs.scope_change(analysis_domain="defense").analysis_domain == "defense"


def test_structured_thread_state_and_follow_up_synthesis_mode():
    from sports_analyst.analysis.thread_state import turn_state

    plan = {"objectives": ["Pass defense change"]}
    bundle = SimpleNamespace(
        run=SimpleNamespace(investigation_id="investigation-1", question="Did the pass defense improve?",
            scope=AnalysisRequest(question="xyz", scope={"team": "CHI", "baseline": {"season": 2024},
                                                         "comparison": {"season": 2025}}).scope,
            analysis_domain="defense", metrics=[], splits=[]),
        executions=[SimpleNamespace(tool="complete_calculations", parameters={
            "plan": plan, "question_review": {"evidence_by_objective": {"0": ["evidence-a"]}, "unresolved": {}}})],
        play_evidence=[PlayEvidence(evidence_id="play-a", season=2025, game_id="g7", play_id=3, team="CHI",
                                    description="Interception", dataset_manifest_id="m")],
        claims=[SimpleNamespace(statement="EPA allowed fell.", evidence_ids=["evidence-a", "play-a"])],
        aggregate_evidence=[evidence("evidence-a")], summary="The pass defense improved.")
    state = turn_state(bundle)
    assert state["objectives"][0]["evidence_ids"] == ["evidence-a"] and state["cited_games"] == ["2025:g7"]
    brief = conversation_brief([state, {"question": "Why?", "summary": "Because."}])
    assert "evidence-a" in brief and "2025:g7" in brief and '"answer": "Because."' in brief
    assert evidence_digest([evidence("evidence-a")])[0]["records"] == 1
    assert _synthesis_mode("Why?", 3, [{"question": "q"}], "new_measurement") == "reviewed"
    assert _synthesis_mode("Why?", 3, [{"question": "q"}], "explain_existing") == "direct"
