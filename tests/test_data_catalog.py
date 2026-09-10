from pathlib import Path

import polars as pl

from sports_analyst.config import Settings
from sports_analyst.data import NFLVerseConnector
from sports_analyst.models import AnalysisPlan, AnalysisScope, InvestigationBundle, InvestigationRun, RunStatus
from sports_analyst.storage import LocalStore


class MemoryPersistence:
    durable = True

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))

    def read_bytes(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def download_file(self, key: str, destination: Path) -> bool:
        payload = self.objects.get(key)
        if payload is None:
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return True

    def write_bytes(self, key: str, payload: bytes, content_type: str = "application/octet-stream") -> None:
        del content_type
        self.objects[key] = payload

    def upload_file(self, key: str, source: Path) -> None:
        self.objects[key] = source.read_bytes()

    def delete_prefix(self, prefix: str) -> None:
        for key in [key for key in self.objects if key.startswith(prefix)]:
            del self.objects[key]


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


def test_durable_store_restores_metadata_and_lazily_materializes_artifacts(tmp_path: Path) -> None:
    persistence = MemoryPersistence()
    source_settings = Settings(data_dir=tmp_path / "source", foundry_endpoint="")
    source_connector = NFLVerseConnector(source_settings)
    source_store = LocalStore(source_settings, persistence)
    frame = pl.DataFrame({"season": [2025], "posteam": ["KC"], "epa": [0.2]})
    dataset_path = source_settings.raw_dir / "play_by_play_2025.parquet"
    frame.write_parquet(dataset_path)
    manifest = source_connector.manifest_for(dataset_path, 2025, frame)
    source_store.save_manifest(manifest)

    scope = AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025)
    investigation_id = "investigation-cloud-restore"
    bundle = InvestigationBundle(
        run=InvestigationRun(
            investigation_id=investigation_id,
            question="Did efficiency change?",
            scope=scope,
            status=RunStatus.COMPLETED,
        ),
        plan=AnalysisPlan(plan_id="plan-cloud-restore", question="Did efficiency change?", scope=scope, calls=[]),
        summary="Efficiency improved.",
        claims=[],
        aggregate_evidence=[],
        play_evidence=[],
        charts=[],
        executions=[],
        dataset_manifests=[manifest],
        methodological_caveats=[],
        fallback_used=True,
    )
    source_store.save_investigation(bundle)

    restored_settings = Settings(data_dir=tmp_path / "restored", foundry_endpoint="")
    restored_store = LocalStore(restored_settings, persistence)
    restored_manifest = restored_store.manifest_for_season(2025)
    assert not Path(restored_manifest.local_path).exists()
    materialized = restored_store.materialize_manifest(restored_manifest)
    assert NFLVerseConnector(restored_settings).load(materialized).get_column("epa").to_list() == [0.2]
    assert restored_store.get_investigation(investigation_id).summary == "Efficiency improved."
    assert restored_store.export_path(investigation_id, "html").exists()

    restored_store.delete_investigation(investigation_id)
    reloaded_store = LocalStore(Settings(data_dir=tmp_path / "reloaded", foundry_endpoint=""), persistence)
    assert reloaded_store.list_investigations() == []


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
