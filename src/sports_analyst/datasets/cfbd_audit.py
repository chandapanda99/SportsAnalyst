"""Explicit, bounded CFBD season-asset audit, never part of normal preparation.

The upstream bulk loader has no game filter. Download once, verify its published
digest, then lazily select only the requested games/columns from the local file.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

import polars as pl
import pyarrow.parquet as pq

RELEASE_API = "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases/tags/cfbfastR_cfb_pbp"
RELEASE_ROOT = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/cfbfastR_cfb_pbp"
MAX_BYTES = 160 * 1024 * 1024


def validated_asset(asset, season):
    name = f"play_by_play_{season}.parquet"
    digest = str(asset.get("digest") or "")
    size = asset.get("size")
    url = f"{RELEASE_ROOT}/{name}"
    if (asset.get("name") != name or asset.get("browser_download_url") != url
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or not isinstance(size, int) or not 0 < size <= MAX_BYTES):
        raise ValueError("Asset identity, size or published checksum is unverified")
    checksum = digest.split(":")[1]
    return name, checksum, size, url


def cached_asset(asset, season, cache_dir, *, opener=urlopen):
    name, checksum, size, url = validated_asset(asset, season)
    directory = Path(cache_dir) / "cfb" / "cfbd" / "audit-v1" / str(season) / checksum
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name

    def valid_file():
        if not path.exists() or path.stat().st_size != size:
            return False
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == checksum

    if valid_file():
        return path, True
    temporary = None
    try:
        deadline = time.monotonic() + 120
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".partial", delete=False) as stream:
            temporary = Path(stream.name)
            request = Request(url, headers={"User-Agent": "OpenSportsAnalyst-source-audit/2"})
            with opener(request, timeout=20) as response:
                total, hasher = 0, hashlib.sha256()
                while chunk := response.read(min(1024 * 1024, size - total + 1)):
                    total += len(chunk)
                    if total > size or time.monotonic() > deadline:
                        raise ValueError("Asset download exceeded its declared size or time bound")
                    stream.write(chunk)
                    hasher.update(chunk)
            if total != size or hasher.hexdigest() != checksum:
                raise ValueError("Asset size/checksum verification failed")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path, False


def audit_season(season, games, cache_dir, *, fetch, opener=urlopen):
    if not 2000 <= season <= 2100 or not games or len(games) > 12 or not all(str(game).isdigit() for game in games):
        raise ValueError("Audit requires a valid season and 1–12 explicit game IDs")
    release = fetch(RELEASE_API)
    assets = [row for row in release.get("assets", []) if row.get("name") == f"play_by_play_{season}.parquet"]
    if len(assets) != 1:
        raise ValueError("No unique published asset for the requested season")
    asset = assets[0]
    path, reused = cached_asset(asset, season, cache_dir, opener=opener)
    lazy = pl.scan_parquet(path)
    schema = lazy.collect_schema()
    metadata = pq.read_metadata(path).metadata or {}
    published_metadata = {key.decode(): value.decode(errors="replace")[:1000] for key, value in metadata.items()
                          if key in {b"sportsdataverse_timestamp", b"sportsdataverse_type"}}
    game_column = next((field for field in ("game_id", "gameId", "id_game") if field in schema), None)
    if game_column is None:
        raise ValueError("Published asset has no recognized game identity field")
    # Bounded projection avoids assembling a national season in memory.
    fields = [field for field in schema if any(word in field.lower() for word in
              ("epa", "wpa", "expected", "model", "version", "participant", "formation", "player", "athlete"))]
    context = [field for field in ("id", "play_id", "id_play", "provider", "home_team_id", "away_team_id",
                                  "season", "home", "away", "offense", "defense",
                                  "period", "down", "distance", "yards_to_goal") if field in schema]
    selected = list(dict.fromkeys([game_column, *context, *fields]))
    # Stay bounded even if a future schema adds hundreds of participant columns.
    if len(selected) > 150:
        raise ValueError("Published asset projection exceeds the audit column bound")
    frame = (lazy.filter(pl.col(game_column).cast(pl.String).is_in([str(game) for game in games]))
             .select(selected).limit(12001).collect())
    if frame.height > 12000:
        raise ValueError("Selected game sample exceeds the audit row bound")
    counts = {str(game): frame.filter(pl.col(game_column).cast(pl.String) == str(game)).height for game in games}
    model_fields = [field for field in selected if "model" in field.lower() or "version" in field.lower()]
    return {"status": "sampled", "season": season, "source_url": asset["browser_download_url"],
            "asset_id": asset["id"], "asset_updated_at": asset.get("updated_at"), "sha256": asset["digest"],
            "asset_bytes": asset["size"], "cache_reused": reused, "requested_game_rows": counts,
            "published_metadata": published_metadata,
            "provider_chain": "SportsDataverse cfbfastR_cfb_pbp release (CFBD-derived), not a direct CFBD API response",
            "selected_columns": selected, "populated_fields": {field: frame[field].drop_nulls().len() for field in fields},
            "model_identity_fields": model_fields,
            "model_identity_values": {field: frame[field].drop_nulls().unique().head(10).to_list() for field in model_fields},
            "automatic_merge_approved": False, "modeled_comparison_approved": False,
            "limitation": "Rows and populated modeled columns are acquisition evidence, not validated play joins or model compatibility. "
                          "No EPA/WPA is mixed into existing comparison windows."}
