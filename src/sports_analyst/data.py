from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path

import polars as pl

from sports_analyst.config import Settings, get_settings
from sports_analyst.models import DatasetManifest, stable_id

SOURCE_TEMPLATE = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet"


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

    def sync(self, seasons: list[int]) -> list[DatasetManifest]:
        import nflreadpy as nfl

        manifests = []
        for season in sorted(set(seasons)):
            frame = nfl.load_pbp([season])
            path = self.settings.raw_dir / f"play_by_play_{season}.parquet"
            frame.write_parquet(path)
            manifests.append(self.manifest_for(path, season, frame))
        return manifests

    def register_local(self, path: Path, season: int) -> DatasetManifest:
        frame = pl.read_parquet(path)
        target = self.settings.raw_dir / f"play_by_play_{season}.parquet"
        if path.resolve() != target.resolve():
            frame.write_parquet(target)
        return self.manifest_for(target, season, frame)

    def manifest_for(self, path: Path, season: int, frame: pl.DataFrame | None = None) -> DatasetManifest:
        frame = frame if frame is not None else pl.read_parquet(path)
        checksum = sha256_file(path)
        payload = {"season": season, "sha256": checksum, "rows": frame.height, "columns": frame.columns}
        try:
            package_version = importlib.metadata.version("nflreadpy")
        except importlib.metadata.PackageNotFoundError:
            package_version = "unknown"
        return DatasetManifest(
            manifest_id=stable_id("dataset", payload),
            season=season,
            source_url=SOURCE_TEMPLATE.format(season=season),
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
