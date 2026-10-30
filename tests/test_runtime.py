"""Startup isolation and snapshot reuse across the supported sports."""
from concurrent.futures import ThreadPoolExecutor

import polars as pl
import pytest

from sports_analyst.application.service import AnalystApplication
from sports_analyst.config import Settings
from sports_analyst.datasets.snapshots import sha256_file
from sports_analyst.models import DatasetManifest


@pytest.mark.parametrize("sport", ["nfl", "nba", "soccer", "cfb"])
def test_snapshot_reads_preserve_scope_and_refresh_across_sports(tmp_path, sport):
    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, dataset_cache_mb=1,
                                     verify_dataset_checksums_on_load=True), analysis_runtime=False)
    assert not app.connectors.initialized_values()
    app.capabilities()
    app.clear_caches()
    assert not app.connectors.initialized_values()
    with ThreadPoolExecutor(max_workers=4) as pool:
        connectors = list(pool.map(lambda _: app.connectors[sport], range(8)))
    assert all(connector is connectors[0] for connector in connectors)
    assert len(app.connectors.initialized_values()) == 1
    connector = connectors[0]
    path = connector._reader.root / "runtime-test.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame({"id": [1, 2], "value": [10, 20]})
    frame.write_parquet(path)
    manifest = DatasetManifest(manifest_id=f"{sport}-runtime", sport=sport, dataset="play_by_play", season=2025,
                               competition="eng.1" if sport == "soccer" else None, source_url="synthetic-test",
                               sha256=sha256_file(path), row_count=2, columns=frame.columns,
                               package_version="test", local_path=str(path))
    loaded = connector.load(manifest)
    loaded.replace_column(1, pl.Series("value", [90, 90]))
    assert connector.load(manifest)["value"].to_list() == [10, 20]
    assert connector.load(manifest, ["id"]).columns == ["id"]
    assert connector.load(manifest, ["value"], predicate=pl.col("id") == 2)["value"].to_list() == [20]
    assert connector.load(manifest).height == 2
    assert connector.load(manifest, set()).height == 2  # CFB primary schedule contract.
    frame.with_columns(pl.col("value") + 1).write_parquet(path)
    refreshed = manifest.model_copy(update={"sha256": sha256_file(path)})
    assert connector.load(refreshed)["value"].to_list() == [11, 21]
    with pytest.raises(ValueError, match="checksum"):
        connector.load(manifest)
    with pytest.raises(ValueError, match="No requested columns"):
        connector.load(refreshed, ["unrecorded"])
    with pytest.raises(ValueError, match="outside"):
        connector.load(refreshed.model_copy(update={"local_path": str(tmp_path / "outside.parquet")}))
    app.clear_caches()
    assert not connector._reader.cache.frames


def test_sports_share_one_cache_budget_and_legacy_aliases(tmp_path):
    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path, dataset_cache_mb=1), analysis_runtime=False)
    for sport in ("nfl", "nba"):
        connector = app.connectors[sport]
        path = connector._reader.root / "large.parquet"
        frame = pl.DataFrame({"description": ["x" * 600_000]})
        frame.write_parquet(path)
        manifest = DatasetManifest(manifest_id=sport, sport=sport, dataset="play_by_play", season=2025,
                                   source_url="synthetic-test", sha256=sha256_file(path), row_count=1,
                                   columns=frame.columns, package_version="test", local_path=str(path))
        connector.load(manifest)
    cache = app.connector._reader.cache
    assert cache is app.connectors["nba"]._reader.cache
    assert cache.bytes <= 1024 * 1024 and len(cache.frames) == 1
    replacement = object()
    app.connector = replacement
    assert app.connectors["nfl"] is replacement
