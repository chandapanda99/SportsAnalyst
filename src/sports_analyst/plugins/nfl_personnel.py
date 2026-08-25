"""Player-week, usage, availability, and lineup-continuity tools."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

import polars as pl

from sports_analyst.models import (
    AggregateEvidence,
    AnalysisWindow,
    DatasetManifest,
    ToolExecutionRecord,
    stable_id,
)
from sports_analyst.plugins.nfl_player_weeks import (
    PlayerWeekLayer,
    summarize_lineup_continuity,
    summarize_player_usage,
    summarize_position_availability,
)
from sports_analyst.plugins.nfl_shared import (
    _execution_record,
    _first_column,
    _sha,
)


class NFLPersonnelMixin:
    """Provide normalized player and personnel analysis methods."""

    def _player_week_coverage(
        self,
        team: str,
        windows: list[AnalysisWindow],
        layer: PlayerWeekLayer,
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {
            "team": team,
            "windows": [window.model_dump() for window in windows],
            "sources": layer.source_rows,
        }
        execution_id = stable_id("execution", {"tool": "build_player_week_dataset", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        frame = layer.frame
        evidence: list[AggregateEvidence] = []
        if not frame.is_empty():
            resolved_rows = frame.filter(~pl.col("player_id").str.starts_with("NAME:")).height
            coverage = resolved_rows / frame.height
            payload = {
                "tool": "build_player_week_dataset",
                **parameters,
                "player_weeks": frame.height,
                "identity_resolution_rate": coverage,
            }
            evidence.extend(
                [
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", {**payload, "metric": "normalized_player_weeks"}),
                        metric="normalized_player_weeks",
                        label="Normalized player-week records",
                        value=frame.height,
                        unit="player-weeks",
                        sample_size=frame.height,
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=layer.caveats,
                    ),
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", {**payload, "metric": "player_identity_resolution_rate"}),
                        metric="player_identity_resolution_rate",
                        label="Canonical player-ID coverage",
                        value=round(coverage, 4),
                        unit="share of player-weeks",
                        sample_size=frame.height,
                        row_set_sha256=_sha({**payload, "resolved_rows": resolved_rows}),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=[layer.caveats[1]],
                    ),
                ]
            )
        return evidence, _execution_record(
            "build_player_week_dataset", execution_id, parameters, evidence, manifests, started_at, started
        )

    def _depth_chart_context(
        self,
        layer: PlayerWeekLayer,
        windows: list[AnalysisWindow],
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if not layer.source_rows.get("depth_charts") or layer.frame.is_empty() or "depth_rank" not in layer.frame.columns:
            return None
        parameters = {"windows": [window.model_dump() for window in windows], "starter_rank": 1}
        execution_id = stable_id("execution", {"tool": "join_depth_chart_context", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        summaries: list[tuple[float, set[str], int]] = []
        for window in windows:
            scoped = layer.frame.filter(
                (pl.col("season") == window.season)
                & pl.col("week").is_between(window.weeks[0], window.weeks[1], closed="both")
                & pl.col("depth_rank").is_not_null()
                & (pl.col("depth_rank") <= 1)
            )
            available = scoped.filter(~pl.col("unavailable")).height
            summaries.append((available / scoped.height if scoped.height else 0.0, set(scoped["player_id"].to_list()), scoped.height))
        if not summaries[0][2] or not summaries[1][2]:
            return None
        returning = len(summaries[0][1] & summaries[1][1]) / len(summaries[1][1]) if summaries[1][1] else 0.0
        evidence: list[AggregateEvidence] = []
        values = (
            (
                "depth_chart_starter_availability",
                "First-unit depth-chart availability",
                summaries[0][0],
                summaries[1][0],
                summaries[1][2],
                "share of starter player-weeks",
            ),
            (
                "depth_chart_starter_continuity",
                "Returning first-unit depth-chart players",
                None,
                returning,
                len(summaries[1][1]),
                "share of comparison starters",
            ),
        )
        for metric, label, baseline_value, comparison_value, sample_size, unit in values:
            payload = {"tool": "join_depth_chart_context", "metric": metric, **parameters}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric=metric,
                    label=label,
                    value=round(comparison_value - baseline_value, 4) if baseline_value is not None else round(comparison_value, 4),
                    baseline_value=round(baseline_value, 4) if baseline_value is not None else None,
                    comparison_value=round(comparison_value, 4),
                    unit=unit,
                    sample_size=sample_size,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in manifests],
                    tool_execution_id=execution_id,
                    caveats=["Depth-chart rank identifies listed role, not the exact starter on every play."],
                )
            )
        return evidence, _execution_record(
            "join_depth_chart_context", execution_id, parameters, evidence, manifests, started_at, started
        )

    def _player_usage_change(
        self,
        layer: PlayerWeekLayer,
        windows: list[AnalysisWindow],
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {
            "windows": [window.model_dump() for window in windows],
            "minimum_opportunities": 5,
            "maximum_players_per_metric": 8,
        }
        execution_id = stable_id("execution", {"tool": "compare_player_usage", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        baseline = summarize_player_usage(layer.frame, windows[0])
        comparison = summarize_player_usage(layer.frame, windows[1])
        players = set(baseline) | set(comparison)
        metrics = (
            ("player_opportunity_share", "opportunity_share", "opportunities", "opportunity share", "share of team targets + carries"),
            ("receiver_target_share", "target_share", "targets", "target share", "share of team targets"),
            ("player_carry_share", "carry_share", "carries", "carry share", "share of team carries"),
            ("quarterback_dropback_share", "dropback_share", "dropbacks", "dropback share", "share of team QB dropbacks"),
            (
                "player_opportunities_per_100_snaps",
                "opportunities_per_100_snaps",
                "opportunities",
                "opportunities per 100 snaps",
                "opportunities/100 snaps",
            ),
            (
                "player_epa_per_opportunity",
                "epa_per_opportunity",
                "opportunities",
                "EPA per opportunity",
                "EPA/opportunity",
            ),
        )
        evidence: list[AggregateEvidence] = []
        for metric, value_key, sample_key, label_suffix, unit in metrics:
            candidates = []
            for player_id in players:
                base = baseline.get(player_id, {})
                comp = comparison.get(player_id, {})
                base_sample = int(base.get(sample_key, 0) or 0)
                comp_sample = int(comp.get(sample_key, 0) or 0)
                base_value = base.get(value_key)
                comp_value = comp.get(value_key)
                if max(base_sample, comp_sample) < 5 or (base_value is None and comp_value is None):
                    continue
                base_number = float(base_value or 0)
                comp_number = float(comp_value or 0)
                candidates.append((abs(comp_number - base_number), player_id, base_number, comp_number, base_sample, comp_sample))
            for _, player_id, base_value, comp_value, _base_sample, comp_sample in sorted(
                candidates, key=lambda item: (-item[0], item[1])
            )[:8]:
                player = comparison.get(player_id) or baseline[player_id]
                player_name = str(player.get("player_name") or player_id)
                payload = {
                    "tool": "compare_player_usage",
                    "metric": metric,
                    "player_id": player_id,
                    "windows": parameters["windows"],
                    "baseline": base_value,
                    "comparison": comp_value,
                }
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=metric,
                        label=f"{player_name} {label_suffix}",
                        value=round(comp_value - base_value, 4),
                        baseline_value=round(base_value, 4),
                        comparison_value=round(comp_value, 4),
                        unit=unit,
                        sample_size=comp_sample,
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=[
                            "Usage identifies recorded primary play participants; it does not reconstruct every player's assignment."
                        ],
                    )
                )
        return evidence, _execution_record(
            "compare_player_usage", execution_id, parameters, evidence, manifests, started_at, started
        )

    def _position_group_availability(
        self,
        layer: PlayerWeekLayer,
        windows: list[AnalysisWindow],
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord] | None:
        if not layer.source_rows.get("injuries") and not layer.source_rows.get("weekly_rosters"):
            return None
        parameters = {"windows": [window.model_dump() for window in windows], "unavailable_status_severity": 2}
        execution_id = stable_id("execution", {"tool": "analyze_position_group_availability", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        baseline = summarize_position_availability(layer.frame, windows[0])
        comparison = summarize_position_availability(layer.frame, windows[1])
        evidence: list[AggregateEvidence] = []
        for group in sorted(set(baseline) | set(comparison)):
            base = baseline.get(group)
            comp = comparison.get(group)
            if not base or not comp or base["availability_rate"] is None or comp["availability_rate"] is None:
                continue
            base_value = float(base["availability_rate"])
            comp_value = float(comp["availability_rate"])
            payload = {
                "tool": "analyze_position_group_availability",
                "position_group": group,
                "windows": parameters["windows"],
                "baseline": base_value,
                "comparison": comp_value,
            }
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric="position_group_availability_rate",
                    label=f"{group} recorded availability",
                    value=round(comp_value - base_value, 4),
                    baseline_value=round(base_value, 4),
                    comparison_value=round(comp_value, 4),
                    unit="share of expected player-week participation",
                    sample_size=int(comp["player_weeks"]),
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in manifests],
                    tool_execution_id=execution_id,
                    caveats=[
                        "Availability uses recorded injury designations and median healthy-week snaps when available.",
                        "A designation is not a medical finding and does not prove that availability caused a performance change.",
                    ],
                )
            )
        return evidence, _execution_record(
            "analyze_position_group_availability", execution_id, parameters, evidence, manifests, started_at, started
        )

    def _lineup_continuity(
        self,
        layer: PlayerWeekLayer,
        windows: list[AnalysisWindow],
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], list[ToolExecutionRecord]] | None:
        if not layer.source_rows.get("snap_counts") and not layer.source_rows.get("participation"):
            return None
        parameters = {"windows": [window.model_dump() for window in windows], "weight": "recorded_relevant_snaps"}
        continuity_id = stable_id("execution", {"tool": "analyze_lineup_continuity", **parameters})
        decomposition_id = stable_id("execution", {"tool": "decompose_lineup_continuity", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        summary = summarize_lineup_continuity(layer.frame, windows[0], windows[1])
        if not summary["overall"]["comparison_snaps"]:
            return None
        continuity_evidence: list[AggregateEvidence] = []
        for group, values in [("Overall", summary["overall"]), *sorted(summary["groups"].items())]:
            for metric, label, value_key in (
                ("lineup_returning_snap_share", "returning snap share", "returning_snap_share"),
                ("lineup_weighted_jaccard", "snap-distribution similarity", "weighted_jaccard"),
            ):
                value = float(values[value_key])
                payload = {
                    "tool": "analyze_lineup_continuity",
                    "metric": metric,
                    "position_group": group,
                    "windows": parameters["windows"],
                    "value": value,
                }
                continuity_evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=metric,
                        label=f"{group} {label}",
                        value=round(value - 1, 4),
                        baseline_value=1.0,
                        comparison_value=round(value, 4),
                        unit="share of comparison player-snaps",
                        sample_size=int(values["comparison_snaps"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=continuity_id,
                        caveats=[
                            "The 1.0 baseline is a continuity reference, not an observed baseline-season continuity estimate.",
                            (
                                "Participation rows provide recorded play-level lineup counts."
                                if layer.source_rows.get("participation")
                                else "Game-level snap counts support weekly continuity, not exact 11-player combinations on each play."
                            ),
                        ],
                    )
                )
        decomposition_evidence: list[AggregateEvidence] = []
        for group, contribution in sorted(
            summary["turnover_contributions"].items(), key=lambda item: (-item[1], item[0])
        ):
            payload = {
                "tool": "decompose_lineup_continuity",
                "position_group": group,
                "windows": parameters["windows"],
                "turnover_contribution": contribution,
            }
            decomposition_evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric="lineup_turnover_position_contribution",
                    label=f"{group} contribution to lineup turnover",
                    value=round(float(contribution), 4),
                    unit="share of all comparison player-snaps",
                    sample_size=int(summary["overall"]["comparison_snaps"]),
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in manifests],
                    tool_execution_id=decomposition_id,
                    caveats=["Contributions describe where new-player snaps occurred and do not measure player quality."],
                )
            )
        evidence = [*continuity_evidence, *decomposition_evidence]
        executions = [
            _execution_record(
                "analyze_lineup_continuity",
                continuity_id,
                parameters,
                continuity_evidence,
                manifests,
                started_at,
                started,
            ),
            _execution_record(
                "decompose_lineup_continuity",
                decomposition_id,
                parameters,
                decomposition_evidence,
                manifests,
                started_at,
                started,
            ),
        ]
        return evidence, executions

    def _player_usage(
        self,
        baseline: pl.DataFrame,
        comparison: pl.DataFrame,
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"unit": "target_share", "minimum_targets": 5}
        execution_id = stable_id("execution", {"tool": "compare_player_usage", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        id_column = _first_column(comparison, "receiver_player_id", "receiver_id")
        name_column = _first_column(comparison, "receiver_player_name", "receiver_name")
        baseline_id = _first_column(baseline, "receiver_player_id", "receiver_id")
        baseline_name = _first_column(baseline, "receiver_player_name", "receiver_name")
        if name_column and baseline_name:
            join_column = "player_key"

            def usage(frame: pl.DataFrame, player_id: str | None, player_name: str) -> pl.DataFrame:
                key = pl.col(player_id).cast(pl.Utf8) if player_id else pl.col(player_name).cast(pl.Utf8)
                return (
                    frame.filter(pl.col(player_name).is_not_null())
                    .with_columns(key.alias(join_column), pl.col(player_name).cast(pl.Utf8).alias("player_name"))
                    .group_by(join_column)
                    .agg(pl.first("player_name"), pl.len().alias("targets"), pl.col("_epa").mean().alias("epa"))
                )

            base = usage(baseline, baseline_id, baseline_name)
            comp = usage(comparison, id_column, name_column)
            joined = base.join(comp, on=join_column, how="inner", suffix="_comparison").filter(
                (pl.col("targets") >= 5) | (pl.col("targets_comparison") >= 5)
            )
            rows = []
            for row in joined.iter_rows(named=True):
                baseline_share = row["targets"] / baseline.height
                comparison_share = row["targets_comparison"] / comparison.height
                rows.append((abs(comparison_share - baseline_share), row, baseline_share, comparison_share))
            for _magnitude, row, baseline_share, comparison_share in sorted(rows, key=lambda item: (-item[0], item[1][join_column]))[:8]:
                payload = {"tool": "compare_player_usage", "player": row[join_column]}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric="receiver_target_share",
                        label=f"{row.get('player_name_comparison') or row['player_name']} target share",
                        value=round(comparison_share - baseline_share, 4),
                        baseline_value=round(baseline_share, 4),
                        comparison_value=round(comparison_share, 4),
                        unit="share of team dropbacks",
                        sample_size=int(row["targets_comparison"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("compare_player_usage", execution_id, parameters, evidence, manifests, started_at, started)

    def _qb_receiver_pairs(
        self,
        baseline: pl.DataFrame,
        comparison: pl.DataFrame,
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"metric": "epa_per_target", "minimum_targets": 5}
        execution_id = stable_id("execution", {"tool": "analyze_qb_receiver_pairs", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        passer = _first_column(comparison, "passer_player_name", "passer_name")
        receiver = _first_column(comparison, "receiver_player_name", "receiver_name")
        base_passer = _first_column(baseline, "passer_player_name", "passer_name")
        base_receiver = _first_column(baseline, "receiver_player_name", "receiver_name")
        if passer and receiver and base_passer and base_receiver:

            def pairs(frame: pl.DataFrame, qb: str, target: str) -> pl.DataFrame:
                return (
                    frame.filter(pl.col(qb).is_not_null() & pl.col(target).is_not_null())
                    .with_columns(
                        pl.col(qb).cast(pl.Utf8).alias("quarterback"),
                        pl.col(target).cast(pl.Utf8).alias("receiver"),
                    )
                    .group_by("quarterback", "receiver")
                    .agg(pl.len().alias("targets"), pl.col("_epa").mean().alias("epa"))
                )

            joined = (
                pairs(baseline, base_passer, base_receiver)
                .join(pairs(comparison, passer, receiver), on=["quarterback", "receiver"], how="inner", suffix="_comparison")
                .filter((pl.col("targets") >= 5) | (pl.col("targets_comparison") >= 5))
            )
            rows = sorted(
                joined.iter_rows(named=True),
                key=lambda row: (-int(row["targets_comparison"]), row["quarterback"], row["receiver"]),
            )[:8]
            for row in rows:
                payload = {"tool": "analyze_qb_receiver_pairs", "qb": row["quarterback"], "receiver": row["receiver"]}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric="qb_receiver_epa_per_target",
                        label=f"{row['quarterback']} → {row['receiver']}",
                        value=round(float(row["epa_comparison"] - row["epa"]), 4),
                        baseline_value=round(float(row["epa"]), 4),
                        comparison_value=round(float(row["epa_comparison"]), 4),
                        unit="EPA/target",
                        sample_size=int(row["targets_comparison"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("analyze_qb_receiver_pairs", execution_id, parameters, evidence, manifests, started_at, started)
