import pytest
from pydantic import ValidationError

from sports_analyst.agents import (
    _citation_ledger,
    _citation_response_model,
    _is_citation_error,
    _resolve_citation_draft,
)
from sports_analyst.models import AggregateEvidence, PlayEvidence


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


def test_citation_schema_rejects_unavailable_aliases() -> None:
    response_model = _citation_response_model(["E1", "P1"])
    with pytest.raises(ValidationError) as caught:
        response_model.model_validate(
            {
                "summary": "Invalid citation.",
                "claims": [
                    {
                        "claim_type": "measured",
                        "statement": "Unsupported claim.",
                        "evidence_refs": ["E99"],
                        "confidence": "low",
                    }
                ],
            }
        )
    assert _is_citation_error(caught.value)
