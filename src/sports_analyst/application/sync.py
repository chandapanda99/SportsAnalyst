"""Dataset-only runtime shared by the desktop service and Cloud Run sync target."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from time import perf_counter

from sports_analyst.application.runtime import sport_registries
from sports_analyst.config import Settings
from sports_analyst.datasets.acquisition import timed_stage
from sports_analyst.datasets.availability import completion_message
from sports_analyst.datasets.errors import SyncFailure
from sports_analyst.datasets.nba import NBA_DEFAULT_DATASETS
from sports_analyst.datasets.nfl_catalog import LATEST_SYNCABLE_SEASON
from sports_analyst.datasets.optional import optional_dependencies
from sports_analyst.datasets.soccer.catalog import (
    SOCCER_COMPETITIONS,
    SOCCER_DEFAULT_DATASETS,
    soccer_season_label,
)
from sports_analyst.jobs.object_store import ObjectJobStore
from sports_analyst.models import DatasetManifest, stable_id
from sports_analyst.storage.local import LocalStore

logger = logging.getLogger("sports_analyst.service")


def _season_label(sport: str, competition: str | None, season: int) -> str:
    if season == 0:
        return "reference data"
    if sport == "soccer" and competition in SOCCER_COMPETITIONS:
        return soccer_season_label(competition, season)
    return f"{season - 1}–{str(season)[-2:]}" if sport == "nba" else str(season)


class DatasetSyncApplication:
    """Cloud sync runtime without model, charting, or agent initialization."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = LocalStore(settings, restore_durable_index=False)
        self.connectors, _ = sport_registries(settings, self.store.persistence)
        polling = settings.job_progress_transport == "poll"
        self.jobs = ObjectJobStore(
            self.store.persistence,
            record_events=not polling,
            status_min_interval=0.5 if polling else 0,
        )
        self.events = self.jobs


    def sync(
            self, seasons: list[int], job_id: str | None = None, datasets: list[str] | None = None,
            sport: str = "nfl", competition: str | None = None,
            *, team_ids: list[str] | None = None, conference_id: str | None = None, division_id: str | None = None,
    ) -> list[DatasetManifest]:
        return run_dataset_sync(self, seasons, job_id, datasets, sport, competition,
                                team_ids=team_ids, conference_id=conference_id, division_id=division_id)


def run_dataset_sync(
        application,
        seasons: list[int],
        job_id: str | None = None,
        datasets: list[str] | None = None,
        sport: str = "nfl",
        competition: str | None = None,
        *, team_ids: list[str] | None = None, conference_id: str | None = None, division_id: str | None = None,
) -> list[DatasetManifest]:
    league = (SOCCER_COMPETITIONS.get(competition, ("Soccer",))[0] if sport == "soccer"
              else {"nfl": "NFL", "nba": "NBA", "cfb": "College Football"}.get(sport, "Unknown sport"))
    context = {"sport": sport, "competition": competition, "league": league,
               "seasons": list(seasons), "step": "initializing the data library"}
    context["season_label"] = ", ".join(_season_label(sport, competition, season) for season in seasons)
    try:
        if sport == "cfb":
            connector = application.connectors[sport]
            application.store.invalidate_reset_cache(sport)
            key = job_id or stable_id("sync", {"sport": sport, "teams": team_ids, "seasons": seasons, "time": datetime.now(UTC)})

            def report(phase, dataset, season, completed, total, fraction=None, detail=None, force=False):
                context.update(season=season, season_label=str(season), dataset=dataset, step=detail or phase)
                application.events.emit(key, phase, f"College Football · {season} · {detail or dataset}",
                                        0.1 + 0.7 * (fraction or 0), **context)

            installed = {item.manifest_id: item for item in application.store.manifests(sport="cfb")}
            saved = []

            def register_cfb(manifest):
                previous = installed.get(manifest.manifest_id)
                if previous and previous.model_dump(exclude={"local_path"}) == manifest.model_dump(exclude={"local_path"}):
                    return  # Reused historical snapshots do not need another upload.
                context.update(dataset=manifest.dataset, season=manifest.season,
                               season_label=str(manifest.season), step="saving to the data library")
                with timed_stage("save_dataset", sport="cfb", season=manifest.season,
                                 dataset=manifest.dataset, partition=manifest.partition_key):
                    # A refreshed snapshot can have identical bytes but newer
                    # coverage/freshness metadata. Save that metadata regardless.
                    application.store.save_manifest(manifest, publish_catalog=False, upload_data=previous is None)
                installed[manifest.manifest_id] = manifest
                saved.append(manifest)

            try:
                with timed_stage("sync", sport="cfb", job_id=key):
                    manifests = connector.sync(seasons, datasets, team_ids=team_ids, progress_callback=report,
                                               manifest_callback=register_cfb)
            finally:
                # Per-item files and metadata are checkpointed immediately. Publish
                # their catalog once, including successes from interrupted runs.
                if saved:
                    with timed_stage("publish_catalog", sport="cfb", job_id=key):
                        application.store.publish_dataset_catalog(saved)
            gaps = [item for item in manifests if item.availability != "available"]
            message = "Selected college-football data ready"
            if gaps:
                message = "College-football sync finished with coverage gaps: " + "; ".join(
                    f"{item.partition_key} · {item.season} · {item.dataset}: {item.availability_message}" for item in gaps)
            application.events.emit(key, "complete", message, 1,
                                    manifest_ids=[item.manifest_id for item in manifests])
            return manifests
        from sports_analyst.datasets.download_scope import resolve_download_teams

        scoped_teams = resolve_download_teams(sport, seasons, competition, team_ids, conference_id, division_id)
        return _run_dataset_sync(application, seasons, job_id, datasets, sport, competition, context, scoped_teams)
    except Exception as error:
        logger.exception("dataset_sync_failed job_id=%s context=%s error_type=%s", job_id, context, type(error).__name__)
        raise SyncFailure(context, error) from error


def _run_dataset_sync(application, seasons, job_id, datasets, sport, competition, context, scoped_teams=None) -> list[DatasetManifest]:
    if sport not in application.connectors:
        raise ValueError(f"unsupported sport {sport!r}")
    connector = application.connectors[sport]
    defaults = ["play_by_play"] if sport == "nfl" else SOCCER_DEFAULT_DATASETS if sport == "soccer" else NBA_DEFAULT_DATASETS
    selected_datasets = list(datasets or defaults)
    key = job_id or stable_id(
        "sync", {"sport": sport, "competition": competition, "seasons": sorted(seasons),
                 "datasets": selected_datasets, "time": datetime.now(UTC)}
    )
    started_at = perf_counter()
    logger.info(
        "dataset_sync_started job_id=%s seasons=%s datasets=%s",
        key,
        ",".join(str(season) for season in sorted(seasons)),
        ",".join(selected_datasets),
    )
    application.events.emit(key, "starting", f"Preparing selected {sport.upper()} datasets", 0.05)

    if sport == "soccer" and "team_stats" in selected_datasets and "expected_goals" not in selected_datasets:
        selected_datasets.append("expected_goals")

    application.store.refresh_durable_datasets(sport, seasons, selected_datasets, competition)
    if sport == "soccer":
        secondary = [name for name in selected_datasets if name.startswith("understat_")]
        if secondary:
            application.store.refresh_durable_datasets(sport, seasons, secondary, competition,
                provider_id="understat", processing_version="understat-soccerdata-1")
        if "whoscored_events" in selected_datasets:
            application.store.refresh_durable_datasets(sport, seasons, ["whoscored_events"], competition,
                provider_id="whoscored", processing_version="whoscored-soccerdata-1")
    application.store.invalidate_reset_cache(sport, competition)
    source_options = {"provider_id": None, "processing_version": None} if sport == "soccer" else {}
    existing = {(manifest.dataset, manifest.season) for manifest in application.store.manifests(sport=sport, competition=competition, **source_options)
                if manifest.partition_key is None}
    existing -= {(item.dataset, item.season) for item in application.store.manifests(sport=sport, competition=competition, **source_options)
                 if getattr(item, "availability", "available") != "available"}
    if sport == "soccer":
        if "whoscored_events" in selected_datasets:
            existing |= {(m.dataset, m.season) for m in application.store.manifests(sport=sport, competition=competition,
                provider_id="whoscored", processing_version="whoscored-soccerdata-1")
                if m.partition_key is None and m.availability == "available"}
        incomplete = {(manifest.dataset, manifest.season) for manifest in application.store.manifests(sport=sport, competition=competition, **source_options)
                      if (manifest.coverage.get("fetched_intervals", 0) < manifest.coverage.get("expected_intervals", 0)
                          if manifest.dataset == "play_by_play" else
                          manifest.coverage.get("completed_matches", 0) < manifest.coverage.get("expected_matches", 0))}
        existing -= incomplete
        if competition in SOCCER_COMPETITIONS:
            now = datetime.now(UTC)
            current_season = now.year + int(not SOCCER_COMPETITIONS[competition][1] and now.month >= 7)
            existing = {(dataset, season) for dataset, season in existing if season != current_season}
    if sport == "nfl":
        # In-season nflverse packages change after games and stat corrections.
        # Keep older local seasons, but replace selected current-season snapshots.
        existing = {(dataset, season) for dataset, season in existing if season != LATEST_SYNCABLE_SEASON}
    if sport == "nba":
        # NBA season IDs use the ending year; July starts the next season.
        now = datetime.now(UTC)
        current_season = now.year + int(now.month >= 7)
        existing = {(dataset, season) for dataset, season in existing if season != current_season}
    registered: set[str] = set()
    last_sync_progress = 0.08
    last_detail_at = 0.0
    last_detail_key = None
    progress_lock = Lock()

    def report_sync(phase: str, dataset: str, season: int, completed: int, total: int,
                    fraction: float | None = None, detail: str | None = None, force: bool = False) -> None:
        nonlocal last_sync_progress, last_detail_at, last_detail_key
        with progress_lock:
            season_label = _season_label(sport, competition, season)
            context.update(dataset=dataset, season=season, season_label=season_label,
                           step=detail.split(" · ")[0] if detail else f"{phase} {dataset.replace('_', ' ')}")
            if total <= 0:
                return
            if detail:
                now = perf_counter()
                detail_key = (dataset, season, detail.split(" · ")[0])
                if not force and detail_key == last_detail_key and now - last_detail_at < 0.5:
                    return
                last_detail_at, last_detail_key = now, detail_key
            label = dataset.replace("_", " ").title()
            offsets = {"downloading": 0.0, "processing": 0.65, "downloaded": 0.0, "skipped": 0.0}
            unit_progress = min(total, completed + (max(0.0, fraction) if fraction is not None else offsets.get(phase, 0.0)))
            progress = 0.08 + 0.68 * unit_progress / total
            last_sync_progress = max(last_sync_progress, progress)
            messages = {
                "downloading": f"Downloading {label} for {season_label} · {completed + 1} of {total}",
                "processing": f"Processing {label} for {season_label} · {completed + 1} of {total}",
                "downloaded": f"Downloaded {label} for {season_label} · {completed} of {total}",
                "skipped": f"Skipped unavailable {label} for {season_label} · {completed} of {total}",
                "available": f"Already downloaded {label} for {season_label} · {completed} of {total}",
            }
            application.events.emit(
                key, phase, f"{label} for {season_label} · {detail}" if detail else
                messages.get(phase, f"Syncing {label} for {season_label}"), last_sync_progress,
                **context,
            )

    def register_manifest(manifest: DatasetManifest) -> None:
        context.update(dataset=manifest.dataset, season=manifest.season,
                       season_label=_season_label(sport, competition, manifest.season), step="saving to the data library")
        label = manifest.dataset.replace("_", " ").title()
        application.events.emit(key, "uploading", f"Saving {label} {manifest.season} to the data library", last_sync_progress)
        upload_started_at = perf_counter()
        application.store.save_manifest(manifest, publish_catalog=False)
        registered.add(manifest.manifest_id)
        logger.info(
            "dataset_item_published job_id=%s sport=%s dataset=%s season=%s bytes=%d duration_ms=%d",
            key,
            manifest.sport,
            manifest.dataset,
            manifest.season,
            Path(manifest.local_path).stat().st_size,
            round((perf_counter() - upload_started_at) * 1000),
        )

    sync_kwargs = {"competition": competition, "progress_detail_callback": report_sync,
                   "refresh_seasons": {current_season} if competition in SOCCER_COMPETITIONS else set()} if sport == "soccer" else {}
    context["step"] = "downloading selected datasets"
    try:
        with optional_dependencies(f"{sport.upper()} dataset sync"), timed_stage("acquire_datasets", sport=sport, competition=competition):
            if scoped_teams and sport in {"nfl", "nba"}:
                from sports_analyst.datasets.download_scope import sync_team_partitions

                manifests = sync_team_partitions(application, seasons, selected_datasets, sport, scoped_teams, report_sync, register_manifest)
            elif scoped_teams and sport == "soccer":
                manifests = []
                for season, teams in scoped_teams.items():
                    for team in teams:
                        manifests.extend(connector.sync(
                            [season], selected_datasets, progress_callback=report_sync, manifest_callback=register_manifest,
                            team_id=team, **sync_kwargs))
            else:
                manifests = connector.sync(
                    seasons, selected_datasets, progress_callback=report_sync,
                    manifest_callback=register_manifest, skip=existing, **sync_kwargs)
    finally:
        if registered:
            application.store.publish_dataset_catalog(application.store.manifests(sport=sport, competition=competition, **source_options))
    for manifest in manifests:
        if manifest.manifest_id not in registered:
            register_manifest(manifest)
    context["step"] = "publishing the data catalog"
    context.pop("season", None)
    context.pop("dataset", None)
    context["season_label"] = ", ".join(_season_label(sport, competition, season) for season in seasons)
    application.store.publish_dataset_catalog(application.store.manifests(sport=sport, competition=competition, **source_options))
    connector.clear_cache()
    application.events.emit(key, "complete", completion_message(manifests), 1.0,
                            manifest_ids=[item.manifest_id for item in manifests])
    logger.info(
        "dataset_sync_completed job_id=%s manifests=%d duration_ms=%d",
        key,
        len(manifests),
        round((perf_counter() - started_at) * 1000),
    )
    return manifests
