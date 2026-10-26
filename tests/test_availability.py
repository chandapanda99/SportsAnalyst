"""Crucial shared safeguards: absence, retained data, retries and required coverage."""
from types import SimpleNamespace
from urllib.error import HTTPError

import polars as pl
import pytest
from test_cfb import DurableMemory

from sports_analyst.application.preparation import reusable
from sports_analyst.application.service import AnalystApplication
from sports_analyst.config import Settings
from sports_analyst.datasets.availability import completed_games, missing_source
from sports_analyst.datasets.nba import SportsDataverseNBAConnector
from sports_analyst.datasets.nfl import NFLVerseConnector


@pytest.mark.parametrize("sport,optional", [("nfl", "participation"), ("nba", "shots")])
@pytest.mark.parametrize("durable", [False, True])
def test_missing_optional_packages_continue_persist_retry_and_retain_good_data(tmp_path, monkeypatch, sport, optional, durable):
    state = {"missing": True, "calls": 0, "error": None}

    def load_optional(*args, **kwargs):
        state["calls"] += 1
        if state["error"] is not None:
            raise state["error"]
        if state["missing"]:
            raise HTTPError("https://example.test/source", 404, "Not Found", {}, None)
        return pl.DataFrame({"season": [2025], "game_id": ["1"], "value": [7]})

    def download(url, path):
        frame = load_optional() if "participation" in url else pl.DataFrame({"season": [2025], "game_id": ["1"]})
        frame.write_parquet(path)

    monkeypatch.setattr(NFLVerseConnector, "_download_parquet", staticmethod(download))
    monkeypatch.setattr(SportsDataverseNBAConnector, "_loader_registry", staticmethod(lambda: {
        "play_by_play": lambda *args, **kwargs: pl.DataFrame({"game_id": ["1"], "season": [2025]}), "shots": load_optional}))
    settings = Settings(_env_file=None, data_dir=tmp_path, dataset_sync_concurrency=2)
    app = AnalystApplication(settings, persistence=DurableMemory() if durable else None, analysis_runtime=False)
    result = app.sync([2025], "availability-first", ["play_by_play", optional], sport)
    assert {item.availability for item in result} == {"available", "source_unavailable"}
    absent = next(item for item in result if item.dataset == optional)
    assert absent.row_count == 0 and not reusable(absent, 2026)
    state["missing"] = False
    result = app.sync([2025], "availability-resume", ["play_by_play", optional], sport)
    assert state["calls"] == 2 and len(result) == 1 and result[0].row_count == 1
    # Explicit refresh failure must not replace a good snapshot with empty data.
    state["missing"] = True
    connector = app.connectors[sport]
    refreshed = connector.sync([2025], [optional])[0]
    assert refreshed.row_count == 1 and refreshed.availability == "partial"
    assert refreshed.coverage["retained_previous_data"] == 1
    assert connector.load(refreshed)["value"].to_list() == [7]
    assert not reusable(refreshed, 2026)
    state["error"] = TimeoutError("Source request timed out")
    with pytest.raises(TimeoutError):
        connector.sync([2025], [optional])
    assert connector.load(refreshed)["value"].to_list() == [7]
    # An absent core snapshot remains visible in Data Management, but must not
    # advertise a usable analysis season or break team/player discovery.
    for manifest in connector.sync([1990], ["play_by_play"]):
        app.store.save_manifest(manifest)
    assert 1990 not in app.analysis_options(sport).available_seasons


def test_only_confirmed_absence_is_skippable_and_unplayed_games_are_excluded():
    assert missing_source(HTTPError("https://example.test", 404, "missing", {}, None))
    for error in [HTTPError("https://example.test", code, "error", {}, None) for code in (401, 403, 429, 500)]:
        assert not missing_source(error)
    for error in (TimeoutError(), PermissionError(), ValueError("invalid parquet schema")):
        assert not missing_source(error)
    assert missing_source(ExceptionWithResponse(404))
    assert completed_games(pl.DataFrame({"completed": [True, False, None]}), flag="completed").height == 1
    assert completed_games(pl.DataFrame({"status": ["STATUS_FINAL", "STATUS_SCHEDULED", "STATUS_IN_PROGRESS", None]}),
                           status="status").height == 1


class ExceptionWithResponse(Exception):
    def __init__(self, status):
        self.response = SimpleNamespace(status_code=status)
