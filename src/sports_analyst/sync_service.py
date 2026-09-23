"""Dataset-only runtime shared by the desktop service and Cloud Run sync target."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from time import perf_counter

from sports_analyst.config import Settings
from sports_analyst.data import NFLVerseConnector
from sports_analyst.models import DatasetManifest, stable_id
from sports_analyst.nba_data import NBA_DEFAULT_DATASETS, SportsDataverseNBAConnector
from sports_analyst.object_jobs import ObjectJobStore
from sports_analyst.storage import LocalStore

logger = logging.getLogger("sports_analyst.service")


class DatasetSyncApplication:
    """Cloud sync runtime without model, charting, or agent initialization."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = LocalStore(settings, restore_durable_index=False)
        self.connectors = {
            "nfl": NFLVerseConnector(settings),
            "nba": SportsDataverseNBAConnector(settings),
        }
        polling = settings.job_progress_transport == "poll"
        self.jobs = ObjectJobStore(
            self.store.persistence,
            record_events=not polling,
            status_min_interval=0.5 if polling else 0,
        )
        self.events = self.jobs

    def sync(
            self, seasons: list[int], job_id: str | None = None, datasets: list[str] | None = None, sport: str = "nfl"
    ) -> list[DatasetManifest]:
        return run_dataset_sync(self, seasons, job_id, datasets, sport)


def run_dataset_sync(
        application,
        seasons: list[int],
        job_id: str | None = None,
        datasets: list[str] | None = None,
        sport: str = "nfl",
) -> list[DatasetManifest]:
    if sport not in application.connectors:
        raise ValueError(f"unsupported sport {sport!r}")
    connector = application.connectors[sport]
    selected_datasets = list(datasets or (["play_by_play"] if sport == "nfl" else NBA_DEFAULT_DATASETS))
    key = job_id or stable_id(
        "sync", {"sport": sport, "seasons": sorted(seasons), "datasets": selected_datasets, "time": datetime.now(UTC)}
    )
    started_at = perf_counter()
    logger.info(
        "dataset_sync_started job_id=%s seasons=%s datasets=%s",
        key,
        ",".join(str(season) for season in sorted(seasons)),
        ",".join(selected_datasets),
    )
    application.events.emit(key, "starting", f"Preparing selected {sport.upper()} datasets", 0.05)

    application.store.refresh_durable_datasets(sport, seasons, selected_datasets)
    existing = {(manifest.dataset, manifest.season) for manifest in application.store.manifests(sport=sport)}
    registered: set[str] = set()
    last_sync_progress = 0.08
    progress_lock = Lock()

    def report_sync(phase: str, dataset: str, season: int, completed: int, total: int) -> None:
        nonlocal last_sync_progress
        with progress_lock:
            if total <= 0:
                return
            label = dataset.replace("_", " ").title()
            season_label = "reference data" if season == 0 else (f"{season - 1}–{str(season)[-2:]}" if sport == "nba" else str(season))
            offsets = {"downloading": 0.0, "processing": 0.65, "downloaded": 0.0, "skipped": 0.0}
            unit_progress = min(total, completed + offsets.get(phase, 0.0))
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
                key, phase, messages.get(phase, f"Syncing {label} for {season_label}"), last_sync_progress
            )

    def register_manifest(manifest: DatasetManifest) -> None:
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

    manifests = connector.sync(seasons, selected_datasets, progress_callback=report_sync, manifest_callback=register_manifest, skip=existing)
    for manifest in manifests:
        if manifest.manifest_id not in registered:
            register_manifest(manifest)
    application.store.publish_dataset_catalog(application.store.manifests(sport=sport))
    connector.clear_cache()
    application.events.emit(key, "complete", "Dataset sync complete", 1.0, manifest_ids=[item.manifest_id for item in manifests])
    logger.info(
        "dataset_sync_completed job_id=%s manifests=%d duration_ms=%d",
        key,
        len(manifests),
        round((perf_counter() - started_at) * 1000),
    )
    return manifests
