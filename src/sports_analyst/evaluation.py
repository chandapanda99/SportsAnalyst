from __future__ import annotations

from pydantic import BaseModel


class EvaluationCase(BaseModel):
    sport: str = "nfl"
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
    nfl_cases = [
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
    nba_cases = [
        EvaluationCase(
            sport="nba",
            question="Which five-player units drove Detroit's net-rating change?",
            expected_tools=["compare_time_windows", "analyze_lineup_performance"],
            expected_dimensions=["players", "possessions", "net_rating", "returning_new_departed"],
        ),
        EvaluationCase(
            sport="nba",
            question="Did Boston improve through shot selection or shot making?",
            expected_tools=["compare_time_windows", "compare_shot_profiles", "rank_game_outliers"],
            expected_dimensions=["shot_zone", "attempt_share", "conversion", "game_variability"],
        ),
        EvaluationCase(
            sport="nba",
            question="How meaningful was this player's scoring change?",
            expected_tools=["compare_time_windows", "analyze_game_trends", "find_representative_possessions"],
            expected_dimensions=["games", "confidence_interval", "usage", "counterexample"],
        ),
        EvaluationCase(
            sport="nba",
            question="How did Denver's offense compare with the league after accounting for opponents?",
            expected_tools=["benchmark_against_league", "adjust_for_opponents"],
            expected_dimensions=["league_rank", "opponent_context", "offensive_rating"],
        ),
    ]
    return nfl_cases + nba_cases
