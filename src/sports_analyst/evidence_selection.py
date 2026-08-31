"""Deterministic, diversity-aware selection of representative sport evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


EvidenceWindow = Literal["baseline", "comparison"]
EvidenceRole = Literal["typical", "metric_example", "supports_change", "counterexample"]
SELECTOR_VERSION = "diverse-v1"


@dataclass(frozen=True)
class EvidenceCandidate:
    key: str
    window: EvidenceWindow
    game_id: str
    event_type: str
    payload: Any
    outcome_value: float | None = None
    relevance: float = 0.0
    context_quality: float = 0.0
    opponent: str = ""
    period: str = ""


@dataclass(frozen=True)
class SelectedEvidence:
    candidate: EvidenceCandidate
    role: EvidenceRole
    reason: str
    selection_metric: str | None
    candidate_pool_size: int
    selector_version: str = SELECTOR_VERSION


def _percentiles(candidates: list[EvidenceCandidate]) -> dict[str, float]:
    percentiles: dict[str, float] = {}
    for window in ("baseline", "comparison"):
        pool = [candidate for candidate in candidates if candidate.window == window]
        valued = sorted(
            (candidate for candidate in pool if candidate.outcome_value is not None),
            key=lambda candidate: (float(candidate.outcome_value), candidate.key),
        )
        if len(valued) < 2:
            percentiles.update({candidate.key: 0.5 for candidate in pool})
            continue
        ranks: dict[float, list[int]] = {}
        for index, candidate in enumerate(valued):
            ranks.setdefault(float(candidate.outcome_value), []).append(index)
        mapped = {
            value: (sum(indices) / len(indices)) / (len(valued) - 1)
            for value, indices in ranks.items()
        }
        percentiles.update({
            candidate.key: mapped.get(float(candidate.outcome_value), 0.5)
            if candidate.outcome_value is not None else 0.5
            for candidate in pool
        })
    return percentiles


def _observed_direction(candidates: list[EvidenceCandidate]) -> float:
    values = {
        window: [float(item.outcome_value) for item in candidates if item.window == window and item.outcome_value is not None]
        for window in ("baseline", "comparison")
    }
    if not values["baseline"] or not values["comparison"]:
        return 1.0
    delta = sum(values["comparison"]) / len(values["comparison"]) - sum(values["baseline"]) / len(values["baseline"])
    return -1.0 if delta < 0 else 1.0


def _slot_score(
    candidate: EvidenceCandidate,
    role: EvidenceRole,
    percentile: float,
    direction: float,
    selected: list[EvidenceCandidate],
) -> float:
    centered = (percentile - 0.5) * 2
    window_sign = 1.0 if candidate.window == "comparison" else -1.0
    alignment = centered * direction * window_sign
    if role == "typical":
        score = 1.0 - abs(centered) + candidate.relevance * 0.08
    elif role == "metric_example":
        score = candidate.relevance + abs(centered) * 0.15
    elif role == "supports_change":
        score = alignment + candidate.relevance * 0.12
    else:
        score = -alignment + candidate.relevance * 0.08
    score += candidate.context_quality * 0.08
    score -= sum(0.35 for item in selected if item.event_type and item.event_type == candidate.event_type)
    score -= sum(0.2 for item in selected if item.opponent and item.opponent == candidate.opponent)
    score -= sum(0.08 for item in selected if item.period and item.period == candidate.period)
    return score


def _reason(role: EvidenceRole, window: EvidenceWindow, metric_label: str | None) -> str:
    prefix = "Baseline" if window == "baseline" else "Comparison"
    if role == "typical":
        return f"{prefix} example closest to the typical recorded outcome."
    if role == "metric_example":
        return f"{prefix} example selected for relevance to {metric_label or 'the primary metric'}."
    if role == "supports_change":
        return f"{prefix} outcome consistent with the measured change between windows."
    return f"{prefix} counterexample that runs against the measured change."


def select_diverse_evidence(
    candidates: list[EvidenceCandidate],
    metric_label: str | None = None,
    per_window: int = 4,
    max_per_game: int = 1,
) -> list[SelectedEvidence]:
    """Fill stable evidence roles while preferring different games and contexts."""
    if not candidates:
        return []
    candidates = list({candidate.key: candidate for candidate in candidates}.values())
    percentiles = _percentiles(candidates)
    direction = _observed_direction(candidates)
    roles: list[EvidenceRole] = ["typical", "metric_example", "supports_change", "counterexample"]
    if per_window > len(roles):
        roles.extend(["metric_example"] * (per_window - len(roles)))
    selected: list[SelectedEvidence] = []
    chosen: set[str] = set()
    game_counts: dict[str, int] = {}
    for window in ("baseline", "comparison"):
        pool = [candidate for candidate in candidates if candidate.window == window]
        for role in roles[:per_window]:
            available = [candidate for candidate in pool if candidate.key not in chosen]
            if not available:
                break
            diverse = [candidate for candidate in available if game_counts.get(candidate.game_id, 0) < max_per_game]
            eligible = diverse or available
            ranked = sorted(
                eligible,
                key=lambda candidate: (
                    -_slot_score(candidate, role, percentiles[candidate.key], direction, [item.candidate for item in selected]),
                    candidate.key,
                ),
            )
            winner = ranked[0]
            selected.append(
                SelectedEvidence(
                    candidate=winner,
                    role=role,
                    reason=_reason(role, window, metric_label),
                    selection_metric=metric_label,
                    candidate_pool_size=len(pool),
                )
            )
            chosen.add(winner.key)
            game_counts[winner.game_id] = game_counts.get(winner.game_id, 0) + 1
    return selected
