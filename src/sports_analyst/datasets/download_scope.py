"""Season-aware download discovery and lossless team-game projections."""
from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path

import polars as pl

from sports_analyst.datasets.nfl import REFERENCE_DATASETS
from sports_analyst.datasets.optional import load_optional_module
from sports_analyst.models import DatasetManifest, stable_id

NFL_ESPN = dict(zip(
    (str(i) for i in [*range(1, 31), 33, 34]),
    ["ATL", "BUF", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "TEN", "IND", "KC", "LV", "LA", "MIA", "MIN",
     "NE", "NO", "NYG", "NYJ", "PHI", "ARI", "PIT", "LAC", "SF", "SEA", "TB", "WAS", "CAR", "JAX", "BAL", "HOU"],
    strict=True,
))
NFL_ALIASES = {"STL": "LA", "LAR": "LA", "SD": "LAC", "OAK": "LV", "JAC": "JAX", "WSH": "WAS"}
NBA_HISTORICAL = {"NJN": "BKN", "SEA": "OKC", "VAN": "MEM", "NOH": "NOP", "NOK": "NOP", "CHH": "CHA"}


def canonical_team(sport, value):
    token = str(value or "").strip().upper()
    if sport == "nfl":
        from sports_analyst.plugins.nfl_shared import NFL_TEAMS

        token = NFL_ESPN.get(token, NFL_ALIASES.get(token, token))
        return token if token in NFL_TEAMS else None
    if sport == "nba":
        from sports_analyst.plugins.nba import canonical_nba_team

        return canonical_nba_team(NBA_HISTORICAL.get(token, token))
    return token if token.isdigit() and len(token) <= 16 else None


@lru_cache(maxsize=64)
def _catalog(sport, season, competition, refresh_bucket):
    module = load_optional_module(f"sportsdataverse.{sport}", "Download scope discovery")
    if sport == "soccer":
        from sports_analyst.datasets.soccer.connector import SOCCER_COMPETITIONS

        if competition not in SOCCER_COMPETITIONS:
            raise ValueError("Select a supported soccer competition")
        provider_season = season - int(not SOCCER_COMPETITIONS[competition][1])
        raw = module.espn_soccer_standings(league=competition, season=provider_season,
                                          return_parsed=False, timeout=20, num_retries=1)
        recorded_season = (raw.get("season") or {}).get("year")
        if recorded_season is not None and int(recorded_season) != provider_season:
            raise ValueError("Standings did not return the requested season; historical membership is unverified")
        teams, groups = {}, {}

        def walk(node, parent=None, depth=0):
            if depth > 5:
                raise ValueError("Unsupported standings hierarchy")
            name = str(node.get("name") or node.get("abbreviation") or "")
            identity = str(node.get("id") or node.get("abbreviation") or name)
            entries = (node.get("standings") or {}).get("entries", [])
            group = identity if parent is not None and entries else None
            if group:
                groups[group] = {"value": group, "label": name or identity}
            for entry in entries:
                team = entry.get("team") or {}
                if str(team.get("id", "")).isdigit():
                    teams[str(team["id"])] = {"value": str(team["id"]), "label": team.get("displayName") or team["id"],
                                               "conference_id": group, "division_id": None}
            for child in node.get("children", []):
                walk(child, identity, depth + 1)

        walk(raw)
        if not teams:
            raise ValueError("No season-specific soccer standings are available; try another season or download the competition")
        if len(groups) < 2:
            groups = {}
            for team in teams.values():
                team["conference_id"] = None
        return {"teams": sorted(teams.values(), key=lambda row: row["label"]), "conferences": list(groups.values()), "divisions": []}
    members = getattr(module, f"load_{sport}_team_group_seasons")([season], return_as_pandas=False)
    groups = getattr(module, f"load_{sport}_group_seasons")(return_as_pandas=False)
    members = members.filter(pl.col("season") == season)
    groups = groups.filter(pl.col("season") == season)
    teams = []
    for row in members.iter_rows(named=True):
        identity = canonical_team(sport, row["team_id"])
        if identity:
            teams.append({"value": identity, "label": row.get("team_name") or identity,
                          "conference_id": row.get("conference_id"), "division_id": row.get("division_id")})
    if not teams:
        raise ValueError("No verified team memberships are published for this season")
    return {"teams": sorted(teams, key=lambda row: row["label"]), **{
        level + "s": [{"value": row["group_id"], "label": row.get("name") or row["group_id"],
                       "parent_id": row.get("parent_group_id")} for row in groups.iter_rows(named=True)
                      if row["level"] == level and any(team.get(level + "_id") == row["group_id"] for team in teams)]
        for level in ("conference", "division")}}


def download_catalog(sport, season, competition=None):
    if sport not in {"nfl", "nba", "soccer"} or not 1920 <= season <= 2100:
        raise ValueError("Select a supported sport and season")
    return {"sport": sport, "season": season, "competition": competition,
            **_catalog(sport, season, competition, int(time.time() // 3600))}


def resolve_download_teams(sport, seasons, competition=None, team_ids=None, conference_id=None, division_id=None):
    if sum(bool(value) for value in (team_ids, conference_id, division_id)) > 1:
        raise ValueError("Choose one download scope: teams, conference, or division")
    if not any((team_ids, conference_id, division_id)):
        return None
    result = {}
    for season in sorted(set(seasons)):
        if team_ids:
            teams = [canonical_team(sport, identity) for identity in team_ids]
            if not all(teams):
                raise ValueError("Select valid source team identifiers")
            # Explicit team selection is independent of discovery availability.
        else:
            catalog = download_catalog(sport, season, competition)
            field, value = ("division_id", division_id) if division_id else ("conference_id", conference_id)
            teams = [row["value"] for row in catalog["teams"] if row.get(field) == value]
            if not teams:
                raise ValueError(f"The selected group has no verified members in {season}; select another season or group")
        result[season] = sorted(set(teams))
    if sum(map(len, result.values())) > 1000:
        raise ValueError("Choose at most 1,000 team-season selections per download")
    return result


def team_frame(frame, sport, team, games=None):
    """Keep both teams' rows for selected games, never only the selected offense."""
    if frame.is_empty():
        return frame
    expressions = []
    def matches(name):
        identities = frame[name].cast(pl.String).drop_nulls().unique().to_list()
        selected = [value for value in identities if canonical_team(sport, value) == team]
        return pl.col(name).cast(pl.String).is_in(selected)

    for name in ("home_team", "away_team", "home_team_id", "away_team_id", "home_team_abbrev", "away_team_abbrev",
                 "home_team_abbreviation", "away_team_abbreviation"):
        if name in frame.columns:
            expressions.append(matches(name))
    game_field = next((name for name in ("game_id", "event_id", "nflverse_game_id") if name in frame.columns), None)
    if expressions:
        return frame.filter(pl.any_horizontal(expressions))
    if game_field and games is not None:
        selected = frame.filter(pl.col(game_field).cast(pl.String).is_in(list(games)))
        if selected.height or not games:
            return selected
    for name in ("team", "team_abbr", "team_abbreviation", "team_id", "recent_team", "posteam", "defteam", "club_code"):
        if name in frame.columns:
            expressions.append(matches(name))
    if not expressions and game_field and sport == "nfl":
        # nflverse game IDs encode season, week, away, home. ESPN IDs do not.
        parts = pl.col(game_field).cast(pl.String).str.split("_")
        expressions = [parts.list.get(index, null_on_oob=True).map_elements(
            lambda value: canonical_team(sport, value), return_dtype=pl.String) == team for index in (2, 3)]
    if not expressions:
        raise ValueError("This package has no verified team or game keys for scoped storage; download it with the full league scope")
    selected = frame.filter(pl.any_horizontal(expressions))
    if game_field:
        ids = selected[game_field].cast(pl.String).unique().to_list()
        return frame.filter(pl.col(game_field).cast(pl.String).is_in(ids))
    return selected


def project_manifest(connector, manifest, team, games=None):
    frame = connector.load(manifest)
    selected = team_frame(frame, manifest.sport, team, games)
    root = Path(manifest.local_path).parent
    path = root / "partitions" / "team" / team / str(manifest.season) / f"{manifest.dataset}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    selected.write_parquet(path)
    projected = connector.manifest_for(path, manifest.season, selected, manifest.dataset)
    return DatasetManifest.model_validate({**projected.model_dump(),
        "manifest_id": stable_id("dataset", {"source": manifest.manifest_id, "team": team, "sha256": projected.sha256}),
        "partition_key": f"team:{team}", "acquired_at": manifest.acquired_at,
        "availability": "source_unavailable" if selected.is_empty() and manifest.availability == "available" else manifest.availability,
        "availability_message": f"No recorded rows for {team} in this package and season." if selected.is_empty()
        else manifest.availability_message,
        "input_manifest_ids": [],
        "download_scope": "team", "source_scope": "league", "source_sha256": manifest.sha256,
        "coverage": {**manifest.coverage, "league_benchmarks_available": 0},
    })


def sync_team_partitions(app, seasons, datasets, sport, teams_by_season, report, register):
    """Fetch a bulk source once, publish only isolated selected-team snapshots."""
    from sports_analyst.application.preparation import current_season, reusable

    connector = app.connectors[sport]
    result = []
    selected = list(dict.fromkeys(datasets or (
        ["play_by_play"] if sport == "nfl" else ["play_by_play", "schedules", "team_boxscores", "player_boxscores"])))
    if sport == "nfl":
        from sports_analyst.datasets.nfl import SUPPORTED_DATASETS

        supported = set(SUPPORTED_DATASETS)
    else:
        from sports_analyst.datasets.nba import NBA_DATASETS

        supported = set(NBA_DATASETS)
    if unknown := set(selected) - supported:
        raise ValueError(f"Unsupported {sport.upper()} packages: {sorted(unknown)}")
    # A small schedule supplies verified game IDs for packages without team keys.
    work = ["schedules", *[dataset for dataset in selected if dataset != "schedules"]]
    total_work = len(set(seasons)) * len(work)
    item_index = 0
    for season in sorted(set(seasons)):
        game_ids = {}
        for dataset in work:
            def source_progress(phase, name, year, completed, total, index=item_index):
                fraction = {"downloading": 0.05, "processing": 0.55, "downloaded": 0.7}.get(phase, 0.1)
                report("processing" if phase == "downloaded" else phase, name, year, index, total_work, fraction)

            retained_source = False
            cache_root = connector.settings.raw_dir if sport == "nfl" else connector.data_dir
            receipt = cache_root / ".scoped-sources" / str(season) / f"{dataset}.json"
            try:
                source = app.store.manifest_for_season(0 if dataset in REFERENCE_DATASETS and sport == "nfl" else season, dataset, sport)
                retained_source = True
                if not reusable(source, current_season(sport, None)):
                    raise KeyError("refresh current source")
                source = app.store.materialize_manifest(source)
            except KeyError:
                source = None
                if not retained_source and receipt.exists():
                    try:
                        cached = DatasetManifest.model_validate_json(receipt.read_text(encoding="utf-8"))
                        if Path(cached.local_path).exists() and reusable(cached, current_season(sport, None)):
                            connector.load(cached)  # Verify source integrity before reuse.
                            source = cached
                    except (OSError, ValueError):
                        pass
                if source is None:
                    acquired = connector.sync([season], [dataset], progress_callback=source_progress)
                    source = acquired[0]
                    receipt.parent.mkdir(parents=True, exist_ok=True)
                    receipt.write_text(source.model_dump_json(), encoding="utf-8")
                if retained_source:
                    register(source)
            if (sport == "nfl" and dataset in REFERENCE_DATASETS
                    or sport == "nba" and dataset in {"player_crosswalk", "schedule_crosswalk"}):
                register(source)
                result.append(source)
                item_index += 1
                continue
            for team_index, team in enumerate(teams_by_season[season]):
                try:
                    previous = app.store.manifest_for_season(season, dataset, sport, partition_key=f"team:{team}")
                    previous = app.store.materialize_manifest(previous)
                except KeyError:
                    previous = None
                if previous and previous.source_sha256 == source.sha256 and Path(previous.local_path).exists():
                    projected = previous.model_copy(update={"acquired_at": source.acquired_at})
                else:
                    projected = project_manifest(connector, source, team, game_ids.get(team))
                if dataset == "schedules":
                    schedule = connector.load(projected)
                    field = next((name for name in ("game_id", "event_id") if name in schedule.columns), None)
                    if field:
                        game_ids[team] = set(schedule[field].cast(pl.String).to_list())
                register(projected)
                result.append(projected)
                report("processing", dataset, season, item_index, total_work,
                       .75 + .2 * (team_index + 1) / len(teams_by_season[season]), f"Preparing {team} game data")
            item_index += 1
            report("downloaded", dataset, season, item_index, total_work)
    return result
