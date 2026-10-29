"""Question-driven acquisition through existing, budgeted provider adapters."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import polars as pl

from sports_analyst.analysis.research.contracts import AcquisitionPlan, contract, family
from sports_analyst.analysis.research.state import ACTIVE_BUDGET, ResearchLimit, ResearchState
from sports_analyst.models import DatasetManifest, stable_id

logger = logging.getLogger(__name__)


def packages(sport):
    from sports_analyst.datasets.cfb import CFB_DATASETS
    from sports_analyst.datasets.nba import NBA_ALL_DATASETS
    from sports_analyst.datasets.nfl import SUPPORTED_DATASETS

    return {"nfl": list(SUPPORTED_DATASETS), "nba": list(NBA_ALL_DATASETS), "cfb": CFB_DATASETS,
            "soccer": ["play_by_play", "team_stats", "lineups", "key_events", "expected_goals", "match_analytics", "asa_analytics",
                       "open_events", "match_players",
                       "understat_team_matches", "understat_player_matches", "understat_shots",
                       "player_game_logs", "player_expected_goals", "season_statistics"]}[sport]


def dependencies(sport, dataset, player=False):
    """Adapter-owned dependencies, not model-supplied package/URL graphs."""
    if sport == "cfb" and dataset != "schedules":
        return ["schedules"]
    if sport == "soccer":
        if dataset.startswith("understat_"):
            return ["play_by_play"]
        if dataset in {"player_expected_goals", "season_statistics"}:
            return ["play_by_play", "lineups"]
        if dataset in {"team_stats", "lineups", "key_events", "expected_goals", "match_analytics",
                       "asa_analytics", "open_events", "match_players"}:
            return ["play_by_play"]
    if sport == "nba" and dataset not in {"schedules", "stats_schedules", "player_crosswalk", "schedule_crosswalk", "team_crosswalk"}:
        return (["stats_schedules", "player_crosswalk"] if player else ["stats_schedules"]) if dataset.startswith("stats_") else ["schedules"]
    return []


def inventory(sport, access=None):
    result = []
    for dataset in packages(sport):
        sample = DatasetManifest(manifest_id="declaration", sport=sport, dataset=dataset, season=0,
            source_url="declared", sha256="", row_count=0, columns=[], package_version="declared", local_path="")
        c = contract(sample)
        installed = [m for m in access.manifests.values() if m.dataset == dataset] if access else []
        supported = True
        if sport == "nba":
            from sports_analyst.datasets.nba import NBA_DATASETS

            supported = dataset in NBA_DATASETS
        if sport == "nfl":
            from sports_analyst.datasets.nfl import DIRECT_PARQUET_PATHS

            supported = dataset in DIRECT_PARQUET_PATHS or dataset.startswith("nextgen_") or dataset in {"schedules", "players", "teams"}
        if sport == "soccer" and dataset == "asa_analytics" and access:
            supported = access.request.scope.competition in {"usa.1", "usa.nwsl"}
        if sport == "soccer" and dataset.startswith("understat_") and access:
            from sports_analyst.datasets.soccer.understat import LEAGUES

            supported = (access.request.scope.competition in LEAGUES and access.app.settings.soccer_understat_enabled)
        result.append({"dataset": dataset, "grain": c.grain, "namespace": c.namespace,
                       "installed_manifest_ids": [m.manifest_id for m in installed],
                       "acquisition": "supported_adapter" if supported else "installed_only_no_verified_download",
                       "dependencies": dependencies(sport, dataset, bool(access and access.request.subject and access.request.subject.type == "player")),
                       "verification": "declared; verify source coverage and schema before measurement"})
        if dataset.startswith("understat_"):
            result[-1].update(provider="understat", acquisition_package="soccerdata:1.9.0",
                possible_fields=["expected_goals", "provider_player_id", "xg_chain", "xg_buildup", "minute", "x", "y"],
                description="Understat xG, native player-match counters or shot events. No xGOT; ESPN athlete mapping required.",
                coverage_verified=False)
        if sport == "soccer" and dataset in {"match_analytics", "asa_analytics", "open_events", "match_players"}:
            from sports_analyst.datasets.soccer.statistics import MATCH_METRICS

            described = {
                "match_analytics": "FotMob team-match counters, xG/xGOT, shots, passing, defense, set pieces and recorded physical context",
                "asa_analytics": "ASA MLS/NWSL per-game team-model xG, player-shot-model xG and expected points; source availability unverified",
                "match_players": "Native FotMob player-match stats; identity crosswalk required for a selected ESPN athlete",
                "open_events": "Matched StatsBomb open games: event sequences, action coordinates, pass/shot/duel qualifiers and versioned xT",
            }
            fields = sorted({field for metric in MATCH_METRICS.values() if metric[1] == dataset
                             for field in (metric[3], metric[4]) if field})
            if dataset == "open_events":
                fields = ["event_type", "provider_player_id", "player_name", "minute", "possession", "under_pressure",
                          "start_x", "start_y", "end_x", "end_y", "pass_length", "pass_recipient_name", "xg", "xt", "xt_model_sha256"]
            elif dataset == "match_players":
                fields = ["provider_player_id", "name", "minutes_played", "expected_goals", "expected_assists", "interceptions"]
            result[-1].update({"description": described[dataset], "possible_fields": fields,
                               "coverage_verified": False, "identity_note": "Canonical fixture/team IDs only; never join native athletes by name"})
    return result


class Acquisition:
    def __init__(self, access, identifier):
        self.access = access
        self.state = ResearchState(access.app, identifier)
        self.round = (self.state.read("rounds") or {"next": 1})["next"]
        self.identity = {"sport": access.request.sport, "scope": access.request.scope.model_dump(mode="json"),
                         "subject": access.request.subject.model_dump(mode="json") if access.request.subject else None}
        saved = self.state.read("acquisition_queue")
        if saved and saved["identity"] != self.identity:
            raise ValueError("Persisted acquisition scope changed; use a new investigation identity")
        # Reattach exact completed inputs, including context partitions omitted by
        # initial subject-scoped discovery. No new primary observations are added.
        ids = {key for row in (saved or {}).get("items", {}).values() for key in row.get("receipt", {}).get("manifests", [])}
        if ids:
            for manifest in access.app.store.manifests(sport=access.request.sport, competition=access.request.scope.competition,
                                                     provider_id=None, processing_version=None):
                if manifest.manifest_id in ids:
                    access.manifests[manifest.manifest_id] = manifest

    @property
    def pending(self):
        saved = self.state.read("acquisition_queue") or {"items": {}}
        return [AcquisitionPlan.model_validate(row["plan"]) for row in saved["items"].values()
                if row["status"] in {"queued", "running"}]

    def plan_dependencies(self, plan):
        request = self.access.request
        player = bool(request.subject and request.subject.type == "player")
        ordered = {}

        def visit(item):
            key = stable_id("acquire-plan", item.model_dump(mode="json"))
            if key in ordered:
                return key
            child_ids = []
            for dataset in dependencies(request.sport, item.dataset, player):
                child_ids.append(visit(item.model_copy(update={"dataset": dataset, "fields": []})))
            ordered[key] = {"plan": item.model_dump(mode="json"), "dependencies": child_ids, "status": "queued"}
            return key

        visit(plan)
        return ordered

    def queue(self, raw):
        plan = AcquisitionPlan.model_validate(raw)
        request = self.access.request
        if plan.dataset not in packages(request.sport) or plan.season not in request.scope.included_seasons:
            raise ValueError("Unsupported package or season outside the investigation; inspect acquisition capabilities")
        if plan.round != self.round:
            raise ValueError(f"Current acquisition round is {self.round}")
        if plan.round > self.access.app.settings.research_rounds:
            raise ResearchLimit("Acquisition/replanning round limit exceeded; use scoped Data Management")
        if plan.purpose == "primary" and plan.team_id and plan.team_id != self.primary_team():
            raise ValueError("Primary acquisition cannot change the selected subject")
        decisions = self.plan_dependencies(plan)
        from sports_analyst.application.preparation import coordinator

        with coordinator(self.access.app).lease(f"research-queue:{self.state.root.name}", seconds=60):
            saved = self.state.read("acquisition_queue") or {"identity": self.identity, "items": {}}
            for key, decision in decisions.items():
                saved["items"].setdefault(key, decision)
            self.state.write("acquisition_queue", saved)
        return {"status": "queued", "plan": plan.model_dump(mode="json"),
                "dependency_decisions": decisions,
                "message": "Worker preparation runs outside Interpreter evaluation, then resumes planning"}

    def primary_team(self):
        request = self.access.request
        return str(request.subject.id if request.subject and request.subject.type == "team" else
                   request.subject.team_id if request.subject else request.scope.team)

    def related_team(self, team, season):
        """Membership comes from selected-season schedules, never current player profiles."""
        from sports_analyst.analysis.research.executor import JoinExecutor

        selected = self.primary_team()
        if team == selected:
            return True
        subject = self.access.request.subject
        player_games = set()
        if subject and subject.type == "player":
            for manifest in self.access.manifests.values():
                c = contract(manifest)
                if manifest.season != season or c.grain != "player_game" or not c.player or not c.game or not c.team:
                    continue
                records = JoinExecutor(self.access).scan(manifest, [c.player, c.team, c.game]).filter(
                    pl.col(c.player).cast(pl.String) == subject.id).collect()
                if team in records[c.team].cast(pl.String).to_list():
                    return True  # Recorded transferred-school membership, not profile metadata.
                player_games.update(records[c.game].cast(pl.String).to_list())
        for manifest in self.access.manifests.values():
            c = contract(manifest)
            if c.grain != "game" or manifest.season != season:
                continue
            ids = [key for key in ("home_team_id", "away_team_id", "home_team", "away_team",
                                   "home_team_abbrev", "away_team_abbrev") if key in manifest.columns]
            if not ids:
                continue
            predicate = (pl.col(c.game).cast(pl.String).is_in(sorted(player_games)) if player_games else
                         pl.any_horizontal(pl.col(k).cast(pl.String) == selected for k in ids))
            frame = JoinExecutor(self.access).scan(manifest, [*ids, c.game]).filter(predicate).select(ids).unique().collect()
            if any(str(team) in frame[k].cast(pl.String).to_list() for k in ids):
                return True
        return False

    def run(self):
        from sports_analyst.application.preparation import coordinator

        # One durable owner drains this investigation's persisted queue. A worker
        # replacement resumes running entries after lease expiry, not from RAM.
        with coordinator(self.access.app).lease(f"research-drain:{self.state.root.name}", seconds=1800):
            return self._run()

    def save_queue(self, saved):
        from sports_analyst.application.preparation import coordinator

        with coordinator(self.access.app).lease(f"research-queue:{self.state.root.name}", seconds=60):
            latest = self.state.read("acquisition_queue") or saved
            latest["items"].update(saved["items"])
            self.state.write("acquisition_queue", latest)
            return latest

    def _run(self):
        from sports_analyst.application.preparation import coordinator, current_season, reusable
        from sports_analyst.datasets.availability import missing_source

        output = []
        saved = self.state.read("acquisition_queue") or {"identity": self.identity, "items": {}}
        pending, visited = [], set()

        def order(key):
            if key in visited:
                return
            visited.add(key)
            row = saved["items"][key]
            for dependency in row["dependencies"]:
                order(dependency)
            if row["status"] in {"queued", "running"}:
                pending.append((key, row))

        for key in saved["items"]:
            order(key)
        app, request = self.access.app, self.access.request
        for plan_id, entry in pending:
            plan = AcquisitionPlan.model_validate(entry["plan"])
            entry["status"] = "running"
            saved = self.save_queue(saved)
            token = ACTIVE_BUDGET.set(self.state)
            receipt = {"plan": plan.model_dump(mode="json"), "manifests": []}
            try:
                self.state.consume(round=plan.round)
                failed_dependencies = [key for key in entry["dependencies"]
                                       if saved["items"][key].get("receipt", {}).get("status") not in {"available", "partial"}]
                if failed_dependencies:
                    raise ValueError(f"Required acquisition dependencies failed: {failed_dependencies}; retry them in Data Management")
                team = plan.team_id or self.primary_team()
                if plan.purpose == "context" and not self.related_team(team, plan.season):
                    raise ValueError("Context team must be a verified opponent in the selected subject's schedules")
                partition = f"team:{team}" if request.sport in {"cfb", "soccer"} else None
                player = request.subject and request.subject.type == "player"
                if player and request.sport == "cfb" and plan.purpose == "primary":
                    partition = f"player:{request.subject.id}"
                key = stable_id("acquisition", {"sport": request.sport, "competition": request.scope.competition,
                                               "partition": partition, "dataset": plan.dataset, "season": plan.season})
                with coordinator(app).lease(key, seconds=1800):
                    installed = app.store.manifests(plan.dataset, request.sport, request.scope.competition, partition)
                    ready = [m for m in installed if m.dataset == plan.dataset and m.season in {0, plan.season} and m.row_count
                             and reusable(m, current_season(request.sport, request.scope.competition))
                             and (app.store.persistence.durable or Path(m.local_path).exists())]
                    if request.sport == "nba" and (plan.dataset.startswith("stats_") or plan.dataset == "lineups"):
                        ready = [m for m in ready if "source_season" in m.columns]
                    if plan.purpose == "context" and request.sport in {"cfb", "soccer"}:
                        ready = []  # The adapter reuses exact game partitions, not an opponent's unrelated season snapshot.
                    if ready:
                        produced = ready
                    else:
                        self.state.consume(attempt=key, round=plan.round)
                        progress = getattr(self.access, "progress", lambda _: None)
                        progress(f"Fetching {request.sport.upper()} {plan.dataset.replace('_', ' ')} · {plan.season}")
                        produced = self.fetch(plan, team, player)
                    if self.state.consume().get("blocked"):
                        raise ResearchLimit("Acquisition budget exhausted; incomplete source responses cannot be treated as complete")
                    if not produced:
                        raise ValueError("No usable manifests were produced")
                    for manifest in produced:
                        if (manifest.sport != request.sport or manifest.competition != request.scope.competition
                                or manifest.season not in {0, plan.season}):
                            raise ValueError("Acquired manifest scope mismatch")
                        app.store.save_manifest(manifest)
                        self.access.manifests[manifest.manifest_id] = manifest
                    target = [m for m in produced if family(m.dataset) == plan.dataset]
                    if not target:
                        raise ValueError("Provider returned dependencies but no requested dataset")
                    statuses = {m.availability for m in target}
                    status = ("available" if all(m.availability == "available" and m.row_count for m in target) else
                              "partial" if any(m.row_count for m in target) else
                              "failed" if "download_failed" in statuses else "source_unavailable")
                    receipt.update(status=status, source_states=sorted(statuses),
                                   manifests=[m.manifest_id for m in produced],
                                   coverage=[m.coverage for m in produced])
                    missing = {m.manifest_id: sorted(set(plan.fields) - set(m.columns)) for m in target
                               if not set(plan.fields) <= set(m.columns)}
                    if missing:
                        receipt.update(status="partial", missing_fields=missing)
            except Exception as error:
                if not isinstance(error, (ResearchLimit, ValueError)) and not missing_source(error):
                    logger.exception("research_acquisition_failed sport=%s dataset=%s season=%s", request.sport, plan.dataset, plan.season)
                receipt.update(status="budget_exhausted" if isinstance(error, ResearchLimit) else
                               "source_unavailable" if missing_source(error) else "failed",
                               error_type=type(error).__name__,
                               message=str(error)[:700] if isinstance(error, (ValueError, ResearchLimit)) else
                               "Provider acquisition failed; worker logs contain technical details",
                               action=f"Data Management: {request.sport} / {plan.dataset} / {plan.season}; retry investigation")
            finally:
                ACTIVE_BUDGET.reset(token)
            self.state.write(stable_id("receipt", receipt), receipt)
            entry.update(status="completed", receipt=receipt)
            # Merge newly queued items without losing their durable decisions.
            saved = self.save_queue(saved)
            output.append(receipt)
        if pending:
            self.round = max(self.round, max(row["plan"]["round"] for _, row in pending) + 1)
        self.state.write("rounds", {"next": self.round})
        return output

    def fetch(self, plan, team, player):
        app, request = self.access.app, self.access.request
        connector = app.connectors[request.sport]
        if plan.purpose == "context" and request.sport in {"cfb", "soccer"}:
            from sports_analyst.analysis.research.context import acquire_context

            return acquire_context(self.access, plan, team)
        def heartbeat(*args, **kwargs):
            self.state.consume()
            getattr(self.access, "progress", lambda _: None)(f"Preparing {request.sport.upper()} {plan.dataset} · {plan.season}")
        if request.sport in {"nfl", "nba"}:
            return [self.bulk(plan)]
        if request.sport == "cfb":
            if plan.dataset == "enriched_plays":
                import importlib.metadata

                from sports_analyst.datasets.cfb_model_identity import model_identity

                # Only content-hashed INSTALLED models; never download/install a model from agent instructions.
                model_identity(importlib.metadata.version("sportsdataverse"))
                options = {"athlete_id": request.subject.id} if player and plan.purpose == "primary" else {"team_id": team}
                produced = connector.prepare(plan.season, datasets=["schedules"],
                                             manifest_callback=app.store.save_manifest, **options)
                schedule_manifest = next(m for m in produced if m.dataset == "schedules")
                produced.append(connector.prepare_enriched(plan.season, schedule_manifest.partition_key,
                    connector.load(schedule_manifest), manifest_callback=app.store.save_manifest, progress=heartbeat))
                return produced
            if player and plan.purpose == "primary":
                selected = ["schedules"] if plan.dataset == "recorded_plays" else [plan.dataset]
                produced = connector.prepare(plan.season, athlete_id=request.subject.id, datasets=selected,
                                             manifest_callback=app.store.save_manifest, progress=heartbeat)
                if plan.dataset == "recorded_plays":
                    schedule = connector.load(next(m for m in produced if m.dataset == "schedules"))
                    produced.append(connector.prepare_recorded(plan.season, f"player:{request.subject.id}", schedule,
                                                              app.store.save_manifest, heartbeat,
                                                              feature=self.play_feature(plan)))
                return produced
            if plan.dataset == "recorded_plays" and self.play_feature(plan) == "rendering":
                produced = connector.prepare(plan.season, team_id=team, datasets=["schedules"],
                                             manifest_callback=app.store.save_manifest, progress=heartbeat)
                schedule = connector.load(next(m for m in produced if m.dataset == "schedules"))
                produced.append(connector.prepare_recorded(plan.season, f"team:{team}", schedule, app.store.save_manifest,
                                                          heartbeat, feature="rendering"))
                return produced
            return connector.sync([plan.season], [plan.dataset], team_ids=[team], manifest_callback=app.store.save_manifest,
                                  progress_callback=heartbeat)
        if plan.dataset in {"player_game_logs", "player_expected_goals", "season_statistics"}:
            if not player:
                raise ValueError("Player enrichment requires a selected verified athlete")
            if plan.dataset == "player_game_logs":
                return [connector.player_game_log_manifest(request.scope.competition, plan.season, request.subject.id)]
            candidates = list(self.access.manifests.values())
            schedule = next(m for m in candidates if m.dataset == "play_by_play" and m.season == plan.season)
            lineup = next(m for m in candidates if m.dataset == "lineups" and m.season == plan.season)
            if plan.dataset == "player_expected_goals":
                return [connector.player_expected_goals_manifest(request.scope.competition, plan.season, request.subject.id,
                                                                connector.load(schedule), connector.load(lineup))]
            return [connector.season_statistics_manifest(request.scope.competition, plan.season, "player", request.subject.id,
                                                        connector.load(schedule), connector.load(lineup))]
        return connector.sync([plan.season], [plan.dataset], competition=request.scope.competition, team_id=team,
                              include_expected_goals=False, refresh_seasons={plan.season} if plan.season >= datetime.now(UTC).year else set(),
                              manifest_callback=app.store.save_manifest, progress_callback=heartbeat)

    def play_feature(self, plan):
        from sports_analyst.datasets.cfb_policy import PROVIDER_FIELDS

        settings = self.access.app.settings
        return "rendering" if (settings.cfb_ncaa_enabled and settings.cfb_secondary_usage_confirmed
                               and set(plan.fields) & PROVIDER_FIELDS["ncaa"]) else "analysis"

    def bulk(self, plan):
        """Stream the same published assets as installed loaders; never execute an unmetered loader."""
        from sports_analyst.datasets.nba import NBA_DATASETS
        from sports_analyst.datasets.nfl import DIRECT_PARQUET_PATHS, NFLVERSE_RELEASE_BASE_URL, REFERENCE_DATASETS

        app, sport, dataset, year = self.access.app, self.access.request.sport, plan.dataset, plan.season
        connector = app.connectors[sport]
        if sport == "nfl":
            resource = DIRECT_PARQUET_PATHS.get(dataset)
            if dataset.startswith("nextgen_"):
                resource = f"nextgen_stats/ngs_{dataset.removeprefix('nextgen_')}.parquet"
            resource = {"schedules": "schedules/games.parquet", "players": "players/players.parquet",
                        "teams": "teams/teams_colors_logos.parquet"}.get(dataset, resource)
            if resource is None:
                raise ValueError("No verified bounded asset adapter for package")
            url = NFLVERSE_RELEASE_BASE_URL + resource.format(season=year)
            season = 0 if dataset in REFERENCE_DATASETS else year
            path = app.settings.raw_dir / "research" / f"{dataset}_{season}_{uuid4().hex}.parquet"
        else:
            if dataset not in NBA_DATASETS or year not in NBA_DATASETS[dataset].available_seasons:
                raise ValueError("NBA package does not advertise a snapshot for this season")
            names = {"play_by_play": "play_by_play", "player_boxscores": "player_box", "schedules": "nba_schedule",
                     "team_boxscores": "team_box", "stats_schedules": "nba_schedule", "stats_play_by_play": "nba_play_by_play",
                     "player_crosswalk": "nba_player_crosswalk", "schedule_crosswalk": "nba_schedule_crosswalk",
                     "team_crosswalk": "nba_team_crosswalk", "player_core": "player_core", "player_impact": "nba_player_impact"}
            filename = names.get(dataset, dataset.removeprefix("stats_"))
            # The app's NBA season is the END year (see current_season). Native
            # loaders take START years, but published assets are stamped END year.
            source_year = year
            url = ("https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
                   f"{NBA_DATASETS[dataset][2]}/{filename}_{source_year}.parquet")
            season, path = year, connector.data_dir / "research" / f"{dataset}_{year}_{uuid4().hex}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid4().hex}.part")
        try:
            self.state.fetch(url, temporary)
            scan = pl.scan_parquet(temporary)
            if sport == "nfl" and season and "season" in scan.collect_schema():
                scan = scan.filter(pl.col("season") == year)
            if scan.select(pl.len()).collect().item() == 0:
                raise ValueError("Published asset has no recorded rows for this season")
            if sport == "nba":
                if "season" in scan.collect_schema():
                    scan = scan.filter(pl.col("season") == year).with_columns(pl.col("season").alias("source_season"))
                    if scan.select(pl.len()).collect().item() == 0:
                        raise ValueError("Published NBA season stamp does not match the requested END year")
                scan = connector.normalize(scan, year, dataset)
            normalized = path.with_suffix(f".{uuid4().hex}.normalized")
            try:
                scan.sink_parquet(normalized)
                normalized.replace(path)
            finally:
                normalized.unlink(missing_ok=True)
            return connector.manifest_for(path, season, None, dataset)
        finally:
            temporary.unlink(missing_ok=True)
