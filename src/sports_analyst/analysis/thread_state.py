"""Structured state of a report thread, so follow-ups resolve 'that drop' or 'those games' to IDs."""
from __future__ import annotations

from typing import Any

MAX_CLAIMS = 8
MAX_GAMES = 12


def _planner_review(bundle) -> dict[str, Any]:
    for execution in reversed(bundle.executions):
        if execution.tool == "complete_calculations":
            return {"plan": execution.parameters.get("plan") or {}, "review": execution.parameters.get("question_review") or {}}
    return {"plan": {}, "review": {}}


def turn_state(bundle, earlier_evidence: set[str] | None = None) -> dict[str, Any]:
    """One turn: what was asked, what the planner set out to establish, and what the answer cited."""
    run = bundle.run
    review = _planner_review(bundle)
    objectives = review["plan"].get("objectives") or []
    plays = {item.evidence_id: item for item in bundle.play_evidence}
    cited = [evidence_id for claim in bundle.claims for evidence_id in claim.evidence_ids]
    games = list(dict.fromkeys(f"{plays[e].season}:{plays[e].game_id}" for e in cited if e in plays))
    new = [item.evidence_id for item in bundle.aggregate_evidence if earlier_evidence is not None and item.evidence_id not in earlier_evidence]
    return {
        "investigation_id": run.investigation_id,
        "question": run.question[:500],
        "scope": {"seasons": run.scope.included_seasons, "baseline": run.scope.baseline.model_dump(mode="json"),
                  "comparison": run.scope.comparison.model_dump(mode="json"), "season_type": run.scope.season_type,
                  "analysis_domain": run.analysis_domain, "metrics": run.metrics, "splits": run.splits},
        "summary": bundle.summary[:600],
        "objectives": [{"index": index, "objective": text[:300],
                        "evidence_ids": (review["review"].get("evidence_by_objective") or {}).get(str(index), [])[:24],
                        "unresolved": (review["review"].get("unresolved") or {}).get(str(index))}
                       for index, text in enumerate(objectives)],
        "claims": [{"statement": claim.statement[:300], "evidence_ids": claim.evidence_ids[:12]}
                   for claim in bundle.claims[:MAX_CLAIMS]],
        "cited_games": games[:MAX_GAMES],
        **({"evidence_registered_this_turn": new[:40]} if earlier_evidence is not None else {}),
    }


def thread_state(thread) -> list[dict[str, Any]]:
    """Oldest first. The first entry is the report; later entries are follow-ups."""
    turns, seen = [], set()
    for index, bundle in enumerate(thread):
        turns.append(turn_state(bundle, seen if index else None))
        seen.update(item.evidence_id for item in bundle.aggregate_evidence)
    return turns
