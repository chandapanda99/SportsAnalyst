from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter
from typing import Any

import duckdb

FORBIDDEN = re.compile(
    r"\b(attach|copy|create|delete|detach|drop|export|import|insert|install|load|pragma|replace|set|update|call)\b",
    re.IGNORECASE,
)
FILE_FUNCTIONS = re.compile(r"\b(read_csv|read_json|read_parquet|parquet_scan|glob|httpfs)\s*\(", re.IGNORECASE)


def validate_sql(sql: str) -> str:
    normalized = " ".join(sql.strip().split())
    without_trailing = normalized[:-1].rstrip() if normalized.endswith(";") else normalized
    if ";" in without_trailing:
        raise ValueError("only one SQL statement is allowed")
    first = without_trailing.split(maxsplit=1)[0].lower() if without_trailing else ""
    if first not in {"select", "with", "explain"}:
        raise ValueError("SQL must begin with SELECT, WITH, or EXPLAIN")
    if FORBIDDEN.search(without_trailing) or FILE_FUNCTIONS.search(without_trailing):
        raise ValueError("SQL contains a prohibited operation")
    if "--" in without_trailing or "/*" in without_trailing:
        raise ValueError("SQL comments are not allowed")
    return without_trailing


def execute_read_only_sql(
    sql: str,
    dataset_paths: Mapping[int | tuple[str, int], Path],
    row_limit: int = 10_000,
) -> tuple[list[dict[str, Any]], int]:
    normalized = validate_sql(sql)
    started = perf_counter()
    paths_by_dataset: dict[str, dict[int, Path]] = defaultdict(dict)
    for key, path in dataset_paths.items():
        dataset, season = ("play_by_play", key) if isinstance(key, int) else key
        if not re.fullmatch(r"[a-z][a-z0-9_]*", dataset):
            raise ValueError(f"invalid dataset view name: {dataset!r}")
        paths_by_dataset[dataset][season] = path
    with duckdb.connect(":memory:") as db:
        for dataset, season_paths in paths_by_dataset.items():
            for season, path in season_paths.items():
                safe_path = path.resolve().as_posix().replace("'", "''")
                db.execute(f"CREATE VIEW {dataset}_{season} AS SELECT * FROM read_parquet('{safe_path}')")
            unions = " UNION ALL BY NAME ".join(f"SELECT * FROM {dataset}_{season}" for season in sorted(season_paths))
            db.execute(f"CREATE VIEW {dataset} AS {unions}")
        if "play_by_play" in paths_by_dataset:
            db.execute("CREATE VIEW pbp AS SELECT * FROM play_by_play")
        relation = db.execute(f"SELECT * FROM ({normalized}) AS result LIMIT {int(row_limit) + 1}")
        columns = [item[0] for item in relation.description]
        rows = relation.fetchall()
    if len(rows) > row_limit:
        raise ValueError(f"SQL result exceeds the {row_limit} row limit")
    return [dict(zip(columns, row, strict=True)) for row in rows], int((perf_counter() - started) * 1000)
