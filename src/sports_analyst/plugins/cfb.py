"""Recorded game statistics and explicitly modeled, attributed CFB play values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

import polars as pl

from sports_analyst.datasets.cfb import CFB_DATASETS
from sports_analyst.models import (
    AggregateEvidence,
    AnalysisOptions,
    AnalysisPlan,
    ChartArtifact,
    ComparisonWindowOption,
    MetricDefinition,
    MetricOption,
    PlannedToolCall,
    PlayEvidence,
    PlayVisualization,
    ToolDefinition,
    ToolExecutionRecord,
    stable_id,
)
from sports_analyst.presentation.charts import metric_row_comparison_spec

# label, subject, domain, numerator, denominator (None means per game), unit
METRICS = {
    "win_rate": ("Win rate", "team", "results", "win", "games", "rate"),
    "points_per_game": ("Points scored/game", "team", "results", "points", None, "points"),
    "points_allowed_per_game": ("Points allowed/game", "team", "results", "points_allowed", None, "points"),
    "total_yards_per_game": ("Total yards/game", "team", "offense", "total_yards", None, "yards"),
    "passing_yards_per_game": ("Net passing yards/game", "team", "offense", "passing_yards", None, "yards"),
    "net_yards_per_pass_attempt": ("Net passing yards/attempt", "team", "offense", "passing_yards", "passing_attempts", "yards"),
    "rushing_yards_per_game": ("Rushing yards/game", "team", "offense", "rushing_yards", None, "yards"),
    "yards_per_rush": ("Yards/rush", "team", "offense", "rushing_yards", "rushing_attempts", "yards"),
    "third_down_rate": ("Third-down conversion rate", "team", "offense", "third_down_conversions", "third_down_attempts", "rate"),
    "fourth_down_rate": ("Fourth-down conversion rate", "team", "offense", "fourth_down_conversions", "fourth_down_attempts", "rate"),
    "turnovers_per_game": ("Turnovers/game", "team", "offense", "turnovers", None, "turnovers"),
    "passing_completions": ("Passing completions", "player", "quarterback", "passing_completions", "total", "count"),
    "passing_attempts": ("Passing attempts", "player", "quarterback", "passing_attempts", "total", "count"),
    "completion_rate": ("Completion rate", "player", "quarterback", "passing_completions", "passing_attempts", "rate"),
    "passing_yards": ("Passing yards", "player", "quarterback", "passing_yards", "total", "yards"),
    "passing_yards_per_attempt": ("Passing yards/attempt", "player", "quarterback", "passing_yards", "passing_attempts", "yards"),
    "passing_touchdowns": ("Passing touchdowns", "player", "quarterback", "passing_touchdowns", "total", "touchdowns"),
    "passing_interceptions": ("Passing interceptions", "player", "quarterback", "passing_interceptions", "total", "interceptions"),
    "rushing_attempts": ("Rushing attempts", "player", "rushing", "rushing_attempts", "total", "count"),
    "rushing_yards": ("Rushing yards", "player", "rushing", "rushing_yards", "total", "yards"),
    "rushing_yards_per_attempt": ("Rushing yards/attempt", "player", "rushing", "rushing_yards", "rushing_attempts", "yards"),
    "rushing_touchdowns": ("Rushing touchdowns", "player", "rushing", "rushing_touchdowns", "total", "touchdowns"),
    "receptions": ("Receptions", "player", "receiving", "receptions", "total", "count"),
    "receiving_yards": ("Receiving yards", "player", "receiving", "receiving_yards", "total", "yards"),
    "yards_per_reception": ("Yards/reception", "player", "receiving", "receiving_yards", "receptions", "yards"),
    "receiving_touchdowns": ("Receiving touchdowns", "player", "receiving", "receiving_touchdowns", "total", "touchdowns"),
}
DEFAULTS = {
    domain: [key for key, item in METRICS.items() if item[2] == domain]
    for domain in ("results", "offense", "quarterback", "rushing", "receiving")
}

# Metric -> (modeled field, reducer, play-type filter, structured athlete role).
# Advanced metrics are optional, not part of the cheap box-score defaults.
ADVANCED = {
    "epa_per_play": ("epa", "mean", None, None),
    "passing_epa_per_play": ("epa", "mean", "pass", None),
    "rushing_epa_per_play": ("epa", "mean", "rush", None),
    "epa_success_rate": ("epa", "success", None, None),
    "offensive_wpa": ("wpa", "sum", None, None),
    "passing_cpoe": ("cpoe", "mean", "pass", None),
    "pass_over_expected": ("pass_oe", "mean", None, None),
    "expected_pass_rate": ("xpass", "mean", None, None),
    "player_passing_epa": ("epa", "mean", "pass", "passer_id"),
    "player_passing_wpa": ("wpa", "sum", "pass", "passer_id"),
    "player_passing_cpoe": ("cpoe", "mean", "pass", "passer_id"),
    "player_rushing_epa": ("epa", "mean", "rush", "rusher_id"),
    "player_rushing_wpa": ("wpa", "sum", "rush", "rusher_id"),
    "player_receiving_epa": ("epa", "mean", "pass", "receiver_id"),
    "player_receiving_wpa": ("wpa", "sum", "pass", "receiver_id"),
}
for key, label, subject, domain, unit in [
    ("epa_per_play", "Modeled EPA/scrimmage play", "team", "offense", "points"),
    ("passing_epa_per_play", "Modeled EPA/passing play", "team", "offense", "points"),
    ("rushing_epa_per_play", "Modeled EPA/rushing play", "team", "offense", "points"),
    ("epa_success_rate", "EPA-positive play rate", "team", "offense", "rate"),
    ("offensive_wpa", "Offensive scrimmage WPA (spread-free)", "team", "offense", "probability"),
    ("passing_cpoe", "Modeled completion over expected (pp)", "team", "offense", "percentage_points"),
    ("pass_over_expected", "Modeled pass rate over expected (pp)", "team", "offense", "percentage_points"),
    ("expected_pass_rate", "Modeled expected pass rate", "team", "offense", "rate"),
    ("player_passing_epa", "EPA/verified attributed passing play", "player", "quarterback", "points"),
    ("player_passing_wpa", "Attributed passing WPA (spread-free)", "player", "quarterback", "probability"),
    ("player_passing_cpoe", "CPOE/verified attributed passing play (pp)", "player", "quarterback", "percentage_points"),
    ("player_rushing_epa", "EPA/verified attributed rushing play", "player", "rushing", "points"),
    ("player_rushing_wpa", "Attributed rushing WPA (spread-free)", "player", "rushing", "probability"),
    ("player_receiving_epa", "EPA/verified attributed target", "player", "receiving", "points"),
    ("player_receiving_wpa", "Attributed target WPA (spread-free)", "player", "receiving", "probability"),
]:
    METRICS[key] = (label, subject, domain, ADVANCED[key][0], None, unit)


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class CFBResult:
    aggregate_evidence: list
    play_evidence: list
    charts: list
    executions: list
    caveats: list[str]


class CFBPlugin:
    sport_id = "cfb"
    display_name = "College Football"

    def tools(self):
        return [
            ToolDefinition(name="compare_cfb_windows", description="Compare recorded FBS/FCS team and offensive-player game statistics."),
            ToolDefinition(name="find_cfb_game_evidence", description="Open recorded game context and scoring evidence."),
            ToolDefinition(name="explain_metric", description="Explain qualifying games, numerator, denominator, and coverage."),
        ]

    def analysis_options(self, manifests, context=None):
        years = sorted({manifest.season for manifest in manifests})
        return AnalysisOptions(
            sport="cfb",
            teams=[],
            available_seasons=years,
            syncable_seasons=[],
            metrics=[
                MetricOption(
                    value=name,
                    label=item[0],
                    category=item[2],
                    description=self.explain_metric(name).description,
                    analysis_domain=item[2],
                    available_seasons=years,
                    subject_types=[item[1]],
                )
                for name, item in METRICS.items()
            ],
            default_metrics=DEFAULTS["results"],
            default_metrics_by_domain=DEFAULTS,
            analysis_domains=[
                {
                    "value": name,
                    "label": name.title(),
                    "description": "Recorded statistics; optional modeled play values require game-level preparation and verified coverage.",
                    "subject_type": "team" if name in {"results", "offense"} else "player",
                }
                for name in DEFAULTS
            ],
            comparison_windows=[
                ComparisonWindowOption(value="full_seasons", label="Full seasons", description="Compare season game samples."),
                ComparisonWindowOption(value="date_ranges", label="Date ranges", description="Compare games within selected dates."),
                ComparisonWindowOption(value="week_ranges", label="Week ranges", description="Use recorded ESPN week numbers."),
            ],
            subject_types=[{"value": "team", "label": "Team"}, {"value": "player", "label": "Player"}],
            week_values=list(range(1, 23)),
            split_dimensions=[],
            syncable_datasets=CFB_DATASETS,
            dataset_min_seasons={dataset: None for dataset in CFB_DATASETS},
            data_setup={
                "required_datasets": ["schedules"],
                "recommended_datasets": ["team_stats", "player_stats", "rosters", "scoring_events"],
                "label": "Selected college-football data",
                "description": "Only selected teams/players and games are prepared on demand.",
                "descriptions": {
                    **{name: name.replace("_", " ").title() for name in CFB_DATASETS},
                    "enriched_plays": "Optional per-game SportsDataverse EPA/WPA pipeline; modeled values, not observed statistics.",
                },
            },
        )

    @staticmethod
    def resolve_team(team):
        if not str(team).isdigit():
            raise ValueError("Select an ESPN college-football team")
        return str(team)

    def default_plan(self, request):
        return AnalysisPlan(
            plan_id=stable_id("plan", request.model_dump()),
            question=request.question,
            scope=request.scope,
            calls=[
                PlannedToolCall(
                    tool="compare_cfb_windows",
                    arguments={"subject": request.subject.model_dump()},
                    purpose="Compare verified selected-subject game statistics.",
                )
            ],
        )

    @staticmethod
    def required_play_by_play_columns(request):
        return set()  # CFB's primary dataset is schedules, not national play-by-play.

    @staticmethod
    def required_supplemental_datasets(request):
        return {"team_stats", "player_stats", "scoring_events"} | ({"enriched_plays"} if set(request.metrics) & ADVANCED.keys() else set())

    def explain_metric(self, metric):
        if metric not in METRICS:
            raise ValueError("Unsupported college-football metric")
        label, subject, domain, numerator, denominator, unit = METRICS[metric]
        if metric in ADVANCED:
            field, reducer, kind, role = ADVANCED[metric]
            return MetricDefinition(
                value=metric,
                label=label,
                category=domain,
                description=f"SportsDataverse model-derived {label.lower()}, not a recorded box-score value.",
                formula=f"{'mean(epa > 0)' if reducer == 'success' else f'{reducer}({field})'} over qualifying attributed scrimmage plays",
                qualifying_plays=f"Processed {kind or 'scrimmage'} plays with finite modeled values"
                + (f" and ESPN structured {role}" if role else " and verified possession team"),
                interpretation="EPA is modeled efficiency; WPA is game-state leverage, not causal individual credit or opponent adjustment. "
                "CPOE = 100*(completion - modeled completion probability); pass-over-expected = 100*(pass - modeled pass probability).",
                higher_is_better=True,
                limitations=[
                    "Partial source/pipeline coverage is reported; missing plays are not zero.",
                    "WPA uses the spread-free model; no missing betting spread is substituted.",
                    "Models have not been independently calibrated here across FBS/FCS and historical eras.",
                    "Attributed receiver EPA includes recorded targets, not just catches; no name-only identity joins.",
                ],
            )
        formula = (
            f"sum({numerator})"
            if denominator == "total"
            else f"sum({numerator}) / sum({denominator})"
            if denominator
            else f"sum({numerator}) / qualifying games"
        )
        return MetricDefinition(
            value=metric,
            label=label,
            category=domain,
            description=f"Recorded {subject} {label.lower()} over covered games.",
            formula=formula,
            qualifying_plays="Completed games with the required attributed numerator and denominator.",
            interpretation="Descriptive comparison, not opponent-adjusted or a causal estimate.",
            higher_is_better=None,
            limitations=[
                "Missing values are excluded, never replaced with zero.",
                "Unequal schedules, FBS/FCS opposition and transfers can affect comparisons.",
            ],
        )

    @staticmethod
    def window(schedule, window, request):
        filtered = schedule.filter(pl.col("completed") == True)  # noqa: E712
        if request.scope.season_type != "ALL":
            filtered = filtered.filter(pl.col("season_type") == request.scope.season_type)
        if window.start_date:
            filtered = filtered.filter(pl.col("date").str.slice(0, 10) >= window.start_date)
        if window.end_date:
            filtered = filtered.filter(pl.col("date").str.slice(0, 10) <= window.end_date)
        if request.scope.comparison_design == "week_ranges":
            filtered = filtered.filter(pl.col("week").is_between(*window.weeks))
        return filtered

    @staticmethod
    def value(metric, schedule, stats, subject):
        _, _, _, numerator, denominator, _ = METRICS[metric]
        games = set(schedule["game_id"].to_list())
        if metric in ADVANCED:
            field, reducer, kind, role = ADVANCED[metric]
            identifier = role or "team_id"
            required = {"game_id", "play_id", "scrimmage", identifier, field} | ({kind} if kind else set())
            if not required <= set(stats.columns):
                return None, 0
            values = stats.filter(pl.col("game_id").is_in(games) & pl.col("scrimmage") & (pl.col(identifier) == subject.id))
            if kind:
                values = values.filter(pl.col(kind))
            values = (
                values.drop_nulls(field)
                .with_columns(pl.col(field).cast(pl.Float64))
                .filter(pl.col(field).is_finite())
                .unique(subset=["game_id", "play_id"])
            )
            if values.is_empty():
                return None, 0
            result = (values[field] > 0).mean() if reducer == "success" else values[field].mean() if reducer == "mean" else values[field].sum()
            return result, values.height
        if numerator in {"win", "points", "points_allowed"}:
            values = []
            for row in schedule.to_dicts():
                side = "home" if row["home_team_id"] == subject.id else "away"
                other = "away" if side == "home" else "home"
                points, allowed = row[f"{side}_score"], row[f"{other}_score"]
                if points is not None and allowed is not None:
                    values.append(float(points > allowed) if numerator == "win" else points if numerator == "points" else allowed)
            return (sum(values) / len(values), len(values)) if values else (None, 0)
        identifier = "athlete_id" if subject.type == "player" else "team_id"
        if not {"game_id", identifier, numerator} <= set(stats.columns):
            return None, 0
        selected = stats.filter(pl.col("game_id").is_in(games) & (pl.col(identifier) == subject.id))
        required = [numerator] + ([denominator] if denominator not in {None, "total", "games"} else [])
        if not set(required) <= set(selected.columns):
            return None, 0
        selected = selected.drop_nulls(required).unique(subset=["game_id", identifier])
        if denominator not in {None, "total", "games"}:
            selected = selected.filter(pl.col(denominator) > 0)
        if selected.is_empty():
            return None, 0
        total = selected[numerator].sum()
        divisor = selected[denominator].sum() if denominator not in {None, "total"} else 1 if denominator == "total" else selected.height
        return (total / divisor, selected.height) if divisor and divisor > 0 else (None, 0)

    def analyze(self, request, datasets, manifests, supplemental=None, supplemental_manifests=None):
        started = perf_counter()
        selected = request.metrics or DEFAULTS.get(request.analysis_domain, DEFAULTS["results"])
        subject = request.subject
        if subject is None or any(name not in METRICS or METRICS[name][1] != subject.type for name in selected):
            raise ValueError("Select compatible college-football team/player metrics")
        supplemental, supplemental_manifests = supplemental or {}, supplemental_manifests or {}
        windows = [("baseline", request.scope.baseline), ("comparison", request.scope.comparison)]
        source = "player_stats" if subject.type == "player" else "team_stats"
        used = list(manifests.values()) + [m for group in supplemental_manifests.values() for m in group.values()]
        ids = list(dict.fromkeys(item.manifest_id for item in used))
        parameters = request.model_dump(mode="json")
        execution_id = stable_id("execution", parameters)
        aggregates, gaps, evidence = [], [], []
        schedules = {name: self.window(datasets[window.season], window, request) for name, window in windows}
        for metric in selected:
            metric_source = "enriched_plays" if metric in ADVANCED else source
            frames = [supplemental.get(metric_source, {}).get(window.season, pl.DataFrame()) for _, window in windows]
            if metric in ADVANCED:
                versions = [
                    {*data["provider_version"].drop_nulls().to_list()} if "provider_version" in data.columns else set() for data in frames
                ]
                if not versions[0] or versions[0] != versions[1] or len(versions[0]) != 1:
                    gaps.append(metric)
                    continue
            values = [self.value(metric, schedules[name], data, subject) for (name, window), data in zip(windows, frames, strict=True)]
            (before, before_n), (after, after_n) = values
            if before is None or after is None:
                gaps.append(metric)
                continue
            rows_hash = sha({name: schedules[name].to_dicts() for name, _ in windows})
            aggregates.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", {**parameters, "metric": metric, "rows": rows_hash}),
                    metric=metric,
                    label=METRICS[metric][0],
                    value=round(after - before, 4),
                    baseline_value=round(before, 4),
                    comparison_value=round(after, 4),
                    sample_size=after_n,
                    unit=METRICS[metric][5],
                    row_set_sha256=sha(
                        {
                            "schedules": rows_hash,
                            "source_rows": [data.to_dicts() for data in frames],
                        }
                    ),
                    dataset_manifest_ids=ids,
                    tool_execution_id=execution_id,
                    caveats=(
                        [
                            f"Baseline {before_n} and comparison {after_n} qualifying processed plays; "
                            "not complete-game or opponent-adjusted estimates.",
                            "SportsDataverse modeled values; spread-free WPA measures game leverage, not isolated player contribution.",
                        ]
                        if metric in ADVANCED
                        else [
                            f"Baseline {before_n}/{schedules['baseline'].height} qualifying games; "
                            f"comparison {after_n}/{schedules['comparison'].height}.",
                            "Rates use summed numerators/denominators; totals depend on sample size.",
                        ]
                    ),
                    context={
                        "baseline_sample": before_n,
                        "comparison_sample": after_n,
                        "sample_definition": "Metric-specific processed plays" if metric in ADVANCED else "Metric-specific recorded games",
                        "provider_versions": sorted(versions[0]) if metric in ADVANCED else [],
                        "baseline_schools": self.schools(
                            schedules["baseline"], supplemental.get(source, {}).get(request.scope.baseline.season, pl.DataFrame()), subject
                        ),
                        "comparison_schools": self.schools(
                            schedules["comparison"], supplemental.get(source, {}).get(request.scope.comparison.season, pl.DataFrame()), subject
                        ),
                    },
                )
            )
        if not aggregates:
            raise ValueError("No comparable college-football metrics have attributed coverage in both windows")
        for name, window in windows:
            stats = supplemental.get(source, {}).get(window.season, pl.DataFrame())
            scoring = supplemental.get("scoring_events", {}).get(window.season, pl.DataFrame())
            enriched = supplemental.get("enriched_plays", {}).get(window.season, pl.DataFrame())
            school_names = {
                row[f"{side}_team_id"]: row[f"{side}_team_name"] for row in schedules[name].to_dicts() for side in ("home", "away")
            }
            leaderboard = []
            if {"team_id", "scrimmage", "epa", "game_id", "play_id"} <= set(enriched.columns):
                covered = enriched.filter(pl.col("game_id").is_in(schedules[name]["game_id"].to_list()) & pl.col("scrimmage"))
                covered = covered.drop_nulls("epa").with_columns(pl.col("epa").cast(pl.Float64)).filter(pl.col("epa").is_finite())
                leaderboard = (
                    covered.unique(subset=["game_id", "play_id"])
                    .group_by("team_id")
                    .agg(pl.col("epa").mean().alias("epa_per_play"), pl.len().alias("plays"), pl.col("game_id").n_unique().alias("games"))
                    .sort("epa_per_play", descending=True)
                    .to_dicts()
                )
                for team_row in leaderboard:
                    team_row["team_name"] = school_names.get(team_row["team_id"])
            for row in schedules[name].sort("date").head(3).to_dicts():
                game = row["game_id"]
                game_stats = stats.filter(pl.col("game_id") == game).to_dicts() if "game_id" in stats.columns else []
                events = scoring.filter(pl.col("game_id") == game).to_dicts() if "game_id" in scoring.columns else []
                modeled = enriched.filter(pl.col("game_id") == game).to_dicts() if "game_id" in enriched.columns else []
                team_context = []
                if modeled:
                    team_context = json.loads(modeled[0].get("teams_json") or "[]")
                evidence.append(
                    PlayEvidence(
                        sport="cfb",
                        evidence_id=stable_id("evidence", {"game": game, "window": name, **parameters}),
                        season=window.season,
                        game_id=game,
                        play_id=0,
                        team=subject.id,
                        window=name,
                        evidence_role="typical",
                        description=f"{row['away_team_name']} {row['away_score']} at {row['home_team_name']} {row['home_score']}",
                        selection_reason="Chronological game context; not selected as proof of the direction of change.",
                        dataset_manifest_id=manifests[window.season].manifest_id,
                        tool_execution_id=execution_id,
                        visualization=PlayVisualization(
                            sport="cfb",
                            game_date=row["date"],
                            week=row.get("week"),
                            home_team_name=row["home_team_name"],
                            away_team_name=row["away_team_name"],
                            home_score=int(row["home_score"]) if row["home_score"] is not None else None,
                            away_score=int(row["away_score"]) if row["away_score"] is not None else None,
                            cfb_statistics={
                                "rows": game_stats,
                                "modeled_plays": modeled,
                                "teams": team_context,
                                "covered_team_epa": leaderboard,
                                "schools": {row["home_team_id"]: row["home_team_name"], row["away_team_id"]: row["away_team_name"]},
                            },
                            cfb_scoring_events=events,
                            source_packages=["schedules", source, "scoring_events"] + (["enriched_plays"] if modeled else []),
                        ),
                    )
                )
        execution = ToolExecutionRecord(
            execution_id=execution_id,
            tool="compare_cfb_windows",
            parameters=parameters,
            started_at=datetime.now(UTC),
            duration_ms=round((perf_counter() - started) * 1000),
            result_sha256=sha([item.model_dump() for item in aggregates]),
            dataset_manifest_ids=ids,
        )
        labels = [f"Baseline {request.scope.baseline.season}", f"Comparison {request.scope.comparison.season}"]
        chart = ChartArtifact(
            chart_id=stable_id("chart", parameters),
            title="College-football metric comparison",
            specification=metric_row_comparison_spec(
                [
                    {"metric": item.label, "window": label, "value": value, "unit": item.unit}
                    for item in aggregates
                    for label, value in zip(labels, [item.baseline_value, item.comparison_value], strict=True)
                ],
                series_field="window",
                series_order=labels,
            ),
            evidence_ids=[item.evidence_id for item in aggregates],
        )
        caveats = [
            "College-football comparisons are descriptive and not adjusted for opponent strength or FBS/FCS schedule composition.",
            "Conference membership changes and transfers can change the sample; use recorded game identities, not present-day affiliations.",
            "No recruiting impact, tracking locations, or unrecorded formations are inferred. "
            "Advanced play values are explicitly model-derived, not observed measurements.",
        ]
        if gaps:
            caveats.append("Metrics lacking coverage in both windows: " + ", ".join(gaps))
        absent = sorted(set(request.scope.included_seasons) - set(datasets))
        if absent:
            caveats.append(f"No verified player-season observations for {absent}; these intermediate seasons were not treated as zero.")
        for item in used:
            if item.dataset == "enriched_plays":
                caveats.append(
                    f"{item.partition_key} {item.season}: {item.coverage.get('completed_matches', 0)}/"
                    f"{item.coverage.get('expected_matches', 0)} games enriched; "
                    f"{item.coverage.get('complete_play_games', 0)} match the full source play count. "
                    "Models are not independently validated here for FBS/FCS parity."
                )
            if item.coverage.get("completed_matches", 0) < item.coverage.get("expected_matches", 0):
                caveats.append(
                    f"{item.partition_key} {item.season}: {item.coverage.get('completed_matches', 0)}/"
                    f"{item.coverage.get('expected_matches', 0)} game summaries retrieved."
                )
        return CFBResult(aggregates, evidence, [chart], [execution], list(dict.fromkeys(caveats)))

    @staticmethod
    def schools(schedule, stats, subject):
        identifiers = {subject.id}
        if subject.type == "player" and {"athlete_id", "team_id"} <= set(stats.columns):
            identifiers = set(stats.filter(pl.col("athlete_id") == subject.id)["team_id"].to_list())
        names = set()
        for row in schedule.to_dicts():
            for side in ("home", "away"):
                if row[f"{side}_team_id"] in identifiers and row[f"{side}_team_name"]:
                    names.add(row[f"{side}_team_name"])
        return sorted(names)
