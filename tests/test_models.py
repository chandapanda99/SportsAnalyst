import pytest
from pydantic import ValidationError

from sports_analyst.config import Settings
from sports_analyst.models import AnalysisScope, AnalysisWindow, CustomAnalysisRequest, DisabledCustomAnalysisRunner, RuntimeCapabilities


def test_scope_normalizes_team_and_rejects_same_season() -> None:
    scope = AnalysisScope(team="kc", baseline_season=2024, comparison_season=2025)
    assert scope.team == "KC"
    with pytest.raises(ValidationError):
        AnalysisScope(team="KC", baseline_season=2025, comparison_season=2025)

    same_season = AnalysisScope(
        team="KC",
        baseline=AnalysisWindow(season=2025, weeks=(1, 8)),
        comparison=AnalysisWindow(season=2025, weeks=(9, 18)),
    )
    assert same_season.baseline_season == same_season.comparison_season == 2025


def test_full_season_scope_expands_to_an_inclusive_range() -> None:
    scope = AnalysisScope(
        team="CHI",
        baseline_season=2022,
        comparison_season=2025,
        comparison_design="full_seasons",
    )
    assert scope.included_seasons == [2022, 2023, 2024, 2025]

    with pytest.raises(ValidationError):
        AnalysisScope(
            team="CHI",
            baseline_season=2025,
            comparison_season=2022,
            comparison_design="full_seasons",
        )


def test_custom_analysis_is_explicitly_disabled() -> None:
    result = DisabledCustomAnalysisRunner().execute(CustomAnalysisRequest(code="print('no')", input_manifest_ids=[]))
    assert not result.supported
    assert "not available" in result.message


def test_capabilities_default_to_no_custom_analysis() -> None:
    capabilities = RuntimeCapabilities(providers=["ollama"], configured_provider="ollama", model_configured=True)
    assert capabilities.custom_analysis is False


def test_settings_use_unprefixed_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen-test:8b")

    settings = Settings(_env_file=None)

    assert settings.model_provider == "ollama"
    assert settings.ollama_model == "qwen-test:8b"
