"""Metric-scoped, attributed CFB play evidence; box-score totals remain authoritative."""
from __future__ import annotations

import json

from sports_analyst.analysis.evidence import EvidenceCandidate, select_diverse_evidence
from sports_analyst.datasets.cfb_rendering import with_render_context, is_nullified
from sports_analyst.models import PlayEvidence, PlayVisualization, stable_id


def select_plays(request, schedules, supplemental, manifests, aggregates, execution_id, metrics, advanced):
    primary = next((item for item in aggregates if item.metric in request.metrics), aggregates[0])
    metric = primary.metric
    candidates = []
    for window, schedule in schedules.items():
        year = request.scope.baseline.season if window == "baseline" else request.scope.comparison.season
        frame = supplemental.get("recorded_plays", {}).get(year)
        manifest = manifests.get("recorded_plays", {}).get(year)
        if frame is None or manifest is None or frame.is_empty():
            continue
        modeled = supplemental.get("enriched_plays", {}).get(year)
        modeled_rows = {(row["game_id"], str(row["play_id"])): row for row in modeled.to_dicts()} if modeled is not None else {}
        games = {row["game_id"]: row for row in schedule.to_dicts()}
        for recorded in frame.to_dicts():
            game = games.get(recorded["game_id"])
            if not game or not str(recorded.get("play_id", "")).isdigit() or recorded.get("no_play"):
                continue
            row = {**recorded}
            model = modeled_rows.get((row["game_id"], str(row["play_id"])), {})
            row = with_render_context(row, model)
            if is_nullified(row):
                continue
            row.update({field: model[field] for field in ("epa", "wpa", "cpoe", "cp", "xpass", "pass_oe")
                        if model.get(field) is not None})
            if metric in advanced and model:
                row.update({field: model[field] for field in ("scrimmage", "pass", "rush") if model.get(field) is not None})
            if model:
                model_manifest = manifests.get("enriched_plays", {}).get(year)
                row["model_provenance"] = {
                    "provider_version": model.get("provider_version"), "model_family": model.get("model_family"),
                    "manifest_id": model_manifest.manifest_id if model_manifest else None,
                    "source_play_count": model.get("source_play_count"), "processed_play_count": model.get("processed_play_count")}
            subject = request.subject
            roles = {}
            for actor in row.get("participants") or []:
                roles.setdefault(actor.get("role"), set()).add(actor.get("athlete_id"))
            if subject.type == "player":
                role = {"quarterback": "passer", "rushing": "rusher", "receiving": "receiver"}.get(request.analysis_domain)
                if not role or roles.get(role) != {subject.id}:
                    continue
            elif metric == "points_allowed_per_game":
                if row.get("team_id") == subject.id:
                    continue
            elif row.get("team_id") != subject.id:
                continue
            value = play_value(row, metric, advanced)
            if value is None:
                continue
            contextual = metric in {"win_rate", "points_per_game", "points_allowed_per_game",
                                    "passing_attempts", "rushing_attempts", "receptions"}
            opponent = game["away_team_id"] if game["home_team_id"] == row.get("team_id") else game["home_team_id"]
            candidates.append(EvidenceCandidate(
                key=f"{window}:{year}:{row['game_id']}:{row['play_id']}", window=window, game_id=row["game_id"],
                event_type=row.get("play_type") or "play", payload=(row, manifest, game, contextual),
                outcome_value=value, relevance=min(abs(value) / 20, 1),
                context_quality=sum(row.get(key) is not None for key in ("down", "distance", "clock", "team_id")) / 4,
                opponent=opponent, period=str(row.get("quarter") or "")))
    delta = primary.comparison_value - primary.baseline_value
    selected = select_diverse_evidence(candidates, metric_label=primary.label, per_window=4, direction=-1 if delta < 0 else 1)
    evidence = []
    for item in selected:
        row, manifest, game, contextual = item.candidate.payload
        stat_frame = supplemental.get("player_stats" if request.subject.type == "player" else "team_stats", {}).get(manifest.season)
        stat_rows = [] if stat_frame is None else [entry for entry in stat_frame.to_dicts()
            if entry.get("game_id") == row["game_id"]
            and entry.get("athlete_id" if request.subject.type == "player" else "team_id") == request.subject.id]
        role = "metric_example" if contextual or delta == 0 else item.role
        reason = ("Recorded event context, not proof of a game-level result, total-volume change or scoring-rate change."
                  if contextual else item.reason + " Illustrates the aggregate result; does not replace its full-sample denominator.")
        evidence.append(PlayEvidence(
            sport="cfb", evidence_id=stable_id("evidence", {"key": item.candidate.key, "metric": metric}),
            season=manifest.season, game_id=row["game_id"], play_id=int(row["play_id"]), team=request.subject.id,
            description=row.get("text") or row.get("play_type") or "Recorded play", epa=row.get("epa"),
            metric_value=item.candidate.outcome_value, supporting=role != "counterexample", window=item.candidate.window,
            evidence_role=role, selection_metric=primary.label, selection_reason=reason,
            candidate_pool_size=item.candidate_pool_size, selector_version=item.selector_version,
            dataset_manifest_id=manifest.manifest_id, tool_execution_id=execution_id,
            visualization=PlayVisualization(
                sport="cfb", quarter=row.get("quarter"), clock=row.get("clock"), down=row.get("down"),
                yards_to_go=row.get("distance"), yardline_100=row.get("yards_to_goal"), game_date=game.get("date"),
                home_team_name=game.get("home_team_name"), away_team_name=game.get("away_team_name"),
                source_packages=["recorded_plays"] + (["enriched_plays"] if row.get("epa") is not None else []),
                air_yards=row.get("air_yards"), yards_after_catch=row.get("yards_after_catch"),
                pass_location=row.get("pass_direction"), run_location=row.get("rush_direction"),
                pass_length=row.get("pass_depth"), formation=row.get("formation"), yards_gained=row.get("yards_gained"),
                cfb_statistics={"selected_play": row, "rows": stat_rows,
                                "source_provenance": json.loads(row.get("source_provenance_json") or "{}"),
                                "provider_context": json.loads(row.get("provider_context_json") or "{}"),
                                "context_provenance": "Provider-parsed text and modeled game state; no tracking, inferred coordinates or assignments used as evidence",
                                "teams": json.loads(row.get("teams_json") or "[]"),
                                "selection_signal": "Metric-filtered recorded play outcome; conversions use recorded yardage and distance, "
                                                    "not a substituted box-score rate",
                                "evidence_scope": "Metric-filtered recorded plays; no causal or full-lineup inference"})))
    return evidence


def play_value(row, metric, advanced):
    if metric in advanced:
        field, reducer, kind, _ = advanced[metric]
        if not row.get("scrimmage") or (kind and not row.get(kind)):
            return None
        value = row.get(field)
        return float(value > 0) if value is not None and reducer == "success" else value
    if metric in {"win_rate", "points_per_game", "points_allowed_per_game"}:
        return float(bool(row.get("scoring_play"))) if row.get("scoring_play") else None
    if not row.get("scrimmage"):
        return None
    if metric in {"third_down_rate", "fourth_down_rate"}:
        if row.get("down") != (3 if metric == "third_down_rate" else 4):
            return None
        if not row.get("touchdown") and (row.get("yards_gained") is None or row.get("distance") is None):
            return None
        return float(bool(row.get("touchdown") or (row.get("yards_gained") is not None and row.get("distance") is not None
                                                  and row["yards_gained"] >= row["distance"])))
    if "passing" in metric or metric in {"completion_rate", "net_yards_per_pass_attempt"}:
        if not row.get("pass"):
            return None
        if "completion" in metric:
            return float(bool(row.get("complete")))
        if "interception" in metric:
            return float(bool(row.get("interception")))
        if "touchdown" in metric:
            return float(bool(row.get("touchdown")))
    if "rush" in metric and not row.get("rush"):
        return None
    if ("receiv" in metric or metric in {"receptions", "yards_per_reception"}) and (not row.get("pass") or not row.get("complete")):
        return None
    if "touchdown" in metric:
        return float(bool(row.get("touchdown")))
    if metric in {"passing_attempts", "rushing_attempts", "receptions"}:
        return 1.0
    if metric == "turnovers_per_game":
        return float(row["turnover"]) if row.get("turnover") is not None else None
    return row.get("yards_gained")
