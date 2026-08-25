"""Trend, outlier, benchmark, split, and change-point analysis tools."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import polars as pl

from sports_analyst.models import (
    AggregateEvidence,
    AnalysisWindow,
    DatasetManifest,
    ToolExecutionRecord,
    stable_id,
)
from sports_analyst.plugins.nfl_shared import (
    HIGHER_IS_BETTER,
    METRICS,
    SPLIT_COLUMNS,
    SPLIT_DIMENSIONS,
    TEAM_CONFERENCES,
    _bootstrap_mean,
    _execution_record,
    _game_bootstrap,
    _metric_value,
    _scope_plays,
    _sha,
)


class NFLTrendMixin:
    """Provide deterministic time-series and situational analysis methods."""

    def _season_trends(
        self,
        frames: dict[int, pl.DataFrame],
        metrics: list[str],
        manifests: list[DatasetManifest],
        team: str,
        season_type: str,
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"team": team, "season_type": season_type, "seasons": sorted(frames), "metrics": metrics}
        execution_id = stable_id("execution", {"tool": "analyze_season_trends", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        for season, frame in sorted(frames.items()):
            for index, metric in enumerate(metrics):
                source, label = METRICS[metric]
                value = _metric_value(frame, source)
                if value is None:
                    continue
                low, high = _game_bootstrap(frame, source, seed=season * 100 + index)
                payload = {"tool": "analyze_season_trends", "team": team, "season": season, "metric": metric}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"seasonal_{metric}",
                        label=f"{season} · {label}",
                        value=round(value, 4),
                        unit="rate" if "rate" in metric or metric in {"success_rate", "cpoe"} else "per play",
                        sample_size=frame.height,
                        confidence_low=round(low, 4) if low is not None else None,
                        confidence_high=round(high, 4) if high is not None else None,
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests if item.season == season],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("analyze_season_trends", execution_id, parameters, evidence, manifests, started_at, started)

    def _weekly_trends(
        self,
        frames: list[pl.DataFrame],
        windows: list[AnalysisWindow],
        metric: str,
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        moving_average_weeks = 3
        parameters = {
            "metric": metric,
            "windows": [window.model_dump() for window in windows],
            "moving_average_weeks": moving_average_weeks,
            "classification": "direction agreement across aligned weeks",
        }
        execution_id = stable_id("execution", {"tool": "analyze_weekly_trends", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        column = f"_{METRICS[metric][0]}"
        evidence: list[AggregateEvidence] = []
        window_series: list[list[dict[str, Any]]] = []
        for window, frame in zip(windows, frames, strict=True):
            if "week" not in frame.columns or column not in frame.columns:
                window_series.append([])
                continue
            weekly = frame.group_by("week").agg(pl.col(column).mean().alias("value"), pl.col(column).count().alias("n")).sort("week")
            rows = list(weekly.iter_rows(named=True))
            window_series.append(rows)
            for row_index, row in enumerate(rows):
                values = [float(value) for value in frame.filter(pl.col("week") == row["week"])[column].drop_nulls().to_list()]
                confidence_low, confidence_high = _bootstrap_mean(
                    values,
                    seed=window.season * 1000 + int(row["week"]) * 10 + list(METRICS).index(metric),
                )
                payload = {"tool": "analyze_weekly_trends", "metric": metric, "window": window.model_dump(), "week": row["week"]}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"weekly_{metric}",
                        label=f"{window.season} week {row['week']} · {METRICS[metric][1]}",
                        value=round(float(row["value"]), 4),
                        unit=METRICS[metric][1],
                        sample_size=int(row["n"]),
                        confidence_low=round(confidence_low, 4) if confidence_low is not None else None,
                        confidence_high=round(confidence_high, 4) if confidence_high is not None else None,
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=["Weekly subgroup has fewer than 10 plays."] if row["n"] < 10 else [],
                    )
                )
                if row_index + 1 >= moving_average_weeks:
                    moving_rows = rows[row_index + 1 - moving_average_weeks : row_index + 1]
                    moving_payload = {
                        "tool": "analyze_weekly_trends",
                        "kind": "moving_average",
                        "metric": metric,
                        "window": window.model_dump(),
                        "through_week": row["week"],
                        "weeks": [item["week"] for item in moving_rows],
                    }
                    evidence.append(
                        AggregateEvidence(
                            evidence_id=stable_id("evidence", moving_payload),
                            metric=f"weekly_moving_average_{metric}",
                            label=f"{window.season} through week {row['week']} · 3-week moving average",
                            value=round(sum(float(item["value"]) for item in moving_rows) / moving_average_weeks, 4),
                            unit=METRICS[metric][1],
                            sample_size=sum(int(item["n"]) for item in moving_rows),
                            row_set_sha256=_sha(moving_payload),
                            dataset_manifest_ids=[item.manifest_id for item in manifests if item.season == window.season],
                            tool_execution_id=execution_id,
                        )
                    )

        if len(window_series) == 2 and all(window_series):
            paired = list(zip(window_series[0], window_series[1], strict=False))
            baseline_mean = sum(float(left["value"]) for left, _right in paired) / len(paired)
            comparison_mean = sum(float(right["value"]) for _left, right in paired) / len(paired)
            overall_change = comparison_mean - baseline_mean
            agreements = [
                (float(right["value"]) - float(left["value"])) * overall_change > 0
                or (float(right["value"]) - float(left["value"]) == overall_change == 0)
                for left, right in paired
            ]
            agreement_rate = sum(agreements) / len(agreements)
            classification = "sustained" if agreement_rate >= 2 / 3 else "mixed" if agreement_rate >= 0.4 else "outlier-concentrated"
            trend_payload = {
                "tool": "analyze_weekly_trends",
                "kind": "classification",
                "metric": metric,
                "windows": [window.model_dump() for window in windows],
                "agreement_rate": agreement_rate,
                "classification": classification,
            }
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", trend_payload),
                    metric=f"weekly_trend_classification_{metric}",
                    label=f"Weekly change pattern: {classification}",
                    value=round(agreement_rate, 4),
                    baseline_value=round(baseline_mean, 4),
                    comparison_value=round(comparison_mean, 4),
                    unit="share of aligned weeks matching the overall direction",
                    sample_size=sum(int(right["n"]) for _left, right in paired),
                    row_set_sha256=_sha(trend_payload),
                    dataset_manifest_ids=[item.manifest_id for item in manifests],
                    tool_execution_id=execution_id,
                    caveats=[
                        "Weeks are aligned by their ordinal position within each window; this is descriptive, not a change-point test."
                    ],
                )
            )
        return evidence, _execution_record("analyze_weekly_trends", execution_id, parameters, evidence, manifests, started_at, started)

    def _game_outliers(
        self,
        baseline: pl.DataFrame,
        comparison: pl.DataFrame,
        window: AnalysisWindow,
        metric: str,
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"metric": metric, "comparison": window.model_dump(), "limit": 6}
        execution_id = stable_id("execution", {"tool": "rank_game_outliers", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        column = f"_{METRICS[metric][0]}"
        baseline_value = _metric_value(baseline, METRICS[metric][0])
        evidence: list[AggregateEvidence] = []
        if baseline_value is not None and {"game_id", column} <= set(comparison.columns):
            games = comparison.group_by("game_id").agg(pl.col(column).mean().alias("value"), pl.col(column).count().alias("n"))
            games = (
                games.with_columns((pl.col("value") - baseline_value).abs().alias("magnitude"))
                .sort(["magnitude", "game_id"], descending=[True, False])
                .head(6)
            )
            for row in games.iter_rows(named=True):
                payload = {"tool": "rank_game_outliers", "metric": metric, "game_id": row["game_id"], "window": window.model_dump()}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"game_outlier_{metric}",
                        label=f"{row['game_id']} · {METRICS[metric][1]}",
                        value=round(float(row["value"] - baseline_value), 4),
                        baseline_value=round(baseline_value, 4),
                        comparison_value=round(float(row["value"]), 4),
                        unit=f"difference from baseline-window {METRICS[metric][1]}",
                        sample_size=int(row["n"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=["Game sample has fewer than 10 qualifying plays."] if row["n"] < 10 else [],
                    )
                )
        return evidence, _execution_record("rank_game_outliers", execution_id, parameters, evidence, manifests, started_at, started)

    def _league_benchmarks(
        self,
        team: str,
        datasets: dict[int, pl.DataFrame],
        windows: list[AnalysisWindow],
        season_type: str,
        metrics: list[str],
        manifests: list[DatasetManifest],
        analysis_domain: str,
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"team": team, "metrics": metrics, "windows": [window.model_dump() for window in windows]}
        execution_id = stable_id("execution", {"tool": "benchmark_against_league", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        for metric in metrics:
            summaries: list[dict[str, float | int] | None] = []
            for window in windows:
                raw = datasets[window.season]
                teams = raw["posteam"].drop_nulls().unique().to_list() if "posteam" in raw.columns else []
                values: dict[str, float] = {}
                counts: dict[str, int] = {}
                for candidate in teams:
                    scoped = _scope_plays(raw, str(candidate), season_type, window.weeks, analysis_domain)
                    value = _metric_value(scoped, METRICS[metric][0])
                    if value is not None and scoped.height >= 30:
                        values[str(candidate)] = value
                        counts[str(candidate)] = scoped.height
                target = values.get(team)
                if target is None or not values:
                    summaries.append(None)
                    continue
                higher_is_better = HIGHER_IS_BETTER[metric] is not False
                ordered = sorted(values, key=values.get, reverse=higher_is_better)
                conference = TEAM_CONFERENCES.get(team)
                conference_values = {
                    candidate: value for candidate, value in values.items() if TEAM_CONFERENCES.get(candidate) == conference
                }
                conference_ordered = sorted(conference_values, key=conference_values.get, reverse=higher_is_better)
                percentile = 100 * sum(value <= target if higher_is_better else value >= target for value in values.values()) / len(values)
                summaries.append(
                    {
                        "league_percentile": percentile,
                        "league_rank": ordered.index(team) + 1,
                        "conference_rank": conference_ordered.index(team) + 1,
                        "league_average_delta": target - (sum(values.values()) / len(values)),
                        "sample": counts[team],
                        "league_teams": len(values),
                        "conference_teams": len(conference_values),
                    }
                )
            if not all(summary is not None for summary in summaries):
                continue
            baseline_summary, comparison_summary = (summary for summary in summaries if summary is not None)
            benchmark_kinds = [
                ("league_percentile", "league percentile", "percentile"),
                ("league_rank", "league rank", "rank (1 is best)"),
                ("conference_rank", f"{TEAM_CONFERENCES.get(team, 'conference')} rank", "rank (1 is best)"),
                ("league_average_delta", "distance from league average", METRICS[metric][1]),
            ]
            for kind, label, unit in benchmark_kinds:
                baseline_value = float(baseline_summary[kind])
                comparison_value = float(comparison_summary[kind])
                payload = {"tool": "benchmark_against_league", "metric": metric, "kind": kind, **parameters}
                population = (
                    int(comparison_summary["conference_teams"]) if kind == "conference_rank" else int(comparison_summary["league_teams"])
                )
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"{kind}_{metric}",
                        label=f"{METRICS[metric][1]} {label}",
                        value=round(comparison_value - baseline_value, 4),
                        baseline_value=round(baseline_value, 4),
                        comparison_value=round(comparison_value, 4),
                        unit=unit,
                        sample_size=int(comparison_summary["sample"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=[f"Benchmark includes {population} teams with at least 30 qualifying dropbacks."],
                    )
                )
        return evidence, _execution_record("benchmark_against_league", execution_id, parameters, evidence, manifests, started_at, started)

    def _situational_splits(
        self,
        baseline: pl.DataFrame,
        comparison: pl.DataFrame,
        metric: str,
        splits: list[str],
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"metric": metric, "splits": splits, "minimum_subgroup_sample": 10}
        execution_id = stable_id("execution", {"tool": "analyze_situational_split", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        metric_column = f"_{METRICS[metric][0]}"
        evidence: list[AggregateEvidence] = []
        for split in splits:
            split_column = SPLIT_COLUMNS[split]
            if {split_column, metric_column} - set(baseline.columns) or {split_column, metric_column} - set(comparison.columns):
                continue
            base = (
                baseline.filter(pl.col(split_column).is_not_null())
                .group_by(split_column)
                .agg(pl.col(metric_column).mean().alias("value"), pl.col(metric_column).count().alias("n"))
            )
            comp = (
                comparison.filter(pl.col(split_column).is_not_null())
                .group_by(split_column)
                .agg(pl.col(metric_column).mean().alias("value"), pl.col(metric_column).count().alias("n"))
            )
            joined = (
                base.join(comp, on=split_column, how="inner", suffix="_comparison")
                .filter((pl.col("n") >= 10) & (pl.col("n_comparison") >= 10))
                .sort(split_column)
            )
            for row in joined.iter_rows(named=True):
                payload = {
                    "tool": "analyze_situational_split",
                    "metric": metric,
                    "split": split,
                    "value": row[split_column],
                }
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"situational_{metric}__{split}",
                        label=f"{SPLIT_DIMENSIONS[split][0]}: {row[split_column]}",
                        value=round(float(row["value_comparison"] - row["value"]), 4),
                        baseline_value=round(float(row["value"]), 4),
                        comparison_value=round(float(row["value_comparison"]), 4),
                        unit=METRICS[metric][1],
                        sample_size=int(row["n_comparison"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("analyze_situational_split", execution_id, parameters, evidence, manifests, started_at, started)

    def _play_mix(
        self,
        baseline: pl.DataFrame,
        comparison: pl.DataFrame,
        splits: list[str],
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"splits": splits}
        execution_id = stable_id("execution", {"tool": "compare_play_mix", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        for split in splits:
            column = SPLIT_COLUMNS[split]
            if column not in baseline.columns or column not in comparison.columns:
                continue
            base = baseline.filter(pl.col(column).is_not_null()).group_by(column).len().rename({"len": "n"})
            comp = comparison.filter(pl.col(column).is_not_null()).group_by(column).len().rename({"len": "n"})
            joined = (
                base.join(comp, on=column, how="inner", suffix="_comparison")
                .filter((pl.col("n") >= 10) & (pl.col("n_comparison") >= 10))
                .sort(column)
            )
            for row in joined.iter_rows(named=True):
                baseline_share = row["n"] / baseline.height
                comparison_share = row["n_comparison"] / comparison.height
                payload = {"tool": "compare_play_mix", "split": split, "value": row[column]}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"play_mix_{split}",
                        label=f"{SPLIT_DIMENSIONS[split][0]} mix: {row[column]}",
                        value=round(comparison_share - baseline_share, 4),
                        baseline_value=round(baseline_share, 4),
                        comparison_value=round(comparison_share, 4),
                        unit="share of dropbacks",
                        sample_size=int(row["n_comparison"]),
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                    )
                )
        return evidence, _execution_record("compare_play_mix", execution_id, parameters, evidence, manifests, started_at, started)

    def _change_points(
        self,
        frame: pl.DataFrame,
        window: AnalysisWindow,
        metric: str,
        manifests: list[DatasetManifest],
    ) -> tuple[list[AggregateEvidence], ToolExecutionRecord]:
        parameters = {"metric": metric, "window": window.model_dump()}
        execution_id = stable_id("execution", {"tool": "identify_change_points", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        column = f"_{METRICS[metric][0]}"
        if "week" in frame.columns and column in frame.columns:
            weekly = frame.group_by("week").agg(pl.col(column).mean().alias("value")).drop_nulls().sort("week")
            rows = list(weekly.iter_rows(named=True))
            candidates = []
            for index in range(2, len(rows) - 1):
                before = sum(float(row["value"]) for row in rows[:index]) / index
                after = sum(float(row["value"]) for row in rows[index:]) / (len(rows) - index)
                candidates.append((abs(after - before), index, before, after))
            if candidates:
                _magnitude, index, before, after = max(candidates)
                boundary = int(rows[index]["week"])
                payload = {"tool": "identify_change_points", "metric": metric, "window": window.model_dump(), "week": boundary}
                evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"change_point_{metric}",
                        label=f"Candidate change point before week {boundary}",
                        value=round(after - before, 4),
                        baseline_value=round(before, 4),
                        comparison_value=round(after, 4),
                        unit=METRICS[metric][1],
                        sample_size=frame.height,
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in manifests],
                        tool_execution_id=execution_id,
                        caveats=["The boundary is descriptive and was selected from the observed weekly series; it is not causal."],
                    )
                )
        return evidence, _execution_record("identify_change_points", execution_id, parameters, evidence, manifests, started_at, started)
