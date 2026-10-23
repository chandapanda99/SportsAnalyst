"""Field provenance for CFB evidence; it never turns illustration into fact."""
import json

from sports_analyst.datasets.cfb_source import CORE
from sports_analyst.datasets.providers import FieldObservation, resolve_fields

RECORDED = ("quarter", "clock", "down", "distance", "team_id", "yards_to_goal", "end_yards_to_goal",
            "yards_gained", "home_score", "away_score", "participants", "play_type", "text")
PARSED = ("formation", "pass_direction", "rush_direction", "pass_depth", "air_yards", "yards_after_catch", "no_play")
MODELED = ("epa", "wpa", "cpoe", "cp", "xpass", "pass_oe")


def with_source_provenance(row, version):
    game = row.get("game_id")
    identity = str(row.get("id") or row.get("play_id") or "")
    source_url = row.get("source_url") or (f"{CORE}/events/{game}/competitions/{game}/plays/{identity}" if game else CORE)
    model = f"sportsdataverse:{version}:cfb-spread-free"
    observations = [FieldObservation(
        provider_id="espn", source_record_id=identity, source_url=source_url,
        field=field, value=row[field], method=method, processing_version=version,
        model_id=model if method == "model_derived" else None,
    ) for fields, method in ((RECORDED, "recorded"), (PARSED, "text_parsed"), (MODELED, "model_derived"))
        for field in fields if row.get(field) is not None]
    resolved = resolve_fields(observations, ("espn",), model_id=model)
    resolved["provenance"] = {field: {key: value for key, value in metadata.items() if key not in {"value", "field"}}
                              for field, metadata in resolved["provenance"].items()}
    # Values already live on the row. Store only provenance and conflicts so the
    # record is not doubled in Parquet, prompts, exports and durable bundles.
    return {**row, "source_provenance_json": json.dumps(
        {key: resolved[key] for key in ("provenance", "conflicts", "rejected")}, sort_keys=True)}
