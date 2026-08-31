"""Build representative-play evidence and deterministic chart artifacts."""

from __future__ import annotations

import polars as pl

from sports_analyst.evidence_selection import EvidenceCandidate, select_diverse_evidence
from sports_analyst.models import (
    AggregateEvidence,
    AnalysisWindow,
    ChartArtifact,
    DatasetManifest,
    PlayEvidence,
    PlayVisualization,
    stable_id,
)
from sports_analyst.plugins.nfl_shared import (
    METRICS,
    _metric_value,
    _row_boolean,
    _row_integer,
    _row_number,
    _row_text,
)


class NFLPresentationMixin:
    """Provide evidence selection and report-chart construction methods."""

    def _representative_plays(
        self,
        frame: pl.DataFrame,
        team: str,
        manifest: DatasetManifest,
        execution_id: str,
        minimum_absolute_epa: float = 0,
        baseline_frame: pl.DataFrame | None = None,
        baseline_manifest: DatasetManifest | None = None,
        primary_source: str = "epa",
        metric_label: str = "EPA",
        per_window: int = 4,
    ) -> list[PlayEvidence]:
        required = {"game_id", "play_id", "_epa"}
        if not required <= set(frame.columns):
            return []
        sources = [("comparison", frame, manifest)]
        if baseline_frame is not None and baseline_manifest is not None and required <= set(baseline_frame.columns):
            sources.insert(0, ("baseline", baseline_frame, baseline_manifest))
        metric_column = f"_{primary_source}"
        candidates: list[EvidenceCandidate] = []
        for window, source_frame, source_manifest in sources:
            scoped = source_frame.filter(pl.col("_epa").is_not_null() & (pl.col("_epa").abs() >= minimum_absolute_epa))
            for row in scoped.iter_rows(named=True):
                metric_value = row.get(metric_column)
                if primary_source == "plays_per_game" or metric_value is None:
                    metric_value = row.get("_epa")
                numeric_metric = float(metric_value) if metric_value is not None else None
                relevance = abs(numeric_metric or 0.0)
                if primary_source in {"yards_gained", "air_yards", "yards_after_catch"}:
                    relevance /= 10
                elif primary_source == "cpoe":
                    relevance /= 20
                flags = {
                    "interception": row.get("interception"),
                    "sack": row.get("sack"),
                    "fumble": row.get("fumble_lost"),
                    "touchdown": row.get("touchdown"),
                    "explosive": row.get("_explosive"),
                }
                event_type = next((name for name, value in flags.items() if value), str(row.get("play_type") or "play"))
                context_fields = ("week", "qtr", "down", "ydstogo", "yardline_100", "score_differential", "desc")
                context_quality = sum(row.get(name) is not None for name in context_fields) / len(context_fields)
                candidates.append(
                    EvidenceCandidate(
                        key=f"{source_manifest.season}:{row['game_id']}:{row['play_id']}",
                        window=window,
                        game_id=str(row["game_id"]),
                        event_type=event_type,
                        payload=(row, source_manifest),
                        outcome_value=numeric_metric,
                        relevance=relevance,
                        context_quality=context_quality,
                        opponent=str(row.get("defteam") or ""),
                        period=str(row.get("qtr") or ""),
                    )
                )
        selected = select_diverse_evidence(candidates, metric_label=metric_label, per_window=per_window)
        records = []
        for selection in selected:
            row, source_manifest = selection.candidate.payload
            payload = {"season": source_manifest.season, "game_id": row["game_id"], "play_id": row["play_id"]}
            turnover_values = [row.get(name) for name in ("interception", "fumble_lost")]
            turnover = any(bool(value) for value in turnover_values) if any(value is not None for value in turnover_values) else None
            visualization = PlayVisualization(
                source_packages=["play_by_play"],
                week=_row_integer(row, "week"),
                quarter=_row_integer(row, "qtr"),
                clock=_row_text(row, "game_clock") or _row_text(row, "time"),
                down=_row_integer(row, "down"),
                yards_to_go=_row_number(row, "ydstogo"),
                yardline_100=_row_number(row, "yardline_100"),
                possession_team=_row_text(row, "posteam"),
                defensive_team=_row_text(row, "defteam"),
                possession_score=_row_integer(row, "posteam_score"),
                defensive_score=_row_integer(row, "defteam_score"),
                possession_timeouts=_row_integer(row, "posteam_timeouts_remaining"),
                defensive_timeouts=_row_integer(row, "defteam_timeouts_remaining"),
                score_differential=_row_number(row, "score_differential"),
                goal_to_go=_row_boolean(row, "goal_to_go"),
                play_type=_row_text(row, "play_type"),
                formation=_row_text(row, "offense_formation"),
                personnel=_row_text(row, "offense_personnel"),
                shotgun=_row_boolean(row, "shotgun"),
                no_huddle=_row_boolean(row, "no_huddle"),
                pass_length=_row_text(row, "pass_length"),
                pass_location=_row_text(row, "pass_location"),
                run_location=_row_text(row, "run_location"),
                run_gap=_row_text(row, "run_gap"),
                air_yards=_row_number(row, "air_yards"),
                yards_after_catch=_row_number(row, "yards_after_catch"),
                yards_gained=_row_number(row, "yards_gained"),
                complete_pass=_row_boolean(row, "complete_pass"),
                interception=_row_boolean(row, "interception"),
                fumble=_row_boolean(row, "fumble"),
                fumble_lost=_row_boolean(row, "fumble_lost"),
                return_yards=_row_number(row, "return_yards"),
                return_team=_row_text(row, "return_team"),
                turnover_player=_row_text(row, "interception_player_name")
                or _row_text(row, "fumble_recovery_1_player_name"),
                recovery_player=_row_text(row, "fumble_recovery_1_player_name"),
                recovery_team=_row_text(row, "fumble_recovery_1_team"),
                recovery_yards=_row_number(row, "fumble_recovery_1_yards"),
                passer=_row_text(row, "passer_player_name"),
                receiver=_row_text(row, "receiver_player_name"),
                rusher=_row_text(row, "rusher_player_name"),
                touchdown=_row_boolean(row, "touchdown"),
                turnover=turnover,
                sack=_row_boolean(row, "sack"),
                penalty=_row_boolean(row, "penalty"),
                first_down=_row_boolean(row, "first_down"),
                win_probability=_row_number(row, "wp"),
                win_probability_added=_row_number(row, "wpa"),
            )
            records.append(
                PlayEvidence(
                    evidence_id=stable_id("play", payload),
                    season=source_manifest.season,
                    game_id=str(row["game_id"]),
                    play_id=int(row["play_id"]),
                    team=team,
                    description=str(row.get("desc") or "Play description unavailable"),
                    epa=round(float(row["_epa"]), 4) if row["_epa"] is not None else None,
                    supporting=selection.role != "counterexample",
                    window=selection.candidate.window,
                    evidence_role=selection.role,
                    selection_reason=selection.reason,
                    selection_metric=selection.selection_metric,
                    candidate_pool_size=selection.candidate_pool_size,
                    selector_version=selection.selector_version,
                    dataset_manifest_id=source_manifest.manifest_id,
                    tool_execution_id=execution_id,
                    visualization=visualization,
                )
            )
        return records

    def _charts(
        self,
        evidence: list[AggregateEvidence],
        baseline: pl.DataFrame,
        comparison: pl.DataFrame,
        windows: list[AnalysisWindow],
        season_frames: dict[int, pl.DataFrame] | None = None,
        primary_metric: str = "epa_per_dropback",
        analysis_domain: str = "passing",
    ) -> list[ChartArtifact]:
        domain_title = {"passing": "Passing efficiency", "rushing": "Rushing performance", "offense": "Overall offense"}[analysis_domain]
        window_labels = [f"{window.season} W{window.weeks[0]}–{window.weeks[1]}" for window in windows]
        metric_items = [item for item in evidence if item.metric in METRICS]
        if season_frames:
            values = [
                {"metric": item.label, "season": season, "value": _metric_value(frame, METRICS[item.metric][0])}
                for item in metric_items
                for season, frame in sorted(season_frames.items())
            ]
            series_field = "season"
            chart_title = f"All seasons · {domain_title} comparison"
            chart_evidence_ids = [item.evidence_id for item in evidence if item.metric.startswith("seasonal_")]
        else:
            values = [
                record
                for item in metric_items
                for record in (
                    {"metric": item.label, "window": window_labels[0], "value": item.baseline_value},
                    {"metric": item.label, "window": window_labels[1], "value": item.comparison_value},
                )
            ]
            series_field = "window"
            chart_title = f"{domain_title} comparison"
            chart_evidence_ids = [item.evidence_id for item in metric_items]
        comparison_chart = ChartArtifact(
            chart_id=stable_id(
                "chart",
                {
                    "type": "season-metric-comparison" if season_frames else "metric-comparison",
                    "windows": [window.model_dump() for window in windows],
                },
            ),
            title=chart_title,
            specification={
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {"values": values},
                "mark": {"type": "bar", "cornerRadiusEnd": 3},
                "encoding": {
                    "x": {"field": "metric", "type": "nominal", "sort": None, "axis": {"labelAngle": -25}},
                    "y": {"field": "value", "type": "quantitative"},
                    "color": {"field": series_field, "type": "nominal", "sort": "ascending"},
                    "xOffset": {"field": series_field, "sort": "ascending"},
                    "tooltip": [{"field": "metric"}, {"field": series_field}, {"field": "value", "format": ".3f"}],
                },
            },
            evidence_ids=chart_evidence_ids,
        )
        if season_frames:
            source, label = METRICS[primary_metric]
            seasonal_values = [
                {"series": label, "season": season, "value": _metric_value(frame, source)}
                for season, frame in sorted(season_frames.items())
            ]
            seasonal_evidence = [item for item in evidence if item.metric == f"seasonal_{primary_metric}"]
            season_trend = ChartArtifact(
                chart_id=stable_id(
                    "chart",
                    {"type": "season-range-trend", "seasons": sorted(season_frames), "metric": primary_metric},
                ),
                title=f"Season-by-season {label}",
                specification={
                    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                    "data": {"values": seasonal_values},
                    "mark": {"type": "line", "point": True},
                    "encoding": {
                        "x": {
                            "field": "season",
                            "type": "ordinal",
                            "sort": "ascending",
                            "axis": {"labelAngle": 0, "title": "Season"},
                        },
                        "y": {"field": "value", "type": "quantitative", "axis": {"title": label}},
                        "color": {"field": "series", "type": "nominal", "legend": None},
                        "tooltip": [
                            {"field": "season", "type": "ordinal"},
                            {"field": "value", "title": label, "format": ".3f"},
                        ],
                    },
                },
                evidence_ids=[item.evidence_id for item in seasonal_evidence],
            )
            return [comparison_chart, season_trend]

        source, label = METRICS[primary_metric]
        source_column = f"_{source}"
        weekly_values = []
        for label, frame in zip(window_labels, (baseline, comparison), strict=True):
            if "week" in frame.columns and source_column in frame.columns:
                for row in frame.group_by("week").agg(pl.col(source_column).mean().alias("value")).sort("week").iter_rows(named=True):
                    weekly_values.append({"window": label, "week": row["week"], "value": row["value"]})
        trend = ChartArtifact(
            chart_id=stable_id("chart", {"type": "weekly-trend", "windows": [window.model_dump() for window in windows]}),
            title=f"Weekly {METRICS[primary_metric][1]}",
            specification={
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {"values": weekly_values},
                "mark": {"type": "line", "point": True},
                "encoding": {
                    "x": {"field": "week", "type": "quantitative"},
                    "y": {"field": "value", "type": "quantitative", "axis": {"title": METRICS[primary_metric][1]}},
                    "color": {"field": "window", "type": "nominal"},
                    "tooltip": [{"field": "window"}, {"field": "week"}, {"field": "value", "format": ".3f"}],
                },
            },
            evidence_ids=[item.evidence_id for item in evidence if item.metric == f"weekly_{primary_metric}"],
        )
        return [comparison_chart, trend] if weekly_values else [comparison_chart]
