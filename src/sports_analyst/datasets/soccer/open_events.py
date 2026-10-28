"""Coverage-driven open events; compatible SPADL/xT retain model and event lineage."""
from __future__ import annotations

import hashlib
import io
import json

import polars as pl

from sports_analyst.analysis.research.state import ResearchLimit
from sports_analyst.datasets.optional import OptionalDependencyError, load_optional_module
from sports_analyst.datasets.soccer.enrichment import SoccerEnrichment, fixture_matches

COMPETITIONS = {"eng.1": {"Premier League"}, "esp.1": {"La Liga"}, "ger.1": {"1. Bundesliga", "Bundesliga"},
    "ita.1": {"Serie A"}, "fra.1": {"Ligue 1"}, "usa.1": {"Major League Soccer", "MLS"},
    "usa.nwsl": {"NWSL"}, "uefa.champions": {"Champions League"}}


def event_rows(raw, actions, fixture, game, model_hash):
    teams = {str(game[f"{side}_team"][f"{side}_team_id"]): str(fixture[f"{side}_team_id"]) for side in ("home", "away")}
    valued = actions.group_by("original_event_id").agg(
        pl.when(pl.col("xt_value").count() > 0).then(pl.col("xt_value").sum()).otherwise(None).alias("xt_value"))
    xt = {str(row["original_event_id"]): row.get("xt_value") for row in valued.iter_rows(named=True)}
    results = {}
    for action in actions.iter_rows(named=True):
        results.setdefault(str(action["original_event_id"]), set()).add(action.get("result_name"))
    rows = []
    for event in raw:
        team = teams.get(str((event.get("team") or {}).get("id")))
        if team is None:
            continue
        location = event.get("location") or []
        kind = (event.get("type") or {}).get("name")
        detail = event.get(str(kind).lower().replace(" ", "_")) or {}
        end = detail.get("end_location") or []
        result = results.get(str(event.get("id")), set())
        rows.append({"game_id": str(fixture["event_id"]), "team_id": team, "id": str(event.get("id")),
            "provider": "statsbomb", "provider_game_id": str(game["match_id"]),
            "provider_player_id": str((event.get("player") or {}).get("id") or ""),
            "player_name": (event.get("player") or {}).get("name"), "event_type": kind,
            "sequence": event.get("index"), "period": event.get("period"), "minute": event.get("minute"),
            "second": event.get("second"), "duration": event.get("duration"),
            "possession": event.get("possession"), "under_pressure": event.get("under_pressure"),
            "possession_team_id": teams.get(str((event.get("possession_team") or {}).get("id"))),
            "play_pattern": (event.get("play_pattern") or {}).get("name"),
            "counterpress": event.get("counterpress"), "off_camera": event.get("off_camera"),
            "body_part": (detail.get("body_part") or {}).get("name"),
            "technique": (detail.get("technique") or {}).get("name"),
            "pass_height": ((event.get("pass") or {}).get("height") or {}).get("name"),
            "pass_length": (event.get("pass") or {}).get("length"),
            "pass_angle": (event.get("pass") or {}).get("angle"),
            "pass_recipient_id": str(((event.get("pass") or {}).get("recipient") or {}).get("id") or ""),
            "pass_recipient_name": ((event.get("pass") or {}).get("recipient") or {}).get("name"),
            "pass_assisted_shot_id": (event.get("pass") or {}).get("assisted_shot_id"),
            "shot_key_pass_id": (event.get("shot") or {}).get("key_pass_id"),
            "shot_type": ((event.get("shot") or {}).get("type") or {}).get("name"),
            "duel_type": ((event.get("duel") or {}).get("type") or {}).get("name"),
            "goalkeeper_type": ((event.get("goalkeeper") or {}).get("type") or {}).get("name"),
            "spadl_result": next(iter(result)) if len(result) == 1 else None,
            "start_x": location[0] * 105 / 120 if len(location) >= 2 else None,
            "start_y": location[1] * 68 / 80 if len(location) >= 2 else None,
            "end_x": end[0] * 105 / 120 if len(end) >= 2 else None,
            "end_y": end[1] * 68 / 80 if len(end) >= 2 else None,
            "coordinate_system": "StatsBomb 120x80 scaled to 105x68; executing-team orientation",
            "outcome": (detail.get("outcome") or {}).get("name"),
            "xg": (event.get("shot") or {}).get("statsbomb_xg"), "xt": xt.get(str(event.get("id"))),
            "xt_model_sha256": model_hash, "source_json": json.dumps(event, sort_keys=True)})
    return rows


class OpenEvents:
    def __init__(self, connector):
        self.source = SoccerEnrichment(connector)

    def prepare(self, competition, season, fixtures, refresh=False, progress=None):
        def fetch(resource):
            return self.source.fetch(competition, season, "statsbomb_open", {"resource": resource}, refresh)
        catalog = fetch("competitions.json")
        calendar = competition in {"usa.1", "usa.nwsl"}
        label = str(season) if calendar else f"{season - 1}/{season}"
        selected = [item for item in catalog if item.get("competition_name") in COMPETITIONS[competition]
                    and item.get("season_name") == label
                    and item.get("competition_gender") == ("female" if competition == "usa.nwsl" else "male")]
        games = [game for item in selected for game in fetch(f"matches/{int(item['competition_id'])}/{int(item['season_id'])}.json")]
        rows, failures, unmatched, missing = [], 0, 0, 0
        for index, fixture in enumerate(fixtures.iter_rows(named=True), 1):
            candidates = []
            for game in games:
                native = {side: {"name": game.get(f"{side}_team", {}).get(f"{side}_team_name"),
                                 "score": game.get(f"{side}_score")} for side in ("home", "away")}
                native["status"] = {"finished": game.get("match_status") == "available", "utcTime": game.get("match_date")}
                if fixture_matches(native, fixture):
                    candidates.append(game)
            if len(candidates) != 1:
                unmatched += 1
                continue
            game = candidates[0]
            try:
                raw = fetch(f"events/{int(game['match_id'])}.json")
                lineup = fetch(f"lineups/{int(game['match_id'])}.json")
                kloppy = load_optional_module("kloppy.statsbomb", "Soccer open events (install the soccer-events extra)")
                soccer = load_optional_module("sportsdataverse.soccer", "Soccer action analysis")
                dataset = kloppy.load(event_data=io.BytesIO(json.dumps(raw).encode()),
                                      lineup_data=io.BytesIO(json.dumps(lineup).encode()))
                model = soccer.load_xthreat_model()
                model_hash = hashlib.sha256(model.xT.tobytes() + json.dumps(model.meta, sort_keys=True).encode()).hexdigest()
                actions = soccer.soccer_xthreat_rate(soccer.soccer_spadl(dataset, game_id=str(game["match_id"])), model=model)
                rows.extend(event_rows(raw, actions, fixture, game, model_hash))
            except (ResearchLimit, OptionalDependencyError):
                raise
            except ValueError:
                missing += 1
            except Exception:
                failures += 1
            if progress:
                progress(index, fixtures.height)
        frame = pl.from_dicts(rows, infer_schema_length=None) if rows else pl.DataFrame()
        return frame, {"expected_matches": fixtures.height, "recorded_matches": frame["game_id"].n_unique() if rows else 0,
                       "failed_requests": failures, "unmapped_matches": unmatched, "incompatible_matches": missing}
