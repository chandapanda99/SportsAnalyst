"""Versioned observation contracts. Declaration is never proof of snapshot coverage."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "research-3"


class StrictPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetContract(StrictPlan):
    version: str = VERSION
    sport: str
    dataset: str
    namespace: str
    grain: str
    keys: tuple[str, ...] = ()
    game: str | None = None
    team: str | None = None
    player: str | None = None
    player_namespace: str | None = None
    team_namespace: str | None = None
    temporal: str = "recorded season/event; acquisition time is not validity"
    season_convention: str = "unknown"
    restrictions: tuple[str, ...] = ()


class AcquisitionPlan(StrictPlan):
    objective: str = Field(min_length=1, max_length=500)
    dataset: str
    season: int
    purpose: Literal["primary", "context"] = "primary"
    team_id: str | None = None
    fields: list[str] = Field(default_factory=list, max_length=24)
    expected_reuse: Literal["investigation", "historical_snapshot", "current_refresh"] = "investigation"
    round: int = Field(default=1, ge=1)


class RelationshipContract(StrictPlan):
    version: str = VERSION
    relationship_id: str
    left_dataset_id: str
    right_dataset_id: str
    left_keys: tuple[str, ...]
    right_keys: tuple[str, ...]
    kind: Literal["equality", "crosswalk", "interval"] = "equality"
    point: str | None = None
    start: str | None = None
    end: str | None = None
    boundaries: Literal["closed"] | None = None
    context_role: Literal["own", "opponent", "actor"] = "own"
    bridge_dataset_id: str | None = None
    owner_team: str | None = None
    target_team: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    status: str = "candidate; runtime key/cardinality validation required"
    restriction: str = "Preserve base observations; aggregate children or use existence filters"


class Measure(StrictPlan):
    op: Literal["count", "sum", "mean", "min", "max", "n_unique", "rate"]
    field: str = ""
    denominator: str = ""
    name: str = Field(default="value", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")

    @model_validator(mode="after")
    def validate_rate(self):
        if self.op == "rate" and (not self.field or not self.denominator):
            raise ValueError("Rate requires recorded numerator field and denominator")
        if self.op != "rate" and self.denominator:
            raise ValueError("Denominator is only supported for rate")
        return self


class Filter(StrictPlan):
    field: str
    op: Literal["eq", "ne", "gt", "ge", "lt", "le", "is_not_null"]
    value: str | int | float | bool | None = None


class JoinStep(StrictPlan):
    relationship_id: str
    alias: str = Field(pattern=r"^[a-z][a-z0-9_]{0,19}$")
    left_alias: str = "base"
    mode: Literal["enrich", "exists", "not_exists", "preaggregate"] = "enrich"
    fields: list[str] = Field(default_factory=list, max_length=8)
    filters: list[Filter] = Field(default_factory=list, max_length=8)
    measures: list[Measure] = Field(default_factory=list, max_length=8)


class JoinPlan(StrictPlan):
    objective: str = Field(min_length=1, max_length=500)
    dataset_id: str
    window: str
    grain: str
    steps: list[JoinStep] = Field(default_factory=list, max_length=4)
    group_by: list[str] = Field(default_factory=list, max_length=3)
    filters: list[Filter] = Field(default_factory=list, max_length=8)
    measures: list[Measure] = Field(min_length=1, max_length=8)
    missing: Literal["preserve", "matched", "strict"] = "preserve"
    interpretation: Literal["retrospective", "pregame"] = "retrospective"


def family(dataset):
    for prefix in ("player_expected_goals", "player_game_logs", "season_statistics"):
        if dataset.startswith(prefix):
            return prefix
    return dataset


def contract(manifest):
    """Use explicit upstream namespaces and recorded columns, never column-name similarity across providers."""
    sport, dataset, cols = manifest.sport, family(manifest.dataset), set(manifest.columns)
    namespace = "nflverse" if sport == "nfl" else "nba_stats" if sport == "nba" and (
        dataset.startswith("stats_") or dataset in {"lineups", "lineups_v3", "possessions_v3"}) else "espn"
    first = lambda names: next((key for key in names if key in cols), None)
    game = first(("game_id", "event_id", "nflverse_game_id"))
    team = first(("posteam", "team_id", "team_abbreviation", "team_abbr", "team", "recent_team"))
    if sport == "nba":
        team = first(("team_abbreviation", "team_abbrev", "team_tricode", "team_id"))
    player = first(("athlete_id", "player_id", "gsis_id", "player_gsis_id", "pfr_player_id"))
    if namespace == "nba_stats":
        player = first(("player_id", "person_id", "nba_player_id"))
    grain, keys, restrictions = "unverified", (), []
    if dataset in {"schedules", "stats_schedules"} or (sport == "soccer" and dataset == "play_by_play"):
        grain, keys = "game", (game,) if game else ()
    elif dataset in {"play_by_play", "stats_play_by_play", "recorded_plays", "enriched_plays", "ftn_charting", "participation"}:
        play = first(("play_id", "nflverse_play_id", "id"))
        grain, keys = "play", (game, play) if game and play else ()
    elif dataset in {"team_stats", "team_boxscores", "stats_team_boxscores", "expected_goals"}:
        grain, keys = "team_game", (game, team) if game and team else ()
    elif dataset in {"player_boxscores", "stats_player_boxscores", "stats_player_game_logs", "player_game_logs", "player_expected_goals"} or (
            sport == "cfb" and dataset == "player_stats"):
        grain, keys = "player_game", tuple(key for key in (game, team, player) if key)
        if sport == "nba":
            restrictions.append("Box-score listings can include DNP/inactive players; require recorded minutes/participation for appearance-based rates")
    elif dataset in {"lineups", "game_rosters", "stats_game_rosters"} and not (sport == "nba" and dataset == "lineups"):
        grain, keys = "game_membership", tuple(key for key in (game, team, player) if key)
        restrictions.append("Roster listing is not proof of participation/minutes")
    elif dataset in {"rosters", "weekly_rosters", "stats_rosters"}:
        grain = "membership_snapshot"
        keys = tuple(key for key in ("season", "week", team, player) if key and key in cols)
        restrictions.append("Membership requires recorded season/week/game validity, not current profile")
    elif sport == "nfl" and (dataset == "player_stats" or dataset.startswith(("nextgen_", "pfr_"))):
        grain = "player_week"
        keys = tuple(key for key in ("season", "season_type", "week", team, player) if key and key in cols)
        restrictions.append("Exclude season-total/week-zero rows before weekly measurements")
    elif dataset == "snap_counts":
        grain, keys = "player_game", tuple(key for key in (game, team, player) if key)
    elif dataset in {"shots", "stats_shots"}:
        grain, keys = "shot", tuple(key for key in (game, first(("play_id", "id", "action_number"))) if key)
    elif dataset in {"key_events", "scoring_events"}:
        grain, keys = "recorded_event", tuple(key for key in (game, first(("id",))) if key)
    elif dataset in {"player_crosswalk", "schedule_crosswalk", "team_crosswalk", "players", "teams", "player_core"}:
        grain = "identity_reference"
        restrictions.append("Identity reference does not establish historical membership")
    elif dataset == "season_statistics" or "season_stats" in dataset or dataset == "lineups":
        grain = "season_summary"
        restrictions.append("Do not repeat totals across game/play rows or infer lineup intervals")
    elif dataset in {"lineups_v3", "possessions_v3"}:
        grain = "interval_candidate"
        restrictions.append("Requires verified game, ordering, start/end bounds and provider crosswalk")
    player_namespace = ("pfr" if player == "pfr_player_id" else "gsis" if sport == "nfl" else namespace) if player else None
    team_namespace = ("abbreviation" if sport == "nfl" or team in {
        "team_abbreviation", "team_abbrev", "team_tricode"} else namespace + "_team_id") if team else None
    convention = {"nfl": "start_year", "cfb": "start_year", "nba": "end_year"}.get(sport, "competition_specific")
    return DatasetContract(sport=sport, dataset=dataset, namespace=namespace, grain=grain, season_convention=convention,
                           keys=keys, game=game, team=team, player=player, player_namespace=player_namespace,
                           team_namespace=team_namespace,
                           restrictions=tuple(restrictions))


def relationships(manifests):
    """Only explicit entity-key relationships; same spelling does not bridge namespaces."""
    from sports_analyst.models import stable_id

    result = []
    definitions = {key: contract(m) for key, m in manifests.items()}
    calendars_by_scope = {}
    for item in manifests.values():
        c = definitions[item.manifest_id]
        if c.grain == "game" and c.game:
            calendars_by_scope.setdefault((item.sport, item.competition, item.season, c.namespace), []).append(item)
    for left in manifests.values():
        lc = definitions[left.manifest_id]
        for right in manifests.values():
            if left.manifest_id == right.manifest_id or left.sport != right.sport or left.competition != right.competition:
                continue
            if right.season not in {0, left.season}:
                continue
            rc = definitions[right.manifest_id]
            lk, rk, kind, temporal = [], [], "equality", {}
            native_order = lc.namespace == rc.namespace == "nba_stats" and lc.game and rc.game
            if (native_order and right.dataset == "possessions_v3" and "order_index" in left.columns
                    and {"period", "start_order_index", "end_order_index"} <= set(right.columns)
                    and "period" in left.columns):
                lk, rk, kind = [lc.game, "period"], [rc.game, "period"], "interval"
                temporal = {"point": "order_index", "start": "start_order_index", "end": "end_order_index", "boundaries": "closed"}
            elif (native_order and right.dataset == "lineups_v3" and "action_number" in left.columns
                  and "action_number" in right.columns and "period" in left.columns and "period" in right.columns):
                lk, rk = [lc.game, "period", "action_number"], [rc.game, "period", "action_number"]
                temporal = {"point": "action_number"}
            if lc.namespace == rc.namespace and not temporal:
                if lc.game and rc.game:
                    lk, rk = [lc.game], [rc.game]
                    # Play enrichment is by game AND play, never by clock.
                    if lc.grain == rc.grain == "play":
                        if len(lc.keys) != 2 or len(rc.keys) != 2:
                            continue
                        lk, rk = list(lc.keys), list(rc.keys)
                    elif rc.grain != "game":
                        if lc.team and rc.team and lc.team_namespace == rc.team_namespace:
                            lk.append(lc.team)
                            rk.append(rc.team)
                        if lc.player and rc.player and lc.player_namespace == rc.player_namespace:
                            lk.append(lc.player)
                            rk.append(rc.player)
                elif lc.grain == "player_week" and rc.grain in {"player_week", "membership_snapshot"} and lc.player and rc.player:
                    shared = [key for key in ("season", "week") if key in left.columns and key in right.columns]
                    left_phase = next((k for k in ("season_type", "game_type") if k in left.columns), None)
                    right_phase = next((k for k in ("season_type", "game_type") if k in right.columns), None)
                    if len(shared) != 2 or not left_phase or not right_phase or lc.player_namespace != rc.player_namespace:
                        continue
                    lk, rk = [*shared, left_phase, lc.player], [*shared, right_phase, rc.player]
                    if lc.team and rc.team:
                        lk.append(lc.team)
                        rk.append(rc.team)
            # A recorded crosswalk is the bridge, not a guessed numeric conversion.
            if right.dataset == "player_crosswalk" and lc.player:
                target = "nba_player_id" if lc.namespace == "nba_stats" else "espn_athlete_id"
                if target in right.columns:
                    lk, rk, kind = [lc.player], [target], "crosswalk"
            if left.sport == "nfl" and right.dataset == "players" and lc.player:
                target = {"gsis": "gsis_id", "pfr": "pfr_id"}.get(lc.player_namespace)
                if target in right.columns:
                    lk, rk, kind = [lc.player], [target], "crosswalk"
            if left.sport == "nfl" and right.dataset == "teams" and lc.team and "team_abbr" in right.columns:
                lk, rk = [lc.team], ["team_abbr"]
            # Event crosswalks can connect provider-specific game identities.
            if right.dataset == "schedule_crosswalk" and lc.game:
                target = "nba_game_id" if lc.namespace == "nba_stats" else "espn_game_id"
                if target in right.columns:
                    lk, rk, kind = [lc.game], [target], "crosswalk"
            if left.dataset == "schedule_crosswalk" and rc.grain == "game" and rc.game:
                source = "nba_game_id" if rc.namespace == "nba_stats" else "espn_game_id"
                if source in left.columns:
                    lk, rk, kind = [source], [rc.game], "crosswalk"
            if not lk or rc.grain in {"unverified", "season_summary"} or (rc.grain == "interval_candidate" and not temporal):
                continue
            if rc.grain == "membership_snapshot" and lc.grain != "player_week":
                continue
            if rc.grain == "team_game" and (not lc.team or lc.team_namespace != rc.team_namespace):
                continue
            payload = {"left_dataset_id": left.manifest_id, "right_dataset_id": right.manifest_id,
                       "left_keys": tuple(lk), "right_keys": tuple(rk), "kind": kind, **temporal}
            result.append(RelationshipContract(relationship_id=stable_id("relationship", {"version": VERSION, **payload}), **payload))
    # Role-specific relationships require recorded IDs, not inferred player names
    # or a guessed opponent. A schedule can bridge ownership to the other side.
    for left in manifests.values():
        lc = definitions[left.manifest_id]
        for right in manifests.values():
            rc = definitions[right.manifest_id]
            if left.sport != right.sport or left.competition != right.competition or left.season != right.season:
                continue
            if lc.namespace != rc.namespace:
                continue
            variants = []
            actor_namespace = rc.player_namespace == ("gsis" if left.sport == "nfl" else lc.namespace)
            if lc.game and rc.game and rc.player and actor_namespace and lc.team_namespace == rc.team_namespace:
                for actor in ("passer_player_id", "rusher_player_id", "receiver_player_id", "passer_id", "rusher_id", "receiver_id"):
                    if actor in left.columns and rc.grain in {"player_game", "game_membership"}:
                        variants.append({"left_keys": (lc.game, actor), "right_keys": (rc.game, rc.player), "context_role": "actor"})
            if lc.grain == "play" and rc.grain == "player_week" and rc.player and actor_namespace:
                if {"season", "season_type", "week"} <= set(left.columns) & set(right.columns):
                    for actor in ("passer_player_id", "rusher_player_id", "receiver_player_id"):
                        if actor in left.columns:
                            variants.append({"left_keys": ("season", "season_type", "week", actor),
                                             "right_keys": ("season", "season_type", "week", rc.player), "context_role": "actor"})
            if lc.grain == "play" and rc.grain == "player_week" and left.sport == "nfl" and rc.team:
                if {"season", "season_type", "week", "defteam"} <= set(left.columns) and {"season", "season_type", "week"} <= set(right.columns):
                    variants.append({"left_keys": ("season", "season_type", "week", "defteam"),
                                     "right_keys": ("season", "season_type", "week", rc.team), "context_role": "opponent"})
            if lc.game and rc.game and lc.team and rc.team and rc.grain == "team_game" and lc.team_namespace == rc.team_namespace:
                calendars = calendars_by_scope.get((left.sport, left.competition, left.season, lc.namespace), [])
                for bridge in calendars:
                    home, away = (("home_team", "away_team") if left.sport == "nfl" else
                                  ("home_team_abbrev", "away_team_abbrev") if lc.team_namespace == "abbreviation" else
                                  ("home_team_id", "away_team_id"))
                    if {home, away} <= set(bridge.columns):
                        variants.append({"left_keys": (lc.game,), "right_keys": (rc.game,), "context_role": "opponent",
                            "bridge_dataset_id": bridge.manifest_id, "owner_team": lc.team, "target_team": rc.team,
                            "home_team": home, "away_team": away})
            for variant in variants:
                payload = {"left_dataset_id": left.manifest_id, "right_dataset_id": right.manifest_id, **variant}
                result.append(RelationshipContract(relationship_id=stable_id("relationship", {"version": VERSION, **payload}), **payload))
    return result
