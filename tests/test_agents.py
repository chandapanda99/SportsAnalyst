import json
from types import SimpleNamespace

import pytest

from sports_analyst.analysis.agents import (
    EvidenceBoundAgent,
    SynthesisDraft,
    _citation_ledger,
    _citation_response_model,
    _formulate_user_message,
    _resolve_citation_draft,
)
from sports_analyst.analysis.instructions import PROMPT_VERSION, evidence_brief
from sports_analyst.config import Settings
from sports_analyst.models import AggregateEvidence, AnalysisWindow, Claim, ClaimType, DatasetManifest, MetricDefinition, PlayEvidence


def aggregate_evidence() -> AggregateEvidence:
    return AggregateEvidence(
        evidence_id="evidence-canonical-aggregate",
        metric="epa_per_dropback",
        label="EPA per dropback",
        value=0.1,
        baseline_value=0.0,
        comparison_value=0.1,
        sample_size=100,
        row_set_sha256="rows",
        dataset_manifest_ids=["dataset-1"],
        tool_execution_id="execution-1",
    )


def play_evidence() -> PlayEvidence:
    return PlayEvidence(
        evidence_id="evidence-canonical-play",
        season=2025,
        game_id="2025_01_KC_BUF",
        play_id=42,
        team="KC",
        description="Completed pass for 20 yards.",
        dataset_manifest_id="dataset-1",
    )


def test_citation_ledger_hides_canonical_ids_and_resolves_aliases() -> None:
    ledger, aggregates, plays = _citation_ledger([aggregate_evidence()], [play_evidence()])
    assert ledger == {"E1": "evidence-canonical-aggregate", "P1": "evidence-canonical-play"}
    assert aggregates[0]["citation_key"] == "E1"
    assert plays[0]["citation_key"] == "P1"
    assert "evidence_id" not in aggregates[0]
    assert "evidence_id" not in plays[0]

    response_model = _citation_response_model(list(ledger))
    draft = response_model.model_validate(
        {
            "summary": "KC improved.",
            "claims": [
                {
                    "claim_type": "measured",
                    "statement": "EPA per dropback improved.",
                    "evidence_refs": ["E1"],
                    "confidence": "high",
                }
            ],
        }
    )
    resolved = _resolve_citation_draft(draft, ledger)
    assert resolved.claims[0].evidence_ids == ["evidence-canonical-aggregate"]






def test_chat_model_only_rewords_the_completed_analytical_summary() -> None:
    class Formatter:
        def __init__(self) -> None:
            self.messages = None
            self.config = None

        def invoke(self, messages, config=None):
            self.messages = messages
            self.config = config
            return {"message": "KC's efficiency improved, though the evidence remains descriptive."}

    class ChatModel:
        def __init__(self) -> None:
            self.formatter = Formatter()

        def with_structured_output(self, _schema):
            return self.formatter

    claim = Claim(
        claim_id="claim-1",
        claim_type=ClaimType.MEASURED,
        statement="EPA per dropback improved from 0.01 to 0.08.",
        evidence_ids=["evidence-1"],
        confidence="high",
    )
    draft = SynthesisDraft(summary="Analytical draft.", claims=[claim])
    model = ChatModel()

    message = _formulate_user_message(
        model,
        "Why did efficiency improve?",
        draft,
        "nfl",
        False,
        config={"run_name": "conversation-message"},
    )

    assert message.startswith("KC's efficiency improved")
    assert model.formatter.config == {"run_name": "conversation-message"}
    payload = model.formatter.messages[1]["content"]
    assert "Analytical draft." in payload
    assert "EPA per dropback improved from 0.01 to 0.08." in payload
    assert "evidence-1" not in payload
    assert Settings(_env_file=None, chat_model="writer-model").chat_model == "writer-model"
    instructions = model.formatter.messages[0]["content"]
    assert "measured-versus-interpretive" in instructions
    assert "partial sample into a full season" in instructions


@pytest.mark.parametrize("sport,domain,question,specific_rule", [
    ("nfl", "receiving", "Why did receiving improve despite fewer targets? Did separation improve?", "does not prove separation"),
    ("nba", "defense", "Does a better lineup rating prove this player improved defensive assignments?", "not isolated player impact"),
    ("soccer", "scoring", "Why did goals rise while xG fell? Does possession prove better pressing?", "same covered matches"),
])
def test_sport_analysis_contract_and_coverage_reach_every_agent(sport, domain, question, specific_rule, monkeypatch):
    """Exercise the real synthesis/tool boundary, without paid model calls."""
    import deepagents

    import sports_analyst.analysis.agents as agents

    primary = aggregate_evidence().model_copy(update={
        "unit": "rate", "sample_size": 8,
        "caveats": ["Baseline 100 observations; comparison 8. Missing values excluded."],
        "context": {"baseline_sample": 100, "comparison_sample": 8, "analytical_role": "primary_outcome"}})
    counter = primary.model_copy(update={"evidence_id": "counter", "metric": "counter_metric",
        "baseline_value": 0.5, "comparison_value": 0.4, "value": -0.1,
        "context": {"analytical_role": "counter_signal"}})
    missing = primary.model_copy(update={"evidence_id": "missing", "metric": "unavailable_metric",
        "baseline_value": None, "comparison_value": None, "value": None,
        "sample_size": 0, "caveats": ["Not recorded; must not be estimated."]})
    definition = MetricDefinition(value=primary.metric, label=primary.label, category=domain,
        description="Observed rate", formula="sum(value) / qualifying observations",
        qualifying_plays="Recorded observations only", interpretation="Descriptive association",
        limitations=["Not opponent-adjusted"])
    manifest = DatasetManifest(manifest_id="dataset-1", sport=sport, season=2025,
        source_url="https://example.com/source", sha256="hash", row_count=1000, columns=[],
        package_version="test", local_path="unused.parquet", coverage={"completed_matches": 4, "expected_matches": 10})
    brief = evidence_brief([primary, counter, missing], [definition], [manifest], {"sport": sport, "subject": {"type": "player"}})
    captured = {}

    def build_agent(**kwargs):
        captured.update(kwargs)
        class Agent:
            def invoke(self, _request, config):
                captured["config"] = config
                tool_map = {tool.name: tool for tool in kwargs["tools"]}
                context = json.loads(tool_map["inspect_analysis_context"].invoke({}))
                assert context["sources"][0]["coverage"]["completed_matches"] == 4
                assert context["metric_definitions"][0]["limitations"] == ["Not opponent-adjusted"]
                assert "counter_metric" in context["undefined_metrics"]
                evidence = json.loads(tool_map["inspect_aggregate_evidence"].invoke({}))
                assert evidence[0]["sample_size"] == 8
                assert evidence[0]["context"]["baseline_sample"] == 100
                assert evidence[1]["context"]["analytical_role"] == "counter_signal"
                assert evidence[2]["baseline_value"] is None and evidence[2]["sample_size"] == 0
                return {"structured_response": kwargs["response_format"].model_validate({
                    "summary": "The observed rate changed, but coverage and unequal samples limit interpretation.",
                    "claims": [{"claim_type": "measured", "statement": "The rate changed from 0.0 to 0.1.",
                                "evidence_refs": ["E1"], "confidence": "low"}]})}
        return Agent()

    monkeypatch.setattr(deepagents, "create_deep_agent", build_agent)
    model = object()
    monkeypatch.setattr(agents, "get_provider", lambda _: SimpleNamespace(
        build=lambda *_args, **_kwargs: SimpleNamespace(chat_model=model, model_id="analysis-model")))
    draft, model_id, fallback = EvidenceBoundAgent(Settings(_env_file=None, foundry_endpoint="test")).synthesize(
        question, "selected-player", AnalysisWindow(season=2024), AnalysisWindow(season=2025),
        [primary, counter, missing], [play_evidence()], analysis_seasons=[2024, 2025],
        sport=sport, analysis_domain=domain, analytical_context=brief)
    assert not fallback and model_id == "analysis-model"
    assert draft.claims[0].evidence_ids == [primary.evidence_id]
    assert captured["model"] is model
    for prompt in [captured["system_prompt"], *[item["system_prompt"] for item in captured.get("subagents", [])]]:
        assert specific_rule in prompt
        assert "Missing is not zero" in prompt
        assert "unequal samples" in prompt
        assert "Representative events illustrate" in prompt
        assert "intermediate seasons" in prompt.lower()
    assert "Verify every material sentence" in captured["system_prompt"]
    assert captured["config"]["metadata"]["prompt_version"] == PROMPT_VERSION
