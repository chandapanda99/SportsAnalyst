"""Opt-in, bounded secondary acquisition using the shared local/durable leases.

Published assets only. No NCAA scraping, CFBD API keys or national roster scans.
Permissions must be confirmed by the operator; public hosting is not a license.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import UTC, datetime
from urllib.request import Request, urlopen
from uuid import uuid4

import polars as pl

from sports_analyst.datasets.cfb_crosswalk import game_crosswalk
from sports_analyst.datasets.cfb_source_audit import ROOT, public_json
from sports_analyst.datasets.cfbd_audit import RELEASE_API, cached_asset, validated_asset
from sports_analyst.models import DatasetManifest, stable_id

VERSION = "1"
COMPETITION = "college-football"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class SecondarySources:
    def __init__(self, source, settings, *, fetch=public_json, opener=urlopen):
        self.source, self.settings, self.fetch, self.opener = source, settings, fetch, opener
        from sports_analyst.analysis.research.state import ACTIVE_BUDGET, budget_opener, budget_public_json

        if ACTIVE_BUDGET.get() is not None:
            self.fetch, self.opener = budget_public_json, budget_opener

    @staticmethod
    def key(provider, dataset, season, partition):
        return f"providers/{provider}/{VERSION}/{COMPETITION}/{dataset}/{season}/{partition}"

    def cached(self, key, ttl, acquire):
        result = self.source._cached(key, ttl)
        if result is not None:
            return result
        with self.source.lease(key, seconds=600):
            result = self.source._cached(key, ttl)
            if result is None:
                with self.source._request_slots:
                    result = acquire()
                # Exceptions are retried, not cached as empty successes.
                self.source.store(key, result)
            return result

    def input(self, provider, season, game, payload, url, callback):
        checksum = digest(payload)
        key = self.key(provider, "source_payload", season, f"game/{game}/{checksum}.parquet")
        path = self.source.root / key
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f".{uuid4().hex}.tmp")
            try:
                pl.DataFrame({"game_id": [game], "payload_json": [json.dumps(payload, sort_keys=True, allow_nan=False)]}
                             ).write_parquet(temporary)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        with path.open("rb") as stream:
            file_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        receipt_key = self.key(provider, "input_manifests", season, f"game/{game}/{checksum}.json")
        previous = self.source._cached(receipt_key, float("inf"))
        manifest = DatasetManifest(
            manifest_id=stable_id("input", {"provider": provider, "version": VERSION, "season": season,
                                           "game": game, "checksum": checksum}), sport="cfb", competition=None,
            provider_id=provider, processing_version=VERSION, partition_key=f"game:{game}", dataset="source_payload",
            season=season, source_url=url, sha256=file_hash, row_count=1, columns=["game_id", "payload_json"],
            package_version="published-asset", local_path=str(path.resolve()),
            license="Operator-confirmed source usage; see docs/cfb-source-terms.md",
            attribution=f"SportsDataverse published {provider} source; upstream rights retained.",
            **({"acquired_at": previous["acquired_at"]} if previous else {}),
        )
        if callback:
            callback(manifest)
        elif self.source.persistence.durable:
            self.source.persistence.upload_file(f"raw/cfb/{key}", path)
        # Full receipts survive catalog replacement; referenced bytes are immutable.
        receipt = manifest.model_dump(mode="json")
        self.source.store(receipt_key, receipt)
        return receipt

    def ncaa(self, game, season, summary, callback=None):
        ttl = 300 if season >= datetime.now(UTC).year else 365 * 86400
        index_key = self.key("ncaa", "schedules", season, "season.json")

        def index():
            url = f"{ROOT.rsplit('/json', 1)[0]}/schedules/parquet/{season + 1}.parquet"
            request = Request(url, headers={"User-Agent": "OpenSportsAnalyst/2"})
            with self.opener(request, timeout=20) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError("NCAA discovery index exceeds its byte bound")
            lazy = pl.scan_parquet(io.BytesIO(data))
            columns = lazy.collect_schema().names()
            selected = [field for field in ("contest_id", "espn_game_id", "team_name", "date", "academic_year") if field in columns]
            frame = lazy.select(selected).limit(50001).collect()
            if frame.is_empty() or frame.height > 50000 or "contest_id" not in frame.columns:
                raise ValueError("NCAA discovery index has an unsupported schema/size")
            if "academic_year" in frame.columns and frame.filter(pl.col("academic_year") != season + 1).height:
                raise ValueError("NCAA discovery index has an unexpected academic year")
            return {"rows": frame.to_dicts(), "source_url": url}

        document = self.cached(index_key, ttl, index)
        candidates = {str(row["contest_id"]) for row in document["rows"] if str(row.get("espn_game_id")) == game}
        if not candidates:
            # Historical indexes may lack ESPN IDs. This is candidate discovery,
            # never identity approval: every resulting bundle is verified below.
            header = summary.get("header") or {}
            event = (header.get("competitions") or [{}])[0]
            date = str(event.get("date") or "")[:10]
            names = {str((entry.get("team") or {}).get(field) or "").casefold()
                     for entry in event.get("competitors", []) for field in ("displayName", "location", "shortDisplayName")}
            names.discard("")
            for row in document["rows"]:
                name = re.split(r"\s+\(", str(row.get("team_name") or ""), maxsplit=1)[0].casefold()
                try:
                    day = datetime.strptime(str(row.get("date")), "%m/%d/%Y").date()
                    difference = abs((day - datetime.fromisoformat(date).date()).days)
                except ValueError:
                    continue
                if difference <= 1 and name in names:
                    candidates.add(str(row["contest_id"]))
        if len(candidates) > 4:
            raise ValueError("NCAA contest discovery is ambiguous; no broad game crawl was performed")
        verified = []
        for contest in sorted(candidates):
            if not contest.isdigit():
                raise ValueError("Invalid NCAA contest identity")
            url = f"{ROOT}/{contest}.json.gz"

            def acquire_bundle(url=url, contest=contest):
                result = self.fetch(url)
                if (str(result.get("contest_id")) != contest or not result.get("pbp")
                        or len(result["pbp"]) > 1000 or not game_crosswalk(result, summary, game, season)["verified"]):
                    raise ValueError("NCAA contest payload is incomplete or unverified")
                return result

            try:
                raw = self.cached(self.key("ncaa", "raw_plays", season, f"game/{game}/{contest}.json"), ttl, acquire_bundle)
            except ValueError:
                continue  # An unverified discovery candidate is not a cached success.
            if str(raw.get("contest_id")) == contest and game_crosswalk(raw, summary, game, season)["verified"]:
                verified.append((raw, url))
        if len(verified) != 1:
            raise ValueError("No unique verified NCAA contest for the selected game")
        payload, url = verified[0]
        return payload, self.input("ncaa", season, game, payload, url, callback)

    def cfbd(self, game, season, summary, callback=None):
        ttl = 300 if season >= datetime.now(UTC).year else 86400
        release = self.cached(self.key("cfbd", "release_metadata", season, "season.json"), ttl,
                              lambda: self.fetch(RELEASE_API))
        assets = [row for row in release.get("assets", []) if row.get("name") == f"play_by_play_{season}.parquet"]
        if len(assets) != 1:
            raise ValueError("No unique CFBD-derived season asset")
        asset = assets[0]
        _, checksum, _, _ = validated_asset(asset, season)
        # cached_asset validates URL, digest, size and season filename before I/O.
        with self.source.lease(self.key("cfbd", "asset", season, "season"), seconds=600):
            cache_root = self.source.root / "providers/cfbd/1/college-football/season_assets"
            target = cache_root / "cfb/cfbd/audit-v1" / str(season) / checksum / f"play_by_play_{season}.parquet"
            remote = f"raw/cfb/{target.relative_to(self.source.root).as_posix()}"
            if not target.exists() and self.source.persistence.durable:
                self.source.persistence.download_file(remote, target)
            with self.source._request_slots:
                path, reused = cached_asset(asset, season, cache_root, opener=self.opener)
            if self.source.persistence.durable and not reused:
                self.source.persistence.upload_file(remote, path)
        lazy = pl.scan_parquet(path)
        if "game_id" not in lazy.collect_schema():
            raise ValueError("CFBD asset has no game identity")
        selected = lazy.filter(pl.col("game_id").cast(pl.String) == game).limit(1001).collect()
        if selected.is_empty() or selected.height > 1000:
            raise ValueError("CFBD selected game is absent or exceeds the play bound")
        # Original non-finite values remain preserved in the checksum-verified
        # Parquet asset. JSON snapshots represent them as null, never as zero.
        rows = json.loads(selected.write_json())
        payload = {"game_id": game, "season": season, "asset_id": asset["id"], "asset_sha256": asset["digest"],
                   "rows": rows, "modeled_values_policy": "retained only; current models are recomputed from ESPN"}
        from sports_analyst.datasets.cfb_resolution import cfbd_pair

        if not cfbd_pair(payload, summary, [], game, season)[0]:
            raise ValueError("CFBD game/season/team identity is unverified")
        return payload, self.input("cfbd", season, game, payload, asset["browser_download_url"], callback)
