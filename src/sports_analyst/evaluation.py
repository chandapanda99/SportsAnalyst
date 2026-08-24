from __future__ import annotations

from pydantic import BaseModel


class EvaluationCase(BaseModel):
    question: str
    expected_tools: list[str]
    expected_dimensions: list[str]


def evaluation_cases() -> list[EvaluationCase]:
    teams = ["KC", "BUF", "PHI", "SF", "DAL"]
    patterns = [
        ("Why did {team}'s passing efficiency decline?", ["epa_per_dropback", "success_rate", "sack_rate"]),
        ("What drove the change in {team}'s explosive passing?", ["explosive_pass_rate", "air_yards", "yards_after_catch"]),
        ("Did {team} improve because of situation mix or execution?", ["down", "offense_formation", "score_differential"]),
        ("How stable was {team}'s passing performance across the season?", ["week", "epa_per_dropback", "confidence_interval"]),
    ]
    return [
        EvaluationCase(
            question=pattern.format(team=team),
            expected_tools=[
                "validate_analysis_scope",
                "compare_time_windows",
                "analyze_weekly_trends",
                "rank_game_outliers",
                "benchmark_against_league",
                "analyze_situational_split",
                "decompose_metric_change",
                "adjust_for_opponents",
                "compare_play_mix",
                "identify_change_points",
                "build_player_week_dataset",
                "compare_player_usage",
                "analyze_position_group_availability",
                "analyze_lineup_continuity",
                "decompose_lineup_continuity",
                "analyze_qb_receiver_pairs",
                "find_representative_plays",
            ],
            expected_dimensions=dimensions,
        )
        for team in teams
        for pattern, dimensions in patterns
    ]
