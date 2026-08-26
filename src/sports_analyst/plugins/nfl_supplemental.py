"""Join nflverse supplemental packages and enrich representative plays."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import polars as pl

from sports_analyst.models import (
    AggregateEvidence,
    AnalysisWindow,
    DatasetManifest,
    PlayEvidence,
    PlayVisualization,
    ToolExecutionRecord,
    stable_id,
)
from sports_analyst.plugins.nfl_shared import (
    _execution_record,
    _first_column,
    _row_boolean,
    _row_integer,
    _row_number,
    _row_text,
    _row_text_list,
    _sha,
)


class NFLSupplementalMixin:
    """Provide roster, availability, charting, and schedule context methods."""

    def _roster_context(
        self,
        team: str,
        windows: list[AnalysisWindow],
        frames: dict[int, pl.DataFrame],
        manifests: dict[int, DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
        parameters = {"team": team, "windows": [window.model_dump() for window in windows]}
        execution_id = stable_id("execution", {"tool": "get_roster_context", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        counts: list[dict[str, int]] = []
        for window in windows:
            frame = frames[window.season]
            team_column = _first_column(frame, "team", "team_abbr", "recent_team")
            position_column = _first_column(frame, "position", "position_group")
            if not team_column or not position_column:
                counts.append({})
                continue
            scoped = frame.filter(pl.col(team_column) == team)
            counts.append(
                {str(row[position_column]): int(row["n"]) for row in scoped.group_by(position_column).len(name="n").iter_rows(named=True)}
            )
        evidence: list[AggregateEvidence] = []
        for position in sorted(set(counts[0]) | set(counts[1])):
            baseline_count, comparison_count = counts[0].get(position, 0), counts[1].get(position, 0)
            payload = {"tool": "get_roster_context", "team": team, "position": position, "windows": parameters["windows"]}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric="roster_count_by_position",
                    label=f"{position} roster count",
                    value=comparison_count - baseline_count,
                    baseline_value=baseline_count,
                    comparison_value=comparison_count,
                    unit="players",
                    sample_size=comparison_count,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                )
            )
        return evidence, _execution_record(
            "get_roster_context", execution_id, parameters, evidence, selected_manifests, started_at, started
        )

    def _availability_context(
        self,
        team: str,
        windows: list[AnalysisWindow],
        frames: dict[int, pl.DataFrame],
        manifests: dict[int, DatasetManifest],
    ) -> tuple[list[AggregateEvidence], list[ToolExecutionRecord]] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
        parameters = {"team": team, "windows": [window.model_dump() for window in windows]}
        availability_id = stable_id("execution", {"tool": "analyze_starter_availability", **parameters})
        summary_id = stable_id("execution", {"tool": "summarize_injured_or_inactive_players", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        unavailable: list[list[str]] = []
        for window in windows:
            frame = frames[window.season]
            team_column = _first_column(frame, "team", "team_abbr", "recent_team")
            week_column = _first_column(frame, "week")
            status_column = _first_column(frame, "report_status", "game_status", "practice_status", "status")
            name_column = _first_column(frame, "full_name", "player_name", "player_display_name")
            if not team_column or not status_column or not name_column:
                unavailable.append([])
                continue
            scoped = frame.filter(pl.col(team_column) == team)
            if week_column:
                scoped = scoped.filter(pl.col(week_column).is_between(window.weeks[0], window.weeks[1], closed="both"))
            scoped = scoped.filter(pl.col(status_column).cast(pl.Utf8).str.to_uppercase().str.contains("OUT|DOUBTFUL|INACTIVE|RESERVE|IR"))
            unavailable.append([str(value) for value in scoped[name_column].drop_nulls().to_list()])
        evidence: list[AggregateEvidence] = []
        availability_payload = {"tool": "analyze_starter_availability", **parameters}
        evidence.append(
            AggregateEvidence(
                evidence_id=stable_id("evidence", availability_payload),
                metric="unavailable_player_reports",
                label="Unavailable player reports",
                value=len(unavailable[1]) - len(unavailable[0]),
                baseline_value=len(unavailable[0]),
                comparison_value=len(unavailable[1]),
                unit="player-week reports",
                sample_size=len(unavailable[1]),
                row_set_sha256=_sha(availability_payload),
                dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                tool_execution_id=availability_id,
                caveats=["Injury reports describe listed availability and do not establish performance impact."],
            )
        )
        from collections import Counter

        base_counts, comparison_counts = Counter(unavailable[0]), Counter(unavailable[1])
        player_evidence: list[AggregateEvidence] = []
        for player, count in sorted(comparison_counts.items(), key=lambda item: (-item[1], item[0]))[:8]:
            payload = {"tool": "summarize_injured_or_inactive_players", "player": player, **parameters}
            player_evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric="player_unavailable_reports",
                    label=f"{player} unavailable reports",
                    value=count - base_counts.get(player, 0),
                    baseline_value=base_counts.get(player, 0),
                    comparison_value=count,
                    unit="player-week reports",
                    sample_size=count,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=summary_id,
                )
            )
        evidence.extend(player_evidence)
        records = [
            _execution_record(
                "analyze_starter_availability",
                availability_id,
                parameters,
                evidence[:1],
                selected_manifests,
                started_at,
                started,
            ),
            _execution_record(
                "summarize_injured_or_inactive_players",
                summary_id,
                parameters,
                player_evidence,
                selected_manifests,
                started_at,
                started,
            ),
        ]
        return evidence, records

    def _nextgen_context(
        self,
        team: str,
        windows: list[AnalysisWindow],
        frames: dict[int, pl.DataFrame],
        manifests: dict[int, DatasetManifest],
        stat_type: str = "passing",
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
        parameters = {"team": team, "windows": [window.model_dump() for window in windows]}
        tool = f"join_nextgen_{stat_type}_metrics"
        execution_id = stable_id("execution", {"tool": tool, **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        metric_candidates = {
            "passing": {
                "avg_time_to_throw": "Average time to throw",
                "avg_completed_air_yards": "Completed air yards",
                "aggressiveness": "Aggressiveness",
                "completion_percentage_above_expectation": "NGS CPOE",
                "avg_air_yards_differential": "Air-yards differential",
            },
            "receiving": {
                "avg_cushion": "Average pre-snap cushion",
                "avg_separation": "Average target separation",
                "percent_share_of_intended_air_yards": "Intended air-yards share",
                "avg_yac": "Average YAC",
                "avg_expected_yac": "Expected YAC",
                "avg_yac_above_expectation": "YAC above expectation",
            },
            "rushing": {
                "efficiency": "Rushing path efficiency",
                "percent_attempts_gte_eight_defenders": "Attempts against eight-plus defenders",
                "avg_time_to_los": "Average time to line of scrimmage",
                "expected_rush_yards": "Expected rushing yards",
                "rush_yards_over_expected_per_att": "Rush yards over expected per attempt",
                "rush_pct_over_expected": "Rush rate over expectation",
            },
        }[stat_type]
        summaries: list[dict[str, tuple[float, int]]] = []
        for window in windows:
            frame = frames[window.season]
            team_column = _first_column(frame, "team_abbr", "team", "recent_team")
            week_column = _first_column(frame, "week", "week_number")
            if not team_column:
                summaries.append({})
                continue
            scoped = frame.filter(pl.col(team_column) == team)
            if week_column:
                scoped = scoped.filter(pl.col(week_column).is_between(window.weeks[0], window.weeks[1], closed="both"))
            summary: dict[str, tuple[float, int]] = {}
            for metric in metric_candidates:
                if metric not in scoped.columns or not scoped[metric].drop_nulls().len():
                    continue
                summary[metric] = (float(scoped[metric].drop_nulls().mean()), scoped[metric].drop_nulls().len())
            summaries.append(summary)
        evidence: list[AggregateEvidence] = []
        for metric in sorted(set(summaries[0]) & set(summaries[1])):
            baseline_value, _baseline_n = summaries[0][metric]
            comparison_value, comparison_n = summaries[1][metric]
            payload = {"tool": tool, "metric": metric, **parameters}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric=f"nextgen_{metric}" if stat_type == "passing" else f"nextgen_{stat_type}_{metric}",
                    label=metric_candidates[metric],
                    value=round(comparison_value - baseline_value, 4),
                    baseline_value=round(baseline_value, 4),
                    comparison_value=round(comparison_value, 4),
                    unit="NGS published value",
                    sample_size=comparison_n,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                )
            )
        return evidence, _execution_record(
            tool, execution_id, parameters, evidence, selected_manifests, started_at, started
        )

    def _published_stat_context(
        self,
        team: str,
        windows: list[AnalysisWindow],
        frames: dict[int, pl.DataFrame],
        manifests: dict[int, DatasetManifest],
        tool: str,
        metric_prefix: str,
        metric_candidates: dict[str, str],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
        parameters = {"team": team, "dataset": metric_prefix, "windows": [window.model_dump() for window in windows]}
        execution_id = stable_id("execution", {"tool": tool, **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        summaries: list[dict[str, tuple[float, int]]] = []
        for window in windows:
            frame = frames[window.season]
            team_column = _first_column(frame, "team", "team_abbr", "recent_team")
            week_column = _first_column(frame, "week", "week_number")
            if not team_column:
                summaries.append({})
                continue
            scoped = frame.filter(pl.col(team_column) == team)
            if week_column:
                scoped = scoped.filter(pl.col(week_column).is_between(window.weeks[0], window.weeks[1], closed="both"))
            summary: dict[str, tuple[float, int]] = {}
            for metric in metric_candidates:
                if metric not in scoped.columns:
                    continue
                values = scoped[metric].cast(pl.Float64, strict=False).drop_nulls()
                if values.len():
                    summary[metric] = (float(values.mean()), values.len())
            summaries.append(summary)
        evidence: list[AggregateEvidence] = []
        for metric in sorted(set(summaries[0]) & set(summaries[1])):
            baseline_value, _ = summaries[0][metric]
            comparison_value, comparison_n = summaries[1][metric]
            payload = {"tool": tool, "metric": metric, **parameters}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric=f"{metric_prefix}_{metric}",
                    label=metric_candidates[metric],
                    value=round(comparison_value - baseline_value, 4),
                    baseline_value=round(baseline_value, 4),
                    comparison_value=round(comparison_value, 4),
                    unit="published value",
                    sample_size=comparison_n,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                )
            )
        return evidence, _execution_record(tool, execution_id, parameters, evidence, selected_manifests, started_at, started)

    def _play_level_context(
        self,
        windows: list[AnalysisWindow],
        scoped_plays: list[pl.DataFrame],
        frames: dict[int, pl.DataFrame],
        manifests: dict[int, DatasetManifest],
        play_manifests: dict[int, DatasetManifest],
        tool: str,
        metric_prefix: str,
        metric_candidates: dict[str, str],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = {
            manifest.manifest_id: manifest
            for window in windows
            for manifest in (manifests[window.season], play_manifests[window.season])
        }
        parameters = {"windows": [window.model_dump() for window in windows]}
        execution_id = stable_id("execution", {"tool": tool, **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        summaries: list[dict[str, tuple[float, int]]] = []
        for window, plays in zip(windows, scoped_plays, strict=True):
            frame = frames[window.season]
            source_game = _first_column(frame, "nflverse_game_id", "game_id")
            source_play = _first_column(frame, "nflverse_play_id", "play_id")
            play_game = _first_column(plays, "game_id", "nflverse_game_id")
            play_play = _first_column(plays, "play_id", "nflverse_play_id")
            if not all((source_game, source_play, play_game, play_play)):
                summaries.append({})
                continue
            keys = plays.select(
                pl.col(play_game).cast(pl.Utf8).alias("_join_game"),
                pl.col(play_play).cast(pl.Int64, strict=False).alias("_join_play"),
            ).unique()
            scoped = frame.with_columns(
                pl.col(source_game).cast(pl.Utf8).alias("_join_game"),
                pl.col(source_play).cast(pl.Int64, strict=False).alias("_join_play"),
            ).join(keys, on=["_join_game", "_join_play"], how="inner")
            if tool == "join_participation_context":
                if "was_pressure" in scoped.columns:
                    scoped = scoped.with_columns(pl.col("was_pressure").cast(pl.Float64, strict=False).alias("pressure_rate"))
                if "defense_man_zone_type" in scoped.columns:
                    scoped = scoped.with_columns(
                        pl.col("defense_man_zone_type")
                        .cast(pl.Utf8)
                        .str.to_uppercase()
                        .str.contains("MAN")
                        .cast(pl.Float64)
                        .alias("man_coverage_rate")
                    )
            summary: dict[str, tuple[float, int]] = {}
            for metric in metric_candidates:
                if metric not in scoped.columns:
                    continue
                values = scoped[metric].cast(pl.Float64, strict=False).drop_nulls()
                if values.len():
                    summary[metric] = (float(values.mean()), values.len())
            summaries.append(summary)
        evidence: list[AggregateEvidence] = []
        for metric in sorted(set(summaries[0]) & set(summaries[1])):
            baseline_value, _ = summaries[0][metric]
            comparison_value, comparison_n = summaries[1][metric]
            payload = {"tool": tool, "metric": metric, **parameters}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric=f"{metric_prefix}_{metric}",
                    label=metric_candidates[metric],
                    value=round(comparison_value - baseline_value, 4),
                    baseline_value=round(baseline_value, 4),
                    comparison_value=round(comparison_value, 4),
                    unit="rate" if metric.endswith("rate") or metric.startswith("is_") else "per play",
                    sample_size=comparison_n,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=list(selected_manifests),
                    tool_execution_id=execution_id,
                )
            )
        manifests_list = list(selected_manifests.values())
        return evidence, _execution_record(tool, execution_id, parameters, evidence, manifests_list, started_at, started)

    def _schedule_context(
        self,
        team: str,
        windows: list[AnalysisWindow],
        frames: dict[int, pl.DataFrame],
        manifests: dict[int, DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if any(window.season not in frames or window.season not in manifests for window in windows):
            return None
        selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
        parameters = {"team": team, "windows": [window.model_dump() for window in windows]}
        execution_id = stable_id("execution", {"tool": "join_schedule_context", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        summaries: list[tuple[float | None, int, int]] = []
        for window in windows:
            frame = frames[window.season]
            required = {"home_team", "away_team", "home_score", "away_score"}
            if not required <= set(frame.columns):
                summaries.append((None, 0, 0))
                continue
            scoped = frame.filter((pl.col("home_team") == team) | (pl.col("away_team") == team))
            if "week" in scoped.columns:
                scoped = scoped.filter(pl.col("week").is_between(window.weeks[0], window.weeks[1], closed="both"))
            scoped = scoped.with_columns(
                pl.when(pl.col("home_team") == team)
                .then(pl.col("home_score") - pl.col("away_score"))
                .otherwise(pl.col("away_score") - pl.col("home_score"))
                .cast(pl.Float64, strict=False)
                .alias("team_margin")
            )
            margin = scoped["team_margin"].drop_nulls().mean()
            summaries.append(
                (float(margin) if margin is not None else None, scoped.height, scoped.filter(pl.col("home_team") == team).height)
            )
        evidence: list[AggregateEvidence] = []
        if summaries[0][0] is not None and summaries[1][0] is not None:
            payload = {"tool": "join_schedule_context", "metric": "average_scoring_margin", **parameters}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric="schedule_average_scoring_margin",
                    label="Average scoring margin",
                    value=round(float(summaries[1][0] - summaries[0][0]), 3),
                    baseline_value=round(float(summaries[0][0]), 3),
                    comparison_value=round(float(summaries[1][0]), 3),
                    unit="points/game",
                    sample_size=summaries[1][1],
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                )
            )
        return evidence, _execution_record(
            "join_schedule_context", execution_id, parameters, evidence, selected_manifests, started_at, started
        )

    def _enrich_representative_plays(
        self,
        plays: list[PlayEvidence],
        participation: pl.DataFrame | None,
        ftn: pl.DataFrame | None,
    ) -> list[PlayEvidence]:
        participation_fields = {
            "defenders_in_box": ("defenders_in_box", _row_integer),
            "pass_rushers": ("number_of_pass_rushers", _row_integer),
            "route": ("route", _row_text),
            "coverage_type": ("defense_coverage_type", _row_text),
            "man_zone": ("defense_man_zone_type", _row_text),
            "pressure": ("was_pressure", _row_boolean),
            "time_to_throw": ("time_to_throw", _row_number),
            "defensive_personnel": ("defense_personnel", _row_text),
            "offense_names": ("offense_names", _row_text_list),
            "offense_positions": ("offense_positions", _row_text_list),
            "defense_names": ("defense_names", _row_text_list),
            "defense_positions": ("defense_positions", _row_text_list),
        }
        ftn_fields = {
            "no_huddle": ("is_no_huddle", _row_boolean),
            "motion": ("is_motion", _row_boolean),
            "play_action": ("is_play_action", _row_boolean),
            "rpo": ("is_rpo", _row_boolean),
            "screen": ("is_screen_pass", _row_boolean),
            "catchable_ball": ("is_catchable_ball", _row_boolean),
            "receiver_drop": ("is_drop", _row_boolean),
            "pass_rushers": ("n_pass_rushers", _row_integer),
            "starting_hash": ("starting_hash", _row_text),
            "qb_location": ("qb_location", _row_text),
            "offense_backfield_count": ("n_offense_backfield", _row_integer),
            "defense_box_count": ("n_defense_box", _row_integer),
            "blitzers": ("n_blitzers", _row_integer),
            "trick_play": ("is_trick_play", _row_boolean),
            "qb_out_of_pocket": ("is_qb_out_of_pocket", _row_boolean),
            "interception_worthy": ("is_interception_worthy", _row_boolean),
            "throw_away": ("is_throw_away", _row_boolean),
            "read_thrown": ("read_thrown", _row_text),
            "contested_ball": ("is_contested_ball", _row_boolean),
            "created_reception": ("is_created_reception", _row_boolean),
            "qb_sneak": ("is_qb_sneak", _row_boolean),
            "qb_fault_sack": ("is_qb_fault_sack", _row_boolean),
        }

        def index(frame: pl.DataFrame | None, value_columns: list[str]) -> dict[tuple[str, int], dict[str, Any]]:
            if frame is None or frame.is_empty():
                return {}
            game_column = _first_column(frame, "nflverse_game_id", "game_id")
            play_column = _first_column(frame, "nflverse_play_id", "play_id")
            if not game_column or not play_column:
                return {}
            selected_columns = list(
                dict.fromkeys([game_column, play_column, *(column for column in value_columns if column in frame.columns)])
            )
            return {
                (str(row[game_column]), int(row[play_column])): row
                for row in frame.select(selected_columns).iter_rows(named=True)
                if row.get(game_column) is not None and row.get(play_column) is not None
            }

        participation_rows = index(participation, [source for source, _ in participation_fields.values()])
        ftn_rows = index(ftn, [source for source, _ in ftn_fields.values()])
        enriched: list[PlayEvidence] = []
        for play in plays:
            visualization = play.visualization or PlayVisualization()
            updates: dict[str, Any] = {}
            participation_row = participation_rows.get((play.game_id, play.play_id), {})
            ftn_row = ftn_rows.get((play.game_id, play.play_id), {})
            source_packages = list(visualization.source_packages)
            if participation_row:
                source_packages.append("participation")
            if ftn_row:
                source_packages.append("ftn_charting")
            for target, (source, converter) in participation_fields.items():
                value = converter(participation_row, source)
                if value is not None:
                    updates[target] = value
            for target, (source, converter) in ftn_fields.items():
                value = converter(ftn_row, source)
                if value is not None and target not in updates:
                    updates[target] = value
            updates["source_packages"] = list(dict.fromkeys(source_packages))
            enriched.append(play.model_copy(update={"visualization": visualization.model_copy(update=updates)}))
        return enriched
