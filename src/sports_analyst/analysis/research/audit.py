"""Exact snapshot metadata audits; synthetic tests do not certify source availability."""
from pathlib import Path

import polars as pl

from sports_analyst.analysis.research.contracts import VERSION, contract
from sports_analyst.datasets.nfl import sha256_file


def audit_snapshot(manifest, path=None):
    path = Path(path or manifest.local_path)
    if sha256_file(path) != manifest.sha256:
        raise ValueError("Snapshot checksum changed")
    definition = contract(manifest)
    query = pl.scan_parquet(path)
    schema = query.collect_schema()
    result = {"version": VERSION, "manifest_id": manifest.manifest_id, "checksum": manifest.sha256,
              "contract": definition.model_dump(mode="json"), "schema_matches": set(manifest.columns) == set(schema.names()),
              "rows": query.select(pl.len()).collect().item(), "status": "grain/key unverified"}
    if definition.keys:
        keys = list(definition.keys)
        counts = query.select(pl.len().alias("rows"), pl.struct(keys).n_unique().alias("unique_keys"),
            pl.any_horizontal(pl.col(k).is_null() for k in keys).sum().alias("null_key_rows")).collect().row(0, named=True)
        result.update(**counts, duplicate_rows=counts["rows"] - counts["unique_keys"])
        result["status"] = ("keys_verified_for_snapshot" if not result["duplicate_rows"] and not result["null_key_rows"]
                            and result["schema_matches"] else "key_or_schema_conflict")
    result["limitation"] = "Key verification does not prove identity compatibility, historical availability or causal interpretation"
    return result
