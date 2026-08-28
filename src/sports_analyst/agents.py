from __future__ import annotations

import json
import logging
from collections.abc import Callable
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from sports_analyst.config import Settings, get_settings
from sports_analyst.models import AggregateEvidence, AnalysisWindow, Claim, ClaimType, PlayEvidence, stable_id
from sports_analyst.providers import get_provider

logger = logging.getLogger("sports_analyst.agents")
POSITIVE_IS_BETTER = {
    "epa_per_dropback",
    "success_rate",
    "cpoe",
    "explosive_pass_rate",
    "yards_per_play",
    "yards_after_catch",
    "epa_per_rush",
    "rush_success_rate",
    "yards_per_rush",
    "explosive_run_rate",
    "rush_first_down_rate",
    "epa_per_play",
    "overall_success_rate",
    "overall_yards_per_play",
}
LOWER_IS_BETTER = {"sack_rate", "interception_rate", "stuff_rate", "turnover_rate"}
POSITIVE_IS_BETTER.update(
    {
        "points_per_game",
        "offensive_rating",
        "win_pct",
        "field_goal_pct",
        "three_point_pct",
        "effective_fg_pct",
        "true_shooting_pct",
        "assists_per_game",
        "assist_turnover_ratio",
        "rebounds_per_game",
        "offensive_rebounds_per_game",
        "plus_minus_per_game",
        "lineup_net_rating",
        "lineup_off_rating",
    }
)
LOWER_IS_BETTER.update({"defensive_rating", "turnovers_per_game", "lineup_def_rating"})


def _sample_confidence(sample_size: int) -> str:
    if sample_size < 10:
        return "low"
    return "high" if sample_size >= 100 else "medium"

ANALYST_VOICE_GUIDE = """
Write like an experienced NFL analyst briefing an informed reader, not like a model summarizing a table.

- Lead with the answer and the central football story. Do not open with methodology, generic scene-setting, or a list of metrics.
- Prioritize the two or three findings that best answer the question. Treat the remaining measurements as support, context, or
  counterevidence instead of reciting every available result.
- Connect related measurements in natural prose and explain their football meaning. For example, distinguish changes in play mix from
  changes in execution, and separate sustained movement from a result driven by a few games.
- Use precise football language where the evidence supports it, but translate specialized metrics into practical implications. Avoid
  buzzwords, empty intensifiers, canned phrases, and repetitive sentence templates.
- Vary sentence length and transitions so the writing reads naturally. Prefer direct sentences and active voice. Do not refer to
  yourself, the model, tools, prompts, evidence keys, or the process of generating the report.
- Keep the summary to a compact thesis followed by the most important qualification. Each finding should make one coherent point and
  should not repeat the summary verbatim.
- State measured results plainly. Use interpretation claims to explain what the pattern is consistent with, while making uncertainty
  proportional to sample size and evidence quality. Never turn observational evidence into proven causality.
- Mention counterexamples, noisy samples, endpoint-only comparisons, or conflicting indicators when they materially change the read.
""".strip()

NBA_ANALYST_VOICE_GUIDE = ANALYST_VOICE_GUIDE.replace("NFL", "NBA").replace("football", "basketball").replace("formations", "lineups")


class SynthesisDraft(BaseModel):
    summary: str = Field(min_length=1, max_length=2_500)
    claims: list[Claim] = Field(min_length=1, max_length=12)


def _synthesis_mode(
    question: str,
    aggregate_count: int,
    conversation_context: list[dict[str, str]] | None = None,
) -> Literal["direct", "reviewed", "full"]:
    if conversation_context:
        return "direct"
    normalized = question.lower()
    complex_terms = {"why", "explain", "personnel", "lineup", "injur", "formation", "opponent", "decompos", "context", "pressure"}
    if aggregate_count >= 28 or any(term in normalized for term in complex_terms):
        return "full"
    return "reviewed"


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
    allowed_aliases = frozenset(valid_aliases)

    class CitationClaimDraft(BaseModel):
        claim_type: ClaimType
        statement: str = Field(min_length=1, max_length=1_500)
        evidence_refs: list[str] = Field(min_length=1)
        confidence: Literal["low", "medium", "high"] = "medium"

        @field_validator("evidence_refs")
        @classmethod
        def validate_evidence_refs(cls, references: list[str]) -> list[str]:
            unknown = [reference for reference in references if reference not in allowed_aliases]
            if unknown:
                raise ValueError(f"unknown evidence aliases: {unknown}")
            return references

    class CitationSynthesisDraft(BaseModel):
        summary: str = Field(min_length=1, max_length=2_500)
        claims: list[CitationClaimDraft] = Field(min_length=1, max_length=12)

    return CitationSynthesisDraft


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
    analysis_domain: str = "passing",
    sport: str = "nfl",
) -> SynthesisDraft:
    metrics = [item for item in aggregate if item.baseline_value is not None and item.comparison_value is not None]
    preferred_metric = {
        "passing": "epa_per_dropback",
        "rushing": "epa_per_rush",
        "offense": "epa_per_play",
        "defense": "defensive_rating",
        "scoring": "points_per_game",
        "shooting": "effective_fg_pct",
        "playmaking": "assists_per_game",
        "rebounding": "rebounds_per_game",
        "turnovers": "turnovers_per_game",
        "usage": "minutes_per_game",
        "impact": "plus_minus_per_game",
        "lineups": "lineup_net_rating",
    }.get(analysis_domain, metrics[0].metric if metrics else "")
    primary = next((item for item in metrics if item.metric == preferred_metric), metrics[0] if metrics else None)
    if primary is None:
        raise ValueError("analysis produced no comparable metrics")
    change = float(primary.value or 0)
    if change == 0 or primary.metric not in POSITIVE_IS_BETTER | LOWER_IS_BETTER:
        direction = "was unchanged" if change == 0 else "changed"
    else:
        improved = change > 0 if primary.metric in POSITIVE_IS_BETTER else change < 0
        direction = "improved" if improved else "declined"
    baseline_label = (
        f"{baseline.season} {baseline.segment.replace('_', ' ')}"
        if baseline.segment
        else f"{baseline.season} weeks {baseline.weeks[0]}–{baseline.weeks[1]}"
    )
    comparison_label = (
        f"{comparison.season} {comparison.segment.replace('_', ' ')}"
        if comparison.segment
        else f"{comparison.season} weeks {comparison.weeks[0]}–{comparison.weeks[1]}"
    )
    range_context = (
        f" The analysis includes every full season from {analysis_seasons[0]} through {analysis_seasons[-1]}." if analysis_seasons else ""
    )
    summary = (
        f"{team}'s measured {primary.label.lower()} {direction} from {baseline_label} to {comparison_label}.{range_context} "
        f"The findings below separate measured changes from {('basketball' if sport == 'nba' else 'football')} interpretation "
        "and link each statement to reproducible evidence."
    )
    if conversation_context:
        summary = f"Follow-up: {question} {summary}"
    claims = [
        Claim(
            claim_id=stable_id("claim", {"metric": primary.metric, "statement": direction}),
            claim_type=ClaimType.MEASURED,
            statement=(
                f"{primary.label} moved from {primary.baseline_value:.3f} to {primary.comparison_value:.3f}, "
                f"a change of {float(primary.value or 0):+.3f} across {primary.sample_size} comparison-window observations."
            ),
            evidence_ids=[primary.evidence_id],
            confidence=_sample_confidence(primary.sample_size),
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
                confidence=_sample_confidence(min(item.sample_size for item in seasonal)),
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
                confidence=_sample_confidence(item.sample_size),
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
        analysis_domain: str = "passing",
        sport: str = "nfl",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> tuple[SynthesisDraft, str | None, bool]:
        progress = 0.75
        progress_lock = Lock()

        def report_progress(message: str, target: float | None = None) -> None:
            nonlocal progress
            if progress_callback is None:
                return
            with progress_lock:
                progress = min(0.97, max(progress + 0.015 if target is None else target, progress))
                progress_callback(message, progress)

        report_progress("Organizing the validated evidence", 0.76)
        fallback = _fallback_synthesis(
            question, team, baseline, comparison, aggregate, analysis_seasons, conversation_context, analysis_domain, sport
        )
        logger.debug(
            "synthesis_requested provider=%s aggregate_count=%d play_count=%d",
            self.settings.model_provider,
            len(aggregate),
            len(plays),
        )
        if self.settings.model_provider == "azure_foundry" and not self.settings.foundry_endpoint:
            logger.info("synthesis_fallback reason=model_not_configured provider=azure_foundry")
            report_progress("Writing the deterministic evidence report", 0.94)
            return fallback, None, True
        try:
            from deepagents import create_deep_agent
            from deepagents.backends import StateBackend
            from langchain.tools import tool
            from langchain_core.callbacks import BaseCallbackHandler

            resolved = get_provider(self.settings.model_provider).build(self.settings)
            ledger, aggregate_payload, play_payload = _citation_ledger(aggregate, plays)
            synthesis_mode = _synthesis_mode(question, len(aggregate), conversation_context)
            logger.debug(
                "citation_ledger_created aggregate_aliases=%d play_aliases=%d synthesis_mode=%s",
                len(aggregate_payload),
                len(play_payload),
                synthesis_mode,
            )
            response_model = _citation_response_model(list(ledger))
            allowed_citations = ", ".join(ledger)
            report_progress("Preparing the evidence brief for the analyst", 0.78)

            class SynthesisProgressHandler(BaseCallbackHandler):
                model_passes = 0

                def on_chat_model_start(self, *_args: Any, **_kwargs: Any) -> None:
                    messages = (
                        "Reviewing the analytical brief",
                        "Comparing the strongest performance signals",
                        "Examining situational context and counterexamples",
                        "Challenging the findings against the evidence",
                        "Drafting the analyst's final read",
                    )
                    message = messages[min(self.model_passes, len(messages) - 1)]
                    self.model_passes += 1
                    report_progress(message)

                def on_tool_start(self, serialized: dict[str, Any], _input: str, **_kwargs: Any) -> None:
                    tool_name = str(serialized.get("name", ""))
                    messages = {
                        "inspect_aggregate_evidence": "Inspecting validated metrics and diagnostic cuts",
                        "inspect_representative_plays": "Reviewing representative plays and counterexamples",
                        "task": "Consulting a specialist football analyst",
                    }
                    report_progress(messages.get(tool_name, "Running an evidence review step"))

            progress_handler = SynthesisProgressHandler()

            @tool
            def inspect_aggregate_evidence(
                metric: str | None = None,
                citation_keys: list[str] | None = None,
                limit: int = 60,
            ) -> str:
                """Return validated aggregate findings, optionally filtered by metric or exact citation keys."""
                requested = set(citation_keys or [])
                filtered = [
                    item
                    for item in aggregate_payload
                    if (not metric or metric.lower() in str(item.get("metric", "")).lower())
                    and (not requested or item["citation_key"] in requested)
                ]
                return json.dumps(filtered[: max(1, min(limit, 100))], indent=2, default=str)

            @tool
            def inspect_representative_plays(
                supporting: bool | None = None,
                citation_keys: list[str] | None = None,
                limit: int = 12,
            ) -> str:
                """Return representative plays, optionally filtered by support/counterexample status or citation keys."""
                requested = set(citation_keys or [])
                filtered = [
                    item
                    for item in play_payload
                    if (supporting is None or item.get("supporting") is supporting) and (not requested or item["citation_key"] in requested)
                ]
                return json.dumps(filtered[: max(1, min(limit, 25))], indent=2, default=str)

            tools: list[Any] = [inspect_aggregate_evidence, inspect_representative_plays]
            sport_label = "NBA" if sport == "nba" else "NFL"
            sport_noun = "basketball" if sport == "nba" else "football"
            voice_guide = NBA_ANALYST_VOICE_GUIDE if sport == "nba" else ANALYST_VOICE_GUIDE
            common = (
                "Use only the read-only evidence tools. Cite evidence_refs using only the exact citation_key values returned by "
                f"those tools. The only valid citation keys for this run are: {allowed_citations}. Numerical claims must be "
                f"measured; {sport_noun} explanations must be interpretation claims. Do not claim causality or invent players, schemes, "
                "injuries, citation keys, or evidence IDs. Every material assertion must be supported by the cited evidence.\n\n" + voice_guide
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
            available_subagents = [
                {
                    "name": "efficiency-analyst",
                    "description": f"Diagnoses {analysis_domain} efficiency and production changes.",
                    "system_prompt": (
                        "Act as the lead performance analyst. Identify the strongest answer to the question, determine which changes "
                        "are practically meaningful, and distinguish the main signal from secondary or contradictory indicators. "
                        "Return a prioritized analytical read for the coordinating analyst.\n\n" + common
                    ),
                    "tools": tools,
                    "model": resolved.chat_model,
                },
                {
                    "name": "situational-analyst",
                    "description": "Examines contextual split contributions.",
                    "system_prompt": (
                        f"Act as a situational {sport_noun} analyst. Determine where the change occurred, whether it came from usage mix or "
                        "performance within situations, and whether weekly, opponent, player, or game-level context strengthens or "
                        "weakens the apparent explanation. Do not force a mechanism when the evidence is only descriptive.\n\n" + common
                    ),
                    "tools": tools,
                    "model": resolved.chat_model,
                },
                {
                    "name": "evidence-reviewer",
                    "description": "Challenges claims and verifies citations.",
                    "system_prompt": (
                        f"Act as a skeptical senior {sport_noun} editor. Challenge unsupported explanations, check that the cited evidence "
                        "actually supports each sentence, remove redundant metric recitation, and recommend the clearest defensible "
                        "wording. Preserve useful uncertainty and counterevidence.\n\n" + common
                    ),
                    "tools": tools,
                    "model": resolved.chat_model,
                },
            ]
            subagents = (
                []
                if synthesis_mode == "direct"
                else [available_subagents[0], available_subagents[2]]
                if synthesis_mode == "reviewed"
                else available_subagents
            )
            coordinator_instruction = (
                "Answer directly from the evidence tools and produce the final report."
                if synthesis_mode == "direct"
                else "Delegate diagnosis and review as useful, then write the final report."
            )
            agent_arguments: dict[str, Any] = dict(
                model=resolved.chat_model,
                tools=tools,
                system_prompt=(
                    f"You coordinate an {sport_label} analysis for {team}, comparing {baseline.model_dump()} with {comparison.model_dump()}. "
                    f"{coordinator_instruction} Write the result as a polished analyst's read—not a transcript of the "
                    "specialists and not a metric dump. Build a clear hierarchy: answer, strongest explanation, qualification, then "
                    f"supporting detail. The reader should understand both what changed and why the available {sport_noun} evidence makes "
                    "that interpretation reasonable.\n\n" + common
                ),
                response_format=response_model,
                backend=StateBackend(),
                name="open-sports-analyst",
            )
            if subagents:
                agent_arguments["subagents"] = subagents
            agent = create_deep_agent(**agent_arguments)

            def invoke(prompt: str) -> BaseModel:
                response = agent.invoke(
                    {"messages": [{"role": "user", "content": prompt}]},
                    config={"callbacks": [progress_handler]},
                )
                structured = response.get("structured_response")
                return structured if isinstance(structured, response_model) else response_model.model_validate(structured)

            try:
                logger.info("model_synthesis_started model_id=%s citation_aliases=%d", resolved.model_id, len(ledger))
                aliased_draft = invoke(
                    f"The user's analytical question is {json.dumps(question)}. Synthesize and verify an answer that directly "
                    "addresses that question. Write a concise, natural analyst's read with a clear thesis, prioritized findings, and "
                    f"calibrated {sport_noun} interpretation. Use evidence_refs with exact citation keys from the tools."
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
            report_progress("Validating every finding and citation", 0.94)
            resolved_draft = _resolve_citation_draft(aliased_draft, ledger)
            report_progress("Finalizing the evidence-linked report", 0.97)
            logger.info("model_synthesis_completed model_id=%s claims=%d", resolved.model_id, len(resolved_draft.claims))
            return resolved_draft, resolved.model_id, False
        except Exception as error:
            logger.warning("model_synthesis_fallback error_type=%s", type(error).__name__)
            return fallback, None, True
