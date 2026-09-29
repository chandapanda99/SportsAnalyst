"""Evidence-bound comparisons for ESPN soccer match snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import polars as pl

from sports_analyst.chart_specs import metric_row_comparison_spec
from sports_analyst.models import (
    AggregateEvidence, AnalysisOptions, AnalysisPlan, AnalysisRequest, ChartArtifact,
    ComparisonWindowOption, DatasetManifest, MetricDefinition, MetricOption, PlannedToolCall,
    PlayerOption, PlayEvidence, PlayVisualization, TeamOption, ToolDefinition,
    ToolExecutionRecord, stable_id,
)
from sports_analyst.soccer_data import SOCCER_COMPETITIONS, SOCCER_DATASETS, soccer_season_label


@dataclass
class SoccerAnalysisResult:
    aggregate_evidence: list[AggregateEvidence]
    play_evidence: list[PlayEvidence]
    charts: list[ChartArtifact]
    executions: list[ToolExecutionRecord]
    caveats: list[str]


# label, source dataset, subject, domain, unit, explanation
METRICS = {
    "points_per_match": ("Points per match", "play_by_play", "team", "results", "points", "Three for a win and one for a draw, divided by completed matches."),
    "win_rate": ("Win rate", "play_by_play", "team", "results", "rate", "Share of completed matches won."),
    "draw_rate": ("Draw rate", "play_by_play", "team", "results", "rate", "Share of completed matches drawn."),
    "loss_rate": ("Loss rate", "play_by_play", "team", "results", "rate", "Share of completed matches lost."),
    "goals_for_per_match": ("Goals for per match", "play_by_play", "team", "results", "goals", "Goals scored per completed match."),
    "goals_against_per_match": ("Goals against per match", "play_by_play", "team", "defense", "goals", "Goals conceded per completed match."),
    "shots_per_match": ("Shots per match", "team_stats", "team", "attack", "shots", "Recorded team shots divided by matches with shot statistics."),
    "shots_on_target_per_match": ("Shots on target per match", "team_stats", "team", "attack", "shots", "Recorded shots on target divided by matches with that statistic."),
    "possession_pct": ("Possession", "team_stats", "team", "control", "percentage", "Mean recorded match possession percentage."),
    "appearances": ("Appearances", "lineups", "player", "usage", "matches", "Matches with a recorded lineup entry for this player."),
    "starts": ("Starts", "lineups", "player", "usage", "matches", "Recorded starting lineup selections."),
    "goals": ("Goals", "key_events", "player", "scoring", "goals", "Scoring events attributed to this player in ESPN key events."),
    "assists": ("Assists", "lineups", "player", "scoring", "assists", "Assists recorded in the selected player's ESPN game log."),
    "cards": ("Cards", "key_events", "player", "discipline", "cards", "Yellow and red card events attributed to this player."),
}
DEFAULTS = {
    "results": ["points_per_match", "win_rate", "goals_for_per_match", "goals_against_per_match"],
    "attack": ["goals_for_per_match", "shots_per_match", "shots_on_target_per_match"],
    "defense": ["goals_against_per_match"],
    "control": ["possession_pct"],
    "usage": ["appearances", "starts"],
    "scoring": ["goals", "appearances"],
    "discipline": ["cards", "appearances"],
}


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace("%", "").replace(",", "")) if value is not None else None
    except ValueError:
        return None


def _match_window(frame: pl.DataFrame, start: str | None, end: str | None) -> pl.DataFrame:
    if frame.is_empty() or "date" not in frame.columns:
        return frame
    dates = pl.col("date").cast(pl.String).str.slice(0, 10)
    if start:
        frame = frame.filter(dates >= start)
    if end:
        frame = frame.filter(dates <= end)
    return frame


class SoccerPlugin:
    sport_id = "soccer"
    display_name = "Soccer"

    def tools(self) -> list[ToolDefinition]:
        return [ToolDefinition(name=name, description=description) for name, description in (
            ("compare_soccer_windows", "Compare team or player metrics across verified match windows."),
            ("find_representative_matches", "Show recorded matches and events supporting the comparison."),
            ("explain_metric", "Explain a soccer metric and its source limitations."),
        )]

    def analysis_options(self, manifests: list[DatasetManifest], context: Any = None) -> AnalysisOptions:
        context = context if isinstance(context, dict) else {}
        competition = context.get("competition") or "eng.1"
        if competition not in SOCCER_COMPETITIONS:
            raise ValueError(f"Unsupported soccer competition: {competition}")
        selected = [item for item in manifests if item.competition == competition]
        schedules = context.get("schedules", {})
        available = sorted({item.season for item in selected if item.dataset == "play_by_play"
                            and item.season in schedules and not schedules[item.season].is_empty()
                            and "status" in schedules[item.season].columns
                            and schedules[item.season].get_column("status").cast(pl.String).str.to_lowercase()
                            .is_in(["status_final", "status_full_time", "final"]).any()})
        team_names: dict[str, str] = {}
        for frame in schedules.values():
            for side in ("home", "away"):
                id_column, name_column = f"{side}_team_id", f"{side}_team"
                if {id_column, name_column} <= set(frame.columns):
                    for item in frame.select(id_column, name_column).drop_nulls().unique().iter_rows():
                        team_names[str(item[0])] = str(item[1])
        now = datetime.now(UTC)
        latest = now.year if SOCCER_COMPETITIONS[competition][1] or now.month < 7 else now.year + 1
        years = list(range(2016, latest + 1))
        return AnalysisOptions(
            data_setup={"label": f"{SOCCER_COMPETITIONS[competition][0]} match data",
                        "description": "Download completed fixtures and available match detail before investigating.",
                        "required_datasets": ["play_by_play"],
                        "recommended_datasets": ["team_stats", "lineups", "key_events"],
                        "descriptions": {"play_by_play": "Fixture scores and dates.", "team_stats": "Per-match team figures.",
                                         "lineups": "Player appearances and starts.", "key_events": "Goals, cards, and match timeline."}},
            sport="soccer", teams=[TeamOption(value=key, label=value) for key, value in sorted(team_names.items(), key=lambda pair: pair[1])],
            available_seasons=available, syncable_seasons=list(reversed(years)),
            metrics=[MetricOption(value=name, label=info[0], category=info[3].title(), description=info[5],
                                  analysis_domain=info[3], available_seasons=sorted({m.season for m in selected if m.dataset == info[1] and m.season in available}),
                                  subject_types=[info[2]]) for name, info in METRICS.items()],
            default_metrics=DEFAULTS["results"],
            analysis_domains=[{"value": key, "label": key.title(), "description": f"Compare soccer {key} metrics.",
                               "subject_type": "player" if key in {"usage", "scoring", "discipline"} else "team"}
                              for key in DEFAULTS],
            default_metrics_by_domain=DEFAULTS,
            split_dimensions=[],
            comparison_windows=[
                ComparisonWindowOption(value="full_seasons", label="Full seasons", description="Compare the first and last seasons, with intermediate seasons in the trend."),
                ComparisonWindowOption(value="date_ranges", label="Date ranges", description="Compare matches in two selected date ranges."),
            ],
            week_values=[], syncable_datasets=list(SOCCER_DATASETS),
            dataset_min_seasons={dataset: 2016 for dataset in SOCCER_DATASETS},
            dataset_available_seasons={dataset: years for dataset in SOCCER_DATASETS},
            subject_types=[{"value": "team", "label": "Team"}, {"value": "player", "label": "Player"}],
        )

    def resolve_players(self, query: str, sources: list[tuple[int, pl.DataFrame]]) -> list[PlayerOption]:
        found: dict[str, dict] = {}
        needle = query.casefold().strip()
        for season, frame in sources:
            if not {"athlete_id", "athlete"} <= set(frame.columns):
                continue
            columns = [name for name in ("athlete_id", "athlete", "team_id", "position") if name in frame.columns]
            for row in frame.select(columns).drop_nulls(["athlete_id", "athlete"]).unique().iter_rows(named=True):
                player_id = str(row["athlete_id"])
                name = str(row["athlete"])
                if needle and needle not in name.casefold():
                    continue
                item = found.setdefault(player_id, {"name": name, "teams": set(), "positions": set(), "seasons": set()})
                item["seasons"].add(season)
                if row.get("team_id"):
                    item["teams"].add(str(row["team_id"]))
                if row.get("position"):
                    item["positions"].add(str(row["position"]))
        return [PlayerOption(player_id=key, name=item["name"], teams=sorted(item["teams"]),
                             positions=sorted(item["positions"]), seasons=sorted(item["seasons"]))
                for key, item in sorted(found.items(), key=lambda pair: pair[1]["name"])]

    def resolve_team(self, team: str) -> str:
        return str(team).strip()

    def explain_metric(self, metric: str) -> MetricDefinition:
        if metric not in METRICS:
            raise ValueError(f"Unsupported soccer metric: {metric}")
        label, source, _subject, domain, _unit, description = METRICS[metric]
        return MetricDefinition(value=metric, label=label, category=domain.title(), description=description,
                                formula=description, qualifying_plays=f"Completed matches with {source} coverage.",
                                interpretation="Compare both windows and their sample sizes.",
                                limitations=["ESPN match sections may be absent or incomplete for some competitions and seasons."])

    def default_plan(self, request: AnalysisRequest) -> AnalysisPlan:
        return AnalysisPlan(plan_id=stable_id("plan", request.model_dump()), question=request.question, scope=request.scope,
                            calls=[PlannedToolCall(tool="compare_soccer_windows", arguments={}, purpose="Compare measured soccer metrics."),
                                   PlannedToolCall(tool="find_representative_matches", arguments={}, purpose="Attach match context.")])

    def required_play_by_play_columns(self, request: AnalysisRequest) -> set[str]:
        return {"event_id", "date", "home_team_id", "away_team_id", "home_team", "away_team", "home_score", "away_score", "status", "season", "competition"}

    def required_supplemental_datasets(self, request: AnalysisRequest) -> set[str]:
        return {"team_stats", "lineups", "key_events"}

    @staticmethod
    def _team_rows(schedule: pl.DataFrame, team_id: str) -> list[dict]:
        rows = []
        for item in schedule.iter_rows(named=True):
            if str(item.get("status", "")).lower() not in {"status_final", "status_full_time", "final"}:
                continue
            home = str(item.get("home_team_id")) == team_id
            away = str(item.get("away_team_id")) == team_id
            if not (home or away):
                continue
            scored = _number(item.get("home_score" if home else "away_score"))
            conceded = _number(item.get("away_score" if home else "home_score"))
            if scored is None or conceded is None:
                continue
            rows.append({"game_id": str(item["event_id"]), "date": str(item["date"])[:10], "goals_for": scored,
                         "goals_against": conceded, "points": 3 if scored > conceded else 1 if scored == conceded else 0,
                         "win": float(scored > conceded), "draw": float(scored == conceded), "loss": float(scored < conceded),
                         "opponent": item.get("away_team" if home else "home_team"), "home": home})
        return rows

    @staticmethod
    def _value(metric: str, rows: list[dict], stats: pl.DataFrame, lineups: pl.DataFrame, events: pl.DataFrame,
               subject_id: str, game_logs: pl.DataFrame | None = None) -> tuple[float | None, int]:
        games = {row["game_id"] for row in rows}
        if metric == "assists":
            logs = game_logs if game_logs is not None else pl.DataFrame()
            if not {"game_id", "assists"} <= set(logs.columns):
                return None, 0
            by_game: dict[str, float] = {}
            for item in logs.iter_rows(named=True):
                game_id = str(item["game_id"])
                number = _number(item.get("assists"))
                if game_id in games and number is not None:
                    by_game[game_id] = max(number, by_game.get(game_id, 0))
            return (sum(by_game.values()), len(by_game)) if by_game else (None, 0)
        if metric in {"points_per_match", "win_rate", "draw_rate", "loss_rate", "goals_for_per_match", "goals_against_per_match"}:
            field = {"points_per_match": "points", "win_rate": "win", "draw_rate": "draw", "loss_rate": "loss",
                     "goals_for_per_match": "goals_for", "goals_against_per_match": "goals_against"}[metric]
            return (sum(row[field] for row in rows) / len(rows), len(rows)) if rows else (None, 0)
        if metric in {"shots_per_match", "shots_on_target_per_match", "possession_pct"}:
            aliases = {"shots_per_match": ("total_shots", "shots"),
                       "shots_on_target_per_match": ("shots_on_target", "shots_on_goal"),
                       "possession_pct": ("possession_pct", "possession", "possession_percentage")}[metric]
            col = next((name for name in aliases if name in stats.columns), None)
            if col is None or not {"game_id", "team_id"} <= set(stats.columns):
                return None, 0
            values = [_number(item.get(col)) for item in stats.filter(pl.col("team_id").cast(pl.String) == subject_id).iter_rows(named=True)
                      if str(item["game_id"]) in games]
            valid = [value for value in values if value is not None]
            if metric == "possession_pct":
                valid = [value / 100 if value > 1 else value for value in valid]
            return (sum(valid) / len(valid), len(valid)) if valid else (None, 0)
        source = lineups if metric in {"appearances", "starts"} else events
        if source.is_empty() or not {"game_id", "athlete_id"} <= set(source.columns):
            return None, 0
        covered_games = {str(value) for value in source.get_column("game_id").to_list()} & games
        matches = [item for item in source.filter(pl.col("athlete_id").cast(pl.String) == subject_id).iter_rows(named=True)
                   if str(item["game_id"]) in covered_games]
        if metric == "appearances":
            return float(len({str(item["game_id"]) for item in matches})), len(covered_games)
        if metric == "starts":
            return float(sum(item.get("starter") is True for item in matches)), len(covered_games)
        if metric == "goals":
            return float(sum(item.get("scoring_play") is True
                             and "own goal" not in (str(item.get("text", "")) + str(item.get("type", ""))).lower()
                             for item in matches)), len(covered_games)
        if metric == "cards":
            return float(sum("card" in str(item.get("type", "")).lower() for item in matches)), len(covered_games)
        return None, 0

    def analyze(self, request: AnalysisRequest, datasets: dict[int, pl.DataFrame], manifests: dict[int, DatasetManifest],
                supplemental: dict[str, dict[int, pl.DataFrame]] | None = None,
                supplemental_manifests: dict[str, dict[int, DatasetManifest]] | None = None) -> SoccerAnalysisResult:
        if request.scope.competition not in SOCCER_COMPETITIONS:
            raise ValueError("Select a supported soccer competition")
        subject = request.subject
        if subject is None:
            raise ValueError("Select a team or player")
        supplemental = supplemental or {}
        supplemental_manifests = supplemental_manifests or {}
        selected = request.metrics or DEFAULTS.get(request.analysis_domain, DEFAULTS["results"])
        invalid = [name for name in selected if name not in METRICS or METRICS[name][2] != subject.type]
        if invalid:
            raise ValueError(f"Unsupported metrics for this soccer subject: {invalid}")
        started = perf_counter()
        started_at = datetime.now(UTC)
        used = list(manifests.values()) + [m for seasons in supplemental_manifests.values() for m in seasons.values()]
        ids = [item.manifest_id for item in used]
        frames = {}
        for label, window in (("baseline", request.scope.baseline), ("comparison", request.scope.comparison)):
            schedule = _match_window(datasets[window.season], window.start_date, window.end_date)
            if subject.type == "team":
                rows = self._team_rows(schedule, str(subject.id))
            else:
                lineup = supplemental.get("lineups", {}).get(window.season, pl.DataFrame())
                if not {"athlete_id", "team_id", "game_id"} <= set(lineup.columns):
                    rows = []
                else:
                    player_entries = lineup.filter(pl.col("athlete_id").cast(pl.String) == str(subject.id))
                    player_games = set(player_entries.get_column("game_id").cast(pl.String).to_list())
                    teams = set(player_entries.get_column("team_id").cast(pl.String).to_list())
                    rows = [row for team in teams for row in self._team_rows(schedule, team)
                            if row["game_id"] in player_games]
                    rows = list({row["game_id"]: row for row in rows}.values())
            if not rows:
                raise ValueError(f"No completed matches for the selected subject in the {label} window")
            frames[label] = (window, rows)
        parameters = {"sport": "soccer", "competition": request.scope.competition, "subject": subject.model_dump(),
                      "baseline": request.scope.baseline.model_dump(), "comparison": request.scope.comparison.model_dump(), "metrics": selected}
        execution_id = stable_id("execution", parameters)
        aggregates = []
        gaps = []
        for name in selected:
            values = []
            for label in ("baseline", "comparison"):
                window, rows = frames[label]
                season = window.season
                stat = supplemental.get("team_stats", {}).get(season, pl.DataFrame())
                lineup = supplemental.get("lineups", {}).get(season, pl.DataFrame())
                events = supplemental.get("key_events", {}).get(season, pl.DataFrame())
                game_logs = supplemental.get("player_game_logs", {}).get(season, pl.DataFrame())
                values.append(self._value(name, rows, stat, lineup, events, str(subject.id), game_logs))
            (before, before_n), (after, after_n) = values
            if before is None or after is None or not before_n or not after_n:
                gaps.append(name)
                continue
            payload = {**parameters, "metric": name, "before": before, "after": after}
            aggregates.append(AggregateEvidence(
                evidence_id=stable_id("evidence", payload), metric=name, label=METRICS[name][0],
                value=round(after - before, 4), baseline_value=round(before, 4), comparison_value=round(after, 4),
                unit=METRICS[name][4], sample_size=after_n, row_set_sha256=_sha(payload), dataset_manifest_ids=ids,
                tool_execution_id=execution_id,
                caveats=[f"Baseline: {before_n} qualifying matches; comparison: {after_n} qualifying matches."],
            ))
        if not aggregates:
            raise ValueError("No comparable soccer metrics have coverage in both selected windows")
        execution = ToolExecutionRecord(execution_id=execution_id, tool="compare_soccer_windows", parameters=parameters,
                                        started_at=started_at, duration_ms=round((perf_counter() - started) * 1000),
                                        result_sha256=_sha([a.model_dump() for a in aggregates]), dataset_manifest_ids=ids)
        labels = (soccer_season_label(request.scope.competition, request.scope.baseline.season),
                  soccer_season_label(request.scope.competition, request.scope.comparison.season))
        if labels[0] == labels[1]:
            labels = ("Reference", "Comparison")
        chart = ChartArtifact(chart_id=stable_id("chart", parameters), title="Soccer metric comparison",
                              specification=metric_row_comparison_spec(
                                  [{"metric": a.label, "window": label, "value": value, "unit": a.unit}
                                   for a in aggregates for label, value in zip(labels, (a.baseline_value, a.comparison_value), strict=True)],
                                  series_field="window", series_order=labels),
                              evidence_ids=[a.evidence_id for a in aggregates])
        plays = []
        for label in ("baseline", "comparison"):
            window, rows = frames[label]
            schedule = datasets[window.season]
            for row in rows[:3]:
                match = schedule.filter(pl.col("event_id").cast(pl.String) == row["game_id"]).to_dicts()[0]
                event_frame = supplemental.get("key_events", {}).get(window.season, pl.DataFrame())
                timeline = []
                has_event_section = False
                if {"game_id", "text"} <= set(event_frame.columns):
                    match_events = event_frame.filter(pl.col("game_id").cast(pl.String) == row["game_id"])
                    has_event_section = not match_events.is_empty()
                    timeline = [{"clock": str(event.get("clock") or ""), "text": str(event.get("text") or ""),
                                 "type": str(event.get("type") or "")}
                                for event in match_events.to_dicts()[:20]
                                if event.get("text")]
                description = f"{match.get('home_team')} {match.get('home_score')}–{match.get('away_score')} {match.get('away_team')} · {row['date']}"
                plays.append(PlayEvidence(
                    sport="soccer", evidence_id=stable_id("evidence", {"game": row["game_id"], "window": label}),
                    season=window.season, game_id=row["game_id"], play_id=0, team=str(subject.id), description=description,
                    metric_value=row["goals_for"], supporting=True, window=label, evidence_role="typical",
                    dataset_manifest_id=manifests[window.season].manifest_id, tool_execution_id=execution_id,
                    visualization=PlayVisualization(sport="soccer", game_date=row["date"],
                        home_team_name=str(match.get("home_team") or ""), away_team_name=str(match.get("away_team") or ""),
                        home_score=int(_number(match.get("home_score")) or 0), away_score=int(_number(match.get("away_score")) or 0),
                        source_packages=["play_by_play", *(["key_events"] if has_event_section else [])],
                        soccer_timeline=timeline),
                ))
        caveats = ["ESPN soccer coverage varies by match and competition; missing match sections are excluded from metric denominators."]
        for source, season_manifests in supplemental_manifests.items():
            if source not in {"team_stats", "lineups", "key_events"}:
                continue
            for season, manifest in season_manifests.items():
                expected = manifest.coverage.get("expected_matches", 0)
                recorded = manifest.coverage.get("recorded_matches", 0)
                if expected and recorded < expected:
                    caveats.append(f"{source.replace('_', ' ').title()} {soccer_season_label(request.scope.competition, season)}: "
                                   f"{recorded} of {expected} completed matches have a stored section.")
        if gaps:
            caveats.append(f"Unavailable in both windows: {', '.join(gaps)}")
        return SoccerAnalysisResult(aggregates, plays, [chart], [execution], caveats)
