"""Major automatic-preparation workflows; provider requests are fully captured."""

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from test_cfb import DurableMemory

from sports_analyst.application.preparation import prepare_investigation
from sports_analyst.application.service import AnalystApplication
from sports_analyst.config import Settings
from sports_analyst.models import AnalysisRequest, DatasetManifest


@pytest.mark.parametrize("sport,datasets", [("nfl", {"play_by_play", "schedules"}), ("nba", {"play_by_play", "schedules", "team_boxscores"})])
@pytest.mark.parametrize("durable", [False, True])
def test_bulk_preparation_reuses_history_and_coalesces_workers(tmp_path, sport, datasets, durable, monkeypatch):
    persistence = DurableMemory() if durable else None
    roots = [tmp_path / "one", tmp_path / "two"] if durable else [tmp_path / "local"] * 2
    apps = [AnalystApplication(Settings(data_dir=root, _env_file=None), persistence, analysis_runtime=False) for root in roots]
    calls = Counter()

    for app in apps:

        def sync(years, selected, manifest_callback, progress_callback, application=app):
            result = []
            for year in years:
                for dataset in selected:
                    calls[(year, dataset)] += 1
                    time.sleep(0.02)
                    path = application.settings.data_dir / "raw" / sport / f"{dataset}-{year}.parquet"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    frame = pl.DataFrame({"season": [year], "game_id": [str(year)]})
                    frame.write_parquet(path)
                    manifest = DatasetManifest(
                        manifest_id=f"{sport}-{year}-{dataset}",
                        sport=sport,
                        dataset=dataset,
                        season=year,
                        source_url="https://example.test/source",
                        sha256="test",
                        row_count=1,
                        columns=frame.columns,
                        package_version="test",
                        local_path=str(path),
                    )
                    manifest_callback(manifest)
                    result.append(manifest)
            return result

        monkeypatch.setattr(app.connectors[sport], "sync", sync)
    request = AnalysisRequest(
        sport=sport,
        question="Compare recorded efficiency",
        subject={"type": "team", "id": "KC" if sport == "nfl" else "BOS"},
        analysis_domain="passing" if sport == "nfl" else "offense",
        metrics=["epa_per_dropback" if sport == "nfl" else "points_per_game"],
        scope={"team": "KC" if sport == "nfl" else "BOS", "baseline_season": 2024, "comparison_season": 2025},
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda app: prepare_investigation(app, request, "prepare"), apps))
    assert all(result == (None, [2024, 2025]) for result in results)
    assert set(dataset for _, dataset in calls) == datasets
    assert all(count == 1 for count in calls.values())
    prepare_investigation(apps[0], request, "repeat")
    assert all(count == 1 for count in calls.values())
    if sport == "nfl":
        current = datetime.now(UTC).year
        current_request = request.model_copy(
            update={"scope": request.scope.model_copy(update={"comparison": request.scope.comparison.model_copy(update={"season": current})})}
        )
        prepare_investigation(apps[0], current_request, "current")
        primary = apps[0].store.manifest_for_season(current, "play_by_play", sport)
        apps[0].store.save_manifest(primary.model_copy(update={"acquired_at": datetime.now(UTC) - timedelta(hours=2)}))
        prepare_investigation(apps[0], current_request, "refresh")
        assert calls[(current, "play_by_play")] == 2
    if durable:
        manifest = apps[1].store.manifest_for_season(2024, "play_by_play", sport)
        materialized = apps[1].store.materialize_manifest(manifest)
        assert Path(materialized.local_path).exists()


def test_soccer_scopes_matches_resumes_and_projects_installed_competition_data(tmp_path, monkeypatch):
    app = AnalystApplication(Settings(data_dir=tmp_path, _env_file=None), analysis_runtime=False)
    connector = app.connectors["soccer"]
    calls = Counter()
    failed = {"20241"}

    def scoreboard(competition, season):
        return pl.DataFrame(
            [
                {
                    "event_id": f"{season}{index}",
                    "date": f"{season - 1}-09-0{index}",
                    "home_team_id": home,
                    "away_team_id": away,
                    "home_team": f"School {home}",
                    "away_team": f"School {away}",
                    "home_score": "2",
                    "away_score": "1",
                    "status": "STATUS_FINAL",
                }
                for index, home, away in [(1, "1", "2"), (2, "3", "4")]
            ]
        )

    def summary(competition, season, game, **kwargs):
        calls[game] += 1
        if game in failed:
            failed.remove(game)
            raise OSError("temporary summary gap")
        return {"header": {"id": game}, "keyEvents": []}

    monkeypatch.setattr(connector, "_scoreboard", scoreboard)
    monkeypatch.setattr(connector, "_summary", summary)
    monkeypatch.setattr(connector.expected_goals, "team_matches", lambda *a, **k: pytest.fail("Results-only preparation must not fetch xG"))
    request = AnalysisRequest(
        sport="soccer",
        question="Compare team results",
        subject={"type": "team", "id": "1"},
        analysis_domain="results",
        metrics=["goals_for_per_match"],
        scope={"team": "1", "competition": "eng.1", "baseline_season": 2024, "comparison_season": 2025},
    )
    assert prepare_investigation(app, request, "soccer") == ("team:1", [2024, 2025])
    assert set(calls) == {"20241", "20251"}
    prepare_investigation(app, request, "resume")
    assert calls["20241"] == 2 and calls["20251"] == 1
    prepare_investigation(app, request, "cached")
    assert calls["20241"] == 2 and calls["20251"] == 1
    for year in (2024, 2025):
        assert app.store.manifest_for_season(year, "play_by_play", "soccer", "eng.1", "team:1").row_count == 1
    # Explicit competition downloads remain unpartitioned and do not replace the team snapshot.
    connector.sync([2024, 2025], ["play_by_play", "key_events"], competition="eng.1", manifest_callback=app.store.save_manifest)
    before = calls.copy()
    other = request.model_copy(update={"subject": request.subject.model_copy(update={"id": "3"})})
    prepare_investigation(app, other, "project")
    assert calls == before
    assert app.store.manifest_for_season(2024, "play_by_play", "soccer", "eng.1", "team:3").row_count == 1
    assert app.store.manifest_for_season(2024, "play_by_play", "soccer", "eng.1").row_count == 2
