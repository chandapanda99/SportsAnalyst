from pathlib import Path

import polars as pl

from sports_analyst.config import Settings
from sports_analyst.data import NFLVerseConnector
from sports_analyst.storage import LocalStore


def test_dataset_catalog_distinguishes_packages_within_a_season(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, foundry_endpoint="")
    connector = NFLVerseConnector(settings)
    store = LocalStore(settings)
    frames = {
        "play_by_play": pl.DataFrame({"season": [2025], "posteam": ["KC"]}),
        "rosters": pl.DataFrame({"season": [2025], "team": ["KC"], "full_name": ["Test Player"]}),
    }
    manifests = []
    for dataset, frame in frames.items():
        path = settings.raw_dir / f"{dataset}_2025.parquet"
        frame.write_parquet(path)
        manifest = connector.manifest_for(path, 2025, frame, dataset)
        store.save_manifest(manifest)
        manifests.append(manifest)

    assert manifests[0].manifest_id != manifests[1].manifest_id
    assert store.manifest_for_season(2025, "play_by_play").dataset == "play_by_play"
    assert store.manifest_for_season(2025, "rosters").dataset == "rosters"
    assert len(store.manifests()) == 2
