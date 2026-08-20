from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import polars as pl

from sports_analyst.models import (
    AggregateEvidence,
    AnalysisPlan,
    AnalysisRequest,
    ChartArtifact,
    DatasetManifest,
    PlannedToolCall,
    PlayEvidence,
    ToolDefinition,
    ToolExecutionRecord,
    stable_id,
)

TEAM_ALIASES = {
    "ARIZONA": "ARI", "ATLANTA": "ATL", "BALTIMORE": "BAL", "BUFFALO": "BUF", "CAROLINA": "CAR",
    "CHICAGO": "CHI", "CINCINNATI": "CIN", "CLEVELAND": "CLE", "DALLAS": "DAL", "DENVER": "DEN",
    "DETROIT": "DET", "GREEN BAY": "GB", "HOUSTON": "HOU", "INDIANAPOLIS": "IND", "JACKSONVILLE": "JAX",
    "KANSAS CITY": "KC", "KC": "KC", "LAS VEGAS": "LV", "LOS ANGELES CHARGERS": "LAC",
    "LOS ANGELES RAMS": "LA", "MIAMI": "MIA", "MINNESOTA": "MIN", "NEW ENGLAND": "NE",
    "NEW ORLEANS": "NO", "NEW YORK GIANTS": "NYG", "NEW YORK JETS": "NYJ", "PHILADELPHIA": "PHI",
    "PITTSBURGH": "PIT", "SAN FRANCISCO": "SF", "SEATTLE": "SEA", "TAMPA BAY": "TB",
    "TENNESSEE": "TEN", "WASHINGTON": "WAS",
}

METRICS: dict[str, tuple[str, str]] = {
    "epa_per_dropback": ("epa", "EPA/dropback"),
    "success_rate": ("success", "Success rate"),
    "cpoe": ("cpoe", "CPOE"),
    "explosive_pass_rate": ("explosive", "Explosive pass rate"),
    "yards_per_play": ("yards_gained", "Yards/play"),
    "sack_rate": ("sack", "Sack rate"),
    "interception_rate": ("interception", "Interception rate"),
    "air_yards": ("air_yards", "Air yards/attempt"),
    "yards_after_catch": ("yards_after_catch", "YAC/completion"),
}


@dataclass
class NFLAnalysisResult:
    aggregate_evidence: list[AggregateEvidence]
    play_evidence: list[PlayEvidence]
    charts: list[ChartArtifact]
    executions: list[ToolExecutionRecord]
    caveats: list[str]


def _sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _present(frame: pl.DataFrame, name: str, default: Any = None) -> pl.Expr:
    return pl.col(name) if name in frame.columns else pl.lit(default)


def _dropbacks(frame: pl.DataFrame, team: str, season_type: str) -> pl.DataFrame:
    scoped = frame.filter(_present(frame, "posteam", "") == team)
    if season_type != "ALL" and "season_type" in scoped.columns:
        scoped = scoped.filter(pl.col("season_type") == season_type)
    if "qb_dropback" in scoped.columns:
        scoped = scoped.filter(pl.col("qb_dropback") == 1)
    elif "play_type" in scoped.columns:
        scoped = scoped.filter(pl.col("play_type").is_in(["pass", "qb_kneel", "qb_spike"]).not_())
    return scoped.with_columns(
        _present(scoped, "epa", None).cast(pl.Float64, strict=False).alias("_epa"),
        _present(scoped, "success", None).cast(pl.Float64, strict=False).alias("_success"),
        _present(scoped, "cpoe", None).cast(pl.Float64, strict=False).alias("_cpoe"),
        (_present(scoped, "yards_gained", 0).cast(pl.Float64, strict=False) >= 20).cast(pl.Float64).alias("_explosive"),
        _present(scoped, "yards_gained", None).cast(pl.Float64, strict=False).alias("_yards_gained"),
        _present(scoped, "sack", 0).cast(pl.Float64, strict=False).alias("_sack"),
        _present(scoped, "interception", 0).cast(pl.Float64, strict=False).alias("_interception"),
        _present(scoped, "air_yards", None).cast(pl.Float64, strict=False).alias("_air_yards"),
        _present(scoped, "yards_after_catch", None).cast(pl.Float64, strict=False).alias("_yards_after_catch"),
    )


def _metric_value(frame: pl.DataFrame, source: str) -> float | None:
    column = f"_{source}"
    if column not in frame.columns or frame[column].drop_nulls().len() == 0:
        return None
    return float(frame[column].drop_nulls().mean())


def _game_bootstrap(frame: pl.DataFrame, source: str, seed: int, iterations: int = 500) -> tuple[float | None, float | None]:
    column = f"_{source}"
    if "game_id" not in frame.columns or column not in frame.columns:
        return None, None
    games = frame.group_by("game_id").agg(pl.col(column).drop_nulls().mean().alias("value")).drop_nulls()
    values = games["value"].to_list()
    if len(values) < 3:
        return None, None
    population = [float(value) for value in values]
    rng = random.Random(seed)
    samples = sorted(sum(rng.choice(population) for _ in population) / len(population) for _ in range(iterations))
    low_index = round(0.025 * (len(samples) - 1))
    high_index = round(0.975 * (len(samples) - 1))
    return samples[low_index], samples[high_index]


def _decomposition(
        baseline: pl.DataFrame,
        comparison: pl.DataFrame,
        dimension: str,
        manifests: list[DatasetManifest],
        execution_id: str,
) -> list[AggregateEvidence]:
    if dimension not in baseline.columns or dimension not in comparison.columns:
        return []
    if baseline[dimension].is_not_null().mean() < 0.7 or comparison[dimension].is_not_null().mean() < 0.7:
        return []

    base = (baseline.filter(pl.col(dimension).is_not_null())
            .group_by(dimension).agg(pl.len().alias("n"), pl.col("_epa").mean().alias("epa")))
    comp = (comparison.filter(pl.col(dimension).is_not_null())
            .group_by(dimension).agg(pl.len().alias("n"), pl.col("_epa").mean().alias("epa")))
    if not base.height or not comp.height:
        return []

    joined = base.join(comp, on=dimension, how="inner", suffix="_comparison").filter((pl.col("n") >= 10) & (pl.col("n_comparison") >= 10))
    results = []
    for row in joined.sort(dimension).iter_rows(named=True):
        base_share = row["n"] / baseline.height
        comp_share = row["n_comparison"] / comparison.height
        performance = comp_share * (row["epa_comparison"] - row["epa"])
        mix = (comp_share - base_share) * row["epa"]
        payload = {"dimension": dimension, "value": str(row[dimension]), "performance": performance, "mix": mix}
        evidence_id = stable_id("evidence", payload)
        results.append(
            AggregateEvidence(
                evidence_id=evidence_id,
                metric=f"{dimension}_decomposition",
                label=f"{dimension}: {row[dimension]}",
                value=round(performance + mix, 4),
                baseline_value=round(float(row["epa"]), 4),
                comparison_value=round(float(row["epa_comparison"]), 4),
                unit="EPA/dropback contribution",
                sample_size=int(row["n_comparison"]),
                row_set_sha256=_sha(payload),
                dataset_manifest_ids=[item.manifest_id for item in manifests],
                tool_execution_id=execution_id,
                caveats=["Contributions within a dimension are descriptive and must not be summed across overlapping dimensions."],
            )
        )
    return sorted(results, key=lambda item: abs(float(item.value or 0)), reverse=True)[:8]


def _opponent_adjusted_epa(frame: pl.DataFrame, target: pl.DataFrame, team: str) -> float | None:
    required = {"posteam", "defteam", "game_id", "epa"}
    if not required <= set(frame.columns) or not required <= set(target.columns):
        return None
    league = frame.filter((pl.col("posteam") != team) & pl.col("defteam").is_not_null() & pl.col("epa").is_not_null())
    values: list[tuple[float, int]] = []
    for game in target.select("game_id", "defteam").unique().iter_rows(named=True):
        game_plays = target.filter(pl.col("game_id") == game["game_id"])
        opponent_sample = league.filter((pl.col("defteam") == game["defteam"]) & (pl.col("game_id") != game["game_id"]))
        if opponent_sample.height < 30:
            continue
        actual = game_plays["_epa"].drop_nulls().mean()
        expected = opponent_sample["epa"].drop_nulls().mean()
        if actual is not None and expected is not None:
            values.append((float(actual - expected), game_plays.height))
    total = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / total if total else None


class NFLPlugin:
    sport_id = "nfl"
    display_name = "NFL"

    def tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(name="compare_passing_efficiency", description="Compare versioned passing-efficiency metrics across seasons."),
            ToolDefinition(name="decompose_situational_splits", description="Separate EPA changes into mix and within-group performance."),
            ToolDefinition(name="rank_representative_plays", description="Return supporting and counterexample plays for a diagnosis."),
            ToolDefinition(name="query_play_by_play", description="Run constrained read-only SQL against registered play-by-play views."),
        ]

    def resolve_team(self, team: str) -> str:
        token = team.strip().upper()
        resolved = TEAM_ALIASES.get(token, token)
        if not 2 <= len(resolved) <= 3:
            raise ValueError(f"could not resolve NFL team {team!r}")
        return resolved

    def default_plan(self, request: AnalysisRequest) -> AnalysisPlan:
        calls = [
            PlannedToolCall(tool="compare_passing_efficiency", arguments={}, purpose="Measure the direction and size of the change."),
            PlannedToolCall(tool="decompose_situational_splits", arguments={}, purpose="Identify situations associated with the change."),
            PlannedToolCall(
                tool="rank_representative_plays",
                arguments={},
                purpose="Ground the diagnosis in source plays and counterexamples.",
            ),
        ]
        payload = {"question": request.question, "scope": request.scope.model_dump(), "calls": [item.model_dump() for item in calls]}
        return AnalysisPlan(plan_id=stable_id("plan", payload), question=request.question, scope=request.scope, calls=calls)

    def analyze(
            self,
            request: AnalysisRequest,
            datasets: dict[int, pl.DataFrame],
            manifests: dict[int, DatasetManifest],
    ) -> NFLAnalysisResult:
        team = self.resolve_team(request.scope.team)
        seasons = [request.scope.baseline_season, request.scope.comparison_season]
        missing = [season for season in seasons if season not in datasets]
        if missing:
            raise ValueError(f"missing synced seasons: {missing}")
        baseline = _dropbacks(datasets[seasons[0]], team, request.scope.season_type)
        comparison = _dropbacks(datasets[seasons[1]], team, request.scope.season_type)
        if baseline.height < 30 or comparison.height < 30:
            raise ValueError("each comparison window requires at least 30 qualifying dropbacks")

        selected_manifests = [manifests[season] for season in seasons]
        started_at = datetime.now(UTC)
        start = perf_counter()
        execution_id = stable_id("execution", {"tool": "compare_passing_efficiency", "team": team, "seasons": seasons})
        aggregate: list[AggregateEvidence] = []
        for index, (metric, (source, label)) in enumerate(METRICS.items()):
            base_value = _metric_value(baseline, source)
            comp_value = _metric_value(comparison, source)
            if base_value is None or comp_value is None:
                continue
            low, high = _game_bootstrap(comparison, source, seed=seasons[1] * 100 + index)
            payload = {"metric": metric, "team": team, "seasons": seasons, "baseline": base_value, "comparison": comp_value}
            caveats = []
            if min(baseline.height, comparison.height) < 100:
                caveats.append("The qualifying sample is under 100 plays; interpret the change cautiously.")
            aggregate.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric=metric,
                    label=label,
                    value=round(comp_value - base_value, 4),
                    baseline_value=round(base_value, 4),
                    comparison_value=round(comp_value, 4),
                    unit="rate" if "rate" in metric or metric in {"success_rate", "cpoe"} else "per play",
                    sample_size=comparison.height,
                    confidence_low=round(low, 4) if low is not None else None,
                    confidence_high=round(high, 4) if high is not None else None,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                    caveats=caveats,
                )
            )

        adjusted_values = [
            _opponent_adjusted_epa(datasets[season], frame, team)
            for season, frame in zip(seasons, (baseline, comparison), strict=True)
        ]
        if all(value is not None for value in adjusted_values):
            base_adjusted, comp_adjusted = (float(value) for value in adjusted_values if value is not None)
            payload = {"metric": "opponent_adjusted_epa_per_dropback", "team": team, "seasons": seasons}
            aggregate.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", {**payload, "values": adjusted_values}),
                    metric="opponent_adjusted_epa_per_dropback",
                    label="Opponent-adjusted EPA/dropback",
                    value=round(comp_adjusted - base_adjusted, 4),
                    baseline_value=round(base_adjusted, 4),
                    comparison_value=round(comp_adjusted, 4),
                    unit="EPA/dropback above opponent baseline",
                    sample_size=comparison.height,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                    caveats=["Opponent baselines exclude the target game and require at least 30 other defensive dropbacks."],
                )
            )

        for dimension in ("down", "offense_formation", "offense_personnel", "yardline_100", "score_differential"):
            aggregate.extend(_decomposition(baseline, comparison, dimension, selected_manifests, execution_id))

        plays = self._representative_plays(comparison, team, manifests[seasons[1]])
        result_payload = [item.model_dump(mode="json") for item in aggregate]
        execution = ToolExecutionRecord(
            execution_id=execution_id,
            tool="compare_passing_efficiency",
            parameters={"team": team, "baseline_season": seasons[0], "comparison_season": seasons[1]},
            started_at=started_at,
            duration_ms=int((perf_counter() - start) * 1000),
            result_sha256=_sha(result_payload),
            dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
        )
        charts = self._charts(aggregate, baseline, comparison, seasons)
        caveats = [
            "The analysis is observational; football interpretations are not causal estimates.",
            "EPA and CPOE are nflverse model outputs and inherit their model assumptions.",
            "Formation and personnel conclusions are omitted when source fields or subgroup samples are insufficient.",
        ]
        return NFLAnalysisResult(aggregate, plays, charts, [execution], caveats)

    def _representative_plays(self, frame: pl.DataFrame, team: str, manifest: DatasetManifest) -> list[PlayEvidence]:
        required = {"game_id", "play_id", "_epa"}
        if not required <= set(frame.columns):
            return []
        selected = pl.concat([frame.sort("_epa", descending=True).head(3), frame.sort("_epa").head(2)])
        records = []
        for index, row in enumerate(selected.iter_rows(named=True)):
            payload = {"season": manifest.season, "game_id": row["game_id"], "play_id": row["play_id"]}
            records.append(
                PlayEvidence(
                    evidence_id=stable_id("play", payload),
                    season=manifest.season,
                    game_id=str(row["game_id"]),
                    play_id=int(row["play_id"]),
                    team=team,
                    description=str(row.get("desc") or "Play description unavailable"),
                    epa=round(float(row["_epa"]), 4) if row["_epa"] is not None else None,
                    supporting=index < 3,
                    dataset_manifest_id=manifest.manifest_id,
                )
            )
        return records

    def _charts(
            self, evidence: list[AggregateEvidence], baseline: pl.DataFrame, comparison: pl.DataFrame, seasons: list[int]
    ) -> list[ChartArtifact]:
        metric_items = [item for item in evidence if item.metric in METRICS]
        values = [
            record
            for item in metric_items
            for record in (
                {"metric": item.label, "season": str(seasons[0]), "value": item.baseline_value},
                {"metric": item.label, "season": str(seasons[1]), "value": item.comparison_value},
            )
        ]
        comparison_chart = ChartArtifact(
            chart_id=stable_id("chart", {"type": "metric-comparison", "seasons": seasons}),
            title="Passing efficiency comparison",
            specification={
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {"values": values},
                "mark": {"type": "bar", "cornerRadiusEnd": 3},
                "encoding": {
                    "x": {"field": "metric", "type": "nominal", "sort": None, "axis": {"labelAngle": -25}},
                    "y": {"field": "value", "type": "quantitative"},
                    "color": {"field": "season", "type": "nominal"},
                    "xOffset": {"field": "season"},
                    "tooltip": [{"field": "metric"}, {"field": "season"}, {"field": "value", "format": ".3f"}],
                },
            },
            evidence_ids=[item.evidence_id for item in metric_items],
        )
        weekly_values = []
        for season, frame in zip(seasons, (baseline, comparison), strict=True):
            if "week" in frame.columns:
                for row in frame.group_by("week").agg(pl.col("_epa").mean().alias("epa")).sort("week").iter_rows(named=True):
                    weekly_values.append({"season": str(season), "week": row["week"], "epa": row["epa"]})
        trend = ChartArtifact(
            chart_id=stable_id("chart", {"type": "weekly-trend", "seasons": seasons}),
            title="Weekly EPA per dropback",
            specification={
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {"values": weekly_values},
                "mark": {"type": "line", "point": True},
                "encoding": {
                    "x": {"field": "week", "type": "quantitative"},
                    "y": {"field": "epa", "type": "quantitative"},
                    "color": {"field": "season", "type": "nominal"},
                    "tooltip": [{"field": "season"}, {"field": "week"}, {"field": "epa", "format": ".3f"}],
                },
            },
            evidence_ids=[item.evidence_id for item in metric_items if item.metric == "epa_per_dropback"],
        )
        return [comparison_chart, trend]
