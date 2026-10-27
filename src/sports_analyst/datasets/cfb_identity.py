"""Game-scoped identity resolution; roster membership never implies snap participation."""

from urllib.parse import urlparse

from sports_analyst.analysis.research.state import ContextPool as ThreadPoolExecutor
from sports_analyst.datasets.cfb_plays import IDENTITY_VERSION, source_id, teams_and_athletes
from sports_analyst.datasets.cfb_source import CORE
from sports_analyst.datasets.optional import OptionalDependencyError


def needs_identity_refresh(rows):
    return any((row.get("identity_context_version") or 0) < IDENTITY_VERSION
               or any(not actor.get("name") or not actor.get("position") for actor in row.get("participants") or [])
               for row in rows)


def game_directory(source, game, season, summary, plays, ttl):
    teams, athletes = teams_and_athletes(summary)
    roster, positions, unresolved = [], {}, {}

    def safe_get(url, cache_ttl=ttl):
        try:
            return source.get(url, cache_ttl)
        except OptionalDependencyError:
            raise
        except Exception:
            return {}  # Optional identity enrichment must not hide recorded plays.

    def roster_for(team_id):
        document = safe_get(f"{CORE}/events/{game}/competitions/{game}/competitors/{team_id}/roster")
        if source_id(document.get("team"), "teams") != team_id:
            return []
        entries = document.get("entries") or []
        if len(entries) > 300:
            return []
        result = []
        for entry in entries:
            if entry.get("valid") is False:
                continue
            athlete = entry.get("athlete") or {}
            identity = source_id(athlete, "athletes")
            if not identity or (entry.get("playerId") and str(entry["playerId"]) != identity):
                continue
            # Do not silently relabel current or cross-season athlete references.
            ref = athlete.get("$ref")
            if ref and urlparse(ref).path != f"{urlparse(CORE).path}/seasons/{season}/athletes/{identity}":
                continue
            result.append({"athlete_id": identity, "team_id": team_id,
                           "name": athlete.get("displayName") or entry.get("displayName"),
                           "position": (entry.get("position") or athlete.get("position") or {}).get("abbreviation"),
                           "position_id": source_id(entry.get("position") or athlete.get("position"), "positions"),
                           "starter": entry.get("starter") is True, "did_not_play": entry.get("didNotPlay") is True,
                           "jersey": str(entry.get("jersey") or ""), "identity_source": "ESPN game roster"})
        return result

    with ThreadPoolExecutor(max_workers=source.concurrency) as pool:
        for entries in pool.map(roster_for, teams):
            roster.extend(entries)
        for entry in roster:
            known = athletes.setdefault(entry["athlete_id"], {})
            # Keep fuller box-score names; use the roster for players absent from it.
            for key in ("name", "position", "team_id"):
                if not known.get(key) and entry.get(key):
                    known[key] = entry[key]
                    known[f"{key}_source"] = "ESPN game roster"
                    if key == "team_id":
                        known["team_source"] = "ESPN game roster"
            if entry.get("position_id"):
                positions[entry["position_id"]] = None
        for play in plays:
            for entry in play.get("participants") or []:
                identity = source_id(entry.get("athlete"), "athletes")
                if not identity:
                    continue
                known = athletes.setdefault(identity, {})
                embedded = entry.get("athlete") or {}
                if not known.get("name") and embedded.get("displayName"):
                    known.update(name=embedded["displayName"], name_source="ESPN structured participant")
                if not known.get("name"):
                    unresolved[identity] = None
                position_id = source_id(entry.get("position"), "positions")
                if position_id:
                    positions[position_id] = None

        def resolve_athlete(identity):
            record = safe_get(f"{CORE}/seasons/{season}/athletes/{identity}")
            return identity, record if str(record.get("id")) == identity else {}

        # Resolve missing identities once per game, not once per play or by name.
        for identity, record in pool.map(resolve_athlete, list(unresolved)[:100]):
            known = athletes[identity]
            if record.get("displayName"):
                known.update(name=record["displayName"], name_source="ESPN season athlete")
            # Athlete profiles may expose a new school after a transfer, even
            # through a historical season URL. They can resolve a name, not a stint.
            position = record.get("position") or {}
            if position.get("abbreviation") and not known.get("position"):
                known.update(position=position["abbreviation"], position_source="ESPN season athlete")
            position_id = source_id(position, "positions")
            if position_id:
                positions[position_id] = None
                known.setdefault("position_id", position_id)

        def resolve_position(identity):
            record = safe_get(f"{CORE}/positions/{identity}", 365 * 86400)
            return identity, record.get("abbreviation") if str(record.get("id")) == identity else None

        positions = dict(pool.map(resolve_position, list(positions)[:100]))

    for entry in roster:
        known = athletes[entry["athlete_id"]]
        position = positions.get(entry.get("position_id")) or entry.get("position")
        if not known.get("position") and position:
            known.update(position=position, position_source="ESPN game roster position")
        entry["position"] = position or known.get("position")
        entry["name"] = known.get("name") or entry.get("name")
    for known in athletes.values():
        if not known.get("position") and positions.get(known.get("position_id")):
            known.update(position=positions[known["position_id"]], position_source="ESPN athlete position")
    # Position IDs are per participant: an actual position reference wins over a
    # role-derived schematic guess (e.g. a TE receiving a pass remains a TE).
    return (teams, athletes, positions), list({(entry["team_id"], entry["athlete_id"]): entry for entry in roster}.values())


def with_identity_context(saved, fresh):
    """Upgrade old saved labels without mutating their participants or model values."""
    saved_id = str(saved.get("play_id") or saved.get("id"))
    fresh_id = str(fresh.get("play_id") or fresh.get("id"))
    if not fresh.get("identity_context_version") or saved_id != fresh_id:
        return saved
    if (saved.get("identity_context_version") or 0) > fresh["identity_context_version"]:
        return saved
    actors = {(actor["athlete_id"], actor["role"]): dict(actor) for actor in saved.get("participants") or []}
    for actor in fresh.get("participants") or []:
        key = actor["athlete_id"], actor["role"]
        actors[key] = {**actors.get(key, {}), **{name: value for name, value in actor.items()
                                               if value is not None or name in {"team_id", "team_source"}}}
    return {**saved, "participants": list(actors.values()), "identity_context_version": fresh["identity_context_version"]}
