"""Provider capabilities and field provenance, independent of optional SDK imports.

Capabilities are candidate contracts, not assertions of season/game coverage.
Only audited adapters can be selected for automatic preparation.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderCapability(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    sport: Literal["cfb", "nfl", "nba", "soccer"]
    upstream: str
    datasets: tuple[str, ...]
    acquisition: Literal["game", "season", "team"]
    reference_url: str
    automatic: bool = False
    limitation: str


CAPABILITIES = (
    ProviderCapability(provider_id="espn", sport="cfb", upstream="ESPN", acquisition="game", automatic=True,
                       datasets=("schedules", "rosters", "plays", "participants", "team_stats", "player_stats"),
                       reference_url="https://github.com/sportsdataverse/cfbfastR-cfb-data",
                       limitation="Recorded actors are not a complete snap lineup; derived fields require provenance."),
    ProviderCapability(provider_id="ncaa", sport="cfb", upstream="stats.ncaa.org", acquisition="game",
                       datasets=("schedules", "rosters", "plays", "drives", "team_stats", "player_stats"),
                       reference_url="https://github.com/sportsdataverse/ncaa-mfb-football-data",
                       limitation="Play alignment and season conventions require validation; no native EPA/WPA."),
    ProviderCapability(provider_id="cfbd", sport="cfb", upstream="CollegeFootballData", acquisition="season",
                       datasets=("plays", "participants", "modeled_plays"),
                       reference_url="https://github.com/sportsdataverse/cfbfastR-data",
                       limitation="Published season assets require cached partitioning and model-compatibility auditing."),
    ProviderCapability(provider_id="nflverse", sport="nfl", upstream="nflverse", acquisition="season", automatic=True,
                       datasets=("plays", "participation", "rosters", "charting"),
                       reference_url="https://github.com/nflverse/nflverse-data",
                       limitation="Coverage and licenses vary by package and season."),
    ProviderCapability(provider_id="sportsdataverse_nba", sport="nba", upstream="SportsDataverse NBA releases", acquisition="season",
                       automatic=True, datasets=("plays", "schedules", "team_stats", "player_stats", "shots", "lineups"),
                       reference_url="https://github.com/sportsdataverse/sportsdataverse-data",
                       limitation="Individual release assets and upstream definitions must be verified before new capabilities are enabled."),
    ProviderCapability(provider_id="espn_soccer", sport="soccer", upstream="ESPN", acquisition="game", automatic=True,
                       datasets=("schedules", "events", "rosters", "team_stats", "player_stats", "expected_goals"),
                       reference_url="https://github.com/sportsdataverse/sportsdataverse-py",
                       limitation="Competition-specific coverage; no inferred xG or pitch coordinates."),
)


class FieldObservation(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_id: str
    source_record_id: str
    source_url: str
    field: str
    value: Any
    method: Literal["recorded", "text_parsed", "model_derived", "illustrative"]
    processing_version: str
    model_id: str | None = None


def resolve_fields(observations: list[FieldObservation], priority: tuple[str, ...], *, model_id: str | None = None) -> dict:
    """Resolve only already-aligned records; retain disagreement and rejected values.

    A source priority is an explicit caller policy, never a universal credibility
    ranking. Illustrations cannot become analysis facts. False and zero are data.
    """
    grouped = {}
    for observation in observations:
        if observation.value is not None:
            grouped.setdefault(observation.field, []).append(observation)
    result = {"values": {}, "provenance": {}, "conflicts": {}, "rejected": {}}
    for field, candidates in grouped.items():
        eligible = [item for item in candidates if item.provider_id in priority
                    and item.method != "illustrative"
                    and (item.method != "model_derived" or (model_id is not None and item.model_id == model_id))]
        rejected = [item for item in candidates if item not in eligible]
        if rejected:
            result["rejected"][field] = [item.model_dump(mode="json") for item in rejected]
        if not eligible:
            continue
        eligible.sort(key=lambda item: (priority.index(item.provider_id), item.source_record_id))
        chosen = eligible[0]
        # Multiple contradictory observations from the same preferred source
        # cannot be resolved merely by their lexical record IDs.
        same_source = [item for item in eligible if item.provider_id == chosen.provider_id]
        disagreements = [item for item in eligible if item.value != chosen.value]
        if disagreements:
            result["conflicts"][field] = [item.model_dump(mode="json") for item in eligible]
        if any(item.value != chosen.value for item in same_source):
            continue
        result["values"][field] = chosen.value
        result["provenance"][field] = chosen.model_dump(mode="json")
    return result


def align_plays(primary: list[dict], secondary: list[dict], *, game_verified: bool) -> dict:
    """Conservative one-to-one context alignment, never a sequence/name join.

    Conflicts in event family, possession, field position or yardage leave plays
    unmatched. A verified game/team crosswalk must be supplied by the adapter.
    This deliberately prefers an explicit gap to incorrect player attribution.
    """
    fields = ("quarter", "clock", "team_id", "down", "distance", "yards_to_goal", "play_type", "yards_gained")

    def signature(row):
        values = tuple(row.get(field) for field in fields)
        return values if all(value is not None for value in values) else None

    indexes = []
    for rows in (primary, secondary):
        index = {}
        for row in rows:
            key = signature(row)
            if key is not None:
                index.setdefault(key, []).append(str(row["id"]))
        indexes.append(index)
    matches = {}
    ids = [[str(row.get("id") or "") for row in rows] for rows in (primary, secondary)]
    unique_ids = all(all(items) and len(items) == len(set(items)) for items in ids)
    if game_verified and unique_ids:
        for key, left in indexes[0].items():
            right = indexes[1].get(key, [])
            if len(left) == len(right) == 1:
                matches[left[0]] = right[0]
    return {"matches": matches,
            "unmatched_primary": [str(row["id"]) for row in primary if str(row["id"]) not in matches],
            "unmatched_secondary": [str(row["id"]) for row in secondary if str(row["id"]) not in matches.values()]}
