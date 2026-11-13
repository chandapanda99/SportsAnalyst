"""NBA analysis accuracy: franchise identity, opponent-aware possessions, splits, shots and evidence roles."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from sports_analyst.analysis.research import dictionary
from sports_analyst.models import AnalysisRequest, AnalysisScope, AnalysisSubject, AnalysisWindow, DatasetManifest
from sports_analyst.plugins.nba import NBAPlugin, _metric
from sports_analyst.plugins.nba_context import (
    filter_team,
    franchise_rows,
    rest_days,
    shot_attempts,
    shot_mix_accounting,
    with_opponents,
    zone_profile,
)

OFFSETS = [0, 1, 3, 4, 7, 8, 10, 13]  # Rest before games 1, 3 and 5 is zero days (back-to-backs).
GS, OPPONENTS = ("GS", "9"), [("BOS", "2"), ("LAL", "13")]
SHOOTER, BIG, RIVAL = "100", "200", "300"


def _game_id(season: int, index: int) -> str:
    return f"{season}{index:02d}"


def _box(season, index, team, opponent, venue, score, opponent_score, fgm, tpm, tov, ttov, orb, drb):
    return {
        "game_id": _game_id(season, index), "season": season, "season_type": 2,
        "game_date": date(season - 1, 11, 1) + timedelta(days=OFFSETS[index] if index < len(OFFSETS) else 40),
        "team_abbreviation": team[0], "team_id": team[1], "team_home_away": venue,
        "opponent_team_abbreviation": opponent[0], "opponent_team_id": opponent[1],
        "team_score": score, "opponent_team_score": opponent_score, "team_winner": score > opponent_score,
        "field_goals_made": fgm, "field_goals_attempted": 85, "three_point_field_goals_made": tpm,
        "three_point_field_goals_attempted": 35, "free_throws_attempted": 20, "offensive_rebounds": orb,
        "defensive_rebounds": drb, "total_rebounds": orb + drb, "assists": 25, "turnovers": tov, "team_turnovers": ttov,
        "total_turnovers": tov + ttov,
    }


def _team_box(season: int, opponent_fgm: int) -> pl.DataFrame:
    rows = []
    for index in range(8):
        opponent = OPPONENTS[index % 2]
        venue = "home" if index % 2 == 0 else "away"
        rows.append(_box(season, index, GS, opponent, venue, 110, 104, 41, 12, 12, 1, 10, 33))
        rows.append(_box(season, index, opponent, GS, "away" if venue == "home" else "home", 104, 110, opponent_fgm, 12, 14, 2, 9, 32))
    # An All-Star exhibition must never enter league ranks.
    rows.append(_box(season, 99, ("STARS", "31"), ("STRIPES", "32"), "home", 210, 200, 80, 30, 5, 0, 20, 40))
    rows.append(_box(season, 99, ("STRIPES", "32"), ("STARS", "31"), "away", 200, 210, 78, 28, 5, 0, 20, 40))
    return pl.DataFrame(rows)


def _schedule(season: int) -> pl.DataFrame:
    return pl.DataFrame({
        "game_id": [_game_id(season, index) for index in range(8)],
        "game_date": [date(season - 1, 11, 1) + timedelta(days=offset) for offset in OFFSETS],
        "season_type": [2] * 8, "notes_headline": [""] * 8,
    })


def _player_box(season: int) -> pl.DataFrame:
    rows = []
    for index in range(8):
        venue = "home" if index % 2 == 0 else "away"
        base = {"game_id": _game_id(season, index), "team_abbreviation": "GS", "home_away": venue,
                "opponent_team_abbreviation": OPPONENTS[index % 2][0],
                "game_date": date(season - 1, 11, 1) + timedelta(days=OFFSETS[index])}
        rows.append({**base, "player_id": SHOOTER, "points": 25, "minutes": 34.0, "did_not_play": False,
                     "field_goals_made": 9, "field_goals_attempted": 18, "three_point_field_goals_made": 3,
                     "three_point_field_goals_attempted": 8, "free_throws_attempted": 4, "rebounds": 4,
                     "offensive_rebounds": 1, "assists": 6, "turnovers": 3})
        played = index < 7
        rows.append({**base, "player_id": BIG, "points": 8 if played else None, "minutes": 30.0 if played else None,
                     "did_not_play": not played, "field_goals_made": 4 if played else None,
                     "field_goals_attempted": 7 if played else None, "three_point_field_goals_made": 0 if played else None,
                     "three_point_field_goals_attempted": 1 if played else None, "free_throws_attempted": 2 if played else None,
                     "rebounds": 9 if played else None, "offensive_rebounds": 2 if played else None,
                     "assists": 5 if played else None, "turnovers": 1 if played else None})
    return pl.DataFrame(rows)


def _play_by_play(season: int, layup_made: bool) -> pl.DataFrame:
    rows = []
    for index in range(8):
        home_is_gs = index % 2 == 0
        opponent = OPPONENTS[index % 2][0]
        home, away = ("GS", opponent) if home_is_gs else (opponent, "GS")
        score = {"GS": 0, opponent: 0}
        events = [
            # team, type, text, period, clock, made, value, x, y, athlete 1, athlete 2
            ("GS", "Jump Shot", "Shooter makes 26-foot three point jumper (Big assists)", 1, "11:00", True, 3, 5.0, 20.0, SHOOTER, BIG),
            ("GS", "Driving Layup Shot", f"Shooter {'makes' if layup_made else 'misses'} driving layup", 1, "10:30", layup_made, 2,
             25.0, 6.0, SHOOTER, None),
            ("GS", "Free Throw - 1 of 1", "Shooter makes free throw 1 of 1", 1, "10:30", True, 1, 25.0, 13.75, SHOOTER, None),
            ("GS", "Substitution", "Bench enters the game for Shooter", 1, "10:30", False, 0, None, None, SHOOTER, None),
            (opponent, "Jump Shot", "Rival makes 10-foot jumper", 4, "2:00", True, 2, 25.0, 15.0, RIVAL, None),
            (opponent, "Layup Shot", "Big blocks Rival 's 3-foot layup", 4, "1:50", False, 2, 25.0, 8.0, RIVAL, BIG),
            ("GS", "Defensive Rebound", "Big defensive rebound", 4, "1:48", False, 0, None, None, BIG, None),
            ("GS", "Jump Shot", "Shooter makes 12-foot jumper", 4, "1:30", True, 2, 25.0, 17.0, SHOOTER, None),
            ("GS", "Jump Shot", "Shooter misses 25-foot three point jumper", 4, "1:10", False, 3, 3.0, 10.0, SHOOTER, None),
        ]
        for number, (team, kind, text, period, clock, made, value, x, y, first, second) in enumerate(events, 1):
            shooting = value > 0
            score[team] += value if made else 0
            rows.append({
                "game_id": _game_id(season, index), "play_id": str(number), "description": text, "text": text,
                "type_text": kind, "period": period, "clock": clock, "team_abbreviation": team,
                "home_team_abbrev": home, "away_team_abbrev": away, "home_score": score[home], "away_score": score[away],
                "score_value": value if made else 0, "scoring_play": made, "shooting_play": shooting,
                "points_attempted": value if shooting else None, "coordinate_x_raw": x, "coordinate_y_raw": y,
                "athlete_id_1": int(first), "athlete_id_2": int(second) if second else None,
                "athlete_name_1": {"100": "Shooter", "200": "Big", "300": "Rival"}[first],
                "athlete_name_2": "Big" if second == BIG else None,
            })
    return pl.DataFrame(rows)


def _manifest(dataset: str, season: int) -> DatasetManifest:
    return DatasetManifest(manifest_id=f"{dataset}-{season}", sport="nba", dataset=dataset, season=season, source_url="local",
                           sha256="0" * 64, row_count=1, columns=[], package_version="test", license="test",
                           attribution="test", local_path="local", file_size=1, modified_ns=1)


def _data():
    supplemental = {
        "team_boxscores": {2025: _team_box(2025, 39), 2026: _team_box(2026, 42)},
        "player_boxscores": {2025: _player_box(2025), 2026: _player_box(2026)},
        "schedules": {2025: _schedule(2025), 2026: _schedule(2026)},
    }
    datasets = {2025: _play_by_play(2025, layup_made=False), 2026: _play_by_play(2026, layup_made=True)}
    return datasets, {season: _manifest("play_by_play", season) for season in datasets}, supplemental


def _request(subject: AnalysisSubject, domain: str, metrics=(), splits=()) -> AnalysisRequest:
    return AnalysisRequest(
        sport="nba", subject=subject, question="What changed between these seasons?", analysis_domain=domain,
        metrics=list(metrics), splits=list(splits),
        scope=AnalysisScope(team=subject.team_id or subject.id, baseline=AnalysisWindow(season=2025, segment="regular_season"),
                            comparison=AnalysisWindow(season=2026, segment="regular_season"), season_type="ALL",
                            comparison_design="season_segments"))


def test_espn_short_codes_resolve_to_franchises_and_exhibitions_are_excluded():
    box = _team_box(2025, 39)
    assert filter_team(box, "GSW").height == 8
    assert filter_team(pl.DataFrame({"team_abbreviation": ["UTAH", "NY", "WSH"]}), "UTA").height == 1
    assert set(franchise_rows(box)["team_abbreviation"].unique()) == {"GS", "BOS", "LAL"}
    frame = NBAPlugin._window_frame(_request(AnalysisSubject(type="team", id="GSW"), "offense"), 2025, "regular_season",
                                    _data()[2])
    assert frame.height == 8 and {"opp_field_goals_made", "opp_total_turnovers"} <= set(frame.columns)


def test_possessions_average_both_teams_and_count_team_turnovers():
    frame = filter_team(with_opponents(_team_box(2025, 39)), "GSW")
    own, opponent = 85 - 10 + 13 + 0.44 * 20, 85 - 9 + 16 + 0.44 * 20
    possessions = (own + opponent) / 2
    assert _metric(frame, "pace", "team") == pytest.approx(possessions)
    assert _metric(frame, "defensive_rating", "team") == pytest.approx(100 * 104 / possessions)
    assert _metric(frame, "net_rating", "team") == pytest.approx(100 * 6 / possessions)
    assert _metric(frame, "turnovers_per_game", "team") == 13
    assert _metric(frame, "opponent_effective_fg_pct", "team") == pytest.approx((39 + 6) / 85)
    assert _metric(frame, "forced_turnover_rate", "team") == pytest.approx(16 / possessions)
    assert _metric(frame, "defensive_rebound_pct", "team") == pytest.approx(33 / 42)
    assert _metric(frame, "offensive_rebound_pct", "team") == pytest.approx(10 / 42)
    assert _metric(frame, "opponent_free_throw_rate", "team") == pytest.approx(20 / 85)
    # A missing opponent row is not zero: four-factor metrics skip that game.
    partial = frame.with_columns(pl.when(pl.col("game_id") == "202500").then(None).otherwise(pl.col("opp_offensive_rebounds"))
                                 .alias("opp_offensive_rebounds"))
    assert _metric(partial, "defensive_rebound_pct", "team") == pytest.approx(33 / 42)


def test_rest_days_and_did_not_play_rows():
    rest = rest_days(_team_box(2025, 39)).filter(pl.col("_team") == "GSW").sort("game_id")
    assert rest["_split_rest"].to_list() == [None, "0 days (back-to-back)", "1 day", "0 days (back-to-back)", "2+ days",
                                             "0 days (back-to-back)", "1 day", "2+ days"]
    request = _request(AnalysisSubject(type="player", id=BIG, team_id="GSW"), "scoring")
    frame = NBAPlugin._window_frame(request, 2025, "regular_season", _data()[2])
    assert frame.height == 7
    assert _metric(frame, "points_per_game", "player") == 8


def test_shot_attempts_exclude_free_throws_and_credit_only_the_shooter():
    pbp = _play_by_play(2025, layup_made=False)
    shooter = shot_attempts(pbp, None, "player", SHOOTER)
    assert shooter.height == 32  # four field-goal attempts in each of eight games; free throws excluded
    assert shot_attempts(pbp, None, "player", BIG).is_empty()  # assists and blocks are not the player's shots
    first_game = shooter.filter(pl.col("game_id") == "202500").sort("play_id")
    assert first_game["_zone"].to_list() == ["Three", "Rim", "Short midrange", "Three"]
    assert first_game["_split_score_state"].to_list() == ["Tied", "Leading", "Leading", "Leading"]
    assert first_game["_split_clutch"].to_list() == ["Non-clutch", "Non-clutch", "Clutch", "Clutch"]
    defense = shot_attempts(pbp, {"202501"}, "team", "GSW", side="defense")
    # Read from Golden State's side: 4-0 before the rival's jumper, 4-2 before the blocked layup.
    assert defense["_margin"].to_list() == [4.0, 2.0]
    before, after = zone_profile(shooter), zone_profile(shot_attempts(_play_by_play(2026, True), None, "player", SHOOTER))
    evidence, execution, chart = shot_mix_accounting(before, after, {"id": SHOOTER}, ["m"])
    parts = {item.metric: item.value for item in evidence}
    assert parts["shot_mix_effect"] == pytest.approx(0.0)
    assert parts["shot_conversion_effect"] == pytest.approx(0.5)  # 1.25 -> 1.75 points per field-goal attempt
    assert execution.tool == "decompose_metric_change" and chart.specification["mark"] == "bar"


def test_team_defense_report_uses_opponent_context_and_situations():
    datasets, manifests, supplemental = _data()
    request = _request(AnalysisSubject(type="team", id="GSW"), "defense")
    result = NBAPlugin().analyze(request, datasets, manifests, supplemental, {})
    evidence = {item.metric: item for item in result.aggregate_evidence}
    assert evidence["opponent_effective_fg_pct"].baseline_value == pytest.approx(45 / 85, abs=1e-6)
    assert evidence["opponent_effective_fg_pct"].comparison_value == pytest.approx(48 / 85, abs=1e-6)
    assert evidence["defensive_rating_league_rank"].context["teams"] == 3  # exhibition teams excluded
    assert "baseline_rank" in evidence["defensive_rating_league_rank"].context
    assert evidence["opponent_context"].baseline_value is not None
    splits = [item for item in result.aggregate_evidence if item.metric.startswith("situational_")]
    assert {item.context["split_value"] for item in splits} == {"Home", "Away", "0 days (back-to-back)"}
    split_tool = next(item for item in result.executions if item.tool == "analyze_situational_split")
    assert split_tool.parameters["splits"] == ["home_away", "rest", "score_state"]
    assert split_tool.parameters["excluded_small_subgroups"]["score_state"] >= 1  # 16 opponent attempts < 20
    assert result.play_evidence
    for play in result.play_evidence:
        assert play.visualization.defensive_team == "GS" and play.visualization.possession_team in {"BOS", "LAL"}
        assert "Substitution" not in (play.visualization.event_type or "")
    made = [play for play in result.play_evidence if "makes" in play.description]
    assert made and all(play.metric_value < 0 for play in made)


def test_player_shooting_report_runs_splits_and_shot_accounting():
    datasets, manifests, supplemental = _data()
    request = _request(AnalysisSubject(type="player", id=SHOOTER, team_id="GSW"), "shooting", splits=["period", "score_state", "clutch"])
    result = NBAPlugin().analyze(request, datasets, manifests, supplemental, {})
    splits = {(item.context["split"], item.context["split_value"]): item for item in result.aggregate_evidence
              if item.metric.startswith("situational_")}
    assert splits[("period", "Q1")].baseline_value == pytest.approx(0.75)
    assert splits[("period", "Q1")].comparison_value == pytest.approx(1.25)
    assert splits[("score_state", "Leading")].comparison_value == pytest.approx(2 / 3)
    assert ("score_state", "Tied") not in splits  # eight attempts per window is below the minimum
    # The comparison season's late three comes at +6, outside clutch, leaving eight clutch attempts: below the minimum.
    assert ("clutch", "Non-clutch") in splits and ("clutch", "Clutch") not in splits
    zones = {item.label: item for item in result.aggregate_evidence if item.metric == "shot_zone_share"}
    assert zones["Three attempt share"].baseline_value == pytest.approx(0.5)
    assert "Unlocated two attempt share" not in zones
    tools = {item.tool for item in result.executions}
    assert {"compare_shot_profiles", "decompose_metric_change", "analyze_situational_split"} <= tools
    assert "Where the points-per-shot change came from" in [chart.title for chart in result.charts]
    with pytest.raises(ValueError, match="unsupported NBA split"):
        NBAPlugin().analyze(_request(AnalysisSubject(type="player", id=SHOOTER), "shooting", splits=["down"]), datasets, manifests,
                            supplemental, {})


def test_player_participation_roles_orient_representative_plays():
    datasets, manifests, supplemental = _data()
    request = _request(AnalysisSubject(type="player", id=BIG, team_id="GSW"), "playmaking")
    game = datasets[2026].filter(pl.col("game_id") == "202600")
    plays = NBAPlugin._representative_plays(request, game, supplemental, manifests[2026])
    by_text = {play.description: play for play in plays}
    block = by_text["Big blocks Rival 's 3-foot layup"]
    assert block.metric_value == 2.0 and block.supporting  # a block is the player's positive play, not a missed shot
    assert block.visualization.secondary_player_role == "block"
    assert block.visualization.possession_team == "BOS" and block.visualization.defensive_team == "GS"
    rebound = NBAPlugin._possession_teams({"team_abbreviation": "GS", "home_team_abbrev": "GS", "away_team_abbrev": "BOS",
                                           "type_text": "Defensive Rebound", "description": "Big defensive rebound"})
    assert rebound == ("BOS", "GS")
    assert all(play.visualization.event_type != "Substitution" for play in plays)


def test_options_and_plan_expose_nba_situations_and_defense_metrics():
    plugin = NBAPlugin()
    options = plugin.analysis_options([])
    assert [split.value for split in options.split_dimensions] == ["home_away", "opponent", "rest", "period", "score_state", "clutch"]
    defense = {metric.value for metric in options.metrics if metric.analysis_domain == "defense"}
    assert {"opponent_effective_fg_pct", "forced_turnover_rate", "net_rating"} <= defense
    assert all(metric.subject_types == ["team"] for metric in options.metrics if metric.analysis_domain == "defense")
    player_metrics = {m.value for m in options.metrics if "player" in m.subject_types}
    for domain in ("scoring", "shooting", "playmaking", "rebounding", "turnovers", "usage"):
        # Domain defaults are shared, so a player report keeps only the defaults a player can be measured on.
        selected = plugin._selected_metrics(_request(AnalysisSubject(type="player", id=SHOOTER), domain))
        assert selected and set(selected) <= player_metrics
    plan = plugin.default_plan(_request(AnalysisSubject(type="team", id="GSW"), "shooting"))
    tools = [call.tool for call in plan.calls]
    assert "analyze_situational_split" in tools and "decompose_metric_change" in tools
    assert "opponent" in plugin.explain_metric("defensive_rebound_pct").limitations[-1]


def test_dictionary_curates_nba_play_by_play_and_box_scores():
    score = dictionary.describe("nba", "play_by_play", "home_score")
    assert score["source"] == "curated" and "running score" in score["description"] and score["timing"] == "outcome"
    assert dictionary.describe("nba", "play_by_play", "period")["timing"] == "context"
    assert dictionary.describe("nba", "play_by_play", "athlete_id_2")["timing"] == "identifier"
    assert "free throws" in dictionary.describe("nba", "play_by_play", "shooting_play")["description"]
    assert dictionary.describe("nba", "team_boxscores", "total_turnovers")["unit"] == "turnovers"
    assert dictionary.describe("nba", "player_boxscores", "did_not_play")["timing"] == "context"
    assert "clutch" in dictionary.describe("nba", "play_by_play", "start_quarter_seconds_remaining")["aliases"]
    for table in (dictionary.NBA_PLAY_BY_PLAY, dictionary.NBA_TEAM_BOXSCORES, dictionary.NBA_PLAYER_BOXSCORES):
        assert all(entry.timing in {"context", "outcome", "identifier", "descriptor"} for entry in table.values())
