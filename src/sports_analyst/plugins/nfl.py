"""Public NFL plugin entry point and investigation orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import polars as pl

from sports_analyst.data import DATASET_MIN_SEASONS, REFERENCE_DATASETS, SUPPORTED_DATASETS
from sports_analyst.models import (
    AggregateEvidence,
    AnalysisOptions,
    AnalysisPlan,
    AnalysisRequest,
    ComparisonWindowOption,
    DatasetManifest,
    MetricDefinition,
    MetricOption,
    PlannedToolCall,
    PlayerOption,
    SplitDimensionOption,
    TeamOption,
    ToolDefinition,
    stable_id,
)
from sports_analyst.plugins.nfl_personnel import NFLPersonnelMixin
from sports_analyst.plugins.nfl_player_weeks import (
    normalize_player_weeks,
)
from sports_analyst.plugins.nfl_presentation import NFLPresentationMixin
from sports_analyst.plugins.nfl_shared import (
    DEFAULT_METRICS,
    DEFAULT_METRICS_BY_DOMAIN,
    DEFAULT_SPLITS,
    HIGHER_IS_BETTER,
    LATEST_SYNCABLE_SEASON,
    METRIC_DOMAINS,
    METRIC_FORMULAS,
    METRIC_INTERPRETATIONS,
    METRIC_METADATA,
    METRICS,
    NFL_TEAMS,
    SPLIT_COLUMNS,
    SPLIT_DIMENSIONS,
    TEAM_ALIASES,
    TOOL_INPUT_SCHEMAS,
    NFLAnalysisResult,
    _decomposition,
    _execution_record,
    _first_column,
    _game_bootstrap,
    _metric_value,
    _opponent_adjusted_epa,
    _scope_plays,
    _sha,
)
from sports_analyst.plugins.nfl_supplemental import NFLSupplementalMixin
from sports_analyst.plugins.nfl_trends import NFLTrendMixin


class NFLPlugin(NFLTrendMixin, NFLPersonnelMixin, NFLSupplementalMixin, NFLPresentationMixin):
    """Compose NFL planning, deterministic analysis tools, and presentation artifacts."""

    sport_id = "nfl"
    display_name = "NFL"

    def tools(self) -> list[ToolDefinition]:
        tools = [
            ToolDefinition(name="get_analysis_options", description="Return valid teams, datasets, metrics, splits, and comparison windows."),
            ToolDefinition(name="validate_analysis_scope", description="Validate entities, windows, fields, and sample requirements."),
            ToolDefinition(name="compare_time_windows", description="Compare versioned metrics across arbitrary season/week windows."),
            ToolDefinition(name="analyze_season_trends", description="Measure every season in an inclusive full-season range."),
            ToolDefinition(name="analyze_weekly_trends", description="Measure week-level trends and uncertainty within each window."),
            ToolDefinition(name="rank_game_outliers", description="Rank games that most exceeded or trailed the baseline expectation."),
            ToolDefinition(name="benchmark_against_league", description="Calculate league ranks and percentiles for requested metrics."),
            ToolDefinition(name="analyze_situational_split", description="Compare performance across a registered situational dimension."),
            ToolDefinition(name="find_representative_plays", description="Return supporting and counterexample plays for a diagnosis."),
            ToolDefinition(name="explain_metric", description="Return a metric definition, formula, qualifying rules, and limitations."),
            ToolDefinition(name="decompose_metric_change", description="Separate metric changes into mix and within-group performance."),
            ToolDefinition(name="adjust_for_opponents", description="Compare raw performance with leave-one-game-out opponent context."),
            ToolDefinition(name="analyze_game_state", description="Analyze performance while leading, tied, and trailing."),
            ToolDefinition(name="compare_play_mix", description="Measure changes in formation, personnel, tempo, and situational shares."),
            ToolDefinition(name="identify_change_points", description="Find descriptive week boundaries with the largest sustained shift."),
            ToolDefinition(name="resolve_player", description="Resolve a player name or identifier from synced play and roster data."),
            ToolDefinition(
                name="build_player_week_dataset",
                description="Normalize rosters, injuries, snap counts, and play participants to one player-week grain.",
            ),
            ToolDefinition(name="get_roster_context", description="Compare roster composition by position across windows."),
            ToolDefinition(name="analyze_starter_availability", description="Summarize injured, inactive, and limited-player availability."),
            ToolDefinition(name="compare_player_usage",
                           description="Compare target, carry, dropback, opportunity, and snap-normalized player usage across windows."),
            ToolDefinition(name="analyze_position_group_availability",
                           description="Estimate snap-weighted recorded availability by position group."),
            ToolDefinition(name="analyze_lineup_continuity",
                           description="Measure returning snap share and snap-distribution similarity overall and by position group."),
            ToolDefinition(name="decompose_lineup_continuity", description="Attribute comparison-window lineup turnover to position groups."),
            ToolDefinition(name="analyze_qb_receiver_pairs", description="Compare quarterback-receiver volume and efficiency."),
            ToolDefinition(name="summarize_injured_or_inactive_players", description="Rank players most frequently listed unavailable."),
            ToolDefinition(name="join_nextgen_passing_metrics", description="Compare synced Next Gen Stats passing measurements."),
            ToolDefinition(
                name="join_nextgen_receiving_metrics",
                description="Compare receiving separation, cushion, and YAC-over-expectation.",
            ),
            ToolDefinition(name="join_nextgen_rushing_metrics", description="Compare rushing efficiency and yards over expectation."),
            ToolDefinition(
                name="join_participation_context",
                description="Measure play-level personnel, pressure, coverage, and recorded lineup participation.",
            ),
            ToolDefinition(name="join_depth_chart_context", description="Compare first-unit depth-chart availability and continuity."),
            ToolDefinition(name="join_ftn_charting", description="Compare motion, play action, RPO, pressure, and charted outcome rates."),
            ToolDefinition(
                name="join_pfr_advanced_stats",
                description="Compare PFR passing, rushing, receiving, and defensive advanced metrics.",
            ),
            ToolDefinition(name="join_schedule_context", description="Add opponent, location, scoring-margin, and schedule context."),
            ToolDefinition(name="compare_passing_efficiency", description="Compatibility alias for compare_time_windows."),
            ToolDefinition(name="decompose_situational_splits", description="Compatibility alias for decompose_metric_change."),
            ToolDefinition(name="rank_representative_plays", description="Compatibility alias for find_representative_plays."),
            ToolDefinition(name="query_play_by_play", description="Run constrained read-only SQL against registered play-by-play views."),
        ]
        return [tool.model_copy(update={"input_schema": TOOL_INPUT_SCHEMAS.get(tool.name, tool.input_schema)}) for tool in tools]

    def analysis_options(self, manifests: list[DatasetManifest], teams: pl.DataFrame | None = None) -> AnalysisOptions:
        available_seasons = sorted({manifest.season for manifest in manifests})

        def seasons_with(required: set[str]) -> list[int]:
            return sorted(manifest.season for manifest in manifests if required <= set(manifest.columns))

        metrics = [
            MetricOption(
                value=value,
                label=METRICS[value][1],
                category=METRIC_METADATA[value][0],
                description=METRIC_METADATA[value][1],
                analysis_domain=METRIC_DOMAINS[value],
                available_seasons=seasons_with(METRIC_METADATA[value][2]),
            )
            for value in METRICS
        ]
        splits = [
            SplitDimensionOption(
                value=value,
                label=metadata[0],
                description=metadata[1],
                available_seasons=seasons_with(metadata[2]),
            )
            for value, metadata in SPLIT_DIMENSIONS.items()
        ]
        team_options = [TeamOption(value=code, label=label) for code, label in NFL_TEAMS.items()]
        if teams is not None and not teams.is_empty():
            code_column = _first_column(teams, "team_abbr", "team", "abbr")
            name_column = _first_column(teams, "team_name", "team_nick", "team_full_name", "name")
            if code_column and name_column:
                rows = teams.select(code_column, name_column).drop_nulls().unique().sort(code_column).iter_rows(named=True)
                loaded = [TeamOption(value=str(row[code_column]), label=str(row[name_column])) for row in rows]
                if loaded:
                    team_options = loaded
        return AnalysisOptions(
            sport=self.sport_id,
            teams=team_options,
            available_seasons=available_seasons,
            syncable_seasons=list(range(LATEST_SYNCABLE_SEASON, 1998, -1)),
            metrics=metrics,
            default_metrics=DEFAULT_METRICS,
            analysis_domains=[
                {"value": "passing", "label": "Passing", "description": "Quarterback dropbacks and passing outcomes."},
                {"value": "rushing", "label": "Rushing", "description": "Qualifying rushing attempts excluding kneels and spikes."},
                {"value": "offense", "label": "Overall offense", "description": "Rushing attempts and quarterback dropbacks together."},
            ],
            default_metrics_by_domain=DEFAULT_METRICS_BY_DOMAIN,
            split_dimensions=splits,
            comparison_windows=[
                ComparisonWindowOption(
                    value="full_seasons",
                    label="Full season range",
                    description="Analyze every complete season from the selected start through end season.",
                ),
                ComparisonWindowOption(value="week_ranges", label="Custom week ranges", description="Compare two inclusive week ranges."),
                ComparisonWindowOption(
                    value="before_after",
                    label="Before vs. after",
                    description="Split one season around a selected week.",
                ),
            ],
            syncable_datasets=list(SUPPORTED_DATASETS),
            dataset_min_seasons={
                dataset: None if dataset in REFERENCE_DATASETS else DATASET_MIN_SEASONS[dataset]
                for dataset in SUPPORTED_DATASETS
            },
        )

    def explain_metric(self, metric: str) -> MetricDefinition:
        normalized = metric.strip().lower()
        if normalized not in METRICS:
            raise ValueError(f"unsupported metric {metric!r}")
        category, description, _required = METRIC_METADATA[normalized]
        return MetricDefinition(
            value=normalized,
            label=METRICS[normalized][1],
            category=category,
            description=description,
            formula=METRIC_FORMULAS[normalized],
            qualifying_plays={
                "passing": "Team quarterback dropbacks within the selected season type and inclusive week window.",
                "rushing": "Team rushing attempts excluding kneels and spikes within the selected season type and week window.",
                "offense": "Team quarterback dropbacks and rushing attempts, excluding kneels and spikes, within the selected window.",
            }[METRIC_DOMAINS[normalized]],
            interpretation=METRIC_INTERPRETATIONS[normalized],
            higher_is_better=HIGHER_IS_BETTER[normalized],
            limitations=[
                "Missing source values are excluded from the metric mean or rate denominator.",
                "The metric is descriptive and does not by itself establish causality.",
            ],
        )

    def resolve_players(self, query: str, sources: list[tuple[int, pl.DataFrame]]) -> list[PlayerOption]:
        token = query.strip().lower()
        players: dict[str, dict[str, Any]] = {}
        for season, frame in sources:
            candidates = [
                ("gsis_id", "full_name", "team", "position"),
                ("gsis_id", "display_name", "latest_team", "position"),
                ("player_id", "player_name", "recent_team", "position"),
                ("passer_player_id", "passer_player_name", "posteam", None),
                ("receiver_player_id", "receiver_player_name", "posteam", None),
            ]
            for id_column, name_column, team_column, position_column in candidates:
                if id_column not in frame.columns or name_column not in frame.columns:
                    continue
                selected_columns = [id_column, name_column]
                selected_columns.extend(column for column in (team_column, position_column) if column and column in frame.columns)
                for row in frame.select(selected_columns).drop_nulls([id_column, name_column]).unique().iter_rows(named=True):
                    player_id, name = str(row[id_column]), str(row[name_column])
                    if token and token not in player_id.lower() and token not in name.lower():
                        continue
                    record = players.setdefault(
                        player_id,
                        {"player_id": player_id, "name": name, "teams": set(), "positions": set(), "seasons": set()},
                    )
                    if team_column and row.get(team_column):
                        record["teams"].add(str(row[team_column]))
                    if position_column and row.get(position_column):
                        record["positions"].add(str(row[position_column]))
                    if season:
                        record["seasons"].add(season)
        return [
            PlayerOption(
                player_id=record["player_id"],
                name=record["name"],
                teams=sorted(record["teams"]),
                positions=sorted(record["positions"]),
                seasons=sorted(record["seasons"]),
            )
            for record in sorted(players.values(), key=lambda item: (item["name"], item["player_id"]))[:25]
        ]

    def resolve_team(self, team: str) -> str:
        token = team.strip().upper()
        resolved = TEAM_ALIASES.get(token, token)
        if not 2 <= len(resolved) <= 3:
            raise ValueError(f"could not resolve NFL team {team!r}")
        return resolved

    def default_plan(self, request: AnalysisRequest) -> AnalysisPlan:
        default_metrics = DEFAULT_METRICS_BY_DOMAIN[request.analysis_domain]
        calls = [
            PlannedToolCall(
                tool="validate_analysis_scope",
                arguments={
                    "scope": request.scope.model_dump(),
                    "analysis_domain": request.analysis_domain,
                    "metrics": request.metrics,
                    "splits": request.splits,
                },
                purpose="Confirm that requested entities, windows, fields, and samples are valid.",
            ),
            PlannedToolCall(
                tool="compare_time_windows",
                arguments={
                    "metrics": request.metrics,
                    "analysis_domain": request.analysis_domain,
                    "splits": request.splits,
                    "baseline": request.scope.baseline.model_dump(),
                    "comparison": request.scope.comparison.model_dump(),
                },
                purpose="Measure the direction and size of the change.",
            ),
            PlannedToolCall(
                tool="analyze_season_trends" if request.scope.comparison_design == "full_seasons" else "analyze_weekly_trends",
                arguments={"metric": request.metrics[0] if request.metrics else default_metrics[0]},
                purpose=(
                    "Measure the trajectory across every season in the inclusive range."
                    if request.scope.comparison_design == "full_seasons"
                    else "Determine whether the change was sustained or concentrated in a few weeks."
                ),
            ),
            PlannedToolCall(
                tool="rank_game_outliers",
                arguments={"metric": request.metrics[0] if request.metrics else default_metrics[0]},
                purpose="Identify games that contributed most strongly to the comparison.",
            ),
            PlannedToolCall(
                tool="benchmark_against_league",
                arguments={"metrics": request.metrics or default_metrics},
                purpose="Place the team-level changes in league context.",
            ),
            PlannedToolCall(
                tool="decompose_metric_change",
                arguments={
                    "metric": request.metrics[0] if request.metrics else default_metrics[0],
                    "splits": request.splits or DEFAULT_SPLITS,
                },
                purpose="Separate situational mix changes from performance changes.",
            ),
            PlannedToolCall(
                tool="adjust_for_opponents",
                arguments={"metric": "epa_per_dropback"},
                purpose="Check whether opponent quality helps explain the result.",
            ),
            PlannedToolCall(
                tool="compare_play_mix",
                arguments={"splits": request.splits or DEFAULT_SPLITS},
                purpose="Measure how the offense's situational and structural mix changed.",
            ),
            PlannedToolCall(
                tool="identify_change_points",
                arguments={"metric": request.metrics[0] if request.metrics else default_metrics[0]},
                purpose="Locate candidate week boundaries for sustained changes.",
            ),
            PlannedToolCall(
                tool="build_player_week_dataset",
                arguments={"team": request.scope.team},
                purpose="Normalize player identity, roster, injury, snap, and play-participation records by week.",
            ),
            PlannedToolCall(
                tool="compare_player_usage",
                arguments={"team": request.scope.team},
                purpose="Identify players whose involvement changed most.",
            ),
            PlannedToolCall(
                tool="analyze_qb_receiver_pairs",
                arguments={"team": request.scope.team},
                purpose="Measure changes in quarterback-receiver volume and efficiency.",
            ),
            PlannedToolCall(
                tool="analyze_starter_availability",
                arguments={"team": request.scope.team},
                purpose="Check whether recorded availability changed between windows when injury data is synced.",
            ),
            PlannedToolCall(
                tool="analyze_position_group_availability",
                arguments={"team": request.scope.team},
                purpose="Estimate how much expected participation was unavailable within each position group.",
            ),
            PlannedToolCall(
                tool="analyze_lineup_continuity",
                arguments={"team": request.scope.team},
                purpose="Measure returning snap share and lineup stability between the selected windows.",
            ),
            PlannedToolCall(
                tool="decompose_lineup_continuity",
                arguments={"team": request.scope.team},
                purpose="Identify which position groups account for the largest share of lineup turnover.",
            ),
            PlannedToolCall(
                tool="join_participation_context",
                arguments={"team": request.scope.team},
                purpose="Use recorded on-field players, personnel, pressure, route, and coverage context when available.",
            ),
            PlannedToolCall(
                tool="join_depth_chart_context",
                arguments={"team": request.scope.team},
                purpose="Compare listed first-unit availability and continuity when depth charts are synced.",
            ),
            PlannedToolCall(
                tool="join_ftn_charting",
                arguments={"team": request.scope.team},
                purpose="Compare charted motion, play action, RPO, pressure, and outcome rates when available.",
            ),
            PlannedToolCall(
                tool="join_nextgen_receiving_metrics",
                arguments={"team": request.scope.team},
                purpose="Add receiving separation and YAC-over-expectation context when available.",
            ),
            PlannedToolCall(
                tool="join_nextgen_rushing_metrics",
                arguments={"team": request.scope.team},
                purpose="Add rushing efficiency and yards-over-expectation context when available.",
            ),
            PlannedToolCall(
                tool="join_pfr_advanced_stats",
                arguments={"team": request.scope.team},
                purpose="Add published advanced passing, rushing, receiving, and defensive context when available.",
            ),
            PlannedToolCall(
                tool="find_representative_plays",
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
            supplemental: dict[str, dict[int, pl.DataFrame]] | None = None,
            supplemental_manifests: dict[str, dict[int, DatasetManifest]] | None = None,
    ) -> NFLAnalysisResult:
        supplemental = supplemental or {}
        supplemental_manifests = supplemental_manifests or {}
        team = self.resolve_team(request.scope.team)
        analysis_domain = request.analysis_domain
        seasons = request.scope.included_seasons
        endpoint_seasons = [request.scope.baseline_season, request.scope.comparison_season]
        missing = [season for season in seasons if season not in datasets]
        if missing:
            raise ValueError(f"missing synced seasons: {missing}")
        windows = [request.scope.baseline, request.scope.comparison]
        for window, frame in zip(windows, (datasets[endpoint_seasons[0]], datasets[endpoint_seasons[1]]), strict=True):
            if window.weeks != (1, 22) and "week" not in frame.columns:
                raise ValueError(f"season {window.season} does not contain the week field required for a custom window")
        baseline = _scope_plays(datasets[endpoint_seasons[0]], team, request.scope.season_type, windows[0].weeks, analysis_domain)
        comparison = _scope_plays(datasets[endpoint_seasons[1]], team, request.scope.season_type, windows[1].weeks, analysis_domain)
        if baseline.height < 30 or comparison.height < 30:
            raise ValueError(f"each comparison window requires at least 30 qualifying {analysis_domain} plays")
        season_frames = (
            {season: _scope_plays(datasets[season], team, request.scope.season_type, (1, 22), analysis_domain) for season in seasons}
            if request.scope.comparison_design == "full_seasons"
            else None
        )
        if season_frames:
            undersized = [season for season, frame in season_frames.items() if frame.height < 30]
            if undersized:
                raise ValueError(
                    f"each season in a full-season range requires at least 30 qualifying {analysis_domain} plays: {undersized}"
                )

        unknown_metrics = sorted(set(request.metrics) - set(METRICS))
        if unknown_metrics:
            raise ValueError(f"unsupported metrics: {unknown_metrics}")
        selected_metrics = request.metrics or DEFAULT_METRICS_BY_DOMAIN[analysis_domain]
        incompatible_metrics = sorted(metric for metric in selected_metrics if METRIC_DOMAINS[metric] != analysis_domain)
        if incompatible_metrics:
            raise ValueError(f"metrics are incompatible with the {analysis_domain} analysis domain: {incompatible_metrics}")
        unknown_splits = sorted(set(request.splits) - set(SPLIT_DIMENSIONS))
        if unknown_splits:
            raise ValueError(f"unsupported split dimensions: {unknown_splits}")
        selected_splits = request.splits or DEFAULT_SPLITS

        selected_manifests = list({manifests[season].manifest_id: manifests[season] for season in seasons}.values())
        validation_parameters = {
            "team": team,
            "analysis_domain": analysis_domain,
            "windows": [window.model_dump() for window in windows],
            "metrics": selected_metrics,
            "splits": selected_splits,
            "minimum_window_sample": 30,
        }
        validation_id = stable_id("execution", {"tool": "validate_analysis_scope", **validation_parameters})
        validation_started_at, validation_started = datetime.now(UTC), perf_counter()
        validation_execution = _execution_record(
            "validate_analysis_scope",
            validation_id,
            validation_parameters,
            [],
            selected_manifests,
            validation_started_at,
            validation_started,
        )
        started_at = datetime.now(UTC)
        start = perf_counter()
        execution_id = stable_id(
            "execution",
            {
                "tool": "compare_time_windows",
                "team": team,
                "windows": [window.model_dump() for window in windows],
                "metrics": selected_metrics,
                "splits": selected_splits,
            },
        )
        aggregate: list[AggregateEvidence] = []
        for index, metric in enumerate(selected_metrics):
            source, label = METRICS[metric]
            base_value = _metric_value(baseline, source)
            comp_value = _metric_value(comparison, source)
            if base_value is None or comp_value is None:
                continue
            low, high = _game_bootstrap(comparison, source, seed=endpoint_seasons[1] * 100 + index)
            payload = {
                "metric": metric,
                "team": team,
                "windows": [window.model_dump() for window in windows],
                "baseline": base_value,
                "comparison": comp_value,
            }
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

        if not aggregate:
            raise ValueError(f"selected metrics are unavailable for the requested windows: {selected_metrics}")

        comparison_evidence = list(aggregate)
        comparison_execution = _execution_record(
            "compare_time_windows",
            execution_id,
            {
                "team": team,
                "baseline": windows[0].model_dump(),
                "comparison": windows[1].model_dump(),
                "metrics": selected_metrics,
            },
            comparison_evidence,
            selected_manifests,
            started_at,
            start,
        )
        executions = [validation_execution, comparison_execution]

        preferred_primary = {"passing": "epa_per_dropback", "rushing": "epa_per_rush", "offense": "epa_per_play"}[analysis_domain]
        primary_metric = preferred_primary if preferred_primary in selected_metrics else selected_metrics[0]
        decomposition_parameters = {"metric": primary_metric, "splits": selected_splits}
        decomposition_id = stable_id("execution", {"tool": "decompose_metric_change", **decomposition_parameters})
        decomposition_started_at, decomposition_started = datetime.now(UTC), perf_counter()
        decomposition_evidence: list[AggregateEvidence] = []
        for split_name in (split for split in selected_splits if split != "score_state"):
            decomposition_evidence.extend(
                _decomposition(
                    baseline,
                    comparison,
                    SPLIT_COLUMNS[split_name],
                    selected_manifests,
                    decomposition_id,
                    split_name,
                    primary_metric,
                )
            )
        aggregate.extend(decomposition_evidence)
        executions.append(
            _execution_record(
                "decompose_metric_change",
                decomposition_id,
                decomposition_parameters,
                decomposition_evidence,
                selected_manifests,
                decomposition_started_at,
                decomposition_started,
            )
        )

        if "score_state" in selected_splits:
            game_state_parameters = {"metric": primary_metric, "split": "score_state"}
            game_state_id = stable_id("execution", {"tool": "analyze_game_state", **game_state_parameters})
            game_state_started_at, game_state_started = datetime.now(UTC), perf_counter()
            game_state_evidence = _decomposition(
                baseline,
                comparison,
                SPLIT_COLUMNS["score_state"],
                selected_manifests,
                game_state_id,
                "score_state",
                primary_metric,
            )
            aggregate.extend(game_state_evidence)
            executions.append(
                _execution_record(
                    "analyze_game_state",
                    game_state_id,
                    game_state_parameters,
                    game_state_evidence,
                    selected_manifests,
                    game_state_started_at,
                    game_state_started,
                )
            )

        adjusted_values = [
            _opponent_adjusted_epa(datasets[season], frame, team)
            for season, frame in zip(endpoint_seasons, (baseline, comparison), strict=True)
        ]
        opponent_evidence: list[AggregateEvidence] = []
        opponent_parameters = {"metric": "epa_per_dropback", "windows": [window.model_dump() for window in windows]}
        opponent_id = stable_id("execution", {"tool": "adjust_for_opponents", **opponent_parameters})
        opponent_started_at, opponent_started = datetime.now(UTC), perf_counter()
        if "epa_per_dropback" in selected_metrics and all(value is not None for value in adjusted_values):
            base_adjusted, comp_adjusted = (float(value) for value in adjusted_values if value is not None)
            payload = {
                "metric": "opponent_adjusted_epa_per_dropback",
                "team": team,
                "windows": [window.model_dump() for window in windows],
            }
            opponent_evidence.append(
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
                    tool_execution_id=opponent_id,
                    caveats=["Opponent baselines exclude the target game and require at least 30 other defensive dropbacks."],
                )
            )
        aggregate.extend(opponent_evidence)
        executions.append(
            _execution_record(
                "adjust_for_opponents",
                opponent_id,
                opponent_parameters,
                opponent_evidence,
                selected_manifests,
                opponent_started_at,
                opponent_started,
            )
        )

        if season_frames:
            trend_evidence, trend_execution = self._season_trends(
                season_frames, selected_metrics, selected_manifests, team, request.scope.season_type
            )
        else:
            trend_evidence, trend_execution = self._weekly_trends([baseline, comparison], windows, primary_metric, selected_manifests)
        aggregate.extend(trend_evidence)
        executions.append(trend_execution)

        outlier_evidence, outlier_execution = self._game_outliers(baseline, comparison, windows[1], primary_metric, selected_manifests)
        aggregate.extend(outlier_evidence)
        executions.append(outlier_execution)

        benchmark_evidence, benchmark_execution = self._league_benchmarks(
            team, datasets, windows, request.scope.season_type, selected_metrics, selected_manifests, analysis_domain
        )
        aggregate.extend(benchmark_evidence)
        executions.append(benchmark_execution)

        situational_evidence, situational_execution = self._situational_splits(
            baseline, comparison, primary_metric, selected_splits, selected_manifests
        )
        aggregate.extend(situational_evidence)
        executions.append(situational_execution)

        mix_evidence, mix_execution = self._play_mix(baseline, comparison, selected_splits, selected_manifests)
        aggregate.extend(mix_evidence)
        executions.append(mix_execution)

        change_evidence, change_execution = self._change_points(comparison, windows[1], primary_metric, selected_manifests)
        aggregate.extend(change_evidence)
        executions.append(change_execution)

        player_manifest_map = {manifest.manifest_id: manifest for manifest in selected_manifests}
        for dataset in ("rosters", "weekly_rosters", "injuries", "snap_counts", "participation", "depth_charts", "players"):
            if dataset == "players":
                manifest = supplemental_manifests.get(dataset, {}).get(0)
                if manifest:
                    player_manifest_map[manifest.manifest_id] = manifest
                continue
            for window in windows:
                manifest = supplemental_manifests.get(dataset, {}).get(window.season)
                if manifest:
                    player_manifest_map[manifest.manifest_id] = manifest
        player_manifests = list(player_manifest_map.values())
        player_weeks = normalize_player_weeks(
            team,
            windows,
            datasets,
            supplemental.get("rosters", {}),
            supplemental.get("injuries", {}),
            supplemental.get("snap_counts", {}),
            request.scope.season_type,
            weekly_rosters=supplemental.get("weekly_rosters", {}),
            participation=supplemental.get("participation", {}),
            depth_charts=supplemental.get("depth_charts", {}),
            player_directory=supplemental.get("players", {}).get(0),
        )
        player_week_evidence, player_week_execution = self._player_week_coverage(
            team, windows, player_weeks, player_manifests
        )
        aggregate.extend(player_week_evidence)
        executions.append(player_week_execution)

        depth_result = self._depth_chart_context(player_weeks, windows, player_manifests)
        if depth_result:
            depth_evidence, depth_execution = depth_result
            aggregate.extend(depth_evidence)
            executions.append(depth_execution)

        usage_evidence, usage_execution = self._player_usage_change(player_weeks, windows, player_manifests)
        aggregate.extend(usage_evidence)
        executions.append(usage_execution)

        availability_by_position = self._position_group_availability(player_weeks, windows, player_manifests)
        if availability_by_position:
            position_availability_evidence, position_availability_execution = availability_by_position
            aggregate.extend(position_availability_evidence)
            executions.append(position_availability_execution)

        continuity_result = self._lineup_continuity(player_weeks, windows, player_manifests)
        if continuity_result:
            continuity_evidence, continuity_executions = continuity_result
            aggregate.extend(continuity_evidence)
            executions.extend(continuity_executions)

        pair_evidence, pair_execution = self._qb_receiver_pairs(baseline, comparison, selected_manifests)
        aggregate.extend(pair_evidence)
        executions.append(pair_execution)

        missing_supplemental: list[str] = []
        roster_result = self._roster_context(team, windows, supplemental.get("rosters", {}), supplemental_manifests.get("rosters", {}))
        if roster_result:
            roster_evidence, roster_execution = roster_result
            aggregate.extend(roster_evidence)
            executions.append(roster_execution)
        else:
            missing_supplemental.append("rosters")

        availability_result = self._availability_context(
            team, windows, supplemental.get("injuries", {}), supplemental_manifests.get("injuries", {})
        )
        if availability_result:
            availability_evidence, availability_executions = availability_result
            aggregate.extend(availability_evidence)
            executions.extend(availability_executions)
        else:
            missing_supplemental.append("injuries")

        if any(window.season not in supplemental_manifests.get("snap_counts", {}) for window in windows):
            missing_supplemental.append("snap_counts")
        for dataset_name in ("weekly_rosters", "depth_charts"):
            if any(window.season not in supplemental_manifests.get(dataset_name, {}) for window in windows):
                missing_supplemental.append(dataset_name)

        nextgen_result = self._nextgen_context(
            team,
            windows,
            supplemental.get("nextgen_passing", {}),
            supplemental_manifests.get("nextgen_passing", {}),
        )
        if nextgen_result:
            nextgen_evidence, nextgen_execution = nextgen_result
            aggregate.extend(nextgen_evidence)
            executions.append(nextgen_execution)
        else:
            missing_supplemental.append("nextgen_passing")

        for dataset_name, stat_type in (("nextgen_receiving", "receiving"), ("nextgen_rushing", "rushing")):
            context = self._nextgen_context(
                team,
                windows,
                supplemental.get(dataset_name, {}),
                supplemental_manifests.get(dataset_name, {}),
                stat_type,
            )
            if context:
                context_evidence, context_execution = context
                aggregate.extend(context_evidence)
                executions.append(context_execution)
            else:
                missing_supplemental.append(dataset_name)

        participation_result = self._play_level_context(
            windows,
            [baseline, comparison],
            supplemental.get("participation", {}),
            supplemental_manifests.get("participation", {}),
            manifests,
            "join_participation_context",
            "participation",
            {
                "pressure_rate": "Pressure rate",
                "man_coverage_rate": "Man-coverage rate",
                "defenders_in_box": "Defenders in the box",
                "number_of_pass_rushers": "Number of pass rushers",
                "time_to_throw": "Time to throw",
                "n_offense": "Recorded offensive players",
                "n_defense": "Recorded defensive players",
            },
        )
        if participation_result:
            participation_evidence, participation_execution = participation_result
            aggregate.extend(participation_evidence)
            executions.append(participation_execution)
        else:
            missing_supplemental.append("participation")

        ftn_result = self._play_level_context(
            windows,
            [baseline, comparison],
            supplemental.get("ftn_charting", {}),
            supplemental_manifests.get("ftn_charting", {}),
            manifests,
            "join_ftn_charting",
            "ftn",
            {
                "is_motion": "Pre-snap motion rate",
                "is_play_action": "Play-action rate",
                "is_screen_pass": "Screen rate",
                "is_rpo": "RPO rate",
                "is_qb_out_of_pocket": "Quarterback out-of-pocket rate",
                "is_interception_worthy": "Interception-worthy throw rate",
                "is_catchable_ball": "Catchable-ball rate",
                "is_drop": "Drop rate",
                "n_blitzers": "Number of blitzers",
                "n_pass_rushers": "Number of pass rushers",
                "is_qb_fault_sack": "Quarterback-fault sack rate",
            },
        )
        if ftn_result:
            ftn_evidence, ftn_execution = ftn_result
            aggregate.extend(ftn_evidence)
            executions.append(ftn_execution)
        else:
            missing_supplemental.append("ftn_charting")

        pfr_metric_sets = {
            "pfr_passing": {
                "passing_drop_pct": "Passing drop rate",
                "passing_bad_throw_pct": "Bad-throw rate",
                "times_blitzed": "Times blitzed",
                "times_hurried": "Times hurried",
                "times_hit": "Quarterback hits",
                "times_pressured_pct": "Pressure rate",
            },
            "pfr_rushing": {
                "rushing_yards_before_contact": "Yards before contact",
                "rushing_yards_after_contact": "Yards after contact",
                "rushing_broken_tackles": "Broken tackles",
            },
            "pfr_receiving": {
                "receiving_drop": "Receiver drops",
                "receiving_drop_pct": "Receiver drop rate",
                "receiving_broken_tackles": "Receiving broken tackles",
            },
            "pfr_defense": {
                "def_times_blitzed": "Defensive blitzes",
                "def_times_hurried": "Defensive hurries",
                "def_times_hitqb": "Defensive quarterback hits",
                "def_targets": "Coverage targets",
            },
        }
        for dataset_name, candidates in pfr_metric_sets.items():
            pfr_result = self._published_stat_context(
                team,
                windows,
                supplemental.get(dataset_name, {}),
                supplemental_manifests.get(dataset_name, {}),
                "join_pfr_advanced_stats",
                dataset_name,
                candidates,
            )
            if pfr_result:
                pfr_evidence, pfr_execution = pfr_result
                aggregate.extend(pfr_evidence)
                executions.append(pfr_execution)
            else:
                missing_supplemental.append(dataset_name)

        schedule_result = self._schedule_context(
            team, windows, supplemental.get("schedules", {}), supplemental_manifests.get("schedules", {})
        )
        if schedule_result:
            schedule_evidence, schedule_execution = schedule_result
            aggregate.extend(schedule_evidence)
            executions.append(schedule_execution)
        else:
            missing_supplemental.append("schedules")

        play_parameters = {
            "team": team,
            "window": windows[1].model_dump(),
            "supporting": 3,
            "counterexamples": 2,
            "minimum_absolute_epa": 0.0,
        }
        play_id = stable_id("execution", {"tool": "find_representative_plays", **play_parameters})
        play_started_at, play_started = datetime.now(UTC), perf_counter()
        plays = self._representative_plays(
            comparison,
            team,
            manifests[endpoint_seasons[1]],
            play_id,
            supporting_count=int(play_parameters["supporting"]),
            counterexample_count=int(play_parameters["counterexamples"]),
            minimum_absolute_epa=float(play_parameters["minimum_absolute_epa"]),
        )
        plays = self._enrich_representative_plays(
            plays,
            supplemental.get("participation", {}).get(windows[1].season),
            supplemental.get("ftn_charting", {}).get(windows[1].season),
        )
        executions.append(
            _execution_record(
                "find_representative_plays",
                play_id,
                play_parameters,
                plays,
                selected_manifests,
                play_started_at,
                play_started,
            )
        )
        charts = self._charts(aggregate, baseline, comparison, windows, season_frames, primary_metric, analysis_domain)
        caveats = [
            "The analysis is observational; football interpretations are not causal estimates.",
            "EPA, CPOE, and other nflverse model outputs inherit their model assumptions.",
            "Formation and personnel conclusions are omitted when source fields or subgroup samples are insufficient.",
            *player_weeks.caveats,
        ]
        if missing_supplemental:
            caveats.append(
                "Supplemental tools were skipped because these datasets were not synced for both windows: "
                + ", ".join(missing_supplemental)
                + "."
            )
        if season_frames:
            caveats.append(
                "Season-range trends include every selected season; situational decompositions, representative plays, and contextual "
                "diagnostics compare the range's first and final seasons."
            )
        return NFLAnalysisResult(aggregate, plays, charts, executions, caveats)
