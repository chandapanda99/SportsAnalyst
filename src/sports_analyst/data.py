from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
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
}
SUPPORTED_DATASETS = tuple(SOURCE_TEMPLATES)


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

    def sync(self, seasons: list[int], datasets: list[str] | None = None) -> list[DatasetManifest]:
        selected = list(dict.fromkeys(datasets or ["play_by_play"]))
        unknown = sorted(set(selected) - set(SUPPORTED_DATASETS))
        if unknown:
            raise ValueError(f"unsupported nflverse datasets: {unknown}")
        manifests = []
        for season in sorted(set(seasons)):
            for dataset in selected:
                frame = self._load_remote(nfl, dataset, season)
                path = self.settings.raw_dir / f"{dataset}_{season}.parquet"
                frame.write_parquet(path)
                manifests.append(self.manifest_for(path, season, frame, dataset))
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
        }
        return loaders[dataset]()

    def register_local(self, path: Path, season: int) -> DatasetManifest:
        frame = pl.read_parquet(path)
        target = self.settings.raw_dir / f"play_by_play_{season}.parquet"
        if path.resolve() != target.resolve():
            frame.write_parquet(target)
        return self.manifest_for(target, season, frame, "play_by_play")

    def manifest_for(self, path: Path, season: int, frame: pl.DataFrame | None = None, dataset: str = "play_by_play") -> DatasetManifest:
        frame = frame if frame is not None else pl.read_parquet(path)
        checksum = sha256_file(path)
        payload = {"dataset": dataset, "season": season, "sha256": checksum, "rows": frame.height, "columns": frame.columns}
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
            row_count=frame.height,
            columns=frame.columns,
            package_version=package_version,
            local_path=str(path.resolve()),
        )

    def load(self, manifest: DatasetManifest) -> pl.DataFrame:
        path = Path(manifest.local_path).resolve()
        if self.settings.raw_dir.resolve() not in path.parents:
            raise ValueError("dataset path is outside the managed data directory")
        if sha256_file(path) != manifest.sha256:
            raise ValueError(f"dataset checksum changed: {manifest.manifest_id}")
        return pl.read_parquet(path)
