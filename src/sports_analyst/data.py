from __future__ import annotations

import hashlib
import importlib.metadata
import shutil
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from threading import RLock

import nflreadpy as nfl
import polars as pl

from sports_analyst.config import Settings, get_settings
from sports_analyst.models import DatasetManifest, stable_id

SOURCE_TEMPLATES = {
    "play_by_play": "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet",
    "player_stats": "https://github.com/nflverse/nflverse-data/releases/tag/player_stats",
    "rosters": "https://github.com/nflverse/nflverse-data/releases/tag/rosters",
    "injuries": "https://github.com/nflverse/nflverse-data/releases/tag/injuries",
    "schedules": "https://github.com/nflverse/nflverse-data/releases/tag/schedules",
    "snap_counts": "https://github.com/nflverse/nflverse-data/releases/tag/snap_counts",
    "nextgen_passing": "https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats",
    "participation": "https://github.com/nflverse/nflverse-data/releases/tag/pbp_participation",
    "weekly_rosters": "https://github.com/nflverse/nflverse-data/releases/tag/weekly_rosters",
    "depth_charts": "https://github.com/nflverse/nflverse-data/releases/tag/depth_charts",
    "nextgen_receiving": "https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats",
    "nextgen_rushing": "https://github.com/nflverse/nflverse-data/releases/tag/nextgen_stats",
    "ftn_charting": "https://github.com/nflverse/nflverse-data/releases/tag/ftn_charting",
    "pfr_passing": "https://github.com/nflverse/nflverse-data/releases/tag/pfr_advstats",
    "pfr_rushing": "https://github.com/nflverse/nflverse-data/releases/tag/pfr_advstats",
    "pfr_receiving": "https://github.com/nflverse/nflverse-data/releases/tag/pfr_advstats",
    "pfr_defense": "https://github.com/nflverse/nflverse-data/releases/tag/pfr_advstats",
    "players": "https://github.com/nflverse/nflverse-data/releases/tag/players",
    "teams": "https://github.com/nflverse/nflverse-data/releases/tag/teams",
}
SUPPORTED_DATASETS = tuple(SOURCE_TEMPLATES)
REFERENCE_DATASETS = {"players", "teams"}
DIRECT_PARQUET_PATHS = {
    "play_by_play": "pbp/play_by_play_{season}.parquet",
    "player_stats": "stats_player/stats_player_week_{season}.parquet",
    "rosters": "rosters/roster_{season}.parquet",
    "injuries": "injuries/injuries_{season}.parquet",
    "snap_counts": "snap_counts/snap_counts_{season}.parquet",
    "participation": "pbp_participation/pbp_participation_{season}.parquet",
    "weekly_rosters": "weekly_rosters/roster_weekly_{season}.parquet",
    "depth_charts": "depth_charts/depth_charts_{season}.parquet",
    "ftn_charting": "ftn_charting/ftn_charting_{season}.parquet",
    "pfr_passing": "pfr_advstats/advstats_week_pass_{season}.parquet",
    "pfr_rushing": "pfr_advstats/advstats_week_rush_{season}.parquet",
    "pfr_receiving": "pfr_advstats/advstats_week_rec_{season}.parquet",
    "pfr_defense": "pfr_advstats/advstats_week_def_{season}.parquet",
}
NFLVERSE_RELEASE_BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download/"
DATASET_MIN_SEASONS = {
    "play_by_play": 1999,
    "player_stats": 1999,
    "rosters": 1920,
    "injuries": 2009,
    "schedules": 1920,
    "snap_counts": 2012,
    "nextgen_passing": 2016,
    "participation": 2016,
    "weekly_rosters": 2002,
    "depth_charts": 2001,
    "nextgen_receiving": 2016,
    "nextgen_rushing": 2016,
    "ftn_charting": 2022,
    "pfr_passing": 2018,
    "pfr_rushing": 2018,
    "pfr_receiving": 2018,
    "pfr_defense": 2018,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class NFLVerseConnector:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        self._cache: OrderedDict[tuple[str, tuple[str, ...] | None], pl.DataFrame] = OrderedDict()
        self._cache_bytes = 0
        self._verified_files: set[tuple[str, int, int]] = set()
        self._cache_lock = RLock()

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
            if dataset not in REFERENCE_DATASETS and season >= DATASET_MIN_SEASONS[dataset]
        )
        if not work:
            raise ValueError("none of the selected datasets are available for the selected seasons")
        skipped = skip or set()
        manifests = []
        for index, (season, dataset) in enumerate(work):
            if (dataset, season) in skipped:
                if progress_callback:
                    progress_callback("available", dataset, season, index + 1, len(work))
                continue
            if progress_callback:
                progress_callback("downloading", dataset, season, index, len(work))
            path = self.settings.raw_dir / (f"{dataset}.parquet" if season == 0 else f"{dataset}_{season}.parquet")
            frame: pl.DataFrame | None = None
            if release_path := DIRECT_PARQUET_PATHS.get(dataset):
                self._download_parquet(f"{NFLVERSE_RELEASE_BASE_URL}{release_path.format(season=season)}", path)
            else:
                frame = self._load_remote(nfl, dataset, season)
                if progress_callback:
                    progress_callback("processing", dataset, season, index, len(work))
                frame.write_parquet(path)
            manifest = self.manifest_for(path, season, frame, dataset)
            manifests.append(manifest)
            if progress_callback:
                progress_callback("downloaded", dataset, season, index + 1, len(work))
            if manifest_callback:
                manifest_callback(manifest)
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

    def load(
        self,
        manifest: DatasetManifest,
        columns: set[str] | list[str] | tuple[str, ...] | None = None,
        predicate: pl.Expr | None = None,
    ) -> pl.DataFrame:
        path = Path(manifest.local_path).resolve()
        if self.settings.raw_dir.resolve() not in path.parents:
            raise ValueError("dataset path is outside the managed data directory")
        self._verify(manifest, path)
        requested = set(columns) if columns is not None else None
        selected = tuple(column for column in manifest.columns if requested is not None and column in requested) or None
        cache_key = (manifest.manifest_id, selected)
        if predicate is None:
            with self._cache_lock:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    self._cache.move_to_end(cache_key)
                    return cached
        query = pl.scan_parquet(path)
        if predicate is not None:
            query = query.filter(predicate)
        if selected is not None:
            query = query.select(selected)
        frame = query.collect()
        if predicate is None:
            self._cache_frame(cache_key, frame)
        return frame

    def _verify(self, manifest: DatasetManifest, path: Path) -> None:
        stat = path.stat()
        signature = (manifest.manifest_id, stat.st_size, stat.st_mtime_ns)
        with self._cache_lock:
            if signature in self._verified_files:
                return
        metadata_changed = (
            manifest.file_size is not None
            and manifest.modified_ns is not None
            and (manifest.file_size != stat.st_size or manifest.modified_ns != stat.st_mtime_ns)
        )
        needs_checksum = self.settings.verify_dataset_checksums_on_load or metadata_changed or manifest.file_size is None
        if needs_checksum and sha256_file(path) != manifest.sha256:
            raise ValueError(f"dataset checksum changed: {manifest.manifest_id}")
        with self._cache_lock:
            self._verified_files.add(signature)

    def _cache_frame(self, key: tuple[str, tuple[str, ...] | None], frame: pl.DataFrame) -> None:
        limit = self.settings.dataset_cache_mb * 1024 * 1024
        if limit <= 0:
            return
        size = frame.estimated_size()
        if size > limit:
            return
        with self._cache_lock:
            previous = self._cache.pop(key, None)
            if previous is not None:
                self._cache_bytes -= previous.estimated_size()
            self._cache[key] = frame
            self._cache_bytes += size
            while self._cache and self._cache_bytes > limit:
                _old_key, old_frame = self._cache.popitem(last=False)
                self._cache_bytes -= old_frame.estimated_size()

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()
            self._cache_bytes = 0
            self._verified_files.clear()
