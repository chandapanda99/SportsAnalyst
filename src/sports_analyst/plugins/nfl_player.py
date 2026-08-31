"""First-class NFL quarterback, receiving, and rushing analysis."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import polars as pl

from sports_analyst.models import (
    AggregateEvidence,
    AnalysisRequest,
    AnalysisWindow,
    ChartArtifact,
    DatasetManifest,
    MetricDefinition,
    MetricOption,
    stable_id,
)
from sports_analyst.plugins.nfl_shared import (
    NFLAnalysisResult,
    _execution_record,
    _game_bootstrap,
    _metric_value,
    _scope_plays,
    _sha,
)

# source, label, category, domain, description, formula, interpretation, higher-is-better, required columns
PLAYER_METRICS: dict[str, tuple[str, str, str, str, str, str, str, bool, set[str]]] = {
    "qb_epa_per_dropback": (
        "epa",
        "EPA/dropback",
        "Efficiency",
        "quarterback",
        "Expected points added per quarterback dropback.",
        "mean(epa) over the player's dropbacks",
        "Higher values indicate more expected points added per dropback.",
        True,
        {"epa", "passer_player_id"},
    ),
    "qb_success_rate": (
        "success",
        "Success rate",
        "Efficiency",
        "quarterback",
        "Share of quarterback dropbacks with positive EPA.",
        "successful dropbacks / player dropbacks",
        "Higher values indicate more consistently productive dropbacks.",
        True,
        {"success", "passer_player_id"},
    ),
    "qb_cpoe": (
        "cpoe",
        "CPOE",
        "Accuracy",
        "quarterback",
        "Completion percentage over expectation on recorded attempts.",
        "mean(cpoe) on the player's attempts",
        "Positive values indicate completion above model expectation.",
        True,
        {"cpoe", "passer_player_id"},
    ),
    "qb_yards_per_dropback": (
        "yards_gained",
        "Yards/dropback",
        "Production",
        "quarterback",
        "Team yards gained per quarterback dropback.",
        "sum(yards_gained) / player dropbacks",
        "Higher values indicate more yardage generated per dropback.",
        True,
        {"yards_gained", "passer_player_id"},
    ),
    "qb_explosive_pass_rate": (
        "explosive",
        "Explosive pass rate",
        "Production",
        "quarterback",
        "Share of dropbacks gaining at least 20 yards.",
        "20+ yard dropbacks / player dropbacks",
        "Higher values indicate more explosive passing outcomes.",
        True,
        {"yards_gained", "passer_player_id"},
    ),
    "qb_sack_rate": (
        "sack",
        "Sack rate",
        "Negative outcomes",
        "quarterback",
        "Share of quarterback dropbacks ending in a sack.",
        "sacks / player dropbacks",
        "Lower values are generally better.",
        False,
        {"sack", "passer_player_id"},
    ),
    "qb_interception_rate": (
        "interception",
        "Interception rate",
        "Negative outcomes",
        "quarterback",
        "Share of quarterback dropbacks ending in an interception.",
        "interceptions / player dropbacks",
        "Lower values are generally better.",
        False,
        {"interception", "passer_player_id"},
    ),
    "receiver_targets_per_game": (
        "plays_per_game",
        "Targets/game",
        "Volume",
        "receiving",
        "Recorded targets per game played in the selected window.",
        "targets / distinct games with a target",
        "Higher values indicate greater receiving opportunity.",
        True,
        {"receiver_player_id", "game_id"},
    ),
    "receiver_catch_rate": (
        "complete_pass",
        "Catch rate",
        "Efficiency",
        "receiving",
        "Share of recorded targets completed to the receiver.",
        "receptions / targets",
        "Higher values indicate a greater completion share on targets.",
        True,
        {"receiver_player_id", "complete_pass"},
    ),
    "receiver_yards_per_target": (
        "yards_gained",
        "Yards/target",
        "Production",
        "receiving",
        "Receiving yards generated per recorded target.",
        "sum(yards_gained) / targets",
        "Higher values combine catch conversion and production after the catch.",
        True,
        {"receiver_player_id", "yards_gained"},
    ),
    "receiver_epa_per_target": (
        "epa",
        "EPA/target",
        "Efficiency",
        "receiving",
        "Expected points added per recorded target.",
        "mean(epa) over targets",
        "Higher values indicate more expected points added when targeted.",
        True,
        {"receiver_player_id", "epa"},
    ),
    "receiver_success_rate": (
        "success",
        "Target success rate",
        "Efficiency",
        "receiving",
        "Share of targets with positive EPA.",
        "successful targets / targets",
        "Higher values indicate more consistently productive targets.",
        True,
        {"receiver_player_id", "success"},
    ),
    "receiver_explosive_rate": (
        "explosive",
        "Explosive target rate",
        "Production",
        "receiving",
        "Share of targets gaining at least 20 yards.",
        "20+ yard targets / targets",
        "Higher values indicate more explosive target outcomes.",
        True,
        {"receiver_player_id", "yards_gained"},
    ),
    "receiver_air_yards_per_target": (
        "air_yards",
        "Air yards/target",
        "Usage",
        "receiving",
        "Average intended air yards per recorded target.",
        "mean(air_yards) over targets",
        "Higher values indicate a deeper target profile, not necessarily better performance.",
        True,
        {"receiver_player_id", "air_yards"},
    ),
    "receiver_yac_per_reception": (
        "yards_after_catch",
        "YAC/reception",
        "Production",
        "receiving",
        "Average yards after catch on completed receptions.",
        "mean(yards_after_catch) on completions",
        "Higher values reflect receiver, scheme, and defensive context.",
        True,
        {"receiver_player_id", "yards_after_catch"},
    ),
    "rusher_carries_per_game": (
        "plays_per_game",
        "Carries/game",
        "Volume",
        "running",
        "Qualifying rushing attempts per game with a carry.",
        "carries / distinct games with a carry",
        "Higher values indicate greater rushing volume.",
        True,
        {"rusher_player_id", "game_id"},
    ),
    "rusher_epa_per_carry": (
        "epa",
        "EPA/carry",
        "Efficiency",
        "running",
        "Expected points added per qualifying carry.",
        "mean(epa) over carries",
        "Higher values indicate more expected points added per carry.",
        True,
        {"rusher_player_id", "epa"},
    ),
    "rusher_success_rate": (
        "success",
        "Rush success rate",
        "Efficiency",
        "running",
        "Share of carries with positive EPA.",
        "successful carries / carries",
        "Higher values indicate more consistently productive carries.",
        True,
        {"rusher_player_id", "success"},
    ),
    "rusher_yards_per_carry": (
        "yards_gained",
        "Yards/carry",
        "Production",
        "running",
        "Average yards gained per qualifying carry.",
        "sum(yards_gained) / carries",
        "Higher values indicate more yardage per carry.",
        True,
        {"rusher_player_id", "yards_gained"},
    ),
    "rusher_explosive_rate": (
        "explosive_run",
        "Explosive run rate",
        "Production",
        "running",
        "Share of carries gaining at least 10 yards.",
        "10+ yard carries / carries",
        "Higher values indicate more explosive rushing outcomes.",
        True,
        {"rusher_player_id", "yards_gained"},
    ),
    "rusher_stuff_rate": (
        "stuff",
        "Stuff rate",
        "Negative outcomes",
        "running",
        "Share of carries stopped at or behind the line.",
        "carries gaining zero or fewer yards / carries",
        "Lower values are generally better.",
        False,
        {"rusher_player_id", "yards_gained"},
    ),
}

PLAYER_DEFAULTS = {
    "quarterback": ["qb_epa_per_dropback", "qb_success_rate", "qb_cpoe", "qb_yards_per_dropback"],
    "receiving": ["receiver_targets_per_game", "receiver_epa_per_target", "receiver_catch_rate", "receiver_yards_per_target"],
    "running": ["rusher_carries_per_game", "rusher_epa_per_carry", "rusher_success_rate", "rusher_yards_per_carry"],
}

PLAYER_ID_COLUMNS = (
    "player_id",
    "gsis_id",
    "player_gsis_id",
    "nflverse_id",
    "pfr_id",
    "pfr_player_id",
    "espn_id",
    "nfl_id",
    "esb_id",
    "gsis_it_id",
    "smart_id",
    "sportradar_id",
)
PLAYER_NAME_COLUMNS = ("player_name", "player_display_name", "display_name", "full_name", "player")
PLAYER_TEAM_COLUMNS = ("recent_team", "team", "team_abbr")

PUBLISHED_QB_METRICS = {
    "nextgen_passing": {
        "avg_time_to_throw": "Average time to throw",
        "avg_completed_air_yards": "Completed air yards",
        "aggressiveness": "Aggressiveness",
        "completion_percentage_above_expectation": "NGS CPOE",
        "avg_air_yards_differential": "Air-yards differential",
    },
    "pfr_passing": {
        "passing_drop_pct": "Drop rate",
        "passing_bad_throw_pct": "Bad-throw rate",
        "times_blitzed": "Times blitzed",
        "times_hurried": "Times hurried",
        "times_hit": "Quarterback hits",
        "times_pressured_pct": "Pressure rate",
    },
}


def player_metric_options(seasons_with: Callable[[set[str]], list[int]]) -> list[MetricOption]:
    return [
        MetricOption(
            value=value,
            label=item[1],
            category=item[2],
            description=item[4],
            analysis_domain=item[3],
            available_seasons=seasons_with(item[8]),
            subject_types=["player"],
        )
        for value, item in PLAYER_METRICS.items()
    ]


def player_metric_definition(metric: str) -> MetricDefinition:
    item = PLAYER_METRICS[metric]
    return MetricDefinition(
        value=metric,
        label=item[1],
        category=item[2],
        description=item[4],
        formula=item[5],
        qualifying_plays=f"Plays attributed to the selected NFL player in the {item[3]} domain and requested window.",
        interpretation=item[6],
        higher_is_better=item[7],
        limitations=[
            "Play attribution depends on nflverse player identifiers being recorded on the play.",
            "The analysis is observational and does not isolate supporting cast, scheme, or opponent effects.",
        ],
    )


def _scope_player(
    frame: pl.DataFrame,
    request: AnalysisRequest,
    season: int,
    weeks: tuple[int, int],
    identifiers: set[str] | None = None,
    names: set[str] | None = None,
) -> pl.DataFrame:
    subject = request.subject
    if subject is None or subject.type != "player":
        raise ValueError("NFL player analysis requires a player subject")
    domain = request.analysis_domain
    team = subject.team_id or request.scope.team
    base_domain = "passing" if domain in {"quarterback", "receiving"} else "rushing"
    # Scope by a known team stint when supplied. Otherwise retain every team and
    # filter by player identity below, which supports traded players.
    scoped_team = team if team and team.upper() not in {"NFL", "ALL"} else None
    if scoped_team:
        scoped = _scope_plays(frame, scoped_team.upper(), request.scope.season_type, weeks, base_domain)
    else:
        frames = []
        if "posteam" in frame.columns:
            for candidate in frame["posteam"].drop_nulls().unique().to_list():
                frames.append(_scope_plays(frame, str(candidate), request.scope.season_type, weeks, base_domain))
        scoped = pl.concat(frames, how="diagonal_relaxed") if frames else frame.head(0)
    id_column = {"quarterback": "passer_player_id", "receiving": "receiver_player_id", "running": "rusher_player_id"}[domain]
    name_column = {
        "quarterback": "passer_player_name",
        "receiving": "receiver_player_name",
        "running": "rusher_player_name",
    }[domain]
    if id_column not in scoped.columns:
        raise ValueError(f"the synced play-by-play data does not contain {id_column} required for {domain} analysis")
    known_ids = sorted(identifiers or {subject.id})
    identity_match = pl.col(id_column).cast(pl.String, strict=False).is_in(known_ids)
    if names and name_column in scoped.columns:
        identity_match |= (
            pl.col(name_column)
            .cast(pl.String, strict=False)
            .str.strip_chars()
            .str.to_lowercase()
            .is_in(sorted(names))
        )
    scoped = scoped.filter(identity_match)
    return scoped.with_columns(
        (pl.col("complete_pass").cast(pl.Float64, strict=False) if "complete_pass" in scoped.columns else pl.lit(None)).alias(
            "_complete_pass"
        ),
        (pl.col("touchdown").cast(pl.Float64, strict=False) if "touchdown" in scoped.columns else pl.lit(None)).alias("_touchdown"),
    )


def _value(frame: pl.DataFrame, source: str) -> float | None:
    if source == "plays_per_game":
        if frame.is_empty() or "game_id" not in frame.columns:
            return None
        games = frame["game_id"].drop_nulls().n_unique()
        return frame.height / games if games else None
    return _metric_value(frame, source)


def _player_identity(subject_id: str, directory: pl.DataFrame | None) -> tuple[set[str], set[str]]:
    identifiers = {subject_id}
    names: set[str] = set()
    if directory is None or directory.is_empty():
        return identifiers, names
    id_columns = [column for column in PLAYER_ID_COLUMNS if column in directory.columns]
    if not id_columns:
        return identifiers, names
    matching = directory.filter(
        pl.any_horizontal([pl.col(column).cast(pl.String, strict=False) == subject_id for column in id_columns])
    )
    for row in matching.iter_rows(named=True):
        identifiers.update(str(row[column]) for column in id_columns if row.get(column) is not None)
        names.update(str(row[column]).strip().casefold() for column in PLAYER_NAME_COLUMNS if row.get(column))
    return identifiers, names


def _scope_published_player(
    frame: pl.DataFrame,
    request: AnalysisRequest,
    window: AnalysisWindow,
    identifiers: set[str],
    names: set[str],
) -> pl.DataFrame:
    id_columns = [column for column in PLAYER_ID_COLUMNS if column in frame.columns]
    name_columns = [column for column in PLAYER_NAME_COLUMNS if column in frame.columns]
    identity_expressions = [
        pl.col(column).cast(pl.String, strict=False).is_in(sorted(identifiers)) for column in id_columns
    ]
    identity_expressions.extend(
        pl.col(column)
        .cast(pl.String, strict=False)
        .str.strip_chars()
        .str.to_lowercase()
        .is_in(sorted(names))
        for column in name_columns
        if names
    )
    if not identity_expressions:
        return frame.head(0)
    scoped = frame.filter(pl.any_horizontal(identity_expressions))
    team = request.subject.team_id if request.subject else None
    team_column = next((column for column in PLAYER_TEAM_COLUMNS if column in scoped.columns), None)
    if team and team_column:
        scoped = scoped.filter(pl.col(team_column).cast(pl.String).str.to_uppercase() == team.upper())
    week_column = next((column for column in ("week", "week_number") if column in scoped.columns), None)
    if week_column:
        scoped = scoped.filter(pl.col(week_column).cast(pl.Int64, strict=False).is_between(*window.weeks, closed="both"))
    if request.scope.season_type != "ALL" and "season_type" in scoped.columns:
        scoped = scoped.filter(
            pl.col("season_type").cast(pl.String).str.to_uppercase() == request.scope.season_type
        )
    return scoped


def _numeric_values(frame: pl.DataFrame, column: str) -> pl.Series:
    if column not in frame.columns:
        return pl.Series(name=column, values=[], dtype=pl.Float64)
    return frame[column].cast(pl.Float64, strict=False).drop_nulls()


def _player_stats_summary(frame: pl.DataFrame) -> dict[str, tuple[str, float, int, str]]:
    summary: dict[str, tuple[str, float, int, str]] = {}
    volume = {
        "attempts": ("Pass attempts", "attempts"),
        "completions": ("Completions", "completions"),
        "passing_yards": ("Passing yards", "yards"),
        "passing_tds": ("Passing touchdowns", "touchdowns"),
        "passing_interceptions": ("Interceptions", "interceptions"),
        "sacks_suffered": ("Sacks", "sacks"),
    }
    for column, (label, unit) in volume.items():
        values = _numeric_values(frame, column)
        if values.len():
            summary[column] = (label, float(values.sum()), values.len(), unit)
    attempts = float(_numeric_values(frame, "attempts").sum() or 0)
    completions = float(_numeric_values(frame, "completions").sum() or 0)
    # Current nflverse schemas use these names. Retain the legacy aliases so
    # older synced packages and fixtures remain readable.
    interception_column = "passing_interceptions" if "passing_interceptions" in frame.columns else "interceptions"
    sack_column = "sacks_suffered" if "sacks_suffered" in frame.columns else "sacks"
    sacks = float(_numeric_values(frame, sack_column).sum() or 0)
    if attempts:
        summary["completion_percentage"] = ("Completion percentage", completions / attempts, int(attempts), "rate")
        passing_yards = float(_numeric_values(frame, "passing_yards").sum() or 0)
        touchdowns = float(_numeric_values(frame, "passing_tds").sum() or 0)
        interceptions = float(_numeric_values(frame, interception_column).sum() or 0)
        summary["yards_per_attempt"] = ("Passing yards/attempt", passing_yards / attempts, int(attempts), "yards/attempt")
        summary["touchdown_rate"] = ("Touchdown rate", touchdowns / attempts, int(attempts), "rate")
        summary["interception_rate"] = ("Published interception rate", interceptions / attempts, int(attempts), "rate")
    dropbacks = attempts + sacks
    passing_epa = _numeric_values(frame, "passing_epa")
    if dropbacks and passing_epa.len():
        summary["epa_per_dropback"] = ("Published EPA/dropback", float(passing_epa.sum()) / dropbacks, int(dropbacks), "EPA/dropback")
    cpoe = _numeric_values(frame, "passing_cpoe")
    if cpoe.len():
        summary["cpoe"] = ("Published passing CPOE", float(cpoe.mean()), cpoe.len(), "published value")
    return summary


def _published_summary(dataset: str, frame: pl.DataFrame) -> dict[str, tuple[str, float, int, str]]:
    if dataset == "player_stats":
        return _player_stats_summary(frame)
    summary: dict[str, tuple[str, float, int, str]] = {}
    for column, label in PUBLISHED_QB_METRICS.get(dataset, {}).items():
        values = _numeric_values(frame, column)
        if values.len():
            summary[column] = (label, float(values.mean()), values.len(), "published value")
    return summary


class NFLPlayerAnalysisMixin:
    """Analyze a selected NFL player without routing through team diagnostics."""

    def _published_player_context(
        self,
        request: AnalysisRequest,
        windows: list[AnalysisWindow],
        supplemental: dict[str, dict[int, pl.DataFrame]],
        supplemental_manifests: dict[str, dict[int, DatasetManifest]],
    ) -> tuple[list[AggregateEvidence], list[Any]]:
        subject = request.subject
        assert subject is not None
        directory = supplemental.get("players", {}).get(0)
        identifiers, names = _player_identity(subject.id, directory)
        evidence: list[AggregateEvidence] = []
        executions = []
        for dataset in ("player_stats", "nextgen_passing", "pfr_passing"):
            frames = supplemental.get(dataset, {})
            manifests = supplemental_manifests.get(dataset, {})
            if any(window.season not in frames or window.season not in manifests for window in windows):
                continue
            selected_manifests = list({manifests[window.season].manifest_id: manifests[window.season] for window in windows}.values())
            parameters = {
                "subject": subject.model_dump(),
                "dataset": dataset,
                "windows": [window.model_dump() for window in windows],
            }
            tool = "compare_player_published_stats"
            execution_id = stable_id("execution", {"tool": tool, **parameters})
            started_at, started = datetime.now(UTC), perf_counter()
            summaries = [
                _published_summary(
                    dataset,
                    _scope_published_player(frames[window.season], request, window, identifiers, names),
                )
                for window in windows
            ]
            dataset_evidence: list[AggregateEvidence] = []
            for metric in sorted(set(summaries[0]) & set(summaries[1])):
                base_label, base_value, base_n, unit = summaries[0][metric]
                label, comparison_value, comparison_n, _ = summaries[1][metric]
                payload = {**parameters, "metric": metric, "baseline_value": base_value, "comparison_value": comparison_value}
                caveats = [
                    f"Supplemental {dataset} evidence; this published statistic is not substituted for a differently "
                    "defined play-derived metric."
                ]
                if min(base_n, comparison_n) < 10:
                    caveats.append(
                        f"Small published sample: {base_n} baseline and {comparison_n} comparison observations."
                    )
                dataset_evidence.append(
                    AggregateEvidence(
                        evidence_id=stable_id("evidence", payload),
                        metric=f"{dataset}_{metric}",
                        label=label or base_label,
                        value=round(comparison_value - base_value, 4),
                        baseline_value=round(base_value, 4),
                        comparison_value=round(comparison_value, 4),
                        unit=unit,
                        sample_size=comparison_n,
                        row_set_sha256=_sha(payload),
                        dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                        tool_execution_id=execution_id,
                        caveats=caveats,
                    )
                )
            evidence.extend(dataset_evidence)
            executions.append(
                _execution_record(tool, execution_id, parameters, dataset_evidence, selected_manifests, started_at, started)
            )
        return evidence, executions

    def analyze_player(
        self,
        request: AnalysisRequest,
        datasets: dict[int, pl.DataFrame],
        manifests: dict[int, DatasetManifest],
        supplemental: dict[str, dict[int, pl.DataFrame]],
        supplemental_manifests: dict[str, dict[int, DatasetManifest]],
    ) -> NFLAnalysisResult:
        subject = request.subject
        assert subject is not None
        domain = request.analysis_domain
        if domain not in PLAYER_DEFAULTS:
            raise ValueError(f"unsupported NFL player analysis domain: {domain}")
        seasons = request.scope.included_seasons
        missing = [season for season in seasons if season not in datasets]
        if missing:
            raise ValueError(f"missing synced seasons: {missing}")
        selected_metrics = request.metrics or PLAYER_DEFAULTS[domain]
        unknown = sorted(set(selected_metrics) - set(PLAYER_METRICS))
        if unknown:
            raise ValueError(f"unsupported NFL player metrics: {unknown}")
        incompatible = [metric for metric in selected_metrics if PLAYER_METRICS[metric][3] != domain]
        if incompatible:
            raise ValueError(f"metrics are incompatible with {domain} analysis: {incompatible}")

        windows = [request.scope.baseline, request.scope.comparison]
        directory = supplemental.get("players", {}).get(0)
        identifiers, names = _player_identity(subject.id, directory)
        baseline = _scope_player(
            datasets[windows[0].season], request, windows[0].season, windows[0].weeks, identifiers, names
        )
        comparison = _scope_player(
            datasets[windows[1].season], request, windows[1].season, windows[1].weeks, identifiers, names
        )
        season_frames = (
            {
                season: _scope_player(datasets[season], request, season, (1, 22), identifiers, names)
                for season in seasons
            }
            if request.scope.comparison_design == "full_seasons"
            else None
        )
        selected_manifests = [manifests[season] for season in seasons]
        parameters = {
            "subject": subject.model_dump(),
            "domain": domain,
            "baseline": windows[0].model_dump(),
            "comparison": windows[1].model_dump(),
            "metrics": selected_metrics,
        }
        execution_id = stable_id("execution", {"tool": "compare_player_windows", **parameters})
        started_at, started = datetime.now(UTC), perf_counter()
        evidence: list[AggregateEvidence] = []
        play_sample_caveats = []
        if min(baseline.height, comparison.height) < 10:
            play_sample_caveats.append(
                f"Small attributed-play sample: {baseline.height} baseline and {comparison.height} comparison plays; "
                "all available plays are included and the estimates are highly uncertain."
            )
        for index, metric in enumerate(selected_metrics):
            source, label = PLAYER_METRICS[metric][0:2]
            base_value, comp_value = _value(baseline, source), _value(comparison, source)
            if base_value is None or comp_value is None:
                continue
            low, high = (None, None) if source == "plays_per_game" else _game_bootstrap(comparison, source, windows[1].season * 100 + index)
            payload = {**parameters, "metric": metric, "baseline_value": base_value, "comparison_value": comp_value}
            evidence.append(
                AggregateEvidence(
                    evidence_id=stable_id("evidence", payload),
                    metric=metric,
                    label=label,
                    value=round(comp_value - base_value, 4),
                    baseline_value=round(base_value, 4),
                    comparison_value=round(comp_value, 4),
                    unit="per game" if source == "plays_per_game" else "rate or per play",
                    sample_size=comparison.height,
                    confidence_low=round(low, 4) if low is not None else None,
                    confidence_high=round(high, 4) if high is not None else None,
                    row_set_sha256=_sha(payload),
                    dataset_manifest_ids=[item.manifest_id for item in selected_manifests],
                    tool_execution_id=execution_id,
                    caveats=[
                        *play_sample_caveats,
                        *(
                            ["The comparison window contains fewer than 30 attributed plays; interpret the estimate cautiously."]
                            if comparison.height < 30 and not play_sample_caveats
                            else []
                        ),
                    ],
                )
            )
        executions = [_execution_record("compare_player_windows", execution_id, parameters, evidence, selected_manifests, started_at, started)]
        if domain == "quarterback":
            published_evidence, published_executions = self._published_player_context(
                request, windows, supplemental, supplemental_manifests
            )
            evidence.extend(published_evidence)
            executions.extend(published_executions)
        if not evidence:
            frames_for_availability = season_frames or {
                windows[0].season: baseline,
                windows[1].season: comparison,
            }
            available_seasons = sorted(
                season for season, frame in frames_for_availability.items() if not frame.is_empty()
            )
            display_name = next(
                (
                    str(frame[name_column][0])
                    for frame in frames_for_availability.values()
                    if not frame.is_empty()
                    for name_column in (
                        "passer_player_name",
                        "receiver_player_name",
                        "rusher_player_name",
                    )
                    if name_column in frame.columns and frame[name_column][0] is not None
                ),
                subject.id,
            )
            requested = f"{windows[0].season} and {windows[1].season}"
            available = ", ".join(str(season) for season in available_seasons) or "none"
            raise ValueError(
                f"{display_name} does not have comparable {domain} data in both requested seasons ({requested}). "
                f"Available {domain} seasons in this range: {available}. Choose two seasons with recorded activity."
            )

        primary = next((metric for metric in selected_metrics if any(item.metric == metric for item in evidence)), selected_metrics[0])
        trend_values: list[dict[str, Any]] = []
        trend_evidence: list[AggregateEvidence] = []
        frames = season_frames or {windows[0].season: baseline, windows[1].season: comparison}
        trend_id = stable_id("execution", {"tool": "analyze_player_trends", "subject": subject.id, "metric": primary})
        trend_started_at, trend_started = datetime.now(UTC), perf_counter()
        for season, frame in sorted(frames.items()):
            value = _value(frame, PLAYER_METRICS[primary][0])
            if value is None:
                continue
            payload = {"subject": subject.id, "season": season, "metric": primary, "value": value}
            item = AggregateEvidence(
                evidence_id=stable_id("evidence", payload),
                metric=f"seasonal_{primary}",
                label=f"{season} · {PLAYER_METRICS[primary][1]}",
                value=round(value, 4),
                sample_size=frame.height,
                row_set_sha256=_sha(payload),
                dataset_manifest_ids=[manifests[season].manifest_id],
                tool_execution_id=trend_id,
            )
            trend_evidence.append(item)
            trend_values.append({"season": season, "value": value, "metric": PLAYER_METRICS[primary][1]})
        evidence.extend(trend_evidence)
        executions.append(
            _execution_record(
                "analyze_player_trends",
                trend_id,
                {"subject": subject.id, "metric": primary},
                trend_evidence,
                selected_manifests,
                trend_started_at,
                trend_started,
            )
        )

        labels = [f"{window.season} W{window.weeks[0]}–{window.weeks[1]}" for window in windows]
        metric_evidence = [item for item in evidence if item.metric in PLAYER_METRICS]
        chart_values = [
            record
            for item in metric_evidence
            for record in (
                {"metric": item.label, "window": labels[0], "value": item.baseline_value},
                {"metric": item.label, "window": labels[1], "value": item.comparison_value},
            )
        ]
        charts = []
        if chart_values:
            charts.append(ChartArtifact(
                chart_id=stable_id("chart", {"type": "player-metric-comparison", **parameters}),
                title=f"{domain.title()} performance comparison",
                specification={
                    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                    "data": {"values": chart_values},
                    "mark": {"type": "bar", "cornerRadiusEnd": 3},
                    "encoding": {
                        "x": {"field": "metric", "type": "nominal", "sort": None, "axis": {"labelAngle": -20}},
                        "y": {"field": "value", "type": "quantitative"},
                        "color": {"field": "window", "type": "nominal"},
                        "xOffset": {"field": "window"},
                        "tooltip": [
                            {"field": "metric"},
                            {"field": "window"},
                            {"field": "value", "format": ".3f"},
                        ],
                    },
                },
                evidence_ids=[item.evidence_id for item in metric_evidence],
            ))
        published_metric_evidence = [
            item
            for item in evidence
            if item.metric.startswith(("player_stats_", "nextgen_passing_", "pfr_passing_"))
        ][:8]
        if published_metric_evidence:
            published_values = [
                record
                for item in published_metric_evidence
                for record in (
                    {"metric": item.label, "window": labels[0], "value": item.baseline_value},
                    {"metric": item.label, "window": labels[1], "value": item.comparison_value},
                )
            ]
            charts.append(
                ChartArtifact(
                    chart_id=stable_id("chart", {"type": "published-player-metric-comparison", **parameters}),
                    title="Supplemental published quarterback statistics",
                    specification={
                        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                        "data": {"values": published_values},
                        "mark": {"type": "bar", "cornerRadiusEnd": 3},
                        "encoding": {
                            "x": {"field": "metric", "type": "nominal", "sort": None, "axis": {"labelAngle": -20}},
                            "y": {"field": "value", "type": "quantitative"},
                            "color": {"field": "window", "type": "nominal"},
                            "xOffset": {"field": "window"},
                            "tooltip": [{"field": "metric"}, {"field": "window"}, {"field": "value", "format": ".3f"}],
                        },
                    },
                    evidence_ids=[item.evidence_id for item in published_metric_evidence],
                )
            )
        if trend_values:
            charts.append(
                ChartArtifact(
                    chart_id=stable_id("chart", {"type": "player-season-trend", "subject": subject.id, "metric": primary}),
                    title=f"Season-by-season {PLAYER_METRICS[primary][1]}",
                    specification={
                        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                        "data": {"values": trend_values},
                        "mark": {"type": "line", "point": True},
                        "encoding": {
                            "x": {"field": "season", "type": "ordinal", "sort": "ascending"},
                            "y": {"field": "value", "type": "quantitative", "title": PLAYER_METRICS[primary][1]},
                            "tooltip": [{"field": "season"}, {"field": "value", "format": ".3f"}],
                        },
                    },
                    evidence_ids=[item.evidence_id for item in trend_evidence],
                )
            )

        team = subject.team_id or (
            str(comparison["posteam"][0]) if "posteam" in comparison.columns and comparison.height else request.scope.team
        )
        play_parameters = {
            "subject": subject.id,
            "domain": domain,
            "windows": [window.model_dump() for window in windows],
            "per_window": 4,
            "selector_version": "diverse-v1",
            "selection_metric": primary,
        }
        play_id = stable_id("execution", {"tool": "find_player_representative_plays", **play_parameters})
        play_started_at, play_started = datetime.now(UTC), perf_counter()
        plays = self._representative_plays(
            comparison,
            team,
            manifests[windows[1].season],
            play_id,
            baseline_frame=baseline,
            baseline_manifest=manifests[windows[0].season],
            primary_source=PLAYER_METRICS[primary][0],
            metric_label=PLAYER_METRICS[primary][1],
            per_window=int(play_parameters["per_window"]),
        )
        if hasattr(self, "_enrich_representative_plays"):
            enriched_plays = {}
            for window in windows:
                window_plays = [play for play in plays if play.season == window.season]
                for play in self._enrich_representative_plays(
                    window_plays,
                    supplemental.get("participation", {}).get(window.season),
                    supplemental.get("ftn_charting", {}).get(window.season),
                ):
                    enriched_plays[play.evidence_id] = play
            plays = [enriched_plays.get(play.evidence_id, play) for play in plays]
        executions.append(
            _execution_record(
                "find_player_representative_plays", play_id, play_parameters, plays, selected_manifests, play_started_at, play_started
            )
        )
        caveats = [
            "Player metrics use only plays carrying the selected nflverse player identifier.",
            "Results are descriptive and do not isolate teammate, scheme, opponent, or game-state effects.",
        ]
        if play_sample_caveats:
            caveats.extend(play_sample_caveats)
        if not metric_evidence:
            caveats.append(
                "No selected play-derived metric was comparable across both windows; the report uses compatible synced "
                "published statistics instead."
            )
        return NFLAnalysisResult(evidence, plays, charts, executions, caveats)
