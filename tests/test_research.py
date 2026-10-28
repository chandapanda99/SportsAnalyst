"""Major research behaviors: scoped joins, source budgets, replay and agent registration."""
import warnings
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from sports_analyst.analysis.research.contracts import contract
from sports_analyst.analysis.research.state import ACTIVE_BUDGET, ContextPool, ResearchLimit, ResearchState
from sports_analyst.analysis.scoped_data import ScopedData
from sports_analyst.config import Settings
from sports_analyst.datasets.nfl import sha256_file
from sports_analyst.models import AnalysisRequest, DatasetManifest
from sports_analyst.storage.persistence import LocalPersistenceBackend


def setup_access(tmp_path, sport, frames, player=False, persistence=None):
    manifests = []
    for index, (dataset, values) in enumerate(frames):
        path = tmp_path / f"{index}.parquet"
        data = pl.DataFrame(values)
        if sport == "nba" and (dataset.startswith("stats_") or dataset in {"lineups_v3", "possessions_v3"}):
            data = data.with_columns(pl.lit(2025).alias("source_season"))
        data.write_parquet(path)
        manifests.append(DatasetManifest(manifest_id=f"m{index}", sport=sport, dataset=dataset, season=2025,
            competition="eng.1" if sport == "soccer" else None, source_url="synthetic-test", sha256=sha256_file(path),
            row_count=data.height, columns=data.columns, package_version="test", local_path=str(path)))
    store = SimpleNamespace(manifests=lambda *a, **k: manifests, materialize_manifest=lambda m: m,
                            persistence=persistence or LocalPersistenceBackend())
    app = SimpleNamespace(settings=Settings(_env_file=None, data_dir=tmp_path), store=store)
    request = AnalysisRequest(sport=sport, subject={"type": "player" if player else "team", "id": "7" if player else "A", "team_id": "A"},
        question="Which recorded context explains the change?", scope={"team": "A", "competition": "eng.1" if sport == "soccer" else None,
            "season_type": "ALL", "comparison_design": "full_seasons", "baseline": {"season": 2024}, "comparison": {"season": 2025}})
    return ScopedData(app, request, None, "research-test"), manifests


def test_monthly_joined_measurements_use_recorded_dates_and_paired_counters(tmp_path):
    stats = {"game_id": ["1", "2", "3"], "team_id": ["A"] * 3,
             "accurate_passes": [1., 90., 5.], "total_passes": [2., 100., 10.]}
    schedule = {"event_id": ["1", "2", "3"], "home_team_id": ["A"] * 3,
                "away_team_id": ["B"] * 3, "date": ["2025-01-12", "2025-01-28", "2025-03-02"]}
    access, sources = setup_access(tmp_path, "soccer", [("team_stats", stats), ("play_by_play", schedule)])
    relation = next(r for r in access.executor.discover()["relationships"] if r["left_dataset_id"] == "m0")
    plan = {"objective": "Monthly passing", "dataset_id": "m0", "window": "comparison",
            "grain": contract(sources[0]).grain,
            "steps": [{"relationship_id": relation["relationship_id"], "alias": "game", "fields": ["date"]}],
            "time_bucket": {"field": "game__date", "interval": "month"}, "group_by": ["month"],
            "measures": [{"op": "rate", "field": "accurate_passes", "denominator": "total_passes", "name": "passing"}]}
    result = access.executor.execute(access.executor.validate(plan)["plan_id"])
    assert [r["month"] for r in result["rows"]] == ["2025-01", "2025-03"]
    assert result["rows"][0]["passing"] == 91 / 102
    assert result["rows"][0]["passing_non_null"] == 2
    assert result["qualifying_rows"] == 3
    plan["time_bucket"]["field"] = "accurate_passes"
    with pytest.raises(ValueError, match="recorded match/game date"):
        access.executor.validate(plan)
    plan["time_bucket"]["field"] = "game__date"
    schedule["date"][0] = "not-a-date"
    pl.DataFrame(schedule).write_parquet(sources[1].local_path)
    sources[1] = sources[1].model_copy(update={"sha256": sha256_file(Path(sources[1].local_path))})
    access.manifests["m1"] = sources[1]
    with pytest.raises(ValueError, match="missing/invalid recorded dates"):
        access.executor.execute(access.executor.validate(plan)["plan_id"])


@pytest.mark.parametrize("sport,base,context", [
    ("nfl", "play_by_play", "ftn_charting"), ("cfb", "player_stats", "team_stats"),
    ("nba", "player_boxscores", "team_boxscores"), ("soccer", "team_stats", "expected_goals"),
])
def test_joined_measurements_preserve_scope_coverage_and_replay(tmp_path, sport, base, context):
    team = "posteam" if sport == "nfl" else "team_abbreviation" if sport == "nba" else "team_id"
    rows = {"game_id": ["1", "2", "3"], team: ["A", "A", "OTHER"], "yards": [10, 20, 999]}
    if sport == "nfl":
        rows["play_id"] = ["p1", "p2", "p3"]
    if sport in {"nba", "cfb"}:
        rows["athlete_id"] = ["7", "7", "8"]
    right = {"game_id": ["1"], "coverage": ["recorded"]}
    if sport == "nfl":
        right["play_id"] = ["p1"]
    else:
        right[team] = ["A"]
    access, sources = setup_access(tmp_path, sport, [(base, rows), (context, right)])
    relation = next(r for r in access.executor.discover()["relationships"] if r["left_dataset_id"] == "m0")
    raw = {"objective": "Recorded contextual coverage", "dataset_id": "m0", "window": "comparison", "grain": contract(sources[0]).grain,
           "steps": [{"relationship_id": relation["relationship_id"], "alias": "ctx", "fields": ["coverage"]}],
           "measures": [{"op": "sum", "field": "yards", "name": "yards_sum"}], "missing": "preserve"}
    validated = access.executor.validate(raw)
    result = access.executor.execute(validated["plan_id"])
    assert result["rows"][0]["yards_sum"] == 30 and result["qualifying_rows"] == 2
    assert sum(a["unmatched"] for a in result["audits"]) == 1
    assert access.executor.execute(validated["plan_id"]) == result
    access.acquisition.state.write("measurement", result)
    assert access.acquisition.state.read("measurement")["rows"] == result["rows"]
    raw["missing"] = "matched"
    assert access.executor.execute(access.executor.validate(raw)["plan_id"])["rows"][0]["yards_sum"] == 10
    raw["missing"] = "strict"
    with pytest.raises(ValueError, match="Strict join"):
        access.executor.execute(access.executor.validate(raw)["plan_id"])
    # Fail closed on a checksum mutation, even after validation.
    pl.DataFrame(right).head(0).write_parquet(sources[1].local_path)
    with pytest.raises(ValueError, match="checksum"):
        access.executor.execute(validated["plan_id"])


@pytest.mark.parametrize("sport,base,context", [
    ("nfl", "play_by_play", "ftn_charting"), ("cfb", "player_stats", "team_stats"),
    ("nba", "player_boxscores", "team_boxscores"), ("soccer", "team_stats", "expected_goals"),
])
def test_null_coverage_filters_preserve_scoped_and_joined_measurements(tmp_path, sport, base, context):
    team = "posteam" if sport == "nfl" else "team_abbreviation" if sport == "nba" else "team_id"
    rows = {"game_id": ["1", "2", "3", "4"], team: ["A", "A", "A", "OTHER"],
            "yards": [10., None, 30., 999.]}
    right = {"game_id": ["1", "2", "3"], "coverage": ["recorded", None, "recorded"]}
    if sport == "nfl":
        rows["play_id"] = ["p1", "p2", "p3", "p4"]
        right["play_id"] = ["p1", "p2", "p3"]
    else:
        right[team] = ["A"] * 3
    if sport in {"cfb", "nba"}:
        rows["athlete_id"] = ["7", "7", "7", "8"]
    access, sources = setup_access(tmp_path, sport, [(base, rows), (context, right)])
    relation = next(r for r in access.executor.discover()["relationships"] if r["left_dataset_id"] == "m0")
    # The warning is an error here: even unused comparisons must never be constructed.
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        for op, value, count, total in [
            ("is_not_null", None, 2, 40.), ("eq", None, 1, None), ("ne", None, 2, 40.),
            ("eq", 10, 1, 10.), ("ne", 10, 1, 30.), ("gt", 10, 1, 30.),
            ("ge", 10, 2, 40.), ("lt", 30, 1, 10.), ("le", 30, 2, 40.),
        ]:
            filters = [{"field": "yards", "op": op, "value": value}]
            scoped = access.aggregate("m0", "comparison", [], [{"op": "sum", "field": "yards"}], filters)
            assert scoped["qualifying_rows"] == count and scoped["rows"][0]["m0"] == total
        for field, op, count, total in [
            ("ctx__coverage", "is_not_null", 2, 40.), ("ctx__coverage", "eq", 1, None),
            ("yards", "ne", 2, 40.),
        ]:
            plan = {"objective": "Recorded coverage", "dataset_id": "m0", "window": "comparison",
                "grain": contract(sources[0]).grain,
                "steps": [{"relationship_id": relation["relationship_id"], "alias": "ctx", "fields": ["coverage"]}],
                "filters": [{"field": field, "op": op, "value": None}],
                "measures": [{"op": "sum", "field": "yards", "name": "total_yards"}]}
            joined = access.executor.execute(access.executor.validate(plan)["plan_id"])
            assert joined["qualifying_rows"] == count and joined["rows"][0]["total_yards"] == total
        with pytest.raises(ValueError, match="requires a non-null value"):
            access.aggregate("m0", "comparison", [], [{"op": "count"}], [{"field": "yards", "op": "gt"}])
        plan["filters"] = [{"field": "yards", "op": "lt", "value": None}]
        with pytest.raises(ValueError, match="requires a non-null value"):
            access.executor.validate(plan)


def test_child_fanout_existence_filters_and_preaggregation(tmp_path):
    access, sources = setup_access(tmp_path, "nfl", [
        ("play_by_play", {"game_id": ["1", "1"], "play_id": ["a", "b"], "posteam": ["A", "A"], "epa": [1., 2.]}),
        ("participation", {"game_id": ["1", "1", "1"], "play_id": ["a", "a", "b"],
                           "participant": ["7", "8", "9"], "snaps": [1, 1, 1]})])
    relation = next(r for r in access.executor.discover()["relationships"] if r["left_dataset_id"] == "m0")
    step = {"relationship_id": relation["relationship_id"], "alias": "people", "fields": ["participant"]}
    plan = {"objective": "EPA involving selected participant", "dataset_id": "m0", "window": "comparison", "grain": "play",
            "steps": [step], "measures": [{"op": "sum", "field": "epa", "name": "epa_sum"}]}
    with pytest.raises(ValueError, match="Duplicate"):
        access.executor.execute(access.executor.validate(plan)["plan_id"])
    step.update(mode="exists", fields=[], filters=[{"field": "participant", "op": "eq", "value": "7"}])
    assert access.executor.execute(access.executor.validate(plan)["plan_id"])["rows"][0]["epa_sum"] == 1
    step["mode"] = "not_exists"
    assert access.executor.execute(access.executor.validate(plan)["plan_id"])["rows"][0]["epa_sum"] == 2
    step.update(mode="preaggregate", filters=[], measures=[{"op": "count", "name": "actors"}])
    plan["measures"] = [{"op": "sum", "field": "people__actors", "name": "actor_count"}]
    assert access.executor.execute(access.executor.validate(plan)["plan_id"])["rows"][0]["actor_count"] == 3


def test_crosswalks_membership_and_unverified_intervals(tmp_path):
    access, _ = setup_access(tmp_path, "nba", [
        ("player_boxscores", {"game_id": ["espn-1"], "athlete_id": ["7"], "team_abbreviation": ["A"], "points": [20]}),
        ("schedule_crosswalk", {"espn_game_id": ["espn-1"], "nba_game_id": ["nba-1"]}),
        ("stats_schedules", {"game_id": ["nba-1"], "venue": ["home"]}),
        ("lineups", {"player_id": ["7"], "minutes": [25]})])
    graph = access.executor.discover()["relationships"]
    bridge = next(r for r in graph if r["left_dataset_id"] == "m0" and r["right_dataset_id"] == "m1")
    target = next(r for r in graph if r["left_dataset_id"] == "m1" and r["right_dataset_id"] == "m2")
    assert not any(r["right_dataset_id"] == "m3" for r in graph)
    plan = {"objective": "Cross-provider game context", "dataset_id": "m0", "window": "comparison", "grain": "player_game",
            "steps": [{"relationship_id": bridge["relationship_id"], "alias": "ids", "fields": ["nba_game_id"]},
                      {"relationship_id": target["relationship_id"], "left_alias": "ids", "alias": "game", "fields": ["venue"]}],
            "group_by": ["game__venue"], "measures": [{"op": "sum", "field": "points", "name": "points_sum"}]}
    assert access.executor.execute(access.executor.validate(plan)["plan_id"])["rows"][0]["points_sum"] == 20
    plan["interpretation"] = "pregame"
    with pytest.raises(ValueError, match="publication"):
        access.executor.validate(plan)
    native = tmp_path / "native-player"
    native.mkdir()
    access, sources = setup_access(native, "nba", [
        ("stats_player_boxscores", {"game_id": ["n1", "n1"], "player_id": ["77", "7"],
                                   "team_abbreviation": ["A", "A"], "points": [20, 999]}),
        ("player_crosswalk", {"espn_athlete_id": ["7"], "nba_player_id": ["77"]})], player=True)
    plan = {"objective": "Verified native player", "dataset_id": "m0", "grain": "player_game", "window": "comparison",
            "measures": [{"op": "sum", "field": "points", "name": "points_sum"}]}
    checked = access.executor.validate(plan)
    assert set(checked["inputs"]) == {"m0", "m1"}
    assert access.executor.execute(checked["plan_id"])["rows"][0]["points_sum"] == 20
    pl.DataFrame({"espn_athlete_id": ["7", "7"], "nba_player_id": ["77", "88"]}).write_parquet(sources[1].local_path)
    access.manifests["m1"] = sources[1].model_copy(update={"sha256": sha256_file(Path(sources[1].local_path))})
    with pytest.raises(ValueError, match="ambiguous"):
        access.executor.execute(access.executor.validate(plan)["plan_id"])


def test_transferred_player_and_week_specific_membership(tmp_path):
    access, sources = setup_access(tmp_path, "cfb", [
        ("player_stats", {"game_id": ["1", "2", "3"], "athlete_id": ["7", "7", "8"],
                          "team_id": ["A", "B", "B"], "yards": [10., 20., 999.]}),
        ("team_stats", {"game_id": ["1", "2"], "team_id": ["A", "B"], "division": ["FBS", "FCS"]}),
        ("rosters", {"athlete_id": ["7"], "team_id": ["C"], "season": [2026]})], player=True)
    graph = access.executor.discover()["relationships"]
    assert not any(r["right_dataset_id"] == "m2" for r in graph)
    edge = next(r for r in graph if r["left_dataset_id"] == "m0" and r["right_dataset_id"] == "m1")
    plan = {"objective": "Selected athlete across recorded schools", "dataset_id": "m0", "grain": "player_game",
            "window": "comparison", "steps": [{"relationship_id": edge["relationship_id"], "alias": "team", "fields": ["division"]}],
            "group_by": ["team_id"], "measures": [{"op": "sum", "field": "yards", "name": "yardage"}]}
    result = access.executor.execute(access.executor.validate(plan)["plan_id"])
    assert [r["yardage"] for r in result["rows"]] == [10, 20]
    assert [r["team_id"] for r in result["rows"]] == ["A", "B"]
    # Temporal membership uses season/type/week/player/team, not a current profile.
    nested = tmp_path / "nfl"
    nested.mkdir()
    access, _ = setup_access(nested, "nfl", [
        ("player_stats", {"player_id": ["7", "7"], "recent_team": ["A", "B"],
                          "season": [2025, 2025], "season_type": ["REG", "REG"], "week": [1, 2], "yards": [10, 20]}),
        ("weekly_rosters", {"gsis_id": ["7", "7"], "team": ["A", "B"], "season": [2025, 2025],
                            "game_type": ["REG", "REG"], "week": [1, 2], "position": ["WR", "WR"]})], player=True)
    edge = next(r for r in access.executor.discover()["relationships"] if r["left_dataset_id"] == "m0")
    plan.update(dataset_id="m0", grain="player_week", group_by=["recent_team"],
                steps=[{"relationship_id": edge["relationship_id"], "alias": "membership", "fields": ["position"]}])
    assert access.executor.execute(access.executor.validate(plan)["plan_id"])["qualifying_rows"] == 2


def test_durable_research_artifacts_survive_local_worker_replacement(tmp_path):
    from test_data_catalog import MemoryPersistence

    persistence = MemoryPersistence()
    access, _ = setup_access(tmp_path, "cfb", [], persistence=persistence)
    first = ResearchState(access.app, "durable-job")
    first.consume(requests=1, transferred=100, attempt="package-1")
    first.write("receipt", {"status": "available", "inputs": ["manifest-1"]})
    second_path = tmp_path / "another-worker"
    second_path.mkdir()
    other, _ = setup_access(second_path, "cfb", [], persistence=persistence)
    resumed = ResearchState(other.app, "durable-job")
    assert resumed.consume()["requests"] == 1
    assert resumed.read("receipt")["inputs"] == ["manifest-1"]


def test_native_temporal_intervals_reject_overlap_and_preserve_periods(tmp_path):
    access, sources = setup_access(tmp_path, "nba", [
        ("stats_play_by_play", {"game_id": ["1", "1", "1"], "play_id": [1, 2, 3], "order_index": [5, 15, 5],
                               "period": [1, 1, 5], "team_abbreviation": ["A", "A", "A"], "points": [2, 3, 2]}),
        ("possessions_v3", {"game_id": ["1", "1", "1"], "period": [1, 1, 5],
                            "start_order_index": [1, 10, 1], "end_order_index": [9, 19, 9], "unit": ["first", "second", "overtime"]})])
    edge = next(r for r in access.executor.discover()["relationships"] if r["kind"] == "interval")
    plan = {"objective": "Recorded native possession context", "dataset_id": "m0", "grain": "play", "window": "comparison",
            "steps": [{"relationship_id": edge["relationship_id"], "alias": "possession", "fields": ["unit"]}],
            "group_by": ["possession__unit"], "measures": [{"op": "sum", "field": "points", "name": "points_sum"}]}
    result = access.executor.execute(access.executor.validate(plan)["plan_id"])
    assert {r["possession__unit"]: r["points_sum"] for r in result["rows"]} == {"first": 2, "second": 3, "overtime": 2}
    bad = pl.read_parquet(sources[1].local_path).with_columns(pl.lit(1).alias("start_order_index"))
    bad.write_parquet(sources[1].local_path)
    access.manifests["m1"] = sources[1].model_copy(update={"sha256": sha256_file(Path(sources[1].local_path))})
    edge = next(r for r in access.executor.discover()["relationships"] if r["kind"] == "interval")
    plan["steps"][0]["relationship_id"] = edge["relationship_id"]
    with pytest.raises(ValueError, match="overlapping"):
        access.executor.execute(access.executor.validate(plan)["plan_id"])


@pytest.mark.parametrize("sport", ["cfb", "nba", "soccer"])
def test_default_temporal_scope_uses_authoritative_schedules(tmp_path, sport):
    dataset = "team_boxscores" if sport == "nba" else "team_stats"
    team = "team_abbreviation" if sport == "nba" else "team_id"
    fixture = {"game_id": ["1", "2"], "date": ["2025-01-01", "2025-12-01"], "week": [1, 2],
               "season_type": ["REG", "POST"], "completed": [True, True]}
    if sport == "nba":
        fixture.update(season_type=[2, 3], game_date=fixture.pop("date"))
    if sport == "soccer":
        fixture = {"event_id": ["1", "2"], "date": ["2025-01-01", "2025-12-01"], "status": ["STATUS_FINAL", "STATUS_FINAL"]}
    access, _ = setup_access(tmp_path, sport, [(dataset, {"game_id": ["1", "2"], team: ["A", "A"], "yards": [10, 20]}),
        ("play_by_play" if sport == "soccer" else "schedules", fixture)])
    comparison = access.request.scope.comparison.model_copy(update={"end_date": "2025-06-30"}) if sport == "soccer" else access.request.scope.comparison
    access.request.scope = access.request.scope.model_copy(update={"season_type": "REG", "comparison": comparison})
    plan = {"objective": "Match the primary temporal sample", "dataset_id": "m0", "window": "comparison", "grain": "team_game",
            "measures": [{"op": "sum", "field": "yards", "name": "yardage"}]}
    checked = access.executor.validate(plan)
    assert set(checked["inputs"]) == {"m0", "m1"}
    assert access.executor.execute(checked["plan_id"])["rows"][0]["yardage"] == 10


def test_opponent_context_is_verified_without_changing_primary_observations(tmp_path):
    access, _ = setup_access(tmp_path, "soccer", [
        ("team_stats", {"game_id": ["1", "1", "2", "2"], "team_id": ["A", "B", "A", "C"],
                        "shots": [10, 20, 30, 40]}),
        ("play_by_play", {"event_id": ["1", "2"], "home_team_id": ["A", "C"], "away_team_id": ["B", "A"],
                          "date": ["2025-01-01", "2025-02-01"], "status": ["STATUS_FINAL", "STATUS_FINAL"]})])
    edge = next(r for r in access.executor.discover()["relationships"] if r["left_dataset_id"] == r["right_dataset_id"] == "m0"
                and r["context_role"] == "opponent")
    plan = {"objective": "Own shots relative to opponents", "dataset_id": "m0", "grain": "team_game", "window": "comparison",
            "steps": [{"relationship_id": edge["relationship_id"], "alias": "opponent", "fields": ["shots"]}],
            "measures": [{"op": "sum", "field": "shots", "name": "own_shots"},
                         {"op": "sum", "field": "opponent__shots", "name": "opponent_shots"}]}
    result = access.executor.execute(access.executor.validate(plan)["plan_id"])
    assert result["qualifying_rows"] == 2
    assert result["rows"][0]["own_shots"] == 40 and result["rows"][0]["opponent_shots"] == 60
    assert set(result["inputs"]) == {"m0", "m1"}


def test_research_budgets_resume_and_propagate_across_workers(tmp_path, monkeypatch):
    access, _ = setup_access(tmp_path, "cfb", [])
    access.app.settings.research_source_requests = 2
    access.app.settings.research_transfer_bytes = 1024
    state = ResearchState(access.app, "persistent-job")
    token = ACTIVE_BUDGET.set(state)
    try:
        with ContextPool(max_workers=1) as pool:
            pool.submit(lambda: ACTIVE_BUDGET.get().consume(requests=1, transferred=700, attempt="one")).result()
    finally:
        ACTIVE_BUDGET.reset(token)
    resumed = ResearchState(access.app, "persistent-job")
    assert resumed.consume()["bytes"] == 700
    resumed.consume(requests=1)
    with pytest.raises(ResearchLimit):
        resumed.consume(requests=1)
    assert resumed.read("budget")["attempts"] == ["one"]
    other = ResearchState(access.app, "separate-byte-budget")
    other.consume(transferred=700)
    with pytest.raises(ResearchLimit):
        other.consume(transferred=400)
    import io

    def response(*args, **kwargs):
        stream = io.BytesIO(b"payload")
        stream.headers = {"Content-Length": "7"}
        return stream

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: SimpleNamespace(open=response))
    transport = ResearchState(access.app, "actual-byte-accounting")
    assert transport.fetch("https://github.com/example") == b"payload"
    assert transport.read("budget")["bytes"] == 7
    assert transport.read("budget")["requests"] == 1
    with pytest.raises(ValueError, match="unapproved"):
        transport.fetch("http://127.0.0.1/private")
    assert transport.read("budget")["requests"] == 1


@pytest.mark.parametrize("review_complete", [True, False])
def test_agent_acquires_missing_charting_and_registers_joined_evidence(tmp_path, monkeypatch, review_complete):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    from sports_analyst.analysis.calculations import complete_calculations
    from sports_analyst.datasets.nfl import NFLVerseConnector

    access, manifests = setup_access(tmp_path, "nfl", [("play_by_play", {
        "game_id": ["1", "1"], "play_id": ["a", "b"], "posteam": ["A", "A"], "epa": [1., 2.]})])
    access.app.settings.model_provider = "ollama"
    access.app.connectors = {"nfl": NFLVerseConnector(access.app.settings)}
    access.app.store.save_manifest = lambda m: manifests.append(m) if m.manifest_id not in {s.manifest_id for s in manifests} else None

    def fetch(state, url, destination=None):
        assert ACTIVE_BUDGET.get() is state  # The worker, not QuickJS, owns transport.
        assert "/ftn_charting/" in url
        state.consume(requests=1, transferred=100)
        pl.DataFrame({"nflverse_game_id": ["1"], "nflverse_play_id": ["a"], "coverage": ["zone"]}).write_parquet(destination)

    monkeypatch.setattr(ResearchState, "fetch", fetch)

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    first = '''await tools.recordAnalysisPlan({objectives:["EPA on charted plays"],existing_evidence_ids:[],
required_data:["ftn_charting"],calculations:["Join by verified game/play keys and sum EPA"],limitations:[]});
await tools.prepareAnalysisData({acquisition_plan:{objective:"EPA on charted plays",dataset:"ftn_charting",season:2025,round:1}});
"Waiting for worker acquisition";'''
    second = '''const graph=JSON.parse(await tools.discoverRelationships({}));
const edge=graph.relationships.find(r=>r.left_dataset_id==="m0");
const validated=JSON.parse(await tools.validateJoinPlan({join_plan:{objective:"EPA on charted plays",dataset_id:"m0",
window:"comparison",grain:"play",steps:[{relationship_id:edge.relationship_id,alias:"chart",fields:["coverage"]}],
missing:"matched",group_by:["chart__coverage"],measures:[{op:"sum",field:"epa",name:"epa_sum"}]}}));
const evidence=JSON.parse(await tools.executeJoinedAggregate({plan_id:validated.plan_id})).evidence;
'''
    if review_complete:
        second += 'await tools.finishQuestionReview({evidence_by_objective:{"0":evidence.map(e=>e.evidence_id)},unresolved:{}});'
    second += '"done";'
    model = Model(responses=[
        AIMessage(content="", tool_calls=[{"name": "eval", "id": "acquire", "args": {"code": first}}]),
        AIMessage(content="Queued"),
        AIMessage(content="", tool_calls=[{"name": "eval", "id": "measure", "args": {"code": second}}]),
        AIMessage(content="Done")])
    monkeypatch.setattr("sports_analyst.providers.get_provider", lambda _: SimpleNamespace(
        build=lambda settings: SimpleNamespace(chat_model=model, model_id="offline-research")))
    result = SimpleNamespace(aggregate_evidence=[], executions=[], caveats=[])
    complete_calculations(access.app.settings, access.request.question, result, {}, access)
    assert len(result.aggregate_evidence) == 1, result.executions[-1].parameters.get("tool_audit")
    evidence = result.aggregate_evidence[0]
    assert evidence.value == 1 and evidence.sample_size == 1 and evidence.metric == "joined_aggregate"
    assert len(evidence.dataset_manifest_ids) == 2
    assert access.acquisition.state.read("budget")["requests"] == 1
    assert access.acquisition.state.read("rounds")["next"] == 2
    assert any(e.tool == "execute_joined_aggregate" for e in result.executions)
    assert any(e.tool == "complete_calculations_failed" for e in result.executions) != review_complete


@pytest.mark.parametrize("durable", [False, True])
def test_acquisition_dependencies_survive_interruption_and_coalesce(tmp_path, monkeypatch, durable):
    """Persist decisions before downloading; never redownload completed dependencies after replacement."""
    from test_data_catalog import MemoryPersistence

    from sports_analyst.analysis.research.acquisition import Acquisition

    persistence = MemoryPersistence() if durable else LocalPersistenceBackend()
    access, manifests = setup_access(tmp_path, "cfb", [("player_stats", {
        "game_id": ["1"], "team_id": ["A"], "athlete_id": ["7"], "passing_yards": [20]})], persistence=persistence)
    access.app.settings.research_rounds = 3
    access.app.store.save_manifest = lambda m: manifests.append(m) if m.manifest_id not in {s.manifest_id for s in manifests} else None
    calls = []

    def fetch(self, plan, team, player):
        calls.append(plan.dataset)
        self.state.consume(requests=1)
        if plan.dataset == "team_stats" and calls.count("team_stats") == 1:
            raise KeyboardInterrupt("simulated worker termination")
        return [manifests[0].model_copy(update={"manifest_id": plan.dataset + "-snapshot", "dataset": plan.dataset})]

    monkeypatch.setattr(Acquisition, "fetch", fetch)
    decision = {"objective": "Compare passing share", "dataset": "team_stats", "season": 2025}
    queued = access.acquisition.queue(decision)
    assert len(queued["dependency_decisions"]) == 2
    access.acquisition.queue(decision)
    with pytest.raises(KeyboardInterrupt):
        access.acquisition.run()
    assert calls == ["schedules", "team_stats"]
    replacement = Acquisition(access, access.identifier)
    assert [p.dataset for p in replacement.pending] == ["team_stats"]
    assert replacement.run()[0]["status"] == "available"
    assert calls == ["schedules", "team_stats", "team_stats"]
    assert not replacement.pending and replacement.state.read("budget")["requests"] == 3
    # Repeated delivery and a further allowed round reuse historical bytes.
    assert not replacement.run()
    replacement.queue({**decision, "round": 2})
    assert all(r["status"] == "available" for r in replacement.run())
    assert calls == ["schedules", "team_stats", "team_stats"]
    replacement.queue({**decision, "round": 3})
    replacement.run()
    with pytest.raises(ResearchLimit, match="round"):
        replacement.queue({**decision, "round": 4})


@pytest.mark.parametrize("sport,dataset,numerator,denominator", [
    ("nfl", "player_stats", "passing_completions", "passing_attempts"),
    ("cfb", "player_stats", "passing_yards", "passing_attempts"),
    ("nba", "player_boxscores", "field_goals_made", "field_goals_attempted"),
    ("soccer", "team_stats", "goals", "shots"),
])
def test_rates_use_paired_coverage_and_comparison_definitions(tmp_path, sport, dataset, numerator, denominator):
    from sports_analyst.analysis.research.semantics import assert_comparable

    team = "recent_team" if sport == "nfl" else "team_abbreviation" if sport == "nba" else "team_id"
    data = {"game_id": ["1", "2", "3"], team: ["A"] * 3, "athlete_id": ["7"] * 3,
            numerator: [1., 9., 99.], denominator: [2., 10., None]}
    if sport == "nfl":
        data.update(season=[2025] * 3, week=[1, 2, 3], season_type=["REG"] * 3)
    access, sources = setup_access(tmp_path, sport, [(dataset, data)])
    plan = {"objective": "Recorded efficiency", "dataset_id": "m0", "window": "comparison",
            "grain": contract(sources[0]).grain,
            "measures": [{"op": "rate", "field": numerator, "denominator": denominator, "name": "efficiency"}]}
    payload = access.executor.execute(access.executor.validate(plan)["plan_id"])
    row = payload["rows"][0]
    assert row["efficiency"] == pytest.approx(10 / 12)
    assert row["efficiency_non_null"] == 2 and row["qualifying_rows"] == 3
    assert row["efficiency_numerator"] == 10 and row["efficiency_denominator"] == 12
    definition = payload["measurement_definitions"]["efficiency"]
    prior = SimpleNamespace(context={"objective": "Recorded efficiency", "group": {}, "window": "baseline",
        "measure": {"name": "efficiency"}, "measurement_definition": definition, "model_identities": []})
    assert_comparable([prior], payload, plan["measures"][0], {})
    prior.context["measurement_definition"] = {**definition, "processing_version": "incompatible"}
    with pytest.raises(ValueError, match="incompatible definitions"):
        assert_comparable([prior], payload, plan["measures"][0], {})
    access.manifests["m0"] = sources[0].model_copy(update={"processing_version": "changed-without-byte-change"})
    with pytest.raises(ValueError, match="provenance changed"):
        access.executor.execute(payload["plan_id"])


@pytest.mark.parametrize("sport,base,context,field", [
    ("nfl", "play_by_play", "ftn_charting", "epa"),
    ("cfb", "player_stats", "team_stats", "passing_yards"),
    ("nba", "player_boxscores", "team_boxscores", "points"),
    ("soccer", "team_stats", "expected_goals", "goals"),
])
def test_research_loop_calculates_cites_and_reuses_both_windows(tmp_path, monkeypatch, sport, base, context, field):
    """Four-sport worker -> measure -> chart -> citation -> follow-up path, offline sources/models."""
    import json

    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from test_data_catalog import MemoryPersistence

    from sports_analyst.analysis.agents import _citation_ledger, _citation_response_model, _resolve_citation_draft
    from sports_analyst.analysis.calculations import complete_calculations
    from sports_analyst.analysis.research.acquisition import Acquisition
    from sports_analyst.analysis.research.presentation import add_research_charts

    team = "posteam" if sport == "nfl" else "team_abbreviation" if sport == "nba" else "team_id"
    values = {"game_id": ["1", "2"], team: ["A", "A"], field: [2., 4.]}
    if sport == "nfl":
        values["play_id"] = ["p1", "p2"]
    if sport in {"cfb", "nba"}:
        values["athlete_id"] = ["7", "7"]
    access, manifests = setup_access(tmp_path, sport, [(base, values)], persistence=MemoryPersistence())
    baseline = tmp_path / "baseline.parquet"
    frame = pl.DataFrame(values).with_columns((pl.col(field) / 2).alias(field))
    frame.write_parquet(baseline)
    manifests.append(manifests[0].model_copy(update={"manifest_id": "baseline", "season": 2024,
        "sha256": sha256_file(baseline), "local_path": str(baseline)}))
    access.manifests["baseline"] = manifests[-1]
    access.app.settings.model_provider = "ollama"
    access.app.settings.research_rounds = 1
    access.app.store.save_manifest = lambda m: manifests.append(m) if m.manifest_id not in {s.manifest_id for s in manifests} else None
    downloaded = []
    context_field = {"nfl": "n_defense_box", "cfb": "total_yards", "nba": "points", "soccer": "xg"}[sport]

    def fetch(self, plan, selected_team, player):
        downloaded.append((plan.dataset, plan.season))
        self.state.consume(requests=1, transferred=100)
        if plan.dataset in {"schedules", "play_by_play"} and plan.dataset != context:
            data = {"game_id": ["1", "2"], "event_id": ["1", "2"], "completed": [True, True],
                    "status": ["STATUS_FINAL", "STATUS_FINAL"], "season_type": ["REG", "REG"] if sport == "cfb" else [2, 2],
                    "week": [1, 2], "date": [f"{plan.season}-09-01", f"{plan.season}-09-08"]}
        else:
            data = {"game_id": ["1"], team: ["A"], context_field: [0.5]}
            if sport == "nfl":
                data["play_id"] = ["p1"]
        frame = pl.DataFrame(data)
        path = tmp_path / f"{plan.dataset}-{plan.season}.parquet"
        frame.write_parquet(path)
        return [manifests[0].model_copy(update={"manifest_id": f"new-{plan.dataset}-{plan.season}", "dataset": plan.dataset,
            "season": plan.season, "local_path": str(path), "columns": frame.columns, "row_count": frame.height,
            "sha256": sha256_file(path)})]

    monkeypatch.setattr(Acquisition, "fetch", fetch)

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    first = '''await tools.recordAnalysisPlan({objectives:["Production on context-covered observations"],
existing_evidence_ids:[],required_data:[CONTEXT],calculations:["Compare both covered windows"],limitations:[]});
for(const season of [2024,2025]) await tools.prepareAnalysisData({acquisition_plan:{objective:"Production on context-covered observations",
dataset:CONTEXT,season,round:1}}); "queued";'''.replace("CONTEXT", json.dumps(context))
    second = '''const graph=JSON.parse(await tools.discoverRelationships({})); let ids=[];
for(const [window,base] of [["baseline","baseline"],["comparison","m0"]]) {
const edge=graph.relationships.find(r=>r.left_dataset_id===base && r.right_dataset_id===`new-${CONTEXT}-${window==="baseline"?2024:2025}`);
const checked=JSON.parse(await tools.validateJoinPlan({join_plan:{objective:"Production on context-covered observations",dataset_id:base,
window,grain:GRAIN,steps:[{relationship_id:edge.relationship_id,alias:"ctx",fields:[CONTEXT_FIELD]}],missing:"matched",
measures:[{op:"sum",field:FIELD,name:"production"},{op:"sum",field:"ctx__"+CONTEXT_FIELD,name:"supporting_total"}]}}));
const r=JSON.parse(await tools.executeJoinedAggregate({plan_id:checked.plan_id})); ids.push(...r.evidence.map(e=>e.evidence_id)); }
const refused=JSON.parse(await tools.prepareAnalysisData({acquisition_plan:{objective:"Optional additional enrichment",dataset:CONTEXT,season:2025,round:2}}));
if(refused.status!=="budget_exhausted") throw new Error("Expected an actionable budget refusal");
await tools.finishQuestionReview({evidence_by_objective:{"0":ids},unresolved:{}}); "done";
'''.replace("CONTEXT_FIELD", json.dumps(context_field)).replace("CONTEXT", json.dumps(context)).replace("GRAIN", json.dumps(contract(manifests[0]).grain)).replace("FIELD", json.dumps(field))
    model = Model(responses=[AIMessage(content="", tool_calls=[{"name": "eval", "id": "q", "args": {"code": first}}]),
        AIMessage(content="queued"), AIMessage(content="", tool_calls=[{"name": "eval", "id": "m", "args": {"code": second}}]), AIMessage(content="done")])
    monkeypatch.setattr("sports_analyst.providers.get_provider", lambda _: SimpleNamespace(
        build=lambda settings: SimpleNamespace(chat_model=model, model_id="offline-analytical-model")))
    result = SimpleNamespace(aggregate_evidence=[], executions=[], caveats=[], charts=[])
    complete_calculations(access.app.settings, access.request.question, result, {}, access)
    assert not any(e.tool == "complete_calculations_failed" for e in result.executions), result.executions[-1].parameters
    assert len(result.aggregate_evidence) == 4
    production = [e for e in result.aggregate_evidence if e.context["measure"]["name"] == "production"]
    assert [e.value for e in production] == [1, 2] and all(e.sample_size == 1 for e in production)
    add_research_charts(result)
    assert result.charts and set(result.charts[0].evidence_ids) == {e.evidence_id for e in result.aggregate_evidence}
    ledger, _, _ = _citation_ledger(result.aggregate_evidence, [])
    draft = _citation_response_model(list(ledger)).model_validate({"summary": "Covered production increased.",
        "claims": [{"claim_type": "measured", "statement": "Covered production rose from 1 to 2.", "evidence_refs": list(ledger)}]})
    assert set(_resolve_citation_draft(draft, ledger).claims[0].evidence_ids) == set(ledger.values())
    parent = [e.model_dump(mode="json") for e in result.aggregate_evidence]
    reused = '''const e=JSON.parse(await tools.inspectCalculationInputs({metric:"joined_aggregate"})).evidence;
await tools.recordAnalysisPlan({objectives:["Explain the covered result"],existing_evidence_ids:e.map(x=>x.evidence_id),
required_data:[],calculations:[],limitations:[]});
await tools.finishQuestionReview({evidence_by_objective:{"0":e.map(x=>x.evidence_id)},unresolved:{}}); "done";'''
    model = Model(responses=[AIMessage(content="", tool_calls=[{"name": "eval", "id": "reuse", "args": {"code": reused}}]), AIMessage(content="done")])
    before = list(downloaded)
    replacement = ScopedData(access.app, access.request, None, access.identifier)
    recovered = SimpleNamespace(aggregate_evidence=[], executions=[], caveats=[])
    complete_calculations(access.app.settings, "Explain that result", recovered, {}, replacement)
    assert [e.model_dump(mode="json") for e in recovered.aggregate_evidence] == parent
    assert not any(e.tool == "complete_calculations_failed" for e in recovered.executions)
    assert downloaded == before
    model.i = 0
    followup = SimpleNamespace(aggregate_evidence=list(result.aggregate_evidence), executions=[], caveats=[])
    complete_calculations(access.app.settings, "Explain that result", followup, {}, access)
    assert not any(e.tool == "complete_calculations_failed" for e in followup.executions)
    assert downloaded == before and [e.model_dump(mode="json") for e in result.aggregate_evidence] == parent


@pytest.mark.parametrize("sport", ["cfb", "soccer"])
def test_opponent_acquisition_fetches_only_selected_completed_games(tmp_path, monkeypatch, sport):
    import duckdb

    from sports_analyst.analysis.research.context import acquire_context
    from sports_analyst.analysis.research.contracts import AcquisitionPlan
    from sports_analyst.storage.local import LocalStore

    calendar = "schedules" if sport == "cfb" else "play_by_play"
    game = "game_id" if sport == "cfb" else "event_id"
    access, manifests = setup_access(tmp_path, sport, [(calendar, {
        game: ["1", "2", "3", "4"], "home_team_id": ["12", "12", "88", "12"],
        "away_team_id": ["9", "9", "9", "9"], "completed": [True, True, True, False],
        "status": ["STATUS_FINAL"] * 3 + ["STATUS_SCHEDULED"], "season_type": ["REG"] * 4,
        "date": ["2025-09-01", "2025-09-08", "2025-09-15", "2025-11-01"], "week": [1, 2, 3, 4]})])
    access.request = access.request.model_copy(update={"subject": access.request.subject.model_copy(update={"id": "12", "team_id": "12"}),
        "scope": access.request.scope.model_copy(update={"team": "12"})})
    access.app.store = LocalStore(access.app.settings, LocalPersistenceBackend())
    for manifest in manifests:
        access.app.store.save_manifest(manifest)
    connect, blocked = duckdb.connect, [2]

    def transient_lock(*args, **kwargs):
        if blocked[0]:
            blocked[0] -= 1
            raise duckdb.IOException("The process cannot access the file because it is being used by another process")
        return connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", transient_lock)
    fetched = []
    fail = {"2"}

    def summary(game_id, season):
        fetched.append(game_id)
        if game_id in fail:
            raise OSError("temporary source failure")
        return {"game": game_id}

    def rows(raw):
        return [{"game_id": raw["game"], "team_id": "12", "shots": 12},
                {"game_id": raw["game"], "team_id": "9", "shots": 8}]

    connector = SimpleNamespace(summary=summary, statistics=lambda raw, game, year: (rows(raw), [], []),
        _summary=lambda competition, year, game, **kw: summary(game, year),
        _parse_summary=lambda raw, dataset: pl.DataFrame(rows(raw)))
    access.app.connectors = {sport: connector}
    plan = AcquisitionPlan(objective="Opponent match context", dataset="team_stats", season=2025, purpose="context", team_id="9")
    first = acquire_context(access, plan, "9")[0]
    access.app.store.save_manifest(first)
    assert set(fetched) == {"1", "2"} and first.availability == "partial"
    assert first.coverage["expected_matches"] == 2 and first.coverage["recorded_matches"] == 1
    fail.clear()
    fetched.clear()
    second = acquire_context(access, plan, "9")[0]
    access.app.store.save_manifest(second)
    assert fetched == ["2"] and second.availability == "available"
    assert set(pl.read_parquet(second.local_path)["game_id"]) == {"1", "2"}
    assert first.local_path != second.local_path and Path(first.local_path).exists()
