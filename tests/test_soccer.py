"""High-level soccer sync and analysis contracts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import polars as pl
from fastapi.testclient import TestClient

from sports_analyst.api import create_app
from sports_analyst.config import Settings
from sports_analyst.models import AnalysisRequest
from sports_analyst.plugins.soccer import SoccerPlugin
from sports_analyst.soccer_data import SportsDataverseSoccerConnector, soccer_season_label
from sports_analyst.storage import LocalStore
from sports_analyst.service import AnalystApplication
from sports_analyst.soccer_xg import ExpectedGoalsSource, coverage


def _summary(game: str, with_events: bool = True) -> dict:
    return {
        "header": {"id": game},
        "rosters": [{"team": {"id": "1"}, "roster": [
            {"athlete": {"id": "10", "displayName": "Alex Forward"},
             "position": {"abbreviation": "F"}, "starter": True}]},
            {"team": {"id": "2"}, "roster": []}],
        "boxscore": {"teams": [
            {"team": {"id": "1", "displayName": "Home"}, "statistics": [
                {"name": "totalShots", "displayValue": "12"},
                {"name": "shotsOnTarget", "displayValue": "5"},
                {"name": "possessionPct", "displayValue": "53%"}]},
            {"team": {"id": "2", "displayName": "Away"}, "statistics": []}]},
        "keyEvents": ([{"id": game + "-goal", "type": {"text": "Goal"}, "text": "Alex scores",
                       "clock": {"displayValue": "42'"}, "team": {"id": "1"}, "scoringPlay": True,
                       "participants": [{"athlete": {"id": "10", "displayName": "Alex Forward"}}]}]
                      if with_events else []),
    }


class SoccerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings = Settings(data_dir=Path(self.temporary.name), _env_file=None)
        self.connector = SportsDataverseSoccerConnector(self.settings)
        self.xg_patch = patch.object(ExpectedGoalsSource, "_team_statistics", return_value={})
        self.xg_patch.start()
        self.addCleanup(self.xg_patch.stop)
        self.store = LocalStore(self.settings)
        self.attempts: dict[str, int] = {}

        def scoreboard(competition: str, season: int) -> pl.DataFrame:
            return pl.DataFrame([
                {"event_id": str(season), "date": f"{season - 1}-09-15T12:00:00Z",
                 "home_team_id": "1", "away_team_id": "2", "home_team": "Home", "away_team": "Away",
                 "home_score": "2", "away_score": "0", "status": "STATUS_FINAL",
                 "season": season, "competition": competition},
                {"event_id": str(season) + "0", "date": f"{season - 1}-10-15T12:00:00Z",
                 "home_team_id": "1", "away_team_id": "2", "home_team": "Home", "away_team": "Away",
                 "home_score": "1", "away_score": "1", "status": "STATUS_FINAL",
                 "season": season, "competition": competition},
            ])

        def summary(competition: str, season: int, game: str) -> dict:
            self.attempts[game] = self.attempts.get(game, 0) + 1
            if game.endswith("0") and self.attempts[game] == 1:
                raise ConnectionError("temporary source failure")
            return _summary(game, with_events=not game.endswith("0"))

        self.connector._scoreboard = scoreboard
        self.connector._summary = summary

    def _sync(self, seasons: list[int], competition: str = "eng.1") -> None:
        self.connector.sync(seasons, datasets=["play_by_play", "team_stats", "lineups", "key_events"],
                            manifest_callback=self.store.save_manifest, competition=competition)

    def test_competition_catalog_and_resumable_match_coverage(self) -> None:
        self.assertEqual(soccer_season_label("eng.1", 2025), "2024–25")
        self.assertEqual(soccer_season_label("usa.1", 2025), "2025")
        self._sync([2025])
        first = self.store.manifest_for_season(2025, "team_stats", "soccer", "eng.1")
        self.assertEqual(first.coverage, {"completed_matches": 1, "expected_matches": 2, "recorded_matches": 1})
        self._sync([2025])
        resumed = self.store.manifest_for_season(2025, "team_stats", "soccer", "eng.1")
        self.assertEqual(resumed.coverage, {"completed_matches": 2, "expected_matches": 2, "recorded_matches": 2})
        self._sync([2025], "esp.1")
        self.assertEqual(len(self.store.manifests("play_by_play", "soccer")), 2)
        self.assertEqual(self.store.manifest_for_season(2025, "play_by_play", "soccer", "eng.1").competition, "eng.1")
        self.assertEqual(self.store.manifest_for_season(2025, "play_by_play", "soccer", "esp.1").competition, "esp.1")

    def test_team_player_comparisons_and_missing_event_section(self) -> None:
        self._sync([2024, 2025])
        self._sync([2024, 2025])
        manifests = {year: self.store.manifest_for_season(year, "play_by_play", "soccer", "eng.1") for year in (2024, 2025)}
        schedules = {year: self.connector.load(manifest) for year, manifest in manifests.items()}
        extras = {
            dataset: {year: self.connector.load(self.store.manifest_for_season(year, dataset, "soccer", "eng.1"))
                      for year in (2024, 2025)}
            for dataset in ("team_stats", "lineups", "key_events")
        }
        extras["player_game_logs"] = {
            year: pl.DataFrame({"game_id": [str(year), str(year) + "0"], "assists": ["1", "0"]})
            for year in (2024, 2025)
        }
        plugin = SoccerPlugin()
        scope = {"team": "1", "competition": "eng.1", "baseline": {"season": 2024},
                 "comparison": {"season": 2025}, "comparison_design": "full_seasons"}
        team = AnalysisRequest(sport="soccer", question="How did Home change?", scope=scope,
                               subject={"type": "team", "id": "1"}, analysis_domain="attack",
                               metrics=["points_per_match", "win_rate", "shots_per_match", "possession_pct"])
        team_result = plugin.analyze(team, schedules, manifests, extras)
        self.assertEqual({item.metric for item in team_result.aggregate_evidence}, {"points_per_match", "win_rate", "shots_per_match", "possession_pct"})
        self.assertEqual(next(item.comparison_value for item in team_result.aggregate_evidence if item.metric == "possession_pct"), 0.53)
        self.assertEqual(len(team_result.play_evidence), 4)
        self.assertTrue(any(not play.visualization.soccer_timeline for play in team_result.play_evidence))
        player = AnalysisRequest(sport="soccer", question="How did Alex change?", scope=scope,
                                 subject={"type": "player", "id": "10"}, analysis_domain="usage",
                                 metrics=["appearances", "starts", "goals", "assists"])
        player_result = plugin.analyze(player, schedules, manifests, extras)
        self.assertEqual({item.metric for item in player_result.aggregate_evidence}, {"appearances", "starts", "goals", "assists"})
        self.assertEqual(next(item.comparison_value for item in player_result.aggregate_evidence if item.metric == "goals"), 1.0)
        date_request = AnalysisRequest(sport="soccer", question="Did Home's results change during the season?",
                                       scope={"team": "1", "competition": "eng.1", "comparison_design": "date_ranges",
                                              "baseline": {"season": 2025, "start_date": "2024-09-01", "end_date": "2024-09-30"},
                                              "comparison": {"season": 2025, "start_date": "2024-10-01", "end_date": "2024-10-31"}},
                                       subject={"type": "team", "id": "1"}, analysis_domain="results",
                                       metrics=["points_per_match"])
        date_result = plugin.analyze(date_request, schedules, manifests, extras)
        self.assertEqual(date_result.aggregate_evidence[0].baseline_value, 3.0)
        self.assertEqual(date_result.aggregate_evidence[0].comparison_value, 1.0)

    def test_api_league_sync_options_investigation_and_match_evidence(self) -> None:
        app = AnalystApplication(self.settings)
        app.connectors["soccer"] = self.connector
        client = TestClient(create_app(app))
        payload = {"competition": "eng.1", "seasons": [2024, 2025],
                   "datasets": ["play_by_play", "team_stats", "lineups", "key_events"]}
        for _ in range(2):
            sync = client.post("/api/datasets/soccer/sync-stream", json=payload)
            self.assertEqual(sync.status_code, 200)
            self.assertIn('"stage": "complete"', sync.text)
        options = client.get("/api/sports/soccer/options", params={"competition": "eng.1"})
        self.assertEqual(options.status_code, 200)
        self.assertEqual(options.json()["available_seasons"], [2024, 2025])
        self.assertNotIn("expected_goals", options.json()["syncable_datasets"])
        self.assertIsNotNone(self.store.manifest_for_season(2025, "expected_goals", "soccer", "eng.1"))
        self.assertIn("1", [team["value"] for team in options.json()["teams"]])
        players = client.get("/api/sports/soccer/players", params={"competition": "eng.1", "query": "Alex"})
        self.assertEqual(players.status_code, 200)
        self.assertEqual(players.json()[0]["player_id"], "10")
        request = AnalysisRequest(sport="soccer", question="How did Home's goals change?",
                                  scope={"team": "1", "competition": "eng.1", "baseline": {"season": 2024},
                                         "comparison": {"season": 2025}, "comparison_design": "full_seasons"},
                                  subject={"type": "team", "id": "1"}, analysis_domain="results",
                                  metrics=["goals_for_per_match"])
        result = app.investigate(request)
        self.assertTrue(result.play_evidence)
        self.assertEqual(result.play_evidence[0].visualization.sport, "soccer")
        self.assertTrue(result.claims)
        self.assertIn("2023–24 season", result.summary)

    def test_selected_player_game_log_is_cached(self) -> None:
        payload = {"names": ["goalAssists"], "seasonTypes": [{"categories": [{"events": [
            {"eventId": "2025", "date": "2024-09-15", "stats": ["2"]}]}]}]}
        with patch("sportsdataverse.soccer.espn_soccer_player_gamelog", return_value=payload) as fetch:
            first = self.connector.player_game_log_manifest("eng.1", 2025, "10")
            second = self.connector.player_game_log_manifest("eng.1", 2025, "10")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.kwargs["season"], 2024)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(self.connector.load(second).get_column("assists").to_list(), ["2"])

    def test_expected_goals_sync_resume_and_team_comparison(self) -> None:
        schedule = self.connector._scoreboard("eng.1", 2025).with_columns(
            pl.Series("event_id", ["100", "101"]))
        self.connector._scoreboard = lambda competition, season: schedule

        def payload(value):
            return {"splits": {"type": "total", "categories": [{"stats": [
                {"name": "expectedGoals", "value": value, "displayValue": "9.99"},
                {"name": "expectedGoalsConceded", "value": 0.5},
                {"name": "totalShots", "value": 4}]}]}}

        attempts = {}
        def fetch(competition, game, team):
            attempts[(game, team)] = attempts.get((game, team), 0) + 1
            if game == "101" and team == "2" and attempts[(game, team)] == 1:
                raise OSError("temporary failure")
            return payload(0 if game == "100" else 1.574)

        with patch.object(ExpectedGoalsSource, "_team_statistics", side_effect=fetch) as source:
            for _ in range(2):
                self.connector.sync([2025], datasets=["team_stats"], competition="eng.1",
                                    manifest_callback=self.store.save_manifest)
            self.assertEqual(source.call_count, 5)
        manifest = self.store.manifest_for_season(2025, "expected_goals", "soccer", "eng.1")
        self.assertEqual(manifest.coverage["recorded_matches"], 2)
        self.assertEqual(manifest.coverage["non_penalty_xg_per_match_rows"], 0)
        xg = self.connector.load(manifest)
        request = AnalysisRequest(sport="soccer", question="How did chance quality change?",
            subject={"type": "team", "id": "1"}, analysis_domain="attack",
            metrics=["xg_per_match", "xga_per_match", "xg_difference_per_match", "non_penalty_xg_per_match"],
            scope={"team": "1", "competition": "eng.1", "comparison_design": "date_ranges",
                   "baseline": {"season": 2025, "start_date": "2024-09-01", "end_date": "2024-09-30"},
                   "comparison": {"season": 2025, "start_date": "2024-10-01", "end_date": "2024-10-31"}})
        result = SoccerPlugin().analyze(request, {2025: schedule}, {2025: manifest}, {"expected_goals": {2025: xg}})
        metrics = {item.metric: item for item in result.aggregate_evidence}
        self.assertEqual(metrics["xg_per_match"].baseline_value, 0)
        self.assertEqual(metrics["xg_per_match"].comparison_value, 1.574)
        self.assertAlmostEqual(metrics["xg_difference_per_match"].comparison_value, 1.074)
        self.assertNotIn("non_penalty_xg_per_match", metrics)
        self.assertEqual(result.play_evidence[0].visualization.home_expected_goals, 0)

    def test_selected_player_expected_goals_missing_coverage_and_cache(self) -> None:
        schedule = self.connector._scoreboard("eng.1", 2025).with_columns(pl.Series("event_id", ["100", "101"]))
        lineups = pl.DataFrame({"game_id": ["100", "101"], "team_id": ["1", "1"], "athlete_id": ["10", "10"]})
        def fetch(competition, game, team, athlete):
            stats = [{"name": "totalGoals", "value": 1}]
            if game == "100":
                stats.append({"name": "expectedGoals", "value": 0.375})
            return {"splits": [{"type": "total", "categories": [{"stats": stats}]}]}
        with patch.object(ExpectedGoalsSource, "_player_statistics", side_effect=fetch) as source:
            first = self.connector.player_expected_goals_manifest("eng.1", 2025, "10", schedule, lineups)
            second = self.connector.player_expected_goals_manifest("eng.1", 2025, "10", schedule, lineups)
            self.connector._scoreboard = lambda competition, season: schedule
            self.connector._summary = lambda competition, season, game: _summary(game)
            self.connector.sync([2025], datasets=["play_by_play", "lineups"], competition="eng.1",
                                manifest_callback=self.store.save_manifest)
            app = AnalystApplication(self.settings)
            app.connectors["soccer"] = self.connector
            result = app.investigate(AnalysisRequest(sport="soccer", question="Evaluate Alex's chance quality",
                subject={"type": "player", "id": "10"}, analysis_domain="scoring", metrics=["expected_goals"],
                scope={"team": "10", "competition": "eng.1",
                       "baseline": {"season": 2025, "start_date": "2024-09-01", "end_date": "2024-09-30"},
                       "comparison": {"season": 2025, "start_date": "2024-09-01", "end_date": "2024-10-31"},
                       "comparison_design": "date_ranges"}))
            self.assertEqual(result.aggregate_evidence[0].comparison_value, 0.375)
        self.assertEqual(source.call_count, 2)
        self.assertEqual(first.sha256, second.sha256)
        frame = self.connector.load(second)
        self.assertEqual(coverage(frame, 2)["recorded_matches"], 1)
        rows = [{"game_id": "100"}, {"game_id": "101"}]
        empty = pl.DataFrame()
        self.assertEqual(SoccerPlugin._value("expected_goals", rows, empty, empty, empty, "10", player_xg=frame), (0.375, 1))
        self.assertEqual(SoccerPlugin._value("goals_minus_xg", rows, empty, empty, empty, "10", player_xg=frame), (0.625, 1))


if __name__ == "__main__":
    unittest.main()
