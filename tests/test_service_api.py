from pathlib import Path

from fastapi.testclient import TestClient

from sports_analyst.api import create_app
from sports_analyst.config import Settings
from sports_analyst.models import AnalysisRequest, AnalysisScope
from sports_analyst.service import AnalystApplication


def test_full_deterministic_investigation(tmp_path: Path, pbp_pair) -> None:
    settings = Settings(data_dir=tmp_path, foundry_endpoint="")
    application = AnalystApplication(settings)
    for season, frame in pbp_pair.items():
        source = tmp_path / f"source-{season}.parquet"
        frame.write_parquet(source)
        application.store.save_manifest(application.connector.register_local(source, season))
    request = AnalysisRequest(
        question="Why did KC passing efficiency decline?",
        scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025),
    )
    bundle = application.investigate(request)
    assert bundle.fallback_used
    assert bundle.claims
    assert (tmp_path / "investigations" / bundle.run.investigation_id / "report.html").exists()
    assert all(claim.evidence_ids for claim in bundle.claims)

    client = TestClient(create_app(application))
    assert client.get("/api/capabilities").json()["custom_analysis"] is False
    assert client.get(f"/api/investigations/{bundle.run.investigation_id}").status_code == 200
    evidence_id = bundle.claims[0].evidence_ids[0]
    assert client.get(f"/api/investigations/{bundle.run.investigation_id}/evidence/{evidence_id}").status_code == 200
