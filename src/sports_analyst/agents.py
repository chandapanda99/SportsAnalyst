from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from sports_analyst.config import Settings, get_settings
from sports_analyst.models import AggregateEvidence, Claim, ClaimType, PlayEvidence, stable_id
from sports_analyst.providers import get_provider

logger = logging.getLogger("sports_analyst.agents")


class SynthesisDraft(BaseModel):
    summary: str = Field(min_length=1, max_length=2_500)
    claims: list[Claim] = Field(min_length=1, max_length=12)


def _fallback_synthesis(
    team: str,
    baseline_season: int,
    comparison_season: int,
    aggregate: list[AggregateEvidence],
) -> SynthesisDraft:
    metrics = [item for item in aggregate if item.baseline_value is not None and item.comparison_value is not None]
    epa = next((item for item in metrics if item.metric == "epa_per_dropback"), metrics[0] if metrics else None)
    if epa is None:
        raise ValueError("analysis produced no comparable metrics")
    direction = "improved" if float(epa.value or 0) > 0 else "declined"
    summary = (
        f"{team}'s measured passing efficiency {direction} from {baseline_season} to {comparison_season}. "
        "The findings below separate measured changes from football interpretation and link each statement to reproducible evidence."
    )
    claims = [
        Claim(
            claim_id=stable_id("claim", {"metric": epa.metric, "statement": direction}),
            claim_type=ClaimType.MEASURED,
            statement=(
                f"EPA per dropback moved from {epa.baseline_value:.3f} to {epa.comparison_value:.3f}, "
                f"a change of {float(epa.value or 0):+.3f} across {epa.sample_size} comparison-season dropbacks."
            ),
            evidence_ids=[epa.evidence_id],
            confidence="high" if epa.sample_size >= 100 else "medium",
        )
    ]
    supporting = sorted(
        [item for item in metrics if item.metric != "epa_per_dropback"], key=lambda item: abs(float(item.value or 0)), reverse=True
    )[:3]
    for item in supporting:
        claims.append(
            Claim(
                claim_id=stable_id("claim", {"metric": item.metric, "value": item.value}),
                claim_type=ClaimType.MEASURED,
                statement=f"{item.label} changed from {item.baseline_value:.3f} to {item.comparison_value:.3f}.",
                evidence_ids=[item.evidence_id],
                confidence="high" if item.sample_size >= 100 else "medium",
            )
        )
    decompositions = [item for item in aggregate if item.metric.endswith("_decomposition")][:3]
    if decompositions:
        claims.append(
            Claim(
                claim_id=stable_id("claim", {"interpretation": [item.evidence_id for item in decompositions]}),
                claim_type=ClaimType.INTERPRETATION,
                statement=(
                    "The strongest situational contributors suggest the shift was connected to how efficiently the offense handled "
                    "specific contexts, not merely how often those contexts occurred."
                ),
                evidence_ids=[item.evidence_id for item in decompositions],
                confidence="medium",
            )
        )
    return SynthesisDraft(summary=summary, claims=claims)


class EvidenceBoundAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def synthesize(
        self,
        team: str,
        baseline_season: int,
        comparison_season: int,
        aggregate: list[AggregateEvidence],
        plays: list[PlayEvidence],
    ) -> tuple[SynthesisDraft, str | None, bool]:
        fallback = _fallback_synthesis(team, baseline_season, comparison_season, aggregate)
        if self.settings.model_provider == "azure_foundry" and not self.settings.foundry_endpoint:
            return fallback, None, True
        try:
            from deepagents import create_deep_agent
            from deepagents.backends import StateBackend
            from langchain.tools import tool

            resolved = get_provider(self.settings.model_provider).build(self.settings)
            known = {item.evidence_id for item in aggregate} | {item.evidence_id for item in plays}

            @tool
            def inspect_aggregate_evidence() -> str:
                """Return all validated aggregate findings available for this investigation."""
                return json.dumps([item.model_dump(mode="json") for item in aggregate], indent=2, default=str)

            @tool
            def inspect_representative_plays() -> str:
                """Return source play examples and counterexamples selected by deterministic tools."""
                return json.dumps([item.model_dump(mode="json") for item in plays], indent=2, default=str)

            tools: list[Any] = [inspect_aggregate_evidence, inspect_representative_plays]
            common = (
                "Use only the read-only evidence tools. Every claim must cite returned evidence IDs. Numerical claims must be measured; "
                "football explanations must be interpretation claims. Do not claim causality or invent players, schemes, or injuries."
            )
            subagents = [
                {
                    "name": "efficiency-analyst",
                    "description": "Diagnoses passing efficiency changes.",
                    "system_prompt": common,
                    "tools": tools,
                    "model": resolved.chat_model,
                },
                {
                    "name": "situational-analyst",
                    "description": "Examines contextual split contributions.",
                    "system_prompt": common,
                    "tools": tools,
                    "model": resolved.chat_model,
                },
                {
                    "name": "evidence-reviewer",
                    "description": "Challenges claims and verifies citations.",
                    "system_prompt": common,
                    "tools": tools,
                    "model": resolved.chat_model,
                },
            ]
            agent = create_deep_agent(
                model=resolved.chat_model,
                tools=tools,
                subagents=subagents,
                system_prompt=(
                    f"You coordinate an NFL analysis for {team}, comparing {baseline_season} with {comparison_season}. "
                    "Delegate diagnosis and review. Produce concise analyst-style findings grounded in evidence. " + common
                ),
                response_format=SynthesisDraft,
                backend=StateBackend(),
                name="open-sports-analyst",
            )
            response = agent.invoke({"messages": [{"role": "user", "content": "Synthesize and verify this efficiency investigation."}]})
            draft = response.get("structured_response")
            draft = draft if isinstance(draft, SynthesisDraft) else SynthesisDraft.model_validate(draft)
            cited = {identifier for claim in draft.claims for identifier in claim.evidence_ids}
            if not cited <= known:
                raise ValueError(f"model cited unknown evidence: {sorted(cited - known)}")
            return draft, resolved.model_id, False
        except Exception as error:
            logger.warning("model synthesis unavailable; using deterministic report: %s", " ".join(str(error).split())[:400])
            return fallback, None, True
