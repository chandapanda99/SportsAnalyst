from pathlib import Path

import pytest

from sports_analyst.sql import execute_read_only_sql, validate_sql


@pytest.mark.parametrize("sql", ["DELETE FROM pbp", "SELECT 1; SELECT 2", "SELECT * FROM read_parquet('secret')", "INSTALL httpfs"])
def test_sql_rejects_unsafe_operations(sql: str) -> None:
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_sql_allows_bounded_select(tmp_path: Path, pbp_pair) -> None:
    path = tmp_path / "pbp.parquet"
    pbp_pair[2024].write_parquet(path)
    rows, _ = execute_read_only_sql("SELECT posteam, count(*) AS plays FROM pbp GROUP BY posteam", {2024: path}, 10)
    assert rows == [{"posteam": "KC", "plays": 160}]
