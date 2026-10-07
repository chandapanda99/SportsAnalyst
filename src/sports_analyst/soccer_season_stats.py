"""Selected-subject, season-scoped ESPN totals; never substitutes for match data."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import polars as pl

from sports_analyst.soccer_xg import CORE_ROOT, core_statistics

# Only additive counts are combined across disjoint competition stages.
FIELDS = {
    "goals": "totalGoals", "assists": "goalAssists", "shots": "totalShots",
    "shots_on_target": "shotsOnTarget", "passes": "totalPasses",
    "accurate_passes": "accuratePasses", "tackles": "totalTackles",
    "interceptions": "interceptions", "minutes": "minutes", "appearances": "appearances",
    "expected_goals": "expectedGoals", "non_penalty_expected_goals": "expectedGoalsNonPenalty",
}


class SeasonStatisticsSource:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    @staticmethod
    def _request(url: str) -> dict:
        from sportsdataverse.dl_utils import download
        from sportsdataverse.errors import SportsDataverseError
        try:
            response = download(url=url, timeout=30, num_retries=2)
            if response is None:
                raise OSError("ESPN returned no season statistics")
            return response.json()
        except SportsDataverseError as error:
            raise OSError(str(error)) from error

    def _fetch(self, url: str, checkpoint: Path, refresh: bool) -> dict:
        if checkpoint.exists() and not refresh:
            try:
                return json.loads(checkpoint.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        raw = self._request(url)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(raw), encoding="utf-8")
        temporary.replace(checkpoint)
        return raw

    def fetch(
            self, competition: str, season: int, source_season: int, subject_type: str, subject_id: str, stages: set[str], progress=None
    ) -> pl.DataFrame:
        if subject_type not in {"team", "player"} or not subject_id.isdigit():
            raise ValueError("Expected a team/player and numeric ESPN ID")
        root = f"{CORE_ROOT}/{competition}/seasons/{source_season}"
        directory = self.data_dir / competition / str(season) / "season_statistics"
        refresh = season >= datetime.now(UTC).year
        registry = self._fetch(f"{root}/types?limit=100", directory / "types.json", refresh)
        if registry.get("pageCount", 1) != 1 or registry.get("count", 0) > len(registry.get("items") or []):
            raise ValueError("Incomplete ESPN season-type registry")
        types = []
        for item in registry.get("items") or []:
            path = urlparse(item.get("$ref", "")).path
            prefix = urlparse(root).path + "/types/"
            if not path.startswith(prefix) or not path.removeprefix(prefix).isdigit():
                raise ValueError("ESPN season-type reference does not match requested season")
            type_id = path.removeprefix(prefix)
            metadata = self._fetch(f"{root}/types/{type_id}", directory / f"type_{type_id}.json", refresh)
            types.append((type_id, metadata.get("slug", "")))
        combined = [item for item in types if item[1] in {"combined", "total", "all"}]
        if combined:
            types = combined[:1]  # Do not also add component phases.
        elif len(types) > 1:
            if not stages or not stages <= {slug for _, slug in types}:
                raise ValueError("Resync match results/lineups to verify the subject's competition stages")
            types = [item for item in types if item[1] in stages and "all-star" not in item[1]]
        if not types:
            raise ValueError("No supported season statistics partitions")
        rows = []
        resource = "teams" if subject_type == "team" else "athletes"
        for type_id, slug in types:
            if progress:
                progress()
            url = f"{root}/types/{type_id}/{resource}/{subject_id}/statistics"
            raw = self._fetch(url, directory / f"{subject_type}_{subject_id}_{type_id}.json", refresh)
            expected_path = urlparse(url).path
            actual_path = urlparse(raw.get("$ref", "")).path
            if actual_path not in {expected_path, expected_path + "/0"}:
                raise ValueError("ESPN statistics response does not match requested season, stage and subject")
            stats = core_statistics(raw)
            if not stats:
                raise ValueError("ESPN returned no usable season statistics")
            rows.append({"subject_id": subject_id, "subject_type": subject_type, "season_type": slug,
                         "source_url": url, **{field: stats.get(name) for field, name in FIELDS.items()}})
        return pl.DataFrame(rows, schema_overrides={field: pl.Float64 for field in FIELDS})
