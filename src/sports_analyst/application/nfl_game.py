"""Read-only NFL game browsing over locally synced, game-filtered snapshots."""
from __future__ import annotations

import polars as pl

from sports_analyst.models import PlayEvidence


def game_plays(application, investigation_id, evidence_id):
    bundle = application.store.get_investigation(investigation_id)
    cited = next((item for item in bundle.play_evidence if item.evidence_id == evidence_id), None)
    if cited is None:
        raise KeyError("Selected play evidence was not found")
    if cited.sport != "nfl":
        raise ValueError("NFL play evidence is required")
    connector, plugin = application._sport("nfl")
    warnings = []
    try:
        manifest = application.store.manifest_for_season(cited.season, "play_by_play", "nfl")
    except KeyError:
        manifest = next((item for item in bundle.dataset_manifests
                         if item.manifest_id == cited.dataset_manifest_id and item.dataset == "play_by_play"), None)
        if manifest is None:
            return fallback(cited)
    try:
        if "game_id" not in manifest.columns or "play_id" not in manifest.columns:
            return fallback(cited)
        frame = application._load_dataset(connector, manifest, predicate=pl.col("game_id") == cited.game_id)
        frame = frame.with_columns([
            pl.when(pl.col(name).is_finite()).then(pl.col(name)).otherwise(None).alias(name)
            for name, dtype in frame.schema.items() if dtype in {pl.Float32, pl.Float64}])
        frame = frame.drop_nulls(["game_id", "play_id"]).unique(subset=["game_id", "play_id"], maintain_order=True).sort("play_id")
        if frame.is_empty():
            return fallback(cited)
        if frame.height > 1000:
            raise ValueError("The saved game exceeds the supported play-browser bound")
        plays = plugin._representative_plays(frame, cited.team, manifest, "game-browser", include_all=True)
    except (OSError, RuntimeError, ValueError):
        return fallback(cited)
    sources = {}
    for dataset in ("participation", "ftn_charting", "rosters", "weekly_rosters", "players"):
        available = [item for item in application.store.manifests(dataset, "nfl") if item.season in {0, cited.season}]
        if not available:
            continue
        selected = available[0]
        try:
            predicate = pl.col("game_id") == cited.game_id if "game_id" in selected.columns else (
                pl.col("nflverse_game_id") == cited.game_id if "nflverse_game_id" in selected.columns else None)
            # Never load unrelated national roster history just to browse a game.
            if predicate is None and dataset in {"rosters", "weekly_rosters"} and "season" in selected.columns:
                predicate = pl.col("season") == cited.season
                if "week" in selected.columns and "week" in frame.columns:
                    predicate &= pl.col("week").is_in(frame["week"].drop_nulls().unique().to_list())
                if "team" in selected.columns:
                    teams = set()
                    for column in ("home_team", "away_team", "posteam", "defteam"):
                        if column in frame.columns:
                            teams.update(frame[column].drop_nulls().unique().to_list())
                    if teams:
                        predicate &= pl.col("team").is_in(list(teams))
            sources[dataset] = application._load_dataset(connector, selected, predicate=predicate)
        except (OSError, RuntimeError, ValueError):
            warnings.append(f"{dataset} context could not load")
    plays = plugin._enrich_representative_plays(
        plays, sources.get("participation"), sources.get("ftn_charting"),
        {name: value for name, value in sources.items() if name not in {"participation", "ftn_charting"}})
    # Preserve the exact cited snapshot and selection metadata; browsing never rewrites the report.
    plays = [cited if play.play_id == cited.play_id else play for play in plays]
    if not any(play.play_id == cited.play_id for play in plays):
        plays.append(cited)
        plays.sort(key=lambda play: play.play_id)
        warnings.append("The saved cited play was not present in the current snapshot and has been preserved")
    saved = next((item for item in bundle.dataset_manifests if item.manifest_id == cited.dataset_manifest_id), None)
    if saved and saved.sha256 != manifest.sha256:
        warnings.append("Other plays use the current synced snapshot, which differs from this saved analysis")
    return {"plays": plays, "coverage": f"{frame.height} recorded game plays in the synced snapshot; completeness is not assumed",
            "message": "; ".join(warnings) or "Game context includes both teams and non-analysis plays. "
                       "Only the original cited play is report evidence."}


def fallback(cited: PlayEvidence):
    return {"plays": [cited], "coverage": "Saved cited play only; game play-by-play is unavailable",
            "message": "Sync this NFL season's play-by-play and retry to browse the game. The saved analysis is preserved.",
            "retryable": True}
