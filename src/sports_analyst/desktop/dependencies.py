"""Offline native-provider check, used only by the frozen build smoke test."""
import importlib
import os


def check_runtime_dependencies() -> None:
    from sports_analyst.config import Settings

    os.environ.setdefault("SOCCERDATA_DIR", str(Settings().data_dir / "raw" / "soccer" / "soccerdata"))
    for module in (
        "duckdb", "polars", "pyarrow", "vl_convert", "webview", "nflreadpy",
        "sportsdataverse.soccer", "sportsdataverse.nba.nba_loaders", "sportsdataverse.cfb", "sportsdataverse.cfb.cfb_pbp", "sportsdataverse.dl_utils",
        "kloppy.statsbomb",
        "soccerdata.understat",
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
    from sportsdataverse.soccer import load_xthreat_model

    actions = pl.DataFrame({"type_name": ["pass"], "result_name": ["success"],
                            "start_x": [20.], "start_y": [34.], "end_x": [80.], "end_y": [34.]})
    assert load_xthreat_model().rate(actions).is_not_null().sum() == 1
    # Exercise the bundled Wasm guests as well as wasmtime's native library.
    from quickjs_rs import Context, Runtime

    with Runtime(memory_limit=32 * 1024 * 1024) as runtime, Context(runtime) as context:
        assert context.eval("1 + 2") == 3
        assert context.eval("typeof fetch") == "undefined"
