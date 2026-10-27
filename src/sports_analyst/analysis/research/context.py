"""Acquire opponent context from selected games, never an opponent's full season."""
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import polars as pl

from sports_analyst.analysis.research.contracts import VERSION, contract
from sports_analyst.application.preparation import current_season, reusable
from sports_analyst.datasets.acquisition import bounded_results
from sports_analyst.datasets.nfl import sha256_file
from sports_analyst.models import stable_id


def selected_games(access, plan, team):
    request, executor = access.request, access.executor
    windows = [name for name in ("baseline", "comparison") if getattr(request.scope, name).season == plan.season]
    if not windows and request.scope.comparison_design == "full_seasons":
        windows = [f"season:{plan.season}"]
    player = request.subject and request.subject.type == "player"
    player_games = set()
    if player:
        for manifest in list(access.manifests.values()):
            c = contract(manifest)
            if manifest.season == plan.season and c.grain == "player_game" and c.game and c.player:
                for window in windows:
                    player_games.update(executor.base(manifest, {c.game}, window).select(c.game).unique().collect()[c.game].cast(pl.String))
    result = {}
    for manifest in list(access.manifests.values()):
        c = contract(manifest)
        if manifest.season != plan.season or c.grain != "game" or not c.game:
            continue
        sides = {"home_team_id", "away_team_id"}
        if not sides <= set(manifest.columns):
            continue
        for window in windows:
            frame = (executor.scan(manifest, manifest.columns) if player else executor.base(manifest, set(manifest.columns), window))
            if player:
                frame = frame.filter(pl.col(c.game).cast(pl.String).is_in(sorted(player_games)))
            frame = frame.filter(pl.any_horizontal(pl.col(k).cast(pl.String) == team for k in sides))
            for row in frame.limit(201).collect().iter_rows(named=True):
                if row.get("completed") is not True and str(row.get("status", "")).lower() not in {"status_final", "status_full_time", "final"}:
                    continue
                game = str(row[c.game])
                if not game.isdigit():
                    raise ValueError("Game context requires a recorded ESPN game identifier")
                result[game] = (manifest, row)
    if not result or len(result) > 200:
        raise ValueError("No bounded, verified selected-game context; prepare primary schedules/player history first")
    return result


def acquire_context(access, plan, team):
    sport, connector = access.request.sport, access.app.connectors[access.request.sport]
    supported = {"schedules", "team_stats", "player_stats", "scoring_events"} if sport == "cfb" else {
        "play_by_play", "team_stats", "lineups", "key_events", "expected_goals"}
    if plan.dataset not in supported:
        raise ValueError("No verified selected-game context adapter for this package; use its primary scoped preparation")
    games = selected_games(access, plan, team)
    installed = access.app.store.manifests(sport=sport, competition=access.request.scope.competition,
                                          provider_id="research_context", processing_version=None)
    current = current_season(sport, access.request.scope.competition)

    def fetch(item):
        game, (calendar, row) = item
        cached = [m for m in installed if m.dataset == plan.dataset and m.season == plan.season
                  and m.partition_key == f"game:{game}" and m.processing_version == VERSION and reusable(m, current)
                  and (access.app.store.persistence.durable or Path(m.local_path).exists())]
        if cached:
            return max(cached, key=lambda m: m.acquired_at)
        if plan.dataset in {"schedules", "play_by_play"}:
            frame = pl.DataFrame([row], infer_schema_length=None)
        elif sport == "cfb":
            raw = connector.summary(game, plan.season)
            teams, players, events = connector.statistics(raw, game, plan.season)
            frame = pl.DataFrame({"team_stats": teams, "player_stats": players, "scoring_events": events}[plan.dataset], infer_schema_length=None)
        elif plan.dataset == "expected_goals":
            frame = connector.expected_goals._frame([connector.expected_goals._row(access.request.scope.competition,
                plan.season, game, str(row[k])) for k in ("home_team_id", "away_team_id")])
        else:
            raw = connector._summary(access.request.scope.competition, plan.season, game, refresh=plan.season == current)
            frame = connector._parse_summary(raw, plan.dataset)
            frame = frame.with_columns(pl.lit(game).alias("game_id")) if not frame.is_empty() else frame
        if frame.is_empty():
            return None  # Receipt retains this genuinely missing completed-game section.
        frame = frame.with_columns(pl.lit(plan.season).alias("season"))
        branch = access.app.settings.data_dir / "raw" / sport
        if access.request.scope.competition:
            branch /= access.request.scope.competition
        path = branch / "providers" / "research_context" / VERSION / f"{plan.dataset}_{game}_{uuid4().hex}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(path)
        checksum = sha256_file(path)
        return calendar.model_copy(update={"manifest_id": stable_id("dataset", {"provider": "research_context", "version": VERSION,
            "sport": sport, "dataset": plan.dataset, "game": game, "sha256": checksum}),
            "provider_id": "research_context", "processing_version": VERSION, "partition_key": f"game:{game}",
            "dataset": plan.dataset, "sha256": checksum, "row_count": frame.height, "columns": frame.columns,
            "acquired_at": datetime.now(UTC),
            "source_url": ("https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event=" + game
                           if sport == "cfb" else f"https://site.api.espn.com/apis/site/v2/sports/soccer/{access.request.scope.competition}/summary?event={game}"),
            "local_path": str(path.resolve()), "file_size": path.stat().st_size, "modified_ns": path.stat().st_mtime_ns,
            "availability": "available", "availability_message": None, "input_manifest_ids": [calendar.manifest_id],
            "source_inputs": [calendar.model_dump(mode="json")],
            "coverage": {"expected_matches": 1, "completed_matches": 1, "recorded_matches": 1}})

    results, failures = [], 0
    for _, future in bounded_results(fetch, list(games.items()), access.app.settings.dataset_sync_concurrency):
        try:
            manifest = future.result()
        except Exception as error:
            from sports_analyst.analysis.research.state import ResearchLimit
            from sports_analyst.datasets.optional import OptionalDependencyError

            if isinstance(error, (ResearchLimit, OptionalDependencyError)):
                raise
            failures += 1
            continue
        if manifest is not None:
            access.app.store.save_manifest(manifest)
            results.append(manifest)
    if not results:
        raise ValueError("No selected completed-game records were available for this context package")
    # Consolidate authorized game partitions into one joinable snapshot. The raw
    # per-game context remains independently reusable across investigations.
    frame = pl.concat([pl.scan_parquet(access.app.store.materialize_manifest(m).local_path) for m in results],
                      how="diagonal_relaxed").collect(engine="streaming")
    if frame.estimated_size() > access.app.settings.research_working_bytes:
        raise ValueError("Context working-data budget exceeded; narrow the selected scope")
    path = Path(results[0].local_path).parent / f"{plan.dataset}_{uuid4().hex}.parquet"
    frame.write_parquet(path)
    checksum, missing = sha256_file(path), len(games) - len(results)
    combined = results[0].model_copy(update={
        "manifest_id": stable_id("dataset", {"provider": "research_context", "sha256": checksum,
            "inputs": sorted(m.manifest_id for m in results)}),
        "partition_key": f"team:{team}", "local_path": str(path.resolve()), "sha256": checksum,
        "row_count": frame.height, "columns": frame.columns, "file_size": path.stat().st_size,
        "modified_ns": path.stat().st_mtime_ns, "acquired_at": datetime.now(UTC),
        "input_manifest_ids": sorted(m.manifest_id for m in results),
        "source_inputs": [m.model_dump(mode="json") for m in results],
        "availability": "partial" if missing else "available",
        "availability_message": f"{missing} selected games lack this section ({failures} requests failed)." if missing else None,
        "coverage": {"expected_matches": len(games), "completed_matches": len(games) - failures,
                     "recorded_matches": len(results), "missing_selected_games": missing, "failed_requests": failures}})
    return [combined]
