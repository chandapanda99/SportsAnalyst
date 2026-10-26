"""Major production behaviors: scoped acquisition, resolution, lineage and fallback."""
import hashlib
import io
import json

import polars as pl
import pytest
from test_cfb import DurableMemory

from sports_analyst.config import Settings
from sports_analyst.datasets.cfb import SportsDataverseCFBConnector
from sports_analyst.datasets.cfb_secondary import SecondarySources
from sports_analyst.datasets.cfb_source import CFBSource
from sports_analyst.datasets.cfbd_audit import RELEASE_ROOT
from sports_analyst.storage.local import LocalStore


def payloads():
    summary = {"header": {"id": "2", "season": {"year": 2025}, "competitions": [{"date": "2025-09-01T18:00Z",
        "competitors": [{"team": {"id": "10", "abbreviation": "A", "location": "Team A"}, "score": "0", "homeAway": "home"},
                        {"team": {"id": "20", "abbreviation": "B", "location": "Team B"}, "score": "7", "homeAway": "away"}]}]},
        "drives": {"previous": [{"id": "21", "team": {"id": "10"}, "offensivePlays": 1, "yards": 3, "result": "PUNT",
            "start": {"period": {"number": 1}, "clock": {"displayValue": "12:00"}, "text": "A 25"},
            "end": {"period": {"number": 1}, "clock": {"displayValue": "11:00"}}}]}}
    ncaa = {"contest_id": "1", "espn_game_id": "2", "season": 2025, "academic_year": 2026,
        "teams": [{"team": "Team A", "espn_team_id": "10", "home_away": "home", "final": 0},
                  {"team": "Team B", "espn_team_id": "20", "home_away": "away", "final": 7}],
        "drives": [{"drive_number": 1, "team": "Team A", "period": 1, "start_clock": "12:00", "end_clock": "11:00",
                    "start_yard_line": "AA25", "n_plays": 1, "yards": 3, "end_how": "PUNT"}],
        "drive_titles": [{"drive_number": 1, "score_home": 0, "score_away": 0}],
        "pbp": [{"drive_number": 1, "play_number": 1, "offense": "Team A", "clock": "12:00", "down": 1, "distance": 10,
                 "yard_line_side": "AA", "yard_line_number": 25, "end_yard_line": "A28", "play_type": "rush",
                 "yards_gained": 3, "formation": "Shotgun", "run_direction": "right", "out_of_bounds": False}]}
    source = [{"id": "2100", "period": {"number": 1}, "clock": {"displayValue": "11:59"},
        "start": {"team": {"id": "10"}, "down": 1, "distance": 10, "yardsToEndzone": 75},
        "end": {"yardsToEndzone": 72}, "drive": {"$ref": "https://sports.core.api.espn.com/drives/21"},
        "type": {"text": "Rush"}, "statYardage": 3, "homeScore": 0, "awayScore": 0}]
    source.append({**source[0], "id": "2200", "period": {"number": 5}, "clock": {"displayValue": "0:00"},
                   "start": {**source[0]["start"], "yardsToEndzone": 25}, "end": {"yardsToEndzone": 22}})
    cfbd = pl.DataFrame({"game_id": [2], "season": [2025], "home_team_id": [10], "away_team_id": [20],
        "home": ["Team A"], "away": ["Team B"], "offense_play": ["Team A"], "period": [1],
        "pos_team": ["Team A"], "pos_team_score": [0], "def_pos_team_score": [0],
        "clock_minutes": [11], "clock_seconds": [59], "down": [1], "distance": [10], "yards_to_goal": [75],
        "yards_to_goal_end": [72], "yards_gained": [3], "play_type": ["Rush"], "new_id": [100.0],
        "id_play": [2.100000000000001e17], "offense_score_play": [0], "defense_score_play": [0], "EPA": [9999.0]})
    stream = io.BytesIO()
    cfbd.write_parquet(stream)
    data = stream.getvalue()
    asset = {"name": "play_by_play_2025.parquet", "id": 1, "size": len(data),
             "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
             "browser_download_url": RELEASE_ROOT + "/play_by_play_2025.parquet"}
    schedule = io.BytesIO()
    pl.DataFrame({"contest_id": ["1"], "espn_game_id": ["2"]}).write_parquet(schedule)
    return summary, ncaa, source, data, asset, schedule.getvalue()


@pytest.mark.parametrize("durable", [False, True])
def test_opt_in_sources_resolve_preserve_models_and_lineage_restore_and_clear(tmp_path, monkeypatch, durable):
    summary, ncaa, plays, data, asset, index = payloads()
    calls = []

    def fetch(url):
        calls.append(url)
        return ncaa if url.endswith(".gz") else {"assets": [asset]}

    def opener(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(index if "/schedules/" in request.full_url else data)

    monkeypatch.setattr("sports_analyst.datasets.cfb_secondary.SecondarySources",
                        lambda source, settings: SecondarySources(source, settings, fetch=fetch, opener=opener))
    settings = Settings(_env_file=None, data_dir=tmp_path / "first", cfb_ncaa_enabled=True,
                        cfb_cfbd_enabled=True, cfb_secondary_usage_confirmed=True)
    persistence = DurableMemory() if durable else None
    store = LocalStore(settings, persistence)
    connector = SportsDataverseCFBConnector(settings)
    connector.source.persistence = store.persistence
    original = [{"id": "2100", "play_id": "2100", "game_id": "2", "formation": "I-Formation", "epa": .25},
                {"id": "2200", "play_id": "2200", "game_id": "2", "quarter": 5, "epa": -.5}]
    resolved = connector.resolve_secondary(original, plays, summary, "2", 2025, feature="source_review")
    assert resolved[0]["formation"] == "I-Formation" and resolved[0]["rush_direction"] == "right"
    assert resolved[0]["epa"] == .25 and resolved[1]["epa"] == -.5 and len(resolved) == 2
    detail = json.loads(resolved[0]["source_provenance_json"])
    assert {item["provider_id"] for item in detail["conflicts"]["formation"]} == {"espn", "ncaa"}
    assert detail["alignment"]["ncaa"]["clock_disagreement"]
    assert "cfbd" in detail["alignment"]  # Uses lossless suffix + context, never rounded float id_play.
    assert json.loads(resolved[0]["secondary_coverage_json"])["ncaa"]["primary_overtime_plays"] == 1
    assert resolved[0]["out_of_bounds"] is False
    manifest = connector.snapshot(2025, "team:10", {"recorded_plays": resolved}, 1, 1, store.save_manifest)[0]
    assert len(manifest.input_manifest_ids) == 3 and manifest.resolution_version == "cfb-resolved-2"
    assert len(store.manifests(sport="cfb")) == 1
    assert len(store.manifests(sport="cfb", provider_id=None, processing_version=None)) == 4
    first_calls = len(calls)
    if durable:
        replica_settings = settings.model_copy(update={"data_dir": tmp_path / "replica"})
        restored = LocalStore(replica_settings, persistence)
        replica = SportsDataverseCFBConnector(replica_settings)
        replica.source = CFBSource(replica.data_dir, persistence)
        again = replica.resolve_secondary(original, plays, summary, "2", 2025, feature="source_review")
        replica.snapshot(2025, "team:10", {"recorded_plays": again}, 1, 1, restored.save_manifest)
        assert len(calls) == first_calls  # Both raw JSON and national asset reused across replicas.
        assert len(restored.manifests(sport="cfb", provider_id=None, processing_version=None)) == 4
        store = restored
    else:
        again = connector.resolve_secondary(original, plays, summary, "2", 2025, feature="source_review")
        assert len(calls) == first_calls and again == resolved
    assert store.clear_datasets("cfb") == 4
    if durable:
        assert not any(key.startswith("raw/cfb/providers/") for key in persistence.objects)


def test_secondary_errors_are_retryable_and_usage_confirmation_is_required(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="USAGE_CONFIRMED"):
        Settings(_env_file=None, cfb_ncaa_enabled=True)
    summary, _, plays, *_ = payloads()
    calls = []

    def unavailable(*args):
        calls.append(True)
        raise TimeoutError("private source error must not leak to UI")

    monkeypatch.setattr(SecondarySources, "ncaa", unavailable)
    settings = Settings(_env_file=None, data_dir=tmp_path, cfb_ncaa_enabled=True, cfb_secondary_usage_confirmed=True)
    connector = SportsDataverseCFBConnector(settings)
    row = {"id": "2100", "game_id": "2", "yards_gained": 3}
    first = connector.resolve_secondary([row], plays, summary, "2", 2025, feature="source_review")
    connector.resolve_secondary([row], plays, summary, "2", 2025, feature="source_review")
    assert len(calls) == 2 and first[0]["yards_gained"] == 3
    assert "private source error" not in first[0]["source_provenance_json"]
    assert "unavailable" in json.loads(first[0]["source_provenance_json"])["secondary_status"]["ncaa"]


def test_feature_policy_fetches_only_needed_context_and_preserves_cited_facts(tmp_path, monkeypatch):
    from sports_analyst.datasets.cfb_policy import POLICY_VERSION, acquisition_plan
    from sports_analyst.datasets.cfb_rendering import with_render_context
    from sports_analyst.datasets.cfb_resolution import resolve_game

    summary, ncaa, plays, *_ = payloads()
    ncaa["pbp"][0]["formation"] = "No Huddle-Shotgun"
    settings = Settings(_env_file=None, data_dir=tmp_path, cfb_ncaa_enabled=True,
                        cfb_cfbd_enabled=True, cfb_secondary_usage_confirmed=True)
    connector = SportsDataverseCFBConnector(settings)
    calls = []
    primary = {"id": "2100", "game_id": "2", "play_type": "Rush", "formation": "Shotgun", "rush_direction": "right",
               "clock": "11:59", "epa": .25, "source_provenance_json": json.dumps({"provenance": {
                   "formation": {"provider_id": "espn", "method": "text_parsed"}}})}
    monkeypatch.setattr(connector, "_primary_game_plays", lambda *_: {"plays": [primary]})
    monkeypatch.setattr(connector, "summary", lambda *_: summary)
    monkeypatch.setattr(connector.source, "collection", lambda *args, **kwargs: plays)

    def acquire(adapter, game, season, raw):
        calls.append(game)
        return ncaa, adapter.input("ncaa", season, game, ncaa, "https://example.test/ncaa", None)

    monkeypatch.setattr(SecondarySources, "ncaa", acquire)
    monkeypatch.setattr(SecondarySources, "cfbd", lambda *args: pytest.fail("Unneeded national asset requested"))
    assert connector.game_plays("2", 2025, feature="analysis")["plays"][0] == primary
    assert connector.game_plays("2", 2025, feature="advanced")["plays"][0] == primary
    assert calls == []
    rendered = connector.game_plays("2", 2025)["plays"][0]
    assert calls == ["2"] and rendered["formation"] == "No Huddle-Shotgun"
    assert rendered["epa"] == .25 and rendered["clock"] == "11:59"
    policy = json.loads(rendered["source_provenance_json"])["source_policy"]
    assert policy["version"] == POLICY_VERSION and policy["decisions"]["formation"]["selected_provider"] == "ncaa"
    assert "cfbd" in policy["skipped"]
    assert connector.game_plays("2", 2025, feature="analysis")["plays"][0]["formation"] == "Shotgun"
    saved = with_render_context(primary, rendered)
    assert saved["formation"] == "No Huddle-Shotgun" and saved["epa"] == .25
    incompatible = with_render_context({**primary, "formation": "I-Formation"}, rendered)
    assert incompatible["formation"] == "I-Formation"
    assert json.loads(incompatible["source_provenance_json"])["source_policy"]["decisions"]["formation"]["selected_provider"] == "espn"
    complete = {**primary, "formation": "No Huddle-Shotgun"}
    assert acquisition_plan([complete], "rendering", ["ncaa", "cfbd"])["providers"] == []
    assert acquisition_plan([primary], "historical_sample", ["ncaa", "cfbd"])["providers"] == []
    recorded = {**primary, "source_provenance_json": json.dumps({"provenance": {"formation": {"method": "recorded"}}})}
    assert acquisition_plan([recorded], "rendering", ["ncaa"])["providers"] == []
    receipt = {"source_url": "https://example.test/ncaa", "processing_version": "1"}
    assert resolve_game([recorded], plays, summary, "2", 2025, {"ncaa": (ncaa, receipt)})[0]["formation"] == "Shotgun"
    unknown = {**primary, "formation": "Not recorded"}
    replaced = resolve_game([unknown], plays, summary, "2", 2025, {"ncaa": (ncaa, receipt)})[0]
    assert replaced["formation"] == "No Huddle-Shotgun"
    assert "formation" in json.loads(replaced["source_provenance_json"])["rejected"]
    assert resolve_game([primary], plays, summary, "2", 2025, {"ncaa": (ncaa, receipt)},
                        policy={"feature": "analysis"}) == [primary]
