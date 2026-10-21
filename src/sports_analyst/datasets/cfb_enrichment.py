"""Game-scoped SportsDataverse model enrichment, with explicit provenance."""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import math
import re

from sports_analyst.datasets.cfb_plays import recorded_play, teams_and_athletes
from sports_analyst.datasets.cfb_rendering import hydrate_rows, render_context
from sports_analyst.datasets.cfb_source import CORE
from sports_analyst.datasets.optional import load_optional_module, optional_dependencies

ADAPTER_VERSION = "3"


def numeric(value):
    try:
        result = float(value) if value is not None else None
        return result if result is not None and math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def athlete_roles(play):
    """Only structured ESPN IDs; deliberately never resolve a text name."""
    roles = {}
    for participant in play.get("participants") or []:
        athlete = participant.get("athlete") or {}
        identity = str(athlete.get("id") or "")
        if not identity.isdigit():
            match = re.search(r"/athletes/(\d+)(?:[/?]|$)", athlete.get("$ref", ""))
            identity = match.group(1) if match else ""
        role = participant.get("type")
        if identity and role in {"passer", "rusher", "receiver"}:
            roles.setdefault(role, set()).add(identity)
    return {f"{role}_id": next(iter(ids)) for role, ids in roles.items() if len(ids) == 1}


def process_summary(game, raw, *, context_only=False):
    """Run the provider's public pipeline against an already acquired summary.

    Disable network identity resolution and decision surfaces: the latter need
    verified market inputs. Publish spread-free WPA, not predictions based on a
    fabricated betting line. All pipeline outputs are retained in the cache.
    """
    with optional_dependencies("College-football advanced play analysis"):
        module = load_optional_module("sportsdataverse.cfb.cfb_pbp", "College-football advanced play analysis")
        processor = module.CFBPlayProcess(
            gameId=int(game),
            join_participants=False,
            odds_override={"gameSpread": 0.0, "overUnder": 0.0, "homeFavorite": True, "gameSpreadAvailable": False},
        )
        summary = copy.deepcopy(raw)
        for key in ("leaders", "broadcasts", "pickcenter", "againstTheSpread", "odds", "winprobability", "scoringPlays", "videos"):
            summary.setdefault(key, [])
        for key in ("boxscore", "format", "gameInfo", "drives", "predictor", "header", "standings"):
            summary.setdefault(key, {})
        processor.json = summary
        output = processor.run_cleaning_pipeline() if context_only else processor.run_processing_pipeline(fourth_down_probs=False, two_pt_probs=False)
        if not (processor.ran_cleaning_pipeline if context_only else processor.ran_pipeline):
            raise ValueError("SportsDataverse could not validate/process this game's play sequence")
    return output


class CFBEnrichment:
    def __init__(self, source):
        self.source = source

    def game(self, game, season, raw, ttl):
        version = importlib.metadata.version("sportsdataverse")
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        key = f"enriched/{season}/{game}/{version}-{ADAPTER_VERSION}-{digest}.json"
        with self.source.lease(f"enrich:{season}:{game}", seconds=600):
            cached = self.source._cached(key, ttl)
            if cached is not None and (
                cached["provenance"]["source_plays"] == cached["provenance"]["processed_plays"]
                or self.source._cached(key, min(ttl, 300)) is not None
            ):
                cached["rows"] = hydrate_rows(cached["rows"], cached.get("pipeline") or {}, version)
                return cached
            # Bound pagination and use the application's timeout/retry transport.
            plays = self.source.collection(f"{CORE}/events/{game}/competitions/{game}/plays", ttl, maximum=800)
            if not plays:
                raise ValueError("No recorded detailed plays are available for this game")
            by_id = {str(play["id"]): play for play in plays if play.get("id") is not None}
            if len(by_id) != len(plays):
                raise ValueError("Source play IDs are missing or duplicated")
            output = process_summary(game, raw)
            normalized = []
            directory = teams_and_athletes(raw)
            seen = set()
            for play in output.get("plays") or []:
                identity = str(play.get("id") or "")
                if identity not in by_id or identity in seen:
                    continue
                seen.add(identity)
                team = str(play.get("start.pos_team.id") or "")
                if not team.isdigit():
                    continue
                recorded = by_id[identity]
                recorded_context = recorded_play(recorded, raw, directory)
                normalized.append(
                    {
                        **recorded_context,
                        **render_context(play, version, recorded_context),
                        "teams_json": json.dumps(list(directory[0].values()), sort_keys=True),
                        "game_id": str(game),
                        "season": season,
                        "play_id": identity,
                        "team_id": team,
                        "text": recorded.get("text"),
                        "quarter": (recorded.get("period") or {}).get("number"),
                        "clock": (recorded.get("clock") or {}).get("displayValue"),
                        "down": (recorded.get("start") or {}).get("down"),
                        "distance": (recorded.get("start") or {}).get("distance"),
                        "scrimmage": play.get("scrimmage_play") is True,
                        "pass": play.get("pass") is True,
                        "rush": play.get("rush") is True,
                        "epa": numeric(play.get("EPA")),
                        "wpa": numeric(play.get("wpa_naive")),
                        "cpoe": numeric(play.get("cpoe")),
                        "cp": numeric(play.get("cp")),
                        "xpass": numeric(play.get("xpass")),
                        "pass_oe": numeric(play.get("pass_oe")),
                        **{f"{role}_id": None for role in ("passer", "rusher", "receiver")},
                        **athlete_roles(recorded),
                        "provider_version": version,
                        "model_family": "SportsDataverse CFB EP / spread-free WP",
                        "source_play_count": len(by_id),
                        "processed_play_count": len(seen),
                    }
                )
            if not normalized or not any(row["epa"] is not None for row in normalized):
                raise ValueError("No usable modeled play values were produced")
            # Do not present unprocessed source plays as a complete game.
            count = len(normalized)
            for row in normalized:
                row["processed_play_count"] = count
            result = {
                "rows": normalized,
                "pipeline": output,
                "teams": list(directory[0].values()),
                "provenance": {
                    "provider_version": version,
                    "adapter_version": ADAPTER_VERSION,
                    "summary_sha256": digest,
                    "wpa_model": "spread-free",
                    "source_plays": len(by_id),
                    "processed_plays": count,
                    "decision_surfaces": "not evaluated: verified market inputs required",
                    "player_attribution": "ESPN structured participants only",
                },
            }
            # A partial sequence is useful but retried rather than cached as complete.
            self.source.store(key, result)
            return result
