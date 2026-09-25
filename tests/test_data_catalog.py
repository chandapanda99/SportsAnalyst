from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import polars as pl

from sports_analyst.config import Settings
from sports_analyst.data import NFLVerseConnector
from sports_analyst.models import AnalysisPlan, AnalysisScope, InvestigationBundle, InvestigationRun, RunStatus
from sports_analyst.storage import LocalStore
from sports_analyst.sync_service import run_dataset_sync


class MemoryPersistence:
    durable = True

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.versions: dict[str, int] = {}
        self.list_calls: list[str] = []

    def list_keys(self, prefix: str) -> list[str]:
        self.list_calls.append(prefix)
        return sorted(key for key in self.objects if key.startswith(prefix))

    def read_bytes(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def read_versioned_bytes(self, key: str) -> tuple[bytes | None, str | None]:
        return self.objects.get(key), str(self.versions[key]) if key in self.versions else None

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
        self.versions[key] = self.versions.get(key, 0) + 1

    def write_bytes_if_version(
        self, key: str, payload: bytes, version: str | None, content_type: str = "application/octet-stream"
    ) -> bool:
        current = str(self.versions[key]) if key in self.versions else None
        if current != version:
            return False
        self.write_bytes(key, payload, content_type)
        return True

    def upload_file(self, key: str, source: Path) -> None:
        self.objects[key] = source.read_bytes()

    def delete_prefix(self, prefix: str) -> None:
        for key in [key for key in self.objects if key.startswith(prefix)]:
            del self.objects[key]
            self.versions.pop(key, None)


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


def test_large_nfl_syncs_stream_parquet_without_loading_the_remote_frame(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(data_dir=tmp_path, foundry_endpoint="")
    connector = NFLVerseConnector(settings)
    source = tmp_path / "source.parquet"
    pl.DataFrame({"season": [2025, 2025], "posteam": ["KC", "BUF"], "epa": [0.2, -0.1]}).write_parquet(source)

    def copy_source(_url: str, destination: Path) -> None:
        destination.write_bytes(source.read_bytes())

    monkeypatch.setattr(connector, "_download_parquet", copy_source)
    monkeypatch.setattr(connector, "_load_remote", lambda *_args: (_ for _ in ()).throw(AssertionError("must not load play-by-play")))

    manifests = connector.sync([2025], ["play_by_play", "weekly_rosters"])

    assert manifests[0].row_count == 2
    assert manifests[0].columns == ["season", "posteam", "epa"]
    assert Path(manifests[0].local_path).read_bytes() == source.read_bytes()
    assert manifests[1].dataset == "weekly_rosters"


def test_current_nfl_season_is_refreshed_while_past_seasons_are_reused() -> None:
    connector = MagicMock()
    connector.sync.return_value = []
    store = MagicMock()
    store.manifests.return_value = [
        SimpleNamespace(dataset="play_by_play", season=2025),
        SimpleNamespace(dataset="play_by_play", season=2026),
    ]
    application = SimpleNamespace(connectors={"nfl": connector}, store=store, events=MagicMock())

    run_dataset_sync(application, [2025, 2026], "test-sync", ["play_by_play"], "nfl")

    assert connector.sync.call_args.kwargs["skip"] == {("play_by_play", 2025)}


def test_durable_store_restores_metadata_and_lazily_materializes_artifacts(tmp_path: Path) -> None:
    persistence = MemoryPersistence()
    stale_settings = Settings(data_dir=tmp_path / "stale-replica", foundry_endpoint="")
    stale_store = LocalStore(stale_settings, persistence)
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
    assert "metadata/catalog/datasets.json" in persistence.objects
    assert "metadata/catalog/investigations.json" in persistence.objects
    assert "metadata/catalog/version.json" in persistence.objects

    # This store represents a warm replica whose local catalog was initialized
    # before another replica committed the dataset and investigation to storage.
    stale_manifest = stale_store.manifest_for_season(2025)
    assert Path(stale_store.materialize_manifest(stale_manifest).local_path).exists()
    assert stale_store.get_investigation(investigation_id).summary == "Efficiency improved."

    restored_settings = Settings(data_dir=tmp_path / "restored", foundry_endpoint="")
    persistence.list_calls.clear()
    restored_store = LocalStore(restored_settings, persistence)
    assert not persistence.list_calls  # Compact catalogs avoid per-record R2 listings.
    restored_manifest = restored_store.manifest_for_season(2025)
    assert not Path(restored_manifest.local_path).exists()
    materialized = restored_store.materialize_manifest(restored_manifest)
    assert NFLVerseConnector(restored_settings).load(materialized).get_column("epa").to_list() == [0.2]
    assert restored_store.get_investigation(investigation_id).summary == "Efficiency improved."
    assert restored_store.export_path(investigation_id, "html").exists()

    restored_store.delete_investigation(investigation_id)
    reloaded_store = LocalStore(Settings(data_dir=tmp_path / "reloaded", foundry_endpoint=""), persistence)
    assert reloaded_store.list_investigations() == []
