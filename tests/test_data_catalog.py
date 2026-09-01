from pathlib import Path

import polars as pl

from sports_analyst.config import Settings
from sports_analyst.data import NFLVerseConnector
from sports_analyst.storage import LocalStore


def test_resync_supersedes_the_previous_package_manifest(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, foundry_endpoint="")
    connector = NFLVerseConnector(settings)
    store = LocalStore(settings)
    path = settings.raw_dir / "play_by_play_2025.parquet"

    original = pl.DataFrame({"season": [2025], "posteam": ["KC"], "epa": [-0.1]})
    original.write_parquet(path)
    old_manifest = connector.manifest_for(path, 2025, original)
    store.save_manifest(old_manifest)

    refreshed = pl.DataFrame({"season": [2025], "posteam": ["KC"], "epa": [0.2]})
    refreshed.write_parquet(path)
    new_manifest = connector.manifest_for(path, 2025, refreshed)
    with store.connect(read_only=True) as polling_connection:
        polling_connection.execute("SELECT count(*) FROM datasets").fetchone()
        store.save_manifest(new_manifest)

    manifests = store.manifests("play_by_play")
    assert [manifest.manifest_id for manifest in manifests] == [new_manifest.manifest_id]
    assert connector.load(store.manifest_for_season(2025)).get_column("epa").to_list() == [0.2]


def test_extended_loaders_dispatch_to_the_expected_nflreadpy_variants() -> None:
    class FakeNFLReadPy:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def frame(self, name: str, detail: object = None) -> pl.DataFrame:
            self.calls.append((name, detail))
            return pl.DataFrame({"source": [name]})

        def load_participation(self, seasons):
            return self.frame("participation", seasons)

        def load_rosters_weekly(self, seasons):
            return self.frame("weekly_rosters", seasons)

        def load_depth_charts(self, seasons):
            return self.frame("depth_charts", seasons)

        def load_nextgen_stats(self, seasons, stat_type):
            return self.frame(f"nextgen_{stat_type}", seasons)

        def load_ftn_charting(self, seasons):
            return self.frame("ftn_charting", seasons)

        def load_pfr_advstats(self, seasons, stat_type, summary_level):
            return self.frame(f"pfr_{stat_type}", (seasons, summary_level))

        def load_players(self):
            return self.frame("players")

        def load_teams(self):
            return self.frame("teams")

    fake = FakeNFLReadPy()
    datasets = (
        "participation",
        "weekly_rosters",
        "depth_charts",
        "nextgen_receiving",
        "nextgen_rushing",
        "ftn_charting",
        "pfr_passing",
        "pfr_rushing",
        "pfr_receiving",
        "pfr_defense",
        "players",
        "teams",
    )
    for dataset in datasets:
        NFLVerseConnector._load_remote(fake, dataset, 2025)

    assert [name for name, _ in fake.calls] == [
        "participation",
        "weekly_rosters",
        "depth_charts",
        "nextgen_receiving",
        "nextgen_rushing",
        "ftn_charting",
        "pfr_pass",
        "pfr_rush",
        "pfr_rec",
        "pfr_def",
        "players",
        "teams",
    ]
