"""Prepare and load scoped analysis inputs independently of report construction."""
from __future__ import annotations

import logging

import polars as pl

from sports_analyst.application.preparation import prepare_investigation
from sports_analyst.models import DatasetManifest

logger = logging.getLogger("sports_analyst.service")


def load_investigation_data(app, request, identifier, connector, plugin):
    if request.sport == "soccer":
        from sports_analyst.datasets.soccer.expected_goals import PLAYER_XG_FIELDS
        from sports_analyst.plugins.soccer import DEFAULTS as SOCCER_DEFAULT_METRICS
        from sports_analyst.plugins.soccer import SEASON_METRICS

    partition, prepared_seasons = prepare_investigation(app, request, identifier)
    manifests = {
        season: app.store.manifest_for_season(season, "schedules" if request.sport == "cfb" else "play_by_play",
                                             request.sport, request.scope.competition, partition)
        for season in prepared_seasons
    }
    pbp_columns = plugin.required_play_by_play_columns(request)
    datasets = {
        season: app._load_dataset(
            connector,
            manifest,
            pbp_columns,
            app._nfl_play_by_play_predicate(request, manifest) if request.sport == "nfl" else None,
        )
        for season, manifest in manifests.items()
    }
    required_supplemental = plugin.required_supplemental_datasets(request)
    analysis_seasons = set(request.scope.included_seasons)
    supplemental_manifests: dict[str, dict[int, DatasetManifest]] = {}
    candidates = app.store.manifests(sport=request.sport, competition=request.scope.competition,
        **({"provider_id": None, "processing_version": None} if request.sport == "soccer" else {}))
    scoped_packages = {(item.dataset, item.season) for item in candidates if item.partition_key == partition}
    for manifest in candidates:
        if manifest.row_count == 0:
            continue
        if request.sport in {"cfb", "soccer"} and manifest.partition_key != partition:
            continue
        if request.sport in {"nfl", "nba"}:
            if manifest.partition_key not in {None, partition}:
                continue
            if partition and manifest.partition_key is None and (manifest.dataset, manifest.season) in scoped_packages:
                continue
        if manifest.dataset in {"play_by_play", "teams"}:
            continue
        if manifest.dataset not in required_supplemental:
            continue
        if manifest.dataset != "players" and manifest.season not in analysis_seasons:
            continue
        supplemental_manifests.setdefault(manifest.dataset, {})[manifest.season] = manifest
    supplemental = {
        dataset: {season: app._load_dataset(connector, manifest) for season, manifest in season_manifests.items()}
        for dataset, season_manifests in supplemental_manifests.items()
    }
    if request.sport == "soccer" and request.subject and request.subject.type == "player" and "assists" in request.metrics:
        for season in sorted(analysis_seasons):
            try:
                dataset_name = f"player_game_logs_{request.subject.id}"
                try:
                    manifest = app.store.manifest_for_season(season, dataset_name, "soccer", request.scope.competition)
                except KeyError:
                    manifest = connector.player_game_log_manifest(request.scope.competition, season, request.subject.id)
                    app.store.save_manifest(manifest)
                supplemental_manifests.setdefault("player_game_logs", {})[season] = manifest
                supplemental.setdefault("player_game_logs", {})[season] = app._load_dataset(connector, manifest)
            except (OSError, ValueError) as error:
                logger.warning("soccer_player_gamelog_unavailable competition=%s season=%s player=%s error=%s",
                               request.scope.competition, season, request.subject.id, error)
    if (request.sport == "soccer" and request.subject and request.subject.type == "player"
            and set(request.metrics or SOCCER_DEFAULT_METRICS.get(request.analysis_domain, [])) & set(PLAYER_XG_FIELDS)):
        def player_xg_progress() -> None:
            app.events.emit(identifier, "loading", "Loading recorded player expected goals", 0.2)

        player_xg_progress()
        for season in sorted(analysis_seasons):
            try:
                manifest = connector.player_expected_goals_manifest(
                    request.scope.competition, season, request.subject.id,
                    datasets[season], supplemental.get("lineups", {}).get(season, pl.DataFrame()), player_xg_progress,
                )
                app.store.save_manifest(manifest)
                supplemental_manifests.setdefault("player_expected_goals", {})[season] = manifest
                supplemental.setdefault("player_expected_goals", {})[season] = app._load_dataset(connector, manifest)
            except (OSError, ValueError) as error:
                logger.warning("soccer_player_xg_unavailable competition=%s season=%s player=%s error=%s",
                               request.scope.competition, season, request.subject.id, error)
    if request.sport == "soccer" and request.subject and set(request.metrics) & set(SEASON_METRICS):
        if request.scope.comparison_design != "full_seasons" or any(
                window.start_date or window.end_date for window in (request.scope.baseline, request.scope.comparison)):
            raise ValueError("Published season statistics require full-season comparisons without date filters")
        def season_stats_progress() -> None:
            app.events.emit(identifier, "loading", "Loading published soccer season statistics", 0.2)
        for season in sorted(analysis_seasons):
            season_stats_progress()
            try:
                manifest = connector.season_statistics_manifest(request.scope.competition, season,
                    request.subject.type, str(request.subject.id), datasets[season],
                    supplemental.get("lineups", {}).get(season, pl.DataFrame()), season_stats_progress)
                app.store.save_manifest(manifest)
                supplemental_manifests.setdefault("season_statistics", {})[season] = manifest
                supplemental.setdefault("season_statistics", {})[season] = app._load_dataset(connector, manifest)
            except (OSError, ValueError) as error:
                logger.warning("soccer_season_statistics_unavailable season=%s error=%s", season, error)
    return partition, manifests, datasets, supplemental_manifests, supplemental
