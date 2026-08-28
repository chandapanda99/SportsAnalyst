from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
from collections import OrderedDict
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import NamedTuple

import polars as pl

from sports_analyst.config import Settings, get_settings
from sports_analyst.data import sha256_file
from sports_analyst.models import DatasetManifest, stable_id

logger = logging.getLogger(__name__)

NBA_ATTRIBUTION = "Data loaded through SportsDataverse from its published NBA data releases."
NBA_LICENSE = "See the source release metadata for the selected dataset."

class NBADatasetDefinition(NamedTuple):
    loader: str
    minimum: int
    release: str
    available_seasons: tuple[int, ...]


def _seasons(first: int, last: int) -> tuple[int, ...]:
    return tuple(range(first, last + 1))


# Reviewed against the published sportsdataverse-data assets on 2026-08-28.
# Only high-level release loaders belong in the sync UI; live endpoint wrappers
# and predictive/model helpers remain behind analysis tools.
NBA_DATASETS: dict[str, NBADatasetDefinition] = {
    "play_by_play": NBADatasetDefinition("load_nba_pbp", 2002, "espn_nba_pbp", _seasons(2002, 2026)),
    "schedules": NBADatasetDefinition("load_nba_schedule", 2002, "espn_nba_schedules", _seasons(2002, 2027)),
    "team_boxscores": NBADatasetDefinition("load_nba_team_boxscore", 2002, "espn_nba_team_boxscores", _seasons(2002, 2026)),
    "player_boxscores": NBADatasetDefinition("load_nba_player_boxscore", 2002, "espn_nba_player_boxscores", _seasons(2002, 2026)),
    "shots": NBADatasetDefinition("load_nba_shots", 2002, "espn_nba_shots", _seasons(2002, 2026)),
    "game_rosters": NBADatasetDefinition("load_nba_game_rosters", 2002, "espn_nba_game_rosters", _seasons(2002, 2026)),
    "rosters": NBADatasetDefinition("load_nba_rosters", 2025, "espn_nba_rosters", _seasons(2025, 2027)),
    "officials": NBADatasetDefinition("load_nba_officials", 2002, "espn_nba_officials", _seasons(2002, 2026)),
    "standings": NBADatasetDefinition("load_nba_standings", 2002, "espn_nba_standings", _seasons(2002, 2026)),
    "player_season_stats": NBADatasetDefinition(
        "load_nba_player_season_stats", 2002, "espn_nba_player_season_stats", _seasons(2002, 2026)
    ),
    "team_season_stats": NBADatasetDefinition(
        "load_nba_team_season_stats", 2002, "espn_nba_team_season_stats", _seasons(2002, 2026)
    ),
    "draft": NBADatasetDefinition("load_nba_draft", 2003, "espn_nba_draft", _seasons(2003, 2027)),
    "stats_schedules": NBADatasetDefinition("load_nba_stats_schedules", 1996, "nba_stats_schedules", _seasons(1996, 2026)),
    "stats_coaches": NBADatasetDefinition("load_nba_stats_coaches", 1997, "nba_stats_coaches", _seasons(1997, 2026)),
    "stats_game_rosters": NBADatasetDefinition(
        "load_nba_stats_game_rosters", 1997, "nba_stats_game_rosters", _seasons(1997, 2026)
    ),
    "lineups": NBADatasetDefinition("load_nba_stats_lineups", 2008, "nba_stats_lineups", _seasons(2008, 2026)),
    "stats_officials": NBADatasetDefinition("load_nba_stats_officials", 1997, "nba_stats_officials", _seasons(1997, 2026)),
    "stats_play_by_play": NBADatasetDefinition("load_nba_stats_pbp", 1996, "nba_stats_pbp", _seasons(1996, 2026)),
    "stats_player_boxscores": NBADatasetDefinition(
        "load_nba_stats_player_boxscores", 1997, "nba_stats_player_boxscores", _seasons(1997, 2026)
    ),
    "stats_player_game_logs": NBADatasetDefinition(
        "load_nba_stats_player_game_logs", 1997, "nba_stats_player_game_logs", _seasons(1997, 2026)
    ),
    "stats_player_season_stats": NBADatasetDefinition(
        "load_nba_stats_player_season_stats", 1997, "nba_stats_player_season_stats", _seasons(1997, 2026)
    ),
    "stats_rosters": NBADatasetDefinition("load_nba_stats_rosters", 1997, "nba_stats_rosters", _seasons(1997, 2026)),
    "stats_shots": NBADatasetDefinition("load_nba_stats_shots", 1997, "nba_stats_shots", _seasons(1997, 2026)),
    "stats_standings": NBADatasetDefinition("load_nba_stats_standings", 1997, "nba_stats_standings", _seasons(1997, 2026)),
    "stats_team_boxscores": NBADatasetDefinition(
        "load_nba_stats_team_boxscores", 1997, "nba_stats_team_boxscores", _seasons(1997, 2026)
    ),
    "stats_team_season_stats": NBADatasetDefinition(
        "load_nba_stats_team_season_stats", 1997, "nba_stats_team_season_stats", _seasons(1997, 2026)
    ),
    "player_crosswalk": NBADatasetDefinition("load_nba_player_crosswalk", 2026, "nba_crosswalk", _seasons(2026, 2027)),
    "schedule_crosswalk": NBADatasetDefinition("load_nba_schedule_crosswalk", 2026, "nba_crosswalk", _seasons(2026, 2027)),
    "team_crosswalk": NBADatasetDefinition("load_nba_team_crosswalk", 2026, "nba_crosswalk", _seasons(2026, 2027)),
    "player_core": NBADatasetDefinition("load_nba_player_core", 2002, "espn_nba_player_core", _seasons(2002, 2026)),
    "player_impact": NBADatasetDefinition("load_nba_player_impact", 1997, "nba_player_impact", _seasons(1997, 2026)),
}

# Loadable for saved/local investigations, but deliberately not syncable: the
# SportsDataverse loaders exist while their bulk release tags do not.
NBA_LOCAL_ONLY_DATASETS: dict[str, NBADatasetDefinition] = {
    "lineups_v3": NBADatasetDefinition("load_nba_stats_lineups_v3", 2025, "nba_stats_lineups_v3", ()),
    "stats_play_by_play_v3": NBADatasetDefinition("load_nba_stats_pbp_v3", 2025, "nba_stats_pbpv3", ()),
    "possessions_v3": NBADatasetDefinition("load_nba_stats_possessions_v3", 2025, "nba_stats_possessions_v3", ()),
}
NBA_ALL_DATASETS = {**NBA_DATASETS, **NBA_LOCAL_ONLY_DATASETS}

NBA_DEFAULT_DATASETS = ["play_by_play", "schedules", "team_boxscores", "player_boxscores"]


@lru_cache(maxsize=1)
def nba_live_transport_available() -> bool:
    """Return whether the optional NBA Stats transport is installed.

    Endpoint reachability is deliberately checked only when a live-backed tool
    is invoked; opening the app must never depend on a third-party service.
    """

    return importlib.util.find_spec("curl_cffi") is not None


class SportsDataverseNBAConnector:
    sport_id = "nba"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()
        self.data_dir = self.settings.data_dir / "raw" / self.sport_id
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cache: OrderedDict[tuple[str, tuple[str, ...] | None], pl.DataFrame] = OrderedDict()
        self._cache_bytes = 0
        self._verified_files: set[tuple[str, int, int]] = set()
        self._cache_lock = RLock()

    @staticmethod
    def _loader_registry() -> dict[str, Callable[..., object]]:
        try:
            from sportsdataverse.nba import nba_loaders
        except ImportError as error:  # pragma: no cover - exercised by deployment smoke tests
            raise RuntimeError("SportsDataverse is not installed; sync dependencies before using NBA data") from error
        return {dataset: getattr(nba_loaders, definition[0]) for dataset, definition in NBA_DATASETS.items()}

    def sync(self, seasons: list[int], datasets: list[str] | None = None) -> list[DatasetManifest]:
        selected = list(dict.fromkeys(datasets or NBA_DEFAULT_DATASETS))
        unknown = sorted(set(selected) - set(NBA_DATASETS))
        if unknown:
            raise ValueError(f"unsupported SportsDataverse NBA datasets: {unknown}")
        loaders = self._loader_registry()
        from sportsdataverse.errors import SeasonNotFoundError

        manifests: list[DatasetManifest] = []
        for season in sorted(set(seasons)):
            for dataset in selected:
                definition = NBA_DATASETS[dataset]
                if season not in definition.available_seasons:
                    continue
                try:
                    raw = loaders[dataset]([season], return_as_pandas=False)
                except SeasonNotFoundError as error:
                    # SportsDataverse's release catalog can lag its loader
                    # metadata. An unavailable optional season must not discard
                    # core datasets that loaded successfully in the same job.
                    logger.info(
                        "nba_dataset_season_unavailable dataset=%s season=%d reason=%s",
                        dataset,
                        season,
                        error,
                    )
                    continue
                frame = raw if isinstance(raw, pl.DataFrame) else pl.from_pandas(raw)
                if frame.is_empty():
                    continue
                frame = self.normalize(frame, season, dataset)
                path = self.data_dir / f"{dataset}_{season}.parquet"
                frame.write_parquet(path)
                manifests.append(self.manifest_for(path, season, frame, dataset))
        if not manifests:
            raise ValueError(
                "none of the selected NBA datasets are available for the selected seasons; "
                "choose a supported season or include a core dataset"
            )
        return manifests

    @staticmethod
    def normalize(frame: pl.DataFrame, season: int, dataset: str) -> pl.DataFrame:
        aliases: dict[str, tuple[str, ...]] = {
            "play_id": ("sequence_number", "game_play_number", "action_number", "action_id", "id"),
            "description": ("text", "short_description", "description"),
            "period": ("period", "period_number", "qtr"),
            "clock": ("clock_display_value", "time", "clock"),
            "player_id": ("athlete_id", "person_id"),
            "player_name": ("athlete_display_name", "athlete_name_1", "player_name", "display_name", "full_name", "player"),
            "team_abbreviation": ("team_tricode", "team_abbrev", "team_abbreviation"),
            "game_date": ("game_date", "date", "start_date"),
            "home_team_abbrev": ("home_team_abbrev", "home_abbreviation"),
            "away_team_abbrev": ("away_team_abbrev", "away_abbreviation"),
            "coordinate_x": ("coordinate_x", "coordinate_x_raw"),
            "coordinate_y": ("coordinate_y", "coordinate_y_raw"),
        }
        expressions: list[pl.Expr] = [pl.lit(season).cast(pl.Int32).alias("season")]
        for target, candidates in aliases.items():
            if target in frame.columns:
                continue
            source = next((candidate for candidate in candidates if candidate in frame.columns), None)
            if source:
                expressions.append(pl.col(source).alias(target))
        frame = frame.with_columns(expressions)
        if dataset == "play_by_play" and "team_abbreviation" not in frame.columns:
            required = {"team_id", "home_team_id", "away_team_id", "home_team_abbrev", "away_team_abbrev"}
            if required.issubset(frame.columns):
                frame = frame.with_columns(
                    pl.when(pl.col("team_id") == pl.col("home_team_id"))
                    .then(pl.col("home_team_abbrev"))
                    .when(pl.col("team_id") == pl.col("away_team_id"))
                    .then(pl.col("away_team_abbrev"))
                    .otherwise(None)
                    .alias("team_abbreviation")
                )
        id_columns = [column for column in frame.columns if column == "game_id" or column.endswith("_id")]
        if id_columns:
            frame = frame.with_columns([pl.col(column).cast(pl.String, strict=False) for column in id_columns])
        return frame

    def register_local(self, path: Path, season: int, dataset: str = "play_by_play") -> DatasetManifest:
        if dataset not in NBA_ALL_DATASETS:
            raise ValueError(f"unsupported SportsDataverse NBA dataset: {dataset}")
        frame = self.normalize(pl.read_parquet(path), season, dataset)
        target = self.data_dir / f"{dataset}_{season}.parquet"
        if path.resolve() != target.resolve():
            frame.write_parquet(target)
        return self.manifest_for(target, season, frame, dataset)

    def manifest_for(self, path: Path, season: int, frame: pl.DataFrame | None = None, dataset: str = "play_by_play") -> DatasetManifest:
        frame = frame if frame is not None else pl.read_parquet(path)
        checksum = sha256_file(path)
        stat = path.stat()
        _loader, _minimum, release, available_seasons = NBA_ALL_DATASETS[dataset]
        payload = {
            "sport": self.sport_id,
            "dataset": dataset,
            "season": season,
            "sha256": checksum,
            "rows": frame.height,
            "columns": frame.columns,
        }
        try:
            package_version = importlib.metadata.version("sportsdataverse")
        except importlib.metadata.PackageNotFoundError:
            package_version = "unknown"
        return DatasetManifest(
            manifest_id=stable_id("dataset", payload),
            sport=self.sport_id,
            dataset=dataset,
            season=season,
            source_url=(
                f"https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/{release}"
                if available_seasons
                else "https://py.sportsdataverse.org/docs/nba/"
            ),
            sha256=checksum,
            row_count=frame.height,
            columns=frame.columns,
            package_version=package_version,
            license=NBA_LICENSE,
            attribution=NBA_ATTRIBUTION,
            local_path=str(path.resolve()),
            file_size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )

    def load(self, manifest: DatasetManifest, columns: set[str] | list[str] | tuple[str, ...] | None = None) -> pl.DataFrame:
        if manifest.sport != self.sport_id:
            raise ValueError(f"cannot load {manifest.sport} data with the NBA connector")
        path = Path(manifest.local_path).resolve()
        if self.data_dir.resolve() not in path.parents:
            raise ValueError("dataset path is outside the managed data directory")
        self._verify(manifest, path)
        requested = set(columns) if columns is not None else None
        selected = tuple(column for column in manifest.columns if requested is not None and column in requested) or None
        cache_key = (manifest.manifest_id, selected)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                return cached
        query = pl.scan_parquet(path)
        if selected is not None:
            query = query.select(selected)
        frame = query.collect()
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
        if (self.settings.verify_dataset_checksums_on_load or metadata_changed or manifest.file_size is None) and (
                sha256_file(path) != manifest.sha256
        ):
            raise ValueError(f"dataset checksum changed: {manifest.manifest_id}")
        with self._cache_lock:
            self._verified_files.add(signature)

    def _cache_frame(self, key: tuple[str, tuple[str, ...] | None], frame: pl.DataFrame) -> None:
        limit = self.settings.dataset_cache_mb * 1024 * 1024
        size = frame.estimated_size()
        if limit <= 0 or size > limit:
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
