"""Ordering at observation-selection boundaries, not on every analytical scan."""

import json

import polars as pl


def unique_records(frame: pl.DataFrame, keys: list[str], context: str) -> pl.DataFrame:
    """Collapse identical records; conflicting observations need a source policy."""
    if frame.is_empty():
        return frame
    distinct = frame.unique(maintain_order=True)
    if distinct.select(keys).is_duplicated().any():
        raise ValueError(f"Conflicting {context} records for keys {keys}; no arbitrary first/last selection")
    return distinct.sort(keys, nulls_last=True)


def canonical_records(frame: pl.DataFrame) -> list[dict]:
    """Canonical row-set serialization for evidence hashes; nested event lists keep their order."""
    return sorted(frame.to_dicts(), key=lambda row: json.dumps(row, sort_keys=True, default=str))
