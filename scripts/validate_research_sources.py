"""Opt-in live source acceptance. Never constructs a model or modifies the main library."""

from __future__ import annotations
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import polars as pl
from sports_analyst.analysis.research.audit import audit_snapshot
from sports_analyst.analysis.research.context import acquire_context
from sports_analyst.analysis.research.contracts import AcquisitionPlan
from sports_analyst.analysis.research.state import ACTIVE_BUDGET
from sports_analyst.analysis.scoped_data import ScopedData
from sports_analyst.config import Settings
from sports_analyst.datasets.cfb import SportsDataverseCFBConnector
from sports_analyst.datasets.nba import SportsDataverseNBAConnector
from sports_analyst.datasets.nfl import NFLVerseConnector
from sports_analyst.datasets.soccer.connector import SportsDataverseSoccerConnector
from sports_analyst.models import AnalysisRequest
from sports_analyst.storage.local import LocalStore
from sports_analyst.storage.persistence import LocalPersistenceBackend

CASES = {
    "nfl": ("CHI", "play_by_play", "ftn_charting", "play", ["play_by_play", "ftn_charting"]),
    "nba": ("BOS", "player_boxscores", "team_boxscores", "player_game", ["player_boxscores", "team_boxscores"]),
    "cfb": ("66", "player_stats", "team_stats", "player_game", ["player_stats", "team_stats"]),
    "soccer": ("359", "team_stats", "lineups", "team_game", ["team_stats", "lineups"]),
}


def run(root, sports):
    configured = Settings()
    settings = configured.model_copy(
        update={
            "data_dir": root,
            "persistence_backend": "local",
            "job_backend": "local",
            "job_dispatch_backend": "none",
            "langsmith_tracing": False,
            "calculation_interpreter_enabled": False,
            "research_transfer_bytes": min(configured.research_transfer_bytes, 512 * 1024**2),
        }
    )
    store = LocalStore(settings, LocalPersistenceBackend())
    app = SimpleNamespace(
        settings=settings,
        store=store,
        connectors={
            "nfl": NFLVerseConnector(settings),
            "nba": SportsDataverseNBAConnector(settings),
            "cfb": SportsDataverseCFBConnector(settings),
            "soccer": SportsDataverseSoccerConnector(settings),
        },
    )
    report_path = root / "live-source-report.json"
    report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.exists()
        else {
            "started_at": datetime.now(UTC).isoformat(),
            "models_called": False,
            "concurrency": settings.dataset_sync_concurrency,
            "cases": {},
        }
    )
    for sport in sports:
        team, base_name, right_name, grain, packages = CASES[sport]
        item = report["cases"].setdefault(sport, {"season": 2025, "subject": team})
        request = AnalysisRequest(
            sport=sport,
            subject={"type": "team", "id": team},
            question="Verify recorded source coverage and observation-preserving joins without any model calls.",
            scope={
                "team": team,
                "competition": "eng.1" if sport == "soccer" else None,
                "season_type": "ALL",
                "comparison_design": "full_seasons",
                "baseline": {"season": 2024},
                "comparison": {"season": 2025},
            },
        )
        access = ScopedData(app, request, f"team:{team}" if sport in {"cfb", "soccer"} else None, f"live-source-{sport}")
        access.progress = lambda message: print(message, flush=True)
        try:
            for dataset in packages:
                if not any(m.dataset == dataset and m.season == 2025 and m.availability == "available" for m in access.manifests.values()):
                    access.acquisition.queue(
                        {"objective": "Live source acceptance", "dataset": dataset, "season": 2025, "round": access.acquisition.round}
                    )
            item["acquisition"] = access.acquisition.run()
            inputs = list(access.manifests.values())
            item["snapshots"] = [audit_snapshot(m, store.materialize_manifest(m).local_path) for m in inputs]
            base = next(m for m in inputs if m.dataset == base_name and m.season == 2025)
            right = next(m for m in inputs if m.dataset == right_name and m.season == 2025)
            relation = next(
                r
                for r in access.executor.graph()
                if r.left_dataset_id == base.manifest_id and r.right_dataset_id == right.manifest_id and r.context_role == "own"
            )
            field = next(
                (
                    f
                    for f in {"nfl": ["epa"], "nba": ["points"], "cfb": ["passing_yards"], "soccer": ["shots", "total_shots"]}[sport]
                    if f in base.columns
                ),
                None,
            )
            if field is None:
                raise ValueError(f"Requested recorded measurement absent. Available columns: {base.columns}")
            step = {"relationship_id": relation.relationship_id, "alias": "ctx", "fields": []}
            if sport == "soccer":
                step.update(mode="preaggregate", measures=[{"op": "count", "name": "roster_entries"}])
            elif sport == "nfl":
                step["fields"] = [next(f for f in ("n_defense_box", "n_pass_rushers", "is_blitz") if f in right.columns)]
            else:
                step["fields"] = [next(f for f in ("total_yards", "points", "team_id") if f in right.columns)]
            plan = {
                "objective": "Live source acceptance",
                "dataset_id": base.manifest_id,
                "grain": grain,
                "window": "comparison",
                "steps": [step],
                "missing": "matched",
                "measures": [{"op": "mean" if sport == "nfl" else "sum", "field": field, "name": "recorded_measure"}],
            }
            checked = access.executor.validate(plan)
            item["join"] = access.executor.execute(checked["plan_id"])
            if not item["join"]["qualifying_rows"] or item["join"]["rows"][0]["recorded_measure"] is None:
                raise ValueError("No usable joined measurements in the selected scope")
            if sport == "nba":
                item["native_acquisition"] = []
                for dataset in ("stats_player_boxscores", "stats_team_boxscores"):
                    if not any(m.dataset == dataset and m.season == 2025 for m in access.manifests.values()):
                        access.acquisition.queue(
                            {
                                "objective": "Native NBA source compatibility",
                                "dataset": dataset,
                                "season": 2025,
                                "round": access.acquisition.round,
                            }
                        )
                item["native_acquisition"] = access.acquisition.run()
                native_inputs = [m for m in access.manifests.values() if m.dataset.startswith("stats_")]
                item["native_snapshots"] = [audit_snapshot(m, store.materialize_manifest(m).local_path) for m in native_inputs]
                native_base = next(m for m in native_inputs if m.dataset == "stats_player_boxscores")
                native_right = next(m for m in native_inputs if m.dataset == "stats_team_boxscores")
                native_relation = next(
                    r
                    for r in access.executor.graph()
                    if r.left_dataset_id == native_base.manifest_id
                    and r.right_dataset_id == native_right.manifest_id
                    and r.context_role == "own"
                )
                native_plan = {
                    **plan,
                    "objective": "Native NBA source compatibility",
                    "dataset_id": native_base.manifest_id,
                    "steps": [{"relationship_id": native_relation.relationship_id, "alias": "ctx", "fields": []}],
                    "measures": [
                        {"op": "sum", "field": next(f for f in ("points", "pts") if f in native_base.columns), "name": "recorded_measure"}
                    ],
                }
                item["native_join"] = access.executor.execute(access.executor.validate(native_plan)["plan_id"])
            if sport in {"cfb", "soccer"}:
                schedule = next(m for m in inputs if m.dataset == ("schedules" if sport == "cfb" else "play_by_play"))
                fixture = pl.read_parquet(store.materialize_manifest(schedule).local_path).row(0, named=True)
                opponent = str(fixture["away_team_id"] if str(fixture["home_team_id"]) == team else fixture["home_team_id"])
                token = ACTIVE_BUDGET.set(access.acquisition.state)
                try:
                    context_manifest = acquire_context(
                        access,
                        AcquisitionPlan(
                            objective="Selected opponent game context", dataset="team_stats", season=2025, purpose="context", team_id=opponent
                        ),
                        opponent,
                    )[0]
                    store.save_manifest(context_manifest)
                    access.manifests[context_manifest.manifest_id] = context_manifest
                finally:
                    ACTIVE_BUDGET.reset(token)
                relation = next(
                    r
                    for r in access.executor.graph()
                    if r.left_dataset_id == base.manifest_id
                    and r.right_dataset_id == context_manifest.manifest_id
                    and r.context_role == "opponent"
                )
                opponent_plan = {
                    **plan,
                    "objective": "Selected opponent game context",
                    "steps": [{"relationship_id": relation.relationship_id, "alias": "opponent", "fields": []}],
                }
                item["opponent_join"] = access.executor.execute(access.executor.validate(opponent_plan)["plan_id"])
            if sport == "soccer":
                # Small, explicitly separate probe. Never imply two fixtures prove season xG coverage.
                schedule = next(m for m in inputs if m.dataset == "play_by_play")
                fixtures = (
                    app.connectors[sport]
                    .load(schedule)
                    .filter(pl.col("status").str.to_lowercase().is_in(["status_final", "status_full_time", "final"]))
                    .head(2)
                )
                token = ACTIVE_BUDGET.set(access.acquisition.state)
                try:
                    sample = app.connectors[sport].expected_goals.team_matches("eng.1", 2025, fixtures)
                    sample.write_parquet(root / "soccer-xg-probe.parquet")
                    item["xg_probe"] = {
                        "fixture_sample": fixtures["event_id"].to_list(),
                        "team_rows": sample.to_dicts(),
                        "limitation": "Two-fixture source probe only; not a full-season xG coverage claim",
                    }
                finally:
                    ACTIVE_BUDGET.reset(token)
            item["status"] = "passed"
            item.pop("error_type", None)
            item.pop("message", None)
        except Exception as error:
            item.update(status="failed", error_type=type(error).__name__, message=str(error)[:1800])
        item["budget"] = access.acquisition.state.read("budget")
        report["finished_at"] = datetime.now(UTC).isoformat()
        report_path.write_text(json.dumps(report, indent=2, default=str, allow_nan=False), encoding="utf-8")
        print(
            json.dumps({"sport": sport, "status": item["status"], "message": item.get("message"), "report": str(report_path)}, default=str),
            flush=True,
        )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live-sources", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sports", nargs="+", choices=list(CASES), default=list(CASES))
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    result = run(arguments.output.resolve(), arguments.sports)
    raise SystemExit(0 if all(result["cases"][sport]["status"] == "passed" for sport in arguments.sports) else 1)
