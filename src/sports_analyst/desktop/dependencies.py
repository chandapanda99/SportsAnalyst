"""Offline native-provider check, used only by the frozen build smoke test."""
import importlib


def check_runtime_dependencies() -> None:
    for module in (
        "duckdb", "polars", "pyarrow", "vl_convert", "webview", "nflreadpy",
        "sportsdataverse.soccer", "sportsdataverse.nba.nba_loaders", "sportsdataverse.dl_utils",
    ):
        try:
            importlib.import_module(module)
        except Exception as error:
            raise RuntimeError(f"Packaged runtime dependency failed to load: {module}") from error
    # Exercise basic native entry points, not just Python wrapper imports.
    import duckdb
    import polars as pl
    import pyarrow as pa

    with duckdb.connect(":memory:") as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)
    assert pl.DataFrame({"value": [1, 2]}).select(pl.col("value").sum()).item() == 3
    assert pa.table({"value": [1, 2]}).num_rows == 2
