from __future__ import annotations

import importlib.metadata
import logging
import shutil
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

import polars as pl

from sports_analyst.config import Settings, get_settings
from sports_analyst.datasets.availability import SourceUnavailable, missing_source, unavailable_snapshot
from sports_analyst.datasets.nfl_catalog import (
    DATASET_MIN_SEASONS,
    DIRECT_PARQUET_PATHS,
    NFLVERSE_RELEASE_BASE_URL,
    REFERENCE_DATASETS,
    SOURCE_TEMPLATES,
    SUPPORTED_DATASETS,
)
from sports_analyst.datasets.optional import load_optional_module
from sports_analyst.datasets.snapshots import SnapshotReader, sha256_file
from sports_analyst.models import DatasetManifest, stable_id

logger = logging.getLogger("sports_analyst.data")

class NFLVerseConnector:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        self._reader = SnapshotReader(self.settings, self.settings.raw_dir)

    def sync(
        self,
        seasons: list[int],
        datasets: list[str] | None = None,
        progress_callback: Callable[[str, str, int, int, int], None] | None = None,
        manifest_callback: Callable[[DatasetManifest], None] | None = None,
        skip: set[tuple[str, int]] | None = None,
    ) -> list[DatasetManifest]:
        selected = list(dict.fromkeys(datasets or ["play_by_play"]))
        unknown = sorted(set(selected) - set(SUPPORTED_DATASETS))
        if unknown:
            raise ValueError(f"unsupported nflverse datasets: {unknown}")
        work = [(0, dataset) for dataset in selected if dataset in REFERENCE_DATASETS]
        work.extend(
            (season, dataset)
            for season in sorted(set(seasons))
            for dataset in selected
            if dataset not in REFERENCE_DATASETS
        )
        if not work:
            raise ValueError("none of the selected datasets are available for the selected seasons")
        skipped = skip or set()
        manifests_by_index: dict[int, DatasetManifest] = {}
        pending: list[tuple[int, int, str]] = []
        completed = 0
        for index, (season, dataset) in enumerate(work):
            if (dataset, season) in skipped:
                completed += 1
                if progress_callback:
                    progress_callback("available", dataset, season, completed, len(work))
                continue
            pending.append((index, season, dataset))

        def acquire(index: int, season: int, dataset: str) -> tuple[int, DatasetManifest]:
            item_started_at = perf_counter()
            if progress_callback:
                progress_callback("downloading", dataset, season, index, len(work))
            path = self.settings.raw_dir / (f"{dataset}.parquet" if season == 0 else f"{dataset}_{season}.parquet")
            frame: pl.DataFrame | None = None
            if dataset not in REFERENCE_DATASETS and season < DATASET_MIN_SEASONS[dataset]:
                raise SourceUnavailable("The selected season predates this package's supported coverage")
            if release_path := DIRECT_PARQUET_PATHS.get(dataset):
                self._download_parquet(f"{NFLVERSE_RELEASE_BASE_URL}{release_path.format(season=season)}", path)
            else:
                nfl = load_optional_module("nflreadpy", "NFL dataset sync")
                frame = self._load_remote(nfl, dataset, season)
                if frame.is_empty():
                    raise SourceUnavailable("No rows supplied for the selected NFL package/season")
                if progress_callback:
                    progress_callback("processing", dataset, season, index, len(work))
                frame.write_parquet(path)
            manifest = self.manifest_for(path, season, frame, dataset)
            logger.info(
                "dataset_item_acquired sport=nfl dataset=%s season=%s bytes=%d duration_ms=%d",
                dataset,
                season,
                path.stat().st_size,
                round((perf_counter() - item_started_at) * 1000),
            )
            return index, manifest

        workers = min(self.settings.dataset_sync_concurrency, len(pending))
        if workers:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="nfl-sync") as executor:
                futures = {
                    executor.submit(acquire, index, season, dataset): (season, dataset)
                    for index, season, dataset in pending
                }
                for future in as_completed(futures):
                    season, dataset = futures[future]
                    try:
                        index, manifest = future.result()
                    except Exception as error:
                        if not missing_source(error):
                            raise
                        index = next(i for i, year, name in pending if year == season and name == dataset)
                        path = self.settings.raw_dir / (f"{dataset}.parquet" if season == 0 else f"{dataset}_{season}.parquet")
                        manifest = unavailable_snapshot(path, season,
                            lambda path, frame, year=season, name=dataset: self.manifest_for(path, year, frame, name))
                        logger.warning("dataset_source_unavailable sport=nfl dataset=%s season=%s", dataset, season)
                    manifests_by_index[index] = manifest
                    completed += 1
                    if progress_callback:
                        progress_callback("skipped" if manifest.coverage.get("source_unavailable") else "downloaded",
                                          dataset, season, completed, len(work))
                    if manifest_callback:
                        manifest_callback(manifest)

        manifests = [manifests_by_index[index] for index in sorted(manifests_by_index)]
        return manifests

    @staticmethod
    def _load_remote(nfl: object, dataset: str, season: int) -> pl.DataFrame:
        loaders = {
            "play_by_play": lambda: nfl.load_pbp([season]),
            "player_stats": lambda: nfl.load_player_stats([season], summary_level="week"),
            "rosters": lambda: nfl.load_rosters([season]),
            "injuries": lambda: nfl.load_injuries([season]),
            "schedules": lambda: nfl.load_schedules([season]),
            "snap_counts": lambda: nfl.load_snap_counts([season]),
            "nextgen_passing": lambda: nfl.load_nextgen_stats([season], stat_type="passing"),
            "participation": lambda: nfl.load_participation([season]),
            "weekly_rosters": lambda: nfl.load_rosters_weekly([season]),
            "depth_charts": lambda: nfl.load_depth_charts([season]),
            "nextgen_receiving": lambda: nfl.load_nextgen_stats([season], stat_type="receiving"),
            "nextgen_rushing": lambda: nfl.load_nextgen_stats([season], stat_type="rushing"),
            "ftn_charting": lambda: nfl.load_ftn_charting([season]),
            "pfr_passing": lambda: nfl.load_pfr_advstats([season], stat_type="pass", summary_level="week"),
            "pfr_rushing": lambda: nfl.load_pfr_advstats([season], stat_type="rush", summary_level="week"),
            "pfr_receiving": lambda: nfl.load_pfr_advstats([season], stat_type="rec", summary_level="week"),
            "pfr_defense": lambda: nfl.load_pfr_advstats([season], stat_type="def", summary_level="week"),
            "players": nfl.load_players,
            "teams": nfl.load_teams,
        }
        return loaders[dataset]()

    @staticmethod
    def _download_parquet(url: str, destination: Path) -> None:
        """Stream a published Parquet asset to disk without materializing it in memory."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(f"{destination.suffix}.part")
        request = urllib.request.Request(url, headers={"User-Agent": "Open-Sports-Analyst/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            if pl.scan_parquet(temporary).select(pl.len()).collect().item() == 0:
                raise SourceUnavailable("Published NFL package contains no recorded rows")
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def register_local(self, path: Path, season: int) -> DatasetManifest:
        frame = pl.read_parquet(path)
        target = self.settings.raw_dir / f"play_by_play_{season}.parquet"
        if path.resolve() != target.resolve():
            frame.write_parquet(target)
        return self.manifest_for(target, season, frame, "play_by_play")

    def manifest_for(self, path: Path, season: int, frame: pl.DataFrame | None = None, dataset: str = "play_by_play") -> DatasetManifest:
        if frame is None:
            import pyarrow.parquet as pq

            parquet = pq.ParquetFile(path)
            row_count = parquet.metadata.num_rows
            columns = parquet.schema_arrow.names
        else:
            row_count = frame.height
            columns = frame.columns
        checksum = sha256_file(path)
        stat = path.stat()
        payload = {"dataset": dataset, "season": season, "sha256": checksum, "rows": row_count, "columns": columns}
        try:
            package_version = importlib.metadata.version("nflreadpy")
        except importlib.metadata.PackageNotFoundError:
            package_version = "unknown"
        return DatasetManifest(
            manifest_id=stable_id("dataset", payload),
            dataset=dataset,
            season=season,
            source_url=SOURCE_TEMPLATES[dataset].format(season=season),
            sha256=checksum,
            row_count=row_count,
            columns=columns,
            package_version=package_version,
            local_path=str(path.resolve()),
            file_size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )

    def load(self, manifest: DatasetManifest, columns=None, predicate: pl.Expr | None = None) -> pl.DataFrame:
        return self._reader.load(manifest, columns, predicate)

    def clear_cache(self) -> None:
        self._reader.clear_cache()
