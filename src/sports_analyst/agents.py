from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, create_model

from sports_analyst.config import Settings, get_settings
from sports_analyst.models import AggregateEvidence, AnalysisWindow, Claim, ClaimType, PlayEvidence, stable_id
from sports_analyst.providers import get_provider

logger = logging.getLogger("sports_analyst.agents")
POSITIVE_IS_BETTER = {"epa_per_dropback", "success_rate", "cpoe", "explosive_pass_rate", "yards_per_play", "yards_after_catch"}
LOWER_IS_BETTER = {"sack_rate", "interception_rate"}


class SynthesisDraft(BaseModel):
    summary: str = Field(min_length=1, max_length=2_500)
    claims: list[Claim] = Field(min_length=1, max_length=12)


def _citation_ledger(
    aggregate: list[AggregateEvidence], plays: list[PlayEvidence]
) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    ledger: dict[str, str] = {}
    aggregate_payload: list[dict[str, Any]] = []
    play_payload: list[dict[str, Any]] = []
    for index, item in enumerate(aggregate, start=1):
        alias = f"E{index}"
        ledger[alias] = item.evidence_id
        payload = item.model_dump(mode="json", exclude={"evidence_id"})
        aggregate_payload.append({"citation_key": alias, **payload})
    for index, item in enumerate(plays, start=1):
        alias = f"P{index}"
        ledger[alias] = item.evidence_id
        payload = item.model_dump(mode="json", exclude={"evidence_id"})
        play_payload.append({"citation_key": alias, **payload})
    return ledger, aggregate_payload, play_payload


def _citation_response_model(valid_aliases: list[str]) -> type[BaseModel]:
    if not valid_aliases:
        raise ValueError("citation schema requires at least one evidence alias")
    citation_key = Literal.__getitem__(tuple(valid_aliases))
    claim_model = create_model(
        "CitationClaimDraft",
        claim_type=(ClaimType, ...),
        statement=(str, Field(min_length=1, max_length=1_500)),
        evidence_refs=(list[citation_key], Field(min_length=1)),
        confidence=(Literal["low", "medium", "high"], "medium"),
    )
    return create_model(
        "CitationSynthesisDraft",
        summary=(str, Field(min_length=1, max_length=2_500)),
        claims=(list[claim_model], Field(min_length=1, max_length=12)),
    )


def _resolve_citation_draft(draft: BaseModel, ledger: dict[str, str]) -> SynthesisDraft:
    payload = draft.model_dump()
    claims = []
    for item in payload["claims"]:
        aliases = list(dict.fromkeys(item.pop("evidence_refs")))
        missing = [alias for alias in aliases if alias not in ledger]
        if missing:
            raise ValueError(f"model cited unknown evidence aliases: {missing}")
        evidence_ids = [ledger[alias] for alias in aliases]
        claims.append(
            Claim(
                claim_id=stable_id("claim", {"statement": item["statement"], "evidence_ids": evidence_ids}),
                evidence_ids=evidence_ids,
                **item,
            )
        )
    return SynthesisDraft(summary=payload["summary"], claims=claims)


def _is_citation_error(error: Exception) -> bool:
    if isinstance(error, ValidationError):
        return any("evidence_refs" in validation_error["loc"] for validation_error in error.errors())
    message = str(error).lower()
    return "evidence_refs" in message or "evidence alias" in message or "citation_key" in message


def _fallback_synthesis(
    question: str,
    team: str,
    baseline: AnalysisWindow,
    comparison: AnalysisWindow,
    aggregate: list[AggregateEvidence],
    analysis_seasons: list[int] | None = None,
    conversation_context: list[dict[str, str]] | None = None,
) -> SynthesisDraft:
    metrics = [item for item in aggregate if item.baseline_value is not None and item.comparison_value is not None]
    primary = next((item for item in metrics if item.metric == "epa_per_dropback"), metrics[0] if metrics else None)
    if primary is None:
        raise ValueError("analysis produced no comparable metrics")
    change = float(primary.value or 0)
    if change == 0 or primary.metric not in POSITIVE_IS_BETTER | LOWER_IS_BETTER:
        direction = "was unchanged" if change == 0 else "changed"
    else:
        improved = change > 0 if primary.metric in POSITIVE_IS_BETTER else change < 0
        direction = "improved" if improved else "declined"
    baseline_label = f"{baseline.season} weeks {baseline.weeks[0]}–{baseline.weeks[1]}"
    comparison_label = f"{comparison.season} weeks {comparison.weeks[0]}–{comparison.weeks[1]}"
    range_context = (
        f" The analysis includes every full season from {analysis_seasons[0]} through {analysis_seasons[-1]}."
        if analysis_seasons
        else ""
    )
    summary = (
        f"{team}'s measured {primary.label.lower()} {direction} from {baseline_label} to {comparison_label}.{range_context} "
        "The findings below separate measured changes from football interpretation and link each statement to reproducible evidence."
    )
    if conversation_context:
        summary = f"Follow-up: {question} {summary}"
    claims = [
        Claim(
            claim_id=stable_id("claim", {"metric": primary.metric, "statement": direction}),
            claim_type=ClaimType.MEASURED,
            statement=(
                f"{primary.label} moved from {primary.baseline_value:.3f} to {primary.comparison_value:.3f}, "
                f"a change of {float(primary.value or 0):+.3f} across {primary.sample_size} comparison-window dropbacks."
            ),
            evidence_ids=[primary.evidence_id],
            confidence="high" if primary.sample_size >= 100 else "medium",
        )
    ]
    seasonal = [item for item in aggregate if item.metric == f"seasonal_{primary.metric}" and item.value is not None]
    if analysis_seasons and seasonal:
        seasonal.sort(key=lambda item: int(item.label.split(" ·", 1)[0]))
        trajectory = ", ".join(f"{item.label.split(' ·', 1)[0]}: {float(item.value):.3f}" for item in seasonal)
        claims.append(
            Claim(
                claim_id=stable_id("claim", {"metric": primary.metric, "seasons": analysis_seasons, "trajectory": trajectory}),
                claim_type=ClaimType.MEASURED,
                statement=f"Across the inclusive season range, {primary.label} measured {trajectory}.",
                evidence_ids=[item.evidence_id for item in seasonal],
                confidence="high" if min(item.sample_size for item in seasonal) >= 100 else "medium",
            )
        )
    supporting = sorted(
        [item for item in metrics if item.evidence_id != primary.evidence_id],
        key=lambda item: abs(float(item.value or 0)),
        reverse=True,
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
        question: str,
        team: str,
        baseline: AnalysisWindow,
        comparison: AnalysisWindow,
        aggregate: list[AggregateEvidence],
        plays: list[PlayEvidence],
        analysis_seasons: list[int] | None = None,
        conversation_context: list[dict[str, str]] | None = None,
    ) -> tuple[SynthesisDraft, str | None, bool]:
        fallback = _fallback_synthesis(question, team, baseline, comparison, aggregate, analysis_seasons, conversation_context)
        logger.debug(
            "synthesis_requested provider=%s aggregate_count=%d play_count=%d",
            self.settings.model_provider,
            len(aggregate),
            len(plays),
        )
        if self.settings.model_provider == "azure_foundry" and not self.settings.foundry_endpoint:
            logger.info("synthesis_fallback reason=model_not_configured provider=azure_foundry")
            return fallback, None, True
        try:
            from deepagents import create_deep_agent
            from deepagents.backends import StateBackend
            from langchain.tools import tool

            resolved = get_provider(self.settings.model_provider).build(self.settings)
            ledger, aggregate_payload, play_payload = _citation_ledger(aggregate, plays)
            logger.debug(
                "citation_ledger_created aggregate_aliases=%d play_aliases=%d",
                len(aggregate_payload),
                len(play_payload),
            )
            response_model = _citation_response_model(list(ledger))
            allowed_citations = ", ".join(ledger)

            @tool
            def inspect_aggregate_evidence() -> str:
                """Return all validated aggregate findings available for this investigation."""
                return json.dumps(aggregate_payload, indent=2, default=str)

            @tool
            def inspect_representative_plays() -> str:
                """Return source play examples and counterexamples selected by deterministic tools."""
                return json.dumps(play_payload, indent=2, default=str)

            tools: list[Any] = [inspect_aggregate_evidence, inspect_representative_plays]
            common = (
                "Use only the read-only evidence tools. Cite evidence_refs using only the exact citation_key values returned by those "
                f"tools. The only valid citation keys for this run are: {allowed_citations}. Numerical claims must be measured; football "
                "explanations must be interpretation claims. Do not claim causality or invent players, schemes, injuries, citation keys, "
                "or evidence IDs."
            )
            if analysis_seasons:
                common += (
                    f" This is an inclusive full-season range containing {analysis_seasons}; discuss the season-by-season trajectory, "
                    "not only the first and final seasons. Endpoint diagnostics should be identified as endpoint comparisons."
                )
            if conversation_context:
                common += (
                    " This is a follow-up in an existing investigation thread. Use the prior conversation only as context, answer the "
                    "new question directly, and ground all new claims in this run's evidence. Prior conversation: "
                    f"{json.dumps(conversation_context, default=str)}"
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
                    f"You coordinate an NFL analysis for {team}, comparing {baseline.model_dump()} with {comparison.model_dump()}. "
                    "Delegate diagnosis and review. Produce concise analyst-style findings grounded in evidence. " + common
                ),
                response_format=response_model,
                backend=StateBackend(),
                name="open-sports-analyst",
            )

            def invoke(prompt: str) -> BaseModel:
                response = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
                structured = response.get("structured_response")
                return structured if isinstance(structured, response_model) else response_model.model_validate(structured)

            try:
                logger.info("model_synthesis_started model_id=%s citation_aliases=%d", resolved.model_id, len(ledger))
                aliased_draft = invoke(
                    f"The user's analytical question is {json.dumps(question)}. Synthesize and verify an answer that directly "
                    "addresses that question. Use evidence_refs with exact citation keys from the tools."
                )
            except Exception as citation_error:
                if not _is_citation_error(citation_error):
                    raise
                logger.warning(
                    "model_synthesis_citation_retry model_id=%s error_type=%s",
                    resolved.model_id,
                    type(citation_error).__name__,
                )
                aliased_draft = invoke(
                    f"Repair the prior synthesis while directly answering {json.dumps(question)}. Re-inspect the evidence tools and "
                    "use only these exact evidence_refs: "
                    f"{allowed_citations}. Do not write or infer canonical evidence IDs."
                )
            resolved_draft = _resolve_citation_draft(aliased_draft, ledger)
            logger.info("model_synthesis_completed model_id=%s claims=%d", resolved.model_id, len(resolved_draft.claims))
            return resolved_draft, resolved.model_id, False
        except Exception as error:
            logger.warning("model_synthesis_fallback error_type=%s", type(error).__name__)
            return fallback, None, True
