"""Verified, projected Parquet reads with a bounded runtime cache."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path
from threading import RLock

import polars as pl

from sports_analyst.config import Settings
from sports_analyst.models import DatasetManifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SnapshotCache:
    """Shared byte budget across all initialized sports in an application."""
    def __init__(self) -> None:
        self.frames: OrderedDict[tuple, pl.DataFrame] = OrderedDict()
        self.verified: OrderedDict[tuple, None] = OrderedDict()
        self.bytes = 0
        self.generation = 0
        self.lock = RLock()


class SnapshotReader:
    def __init__(self, settings: Settings, root: Path) -> None:
        self.settings, self.root = settings, root.resolve()
        self.cache = SnapshotCache()

    @staticmethod
    def _signature(path: Path) -> tuple:
        stat = path.stat()
        return (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def load(self, manifest: DatasetManifest, columns=None, predicate: pl.Expr | None = None) -> pl.DataFrame:
        path = Path(manifest.local_path).resolve()
        if self.root not in path.parents:
            raise ValueError("dataset path is outside the managed data directory")
        # Existing plugin contracts use an empty projection for their primary
        # schedule table; it has the same meaning as the default full read.
        requested = set(columns) if columns else None
        selected = None if requested is None else tuple(c for c in manifest.columns if c in requested)
        if selected == ():
            raise ValueError(f"No requested columns are recorded in {manifest.manifest_id}")
        signature = self._signature(path)
        identity = (manifest.manifest_id, manifest.sha256, signature)
        key = (*identity, selected)
        with self.cache.lock:
            generation = self.cache.generation
            verified = identity in self.cache.verified
        if not verified:
            metadata_changed = (manifest.file_size is not None and manifest.modified_ns is not None
                                and (manifest.file_size, manifest.modified_ns) != signature[1:3])
            if ((self.settings.verify_dataset_checksums_on_load or metadata_changed or manifest.file_size is None)
                    and sha256_file(path) != manifest.sha256):
                raise ValueError(f"dataset checksum changed: {manifest.manifest_id}")
            if self._signature(path) != signature:
                raise ValueError(f"dataset changed during verification: {manifest.manifest_id}")
            with self.cache.lock:
                if generation == self.cache.generation:
                    self.cache.verified[identity] = None
                    while len(self.cache.verified) > 512:
                        self.cache.verified.popitem(last=False)
        if predicate is None:
            with self.cache.lock:
                cached = self.cache.frames.get(key)
                if cached is not None:
                    self.cache.frames.move_to_end(key)
                    return cached.clone()
        query = pl.scan_parquet(path)
        if predicate is not None:
            query = query.filter(predicate)
        if selected is not None:
            query = query.select(selected)
        frame = query.collect()
        if self._signature(path) != signature:
            raise ValueError(f"dataset changed during read: {manifest.manifest_id}")
        size, limit = frame.estimated_size(), self.settings.dataset_cache_mb * 1024 * 1024
        if predicate is None and 0 < size <= limit:
            with self.cache.lock:
                if generation == self.cache.generation:
                    old = self.cache.frames.pop(key, None)
                    if old is not None:
                        self.cache.bytes -= old.estimated_size()
                    self.cache.frames[key] = frame.clone()
                    self.cache.bytes += size
                    while self.cache.bytes > limit:
                        _, old = self.cache.frames.popitem(last=False)
                        self.cache.bytes -= old.estimated_size()
        return frame

    def clear_cache(self) -> None:
        with self.cache.lock:
            self.cache.generation += 1
            self.cache.frames.clear()
            self.cache.verified.clear()
            self.cache.bytes = 0
