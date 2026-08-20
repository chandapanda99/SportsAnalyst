from sports_analyst.models import AnalysisRequest, AnalysisScope, DatasetManifest
from sports_analyst.plugins.nfl import NFLPlugin


def manifest(season: int, columns: list[str]) -> DatasetManifest:
    return DatasetManifest(
        manifest_id=f"dataset-{season}", season=season, source_url="https://example.test", sha256="a" * 64,
        row_count=160, columns=columns, package_version="test", local_path=f"C:/data/{season}.parquet"
    )


def test_efficiency_diagnosis_is_deterministic_and_evidence_bound(pbp_pair) -> None:
    plugin = NFLPlugin()
    request = AnalysisRequest(
        question="Why did passing efficiency decline?",
        scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025),
    )
    manifests = {season: manifest(season, frame.columns) for season, frame in pbp_pair.items()}
    first = plugin.analyze(request, pbp_pair, manifests)
    second = plugin.analyze(request, pbp_pair, manifests)
    epa = next(item for item in first.aggregate_evidence if item.metric == "epa_per_dropback")
    assert epa.value == -0.1
    assert epa.sample_size == 160
    assert [item.evidence_id for item in first.aggregate_evidence] == [item.evidence_id for item in second.aggregate_evidence]
    assert len(first.play_evidence) == 5
    assert first.charts


def test_plan_uses_only_registered_tools() -> None:
    plugin = NFLPlugin()
    request = AnalysisRequest(question="Why?", scope=AnalysisScope(team="KC", baseline_season=2024, comparison_season=2025))
    plan = plugin.default_plan(request)
    registered = {tool.name for tool in plugin.tools()}
    assert {call.tool for call in plan.calls} <= registered
