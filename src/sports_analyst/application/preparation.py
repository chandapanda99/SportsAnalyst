"""Coverage-driven investigation preparation; retain each provider's delivery format."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from sports_analyst.datasets.cfb_source import CFBSource
from sports_analyst.datasets.nba import NBA_DATASETS
from sports_analyst.datasets.nfl import DATASET_MIN_SEASONS
from sports_analyst.datasets.soccer.connector import SOCCER_COMPETITIONS
from sports_analyst.plugins.nfl_shared import LATEST_SYNCABLE_SEASON
from sports_analyst.plugins.soccer import DEFAULTS as SOCCER_DEFAULTS
from sports_analyst.plugins.soccer import METRICS as SOCCER_METRICS

logger = logging.getLogger(__name__)
FRESH_SECONDS = 3600


def coordinator(app):
    return CFBSource(app.settings.data_dir / "raw" / "preparation", app.store.persistence, namespace="preparation")


def current_season(sport, competition=None):
    now = datetime.now(UTC)
    if sport == "nfl":
        return LATEST_SYNCABLE_SEASON
    return now.year + int(now.month >= 7) if sport == "nba" or (sport == "soccer" and not SOCCER_COMPETITIONS[competition][1]) else now.year


def reusable(manifest, current):
    if manifest.availability != "available":
        return False
    coverage = manifest.coverage
    expected = coverage.get("expected_intervals", coverage.get("expected_matches", 0))
    completed = coverage.get("fetched_intervals", coverage.get("completed_matches", expected))
    if expected and completed < expected:
        return False
    return manifest.season not in {0, current} or (datetime.now(UTC) - manifest.acquired_at).total_seconds() < FRESH_SECONDS


def requirements(request, first_install):
    player = request.subject is not None and request.subject.type == "player"
    if request.sport == "nfl":
        required = {"play_by_play"}
        if first_install:
            required.add("schedules")
            if player:
                required.add("player_stats")
        # Expensive charting is optional unless the question explicitly calls for it.
        optional = set()
        text = request.question.lower()
        if any(word in text for word in ("personnel", "formation", "coverage", "pressure")):
            optional.update({"participation", "ftn_charting"})
        if any(word in text for word in ("injur", "availability")):
            optional.add("injuries")
        return required, optional
    if request.sport == "nba":
        required = {"play_by_play", "schedules", "player_boxscores" if player else "team_boxscores"}
        if request.analysis_domain == "shooting":
            required.add("shots")
        if request.analysis_domain in {"lineups", "impact"}:
            required.add("lineups")
        return required, set()
    required = {"play_by_play"}
    optional = {"key_events"}
    if player:
        required.add("lineups")
    for metric in request.metrics or SOCCER_DEFAULTS.get(request.analysis_domain, SOCCER_DEFAULTS["results"]):
        source = SOCCER_METRICS.get(metric, (None, None))[1]
        if source in {"team_stats", "lineups", "key_events", "expected_goals", "match_analytics", "asa_analytics", "understat_team_matches"}:
            required.add(source)
    return required, optional - required


def project_soccer(app, connector, competition, season, partition, dataset, current):
    if dataset.startswith("understat_"):
        return None  # Provider identities/coverage must not be rebuilt as ESPN manifests.
    """Reuse full competition snapshots without relabeling them as team downloads."""
    try:
        source = app.store.manifest_for_season(season, dataset, "soccer", competition)
        schedule_source = app.store.manifest_for_season(season, "play_by_play", "soccer", competition)
    except KeyError:
        return None
    if not reusable(source, current) or not reusable(schedule_source, current):
        return None
    team = partition.split(":")[1]
    schedule = app._load_dataset(connector, schedule_source)
    selected = schedule.filter((pl.col("home_team_id") == team) | (pl.col("away_team_id") == team))
    if selected.is_empty():
        return None
    games = selected["event_id"].cast(pl.String).to_list()
    data = selected if dataset == "play_by_play" else app._load_dataset(connector, source)
    if dataset != "play_by_play":
        if "game_id" not in data.columns:
            return None
        data = data.filter(pl.col("game_id").cast(pl.String).is_in(games))
    if data.is_empty():
        return None
    path = connector.data_dir / competition / "partitions" / "team" / team / str(season) / f"{dataset}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    data.write_parquet(path)
    completed = selected.filter(pl.col("status").str.to_lowercase().is_in(["status_final", "status_full_time", "final"])).height
    intervals = source.coverage.get("expected_intervals", 1)
    manifest = connector.manifest_for(
        path,
        competition,
        season,
        dataset,
        data,
        intervals if dataset == "play_by_play" else completed,
        intervals if dataset == "play_by_play" else completed,
        data["game_id"].n_unique() if "game_id" in data.columns else 0,
        partition,
    )
    manifest = manifest.model_copy(
        update={
            "acquired_at": source.acquired_at,
            "package_version": source.package_version,
            "source_url": source.source_url,
            "license": source.license,
            "attribution": source.attribution,
            "resolution_version": source.resolution_version,
            "input_manifest_ids": list(dict.fromkeys([source.manifest_id, *source.input_manifest_ids])),
        }
    )
    app.store.save_manifest(manifest)
    return manifest


def prepare_investigation(app, request, identifier):
    if request.sport == "cfb":
        return app._prepare_cfb(request, identifier)
    connector = app.connectors[request.sport]
    competition = request.scope.competition
    if request.sport == "soccer" and competition not in SOCCER_COMPETITIONS:
        raise ValueError("Select a supported soccer competition before preparing data")
    partition = None
    if request.sport in {"nfl", "nba"}:
        from sports_analyst.datasets.download_scope import canonical_team

        identity = request.subject.team_id if request.subject and request.subject.type == "player" else request.scope.team
        team = canonical_team(request.sport, identity)
        if team:
            candidate = f"team:{team}"
            app.store.refresh_durable_datasets(request.sport, request.scope.included_seasons, ["play_by_play"], partition_key=candidate)
            if any(item.partition_key == candidate for item in app.store.manifests("play_by_play", request.sport)):
                full_years = {item.season for item in app.store.manifests("play_by_play", request.sport)
                              if item.partition_key is None and item.row_count}
                if not set(request.scope.included_seasons) <= full_years:
                    partition = candidate
    if request.sport == "soccer" and (request.subject is None or request.subject.type == "team" or request.subject.team_id):
        team = (request.subject.team_id if request.subject and request.subject.type == "player"
                else request.subject.id if request.subject else request.scope.team)
        if not team.isdigit():
            raise ValueError("Select a numeric ESPN soccer team ID")
        partition = f"team:{team}"
    current = current_season(request.sport, competition)
    if request.sport == "nfl" and any(year < 1999 or year > LATEST_SYNCABLE_SEASON for year in request.scope.included_seasons):
        raise ValueError("Choose NFL seasons offered by the current source catalog")
    app.store.invalidate_reset_cache(request.sport, competition)
    coordination = coordinator(app)
    for season in request.scope.included_seasons:
        with coordination.lease(f"prepare:{request.sport}:{competition}:{partition}:{season}", seconds=1800):
            initial_required, initial_optional = requirements(request, True)
            app.store.refresh_durable_datasets(
                request.sport, [season], sorted(initial_required | initial_optional), partition_key=partition, competition=competition
            )
            try:
                app.store.manifest_for_season(season, "play_by_play", request.sport, competition, partition)
                first_install = False
            except KeyError:
                first_install = True
            required, optional = requirements(request, first_install)
            pending = []
            for dataset in sorted(required | optional):
                if dataset.startswith("understat_"):
                    app.store.refresh_durable_datasets(request.sport, [season], [dataset], competition, partition,
                        provider_id="understat", processing_version="understat-soccerdata-1")
                if request.sport == "nfl" and season < DATASET_MIN_SEASONS[dataset]:
                    continue
                if request.sport == "nba" and season not in NBA_DATASETS[dataset].available_seasons:
                    if dataset in required:
                        raise ValueError(f"{dataset} has no published NBA snapshot for {season}")
                    continue
                try:
                    manifest = app.store.manifest_for_season(season, dataset, request.sport, competition, partition,
                        **({"provider_id": "understat", "processing_version": "understat-soccerdata-1"}
                           if dataset.startswith("understat_") else {}))
                except KeyError:
                    manifest = project_soccer(app, connector, competition, season, partition, dataset, current) if partition else None
                if manifest and reusable(manifest, current) and (app.store.persistence.durable or Path(manifest.local_path).exists()):
                    continue
                pending.append(dataset)
            if not pending:
                app.events.emit(identifier, "preparing", f"Using cached {request.sport.upper()} data · {season}", 0.15)
                continue

            def progress(phase, dataset, year, completed, total, *detail):
                app.events.emit(
                    identifier,
                    "preparing",
                    f"Preparing {request.sport.upper()} · {year} · {dataset.replace('_', ' ')} · {phase}",
                    0.15,
                    season=year,
                    dataset=dataset,
                    partition_key=partition,
                )

            app.events.emit(
                identifier, "preparing", f"Preparing missing {request.sport.upper()} data · {season}; source coverage will be checked", 0.12
            )
            if request.sport == "soccer":
                if "play_by_play" not in pending:
                    pending.insert(0, "play_by_play")  # Publish refreshed acquisition status after a resumed summary download.
                connector.sync(
                    [season],
                    pending,
                    progress_callback=progress,
                    manifest_callback=app.store.save_manifest,
                    competition=competition,
                    team_id=partition.split(":")[1] if partition else None,
                    include_expected_goals="expected_goals" in pending,
                    refresh_seasons={season} if season == current else set(),
                )
            else:
                if partition:
                    from sports_analyst.datasets.download_scope import sync_team_partitions

                    sync_team_partitions(app, [season], pending, request.sport, {season: [team]}, progress, app.store.save_manifest)
                    pending = []
                for dataset in pending:
                    try:
                        connector.sync([season], [dataset], progress_callback=progress, manifest_callback=app.store.save_manifest)
                    except Exception:
                        if dataset in required:
                            raise
                        logger.exception("optional_preparation_unavailable sport=%s dataset=%s season=%s", request.sport, dataset, season)
                        app.events.emit(identifier, "preparing", f"Optional {dataset} unavailable; continuing with recorded core data", 0.16)
            for dataset in required:
                try:
                    manifest = app.store.manifest_for_season(season, dataset, request.sport, competition, partition)
                except KeyError as error:
                    raise ValueError(f"Required {request.sport.upper()} {dataset} data are unavailable for {season}") from error
                if manifest.row_count == 0 or manifest.availability == "source_unavailable":
                    raise ValueError(f"Required {request.sport.upper()} {dataset} data are unavailable for {season}; "
                                     "no analysis can be generated from missing data")
    return partition, request.scope.included_seasons
