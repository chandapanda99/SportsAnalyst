"""Crucial provider isolation, restoration, provenance, and resolution contracts."""
import json

import polars as pl
import pytest
from fastapi.testclient import TestClient
from test_cfb import DurableMemory

from sports_analyst.api import create_app
from sports_analyst.application.service import AnalystApplication
from sports_analyst.config import Settings
from sports_analyst.datasets.cfb_provenance import with_source_provenance
from sports_analyst.datasets.cfb_source_audit import audit_game
from sports_analyst.datasets.providers import FieldObservation, align_plays, resolve_fields
from sports_analyst.models import DatasetManifest
from sports_analyst.storage.local import LocalStore


@pytest.mark.parametrize("durable", [False, True])
def test_provider_snapshots_preserve_legacy_isolate_versions_restore_and_clear(tmp_path, durable):
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    persistence = DurableMemory() if durable else None
    store = LocalStore(settings, persistence)
    manifests = []
    for provider, version in (("primary", "1"), ("espn", "1"), ("ncaa", "1"), ("ncaa", "2")):
        branch = "raw/cfb" if provider == "primary" else f"raw/cfb/providers/{provider}/{version}"
        path = settings.data_dir / branch / "partitions/team/1/2025/recorded_plays.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({"game_id": ["401754374"], "value": [len(manifests)]}).write_parquet(path)
        manifest = DatasetManifest(manifest_id=f"dataset-{provider}-{version}", sport="cfb", season=2025,
            provider_id=provider, processing_version=version, partition_key="team:1", dataset="recorded_plays",
            source_url="https://example.test", sha256=provider + version, row_count=1, columns=["game_id", "value"],
            package_version="test", local_path=str(path))
        if provider == "primary":
            # Simulate a pre-migration record without the new fields.
            old = manifest.model_dump(mode="json", exclude={"provider_id", "processing_version"})
            manifest = DatasetManifest.model_validate(old)
        store.save_manifest(manifest)
        manifests.append(manifest)
    assert len(store.manifests(sport="cfb")) == 1  # Existing analysis sees only its primary channel.
    assert len(store.manifests(sport="cfb", provider_id=None, processing_version=None)) == 4
    restored = (LocalStore(Settings(_env_file=None, data_dir=tmp_path / "replica"), persistence)
                if durable else LocalStore(settings))
    for item in manifests:
        found = restored.manifest_for_season(2025, "recorded_plays", "cfb", partition_key="team:1",
                                            provider_id=item.provider_id, processing_version=item.processing_version)
        assert found.manifest_id == item.manifest_id
        assert restored.materialize_manifest(found).local_path
    assert len(restored.manifests(provider_id=None, processing_version=None)) == 4
    assert "providers" not in store._dataset_metadata_key(manifests[0])
    assert store._dataset_metadata_key(manifests[2]) != store._dataset_metadata_key(manifests[3])
    collision = manifests[2].model_copy(update={"manifest_id": manifests[0].manifest_id})
    with pytest.raises(ValueError, match="different provider scope"):
        store.save_manifest(collision)
    assert restored.clear_datasets("cfb") == 4
    assert restored.manifests(provider_id=None, processing_version=None) == []
    if durable:
        assert not any(key.startswith("raw/cfb/") for key in persistence.objects)


def test_resolution_preserves_conflicts_zero_false_and_rejects_unverified_alignment_and_models():
    def observation(provider, field, value, method="recorded", model_id=None, record="play-1"):
        return FieldObservation(provider_id=provider, source_record_id=record, source_url="https://example.test/play",
                                processing_version="1", field=field, value=value, method=method, model_id=model_id)
    result = resolve_fields([
        observation("espn", "yards", 0), observation("ncaa", "yards", 1),
        observation("ncaa", "formation", "Shotgun", "text_parsed"),
        observation("espn", "no_play", False), observation("espn", "lineup", "22 players", "illustrative"),
        observation("cfbd", "epa", .3, "model_derived", "unmatched-model"),
        observation("ncaa", "ambiguous", "A"), observation("ncaa", "ambiguous", "B", record="play-2"),
    ], ("espn", "ncaa", "cfbd"), model_id="verified-model")
    assert result["values"] == {"yards": 0, "formation": "Shotgun", "no_play": False}
    assert set(result["conflicts"]) == {"yards", "ambiguous"}
    assert set(result["rejected"]) == {"epa", "lineup"}
    play = dict(id="1", quarter=1, clock="12:00", team_id="194", down=1, distance=10,
                yards_to_goal=75, play_type="rush", yards_gained=3)
    other = {**play, "id": "99"}
    assert align_plays([play], [other], game_verified=False)["matches"] == {}
    assert align_plays([play], [{**other, "clock": None}], game_verified=True)["matches"] == {}
    assert align_plays([play], [other, {**other, "id": "100"}], game_verified=True)["matches"] == {}
    assert align_plays([play], [other], game_verified=True)["matches"] == {"1": "99"}
    assert align_plays([play, {**play, "clock": "11:00"}], [other], game_verified=True)["matches"] == {}


def test_source_catalog_and_cfb_evidence_provenance_are_explicit_without_provider_imports(tmp_path):
    app = AnalystApplication(Settings(_env_file=None, data_dir=tmp_path), analysis_runtime=False)
    client = TestClient(create_app(app))
    sources = client.get("/api/data-sources?sport=cfb").json()
    assert {row["provider_id"] for row in sources} == {"espn", "ncaa", "cfbd"}
    assert [row["provider_id"] for row in sources if row["automatic"]] == ["espn"]
    assert client.get("/api/data-sources?sport=unknown").status_code == 400
    row = with_source_provenance({"id": "1", "game_id": "401754374", "yards_gained": 0,
                                  "formation": "Shotgun", "no_play": False, "epa": 0.0}, "test")
    provenance = json.loads(row["source_provenance_json"])["provenance"]
    assert provenance["yards_gained"]["method"] == "recorded"
    assert provenance["formation"]["method"] == "text_parsed"
    assert provenance["epa"]["method"] == "model_derived"
    assert row["no_play"] is False and row["epa"] == 0.0
    assert all("value" not in metadata for metadata in provenance.values())


def test_bounded_game_audit_checks_crosswalk_and_reports_unknown_context_without_false_coverage_claims():
    ncaa = {"contest_id": "1", "espn_game_id": "2", "season": 2025, "academic_year": 2026,
            "teams": [{"team": "Team A", "espn_team_id": "10", "final": 0, "home_away": "home"},
                      {"team": "Team B", "espn_team_id": "20", "final": 7, "home_away": "away"}],
            "drives": [{"drive_number": 1, "period": 1}],
            "pbp": [{"drive_number": 1, "play_number": 1, "offense": "Team A", "clock": "12:00",
                     "down": 1, "distance": 10, "yard_line_side": "A", "yard_line_number": 25,
                     "play_type": "rush", "yards_gained": 3, "formation": "Shotgun"}]}
    summary = {"header": {"id": "2", "season": {"year": 2025}, "competitions": [{"competitors": [
        {"team": {"id": "10", "abbreviation": "A"}, "score": "0", "homeAway": "home"},
        {"team": {"id": "20", "abbreviation": "B"}, "score": "7", "homeAway": "away"}]}]}}
    plays = {"pageCount": 1, "items": [{"id": "100", "period": {"number": 1}, "clock": {"displayValue": "12:00"},
             "start": {"team": {"$ref": "https://sports.core.api.espn.com/teams/10"}, "down": 1,
                       "distance": 10, "yardsToEndzone": 75}, "type": {"text": "Rush"}, "statYardage": 3}]}

    def fetch(url):
        return ncaa if url.endswith(".gz") else summary if "/summary?" in url else plays

    report = audit_game("1", 2025, "FBS", "2", fetch)
    assert report["game_team_identity_verified"] and report["conservative_context_matches"] == 1
    assert report["automatic_merge_approved"] is False
    ncaa["pbp"][0]["clock"] = None
    report = audit_game("1", 2025, "FBS", "2", fetch)
    assert report["conservative_context_matches"] == 0 and report["unmatched_espn"] == 1
    ncaa["season"] = 2024
    assert audit_game("1", 2025, "FBS", "2", fetch)["game_team_identity_verified"] is False
