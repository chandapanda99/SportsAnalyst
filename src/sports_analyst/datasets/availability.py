"""Shared availability semantics. Missing source data is not a transport failure."""
from __future__ import annotations

from urllib.error import HTTPError

import polars as pl


class SourceUnavailable(ValueError):
    """A successful lookup supplied no recorded rows for the requested scope."""


def missing_source(error, *, provider_errors=()):
    """Only explicit absence signals; never infer absence from exception text."""
    visited = set()
    while error is not None and id(error) not in visited:
        visited.add(id(error))
        if isinstance(error, (SourceUnavailable, *provider_errors)):
            return True
        if isinstance(error, HTTPError) and error.code in {404, 410}:
            return True
        response = getattr(error, "response", None)
        if response is not None and getattr(response, "status_code", None) in {404, 410}:
            return True
        error = error.__cause__
    return False


def retain_previous(path, frame):
    if frame.is_empty() and path.exists():
        previous = pl.read_parquet(path)
        if not previous.is_empty():
            return previous, True
    return frame, False


def unavailable_snapshot(path, season, build_manifest, *, message="The source has no published data for this selection; retry later."):
    """Keep last good bytes; otherwise store an explicitly unavailable placeholder."""
    frame, retained = retain_previous(path, pl.DataFrame())
    target = path if retained else path.with_name(f"unavailable_{path.name}")
    if not retained:
        target.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({"season": pl.Series([], dtype=pl.Int32)}).write_parquet(target)
    manifest = build_manifest(target, frame if retained else pl.read_parquet(target))
    return manifest.model_copy(update={"availability": "partial" if retained else "source_unavailable",
        "availability_message": message + (" Last downloaded data have been retained; refresh did not succeed." if retained else ""),
        "coverage": {**manifest.coverage, "source_unavailable": 1, "retained_previous_data": int(retained)}})


def completed_games(frame, *, flag=None, status=None):
    """Unknown, live and scheduled games cannot supply recorded event data."""
    if flag:
        return frame.filter(pl.col(flag) == True)  # noqa: E712
    return frame.filter(pl.col(status).cast(pl.String).str.to_lowercase().is_in(
        ["status_final", "status_full_time", "final"]))


def completion_message(manifests, label="Dataset"):
    gaps = [item for item in manifests if item.availability != "available"]
    if not gaps:
        return f"{label} sync complete"
    return f"{label} sync finished with coverage gaps: " + "; ".join(
        f"{item.dataset} · {item.season}: {item.availability_message or item.availability}" for item in gaps)
