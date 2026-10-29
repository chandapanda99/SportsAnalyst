"""FotMob shot context for an exact selected match; no network calls on tablet open."""
import json
import re
from collections import Counter
from pathlib import Path

import polars as pl

from sports_analyst.datasets.soccer.enrichment import name_key
from sports_analyst.datasets.nfl import sha256_file


def shot_list(value):
    try:
        decoded = json.loads(value or "[]")
        return decoded if isinstance(decoded, list) else []
    except (TypeError, ValueError):
        return []


def hydrate_shots(store, evidence, competition, visual):
    """Older reports can use an installed, verified match-analytics snapshot."""
    attached = [row for row in visual.soccer_analytics if row.get("provider") == "fotmob" and str(row.get("game_id")) == str(evidence.game_id)]
    if len(attached) == 2 and len({str(row.get("team_id")) for row in attached}) == 2 and any(shot_list(row.get("shots_json")) for row in attached):
        return visual
    rows = []
    for manifest in store.manifests("match_analytics", "soccer", competition, provider_id=None, processing_version=None):
        if manifest.season != evidence.season:
            continue
        local = store.materialize_manifest(manifest)
        if sha256_file(Path(local.local_path)) != manifest.sha256:
            continue
        frame = pl.scan_parquet(local.local_path)
        columns = frame.collect_schema().names()
        if not {"game_id", "shots_json", "provider"} <= set(columns):
            continue
        sample = frame.filter((pl.col("game_id").cast(pl.String) == str(evidence.game_id)) & (pl.col("provider") == "fotmob")).limit(3).collect()
        if sample.height != 2:
            continue
        # Preserve provenance, native identities, all shot fields and model values.
        rows = sample.to_dicts()
        visual = visual.model_copy(update={"soccer_analytics": [*[row for row in visual.soccer_analytics
            if row.get("provider") != "fotmob" or str(row.get("game_id")) != str(evidence.game_id)], *rows],
            "soccer_analytics_manifest_ids": list(dict.fromkeys([*visual.soccer_analytics_manifest_ids, manifest.manifest_id]))})
        break
    return visual


def match_shots(visual, game_id):
    shots, provenance = [], {}
    for row in visual.soccer_analytics:
        if row.get("provider") != "fotmob" or str(row.get("game_id")) != str(game_id):
            continue
        for shot in shot_list(row.get("shots_json")):
            if isinstance(shot, dict) and shot.get("id") is not None and str(shot.get("espn_team_id")) == str(row.get("team_id")):
                shots.append(shot)
                provenance[str(shot["id"])] = {"source_sha256":row.get("source_sha256"), "provider_game_id":row.get("provider_game_id")}
    # Duplicate native IDs are ambiguous, not an invitation to select the first.
    ids = Counter(str(shot["id"]) for shot in shots)
    shots = [shot for shot in shots if ids[str(shot["id"])] == 1]
    proposals = []
    for event in visual.soccer_timeline:
        clock = str(event.get("clock") or "").replace("′", "'").replace("’", "'").replace(" ", "")
        time = re.fullmatch(r"(\d+)'?(?:\+(\d+)'?)?", clock)
        kind = str(event.get("type") or "").lower()
        name = str(event.get("athlete_name") or "")
        period = event.get("period")
        if time and period is None:
            minute, added = int(time[1]), time[2]
            period = 1 if minute < 45 or (minute == 45 and added) else 2 if 45 < minute < 90 or (minute == 90 and added) else None
        candidates = []
        if time and period and event.get("athlete_id") and len(name.split()) >= 2 and not re.search(r"disallow|overturn|no goal|own goal", kind + " " + str(event.get("text") or "").lower()):
            for shot in shots:
                shot_period = {"FirstHalf": 1, "SecondHalf": 2, "FirstExtra": 3, "SecondExtra": 4}.get(shot.get("period"))
                if shot_period != period or str(shot.get("espn_team_id")) != str(event.get("team_id")):
                    continue
                if name_key(shot.get("fullName") or shot.get("playerName")) != name_key(name):
                    continue
                if shot.get("min") != int(time[1]) or (shot.get("minAdded") or 0) != int(time[2] or 0):
                    continue
                outcome = str(shot.get("eventType") or "").lower()
                goal = event.get("scoring_play") is True or ("goal" in kind and "goal kick" not in kind)
                if (goal and outcome == "goal") or (not goal and (
                    ("saved" in kind and "saved" in outcome and not shot.get("isBlocked"))
                    or ("blocked" in kind and shot.get("isBlocked") is True)
                    or ("miss" in kind and outcome in {"miss", "post"}))):
                    candidates.append(shot)
        proposals.append(candidates[0] if len(candidates) == 1 else None)
    used = Counter(str(shot["id"]) for shot in proposals if shot)
    timeline = []
    for event, shot in zip(visual.soccer_timeline, proposals):
        if shot and used[str(shot["id"])] == 1:
            event = {**event, "spatial_provider": "fotmob", "spatial_event_id": str(shot["id"]),
                "spatial_context": {"shot": shot, **provenance[str(shot["id"])]}, "spatial_match_method": "unique_match_team_full_name_period_clock_outcome_v1"}
        timeline.append(event)
    return visual.model_copy(update={"soccer_timeline": timeline})
