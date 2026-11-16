"""Season-range reports measure every season between the endpoints, in every sport that offers them."""

from __future__ import annotations

import polars as pl
import pytest

from sports_analyst.models import AnalysisRequest, DatasetManifest
from sports_analyst.plugins.cfb import CFBPlugin

SEASONS = (2022, 2023, 2024)


def _manifest(season):
    return DatasetManifest(manifest_id=f"schedules-{season}", sport="cfb", dataset="schedules", season=season, source_url="local",
                           sha256="0" * 64, row_count=1, columns=[], package_version="test", license="test", attribution="test",
                           local_path="local", file_size=1, modified_ns=1)


def test_college_football_season_range_measures_the_middle_seasons():
    schedules, stats = {}, {}
    for offset, season in enumerate(SEASONS):
        games = [f"{season}-{index}" for index in range(4)]
        schedules[season] = pl.DataFrame({
            "game_id": games, "completed": [True] * 4, "season_type": ["regular"] * 4, "week": [1, 2, 3, 4],
            "date": [f"{season}-09-0{index + 1}" for index in range(4)], "home_team_id": ["1"] * 4, "away_team_id": ["2"] * 4,
            "home_team_name": ["Home"] * 4, "away_team_name": ["Away"] * 4, "home_score": [20 + offset * 7] * 4, "away_score": [17] * 4})
        stats[season] = pl.DataFrame({"game_id": games, "team_id": ["1"] * 4, "third_down_conversions": [4 + offset] * 4,
                                      "third_down_attempts": [10] * 4})
    request = AnalysisRequest(sport="cfb", question="How did third downs develop over three seasons?", analysis_domain="offense",
                              subject={"type": "team", "id": "1"}, metrics=["third_down_rate", "points_per_game"],
                              scope={"team": "1", "baseline_season": 2022, "comparison_season": 2024, "comparison_design": "full_seasons", "season_type": "ALL"})
    result = CFBPlugin().analyze(request, schedules, {season: _manifest(season) for season in SEASONS}, {"team_stats": stats})
    for metric in ("third_down_rate", "points_per_game"):
        seasonal = {item.context["season"]: item for item in result.aggregate_evidence if item.metric == f"seasonal_{metric}"}
        assert set(seasonal) == set(SEASONS), metric
        assert seasonal[2023].label.startswith("2023 · ") and seasonal[2023].sample_size == 4
    middle = {item.metric: item.value for item in result.aggregate_evidence if item.context.get("season") == 2023}
    assert middle["seasonal_third_down_rate"] == pytest.approx(0.5) and middle["seasonal_points_per_game"] == pytest.approx(27)
    endpoint = next(item for item in result.aggregate_evidence if item.metric == "third_down_rate")
    first = next(item for item in result.aggregate_evidence if item.metric == "seasonal_third_down_rate" and item.context["season"] == 2022)
    assert first.value == endpoint.baseline_value  # endpoints reuse the comparison's own values
    assert any(item.tool == "analyze_season_trends" for item in result.executions)
    assert any(chart.title.startswith("Season-by-season") for chart in result.charts)
