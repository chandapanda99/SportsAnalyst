from __future__ import annotations

import json
from typing import Annotated

import typer

from sports_analyst.models import AnalysisRequest, AnalysisScope
from sports_analyst.service import AnalystApplication

app = typer.Typer(help="Open Sports Analyst — evidence-bound local sports analysis")
data_app = typer.Typer(help="Manage local sports datasets")
investigate_app = typer.Typer(help="Inspect and export investigations")
providers_app = typer.Typer(help="Inspect model providers")
eval_app = typer.Typer(help="Run the deterministic evaluation suite")
app.add_typer(data_app, name="data")
app.add_typer(investigate_app, name="investigate")
app.add_typer(providers_app, name="providers")
app.add_typer(eval_app, name="eval")


@data_app.command("sync")
def data_sync(
    sport: Annotated[str, typer.Argument()] = "nfl",
    season: Annotated[list[int] | None, typer.Option("--season")] = None,
) -> None:
    if sport.lower() != "nfl":
        raise typer.BadParameter("v1 supports only nfl")
    if not season:
        raise typer.BadParameter("provide at least one --season")
    manifests = AnalystApplication().sync(season)
    for manifest in manifests:
        typer.echo(f"{manifest.season}: {manifest.row_count:,} plays · {manifest.manifest_id}")


@data_app.command("list")
def data_list() -> None:
    for manifest in AnalystApplication().store.manifests():
        typer.echo(f"{manifest.season}  {manifest.row_count:>7,} rows  {manifest.sha256[:12]}")


@app.command("ask")
def ask(
    question: str,
    compare: str = typer.Option(..., help="Baseline and comparison seasons, for example 2024:2025"),
    team: str = typer.Option(..., help="NFL team abbreviation or city/name"),
    season_type: str = typer.Option("REG"),
) -> None:
    try:
        baseline, comparison = (int(item) for item in compare.split(":", 1))
    except ValueError as error:
        raise typer.BadParameter("--compare must look like 2024:2025") from error
    request = AnalysisRequest(
        question=question,
        scope=AnalysisScope(team=team, baseline_season=baseline, comparison_season=comparison, season_type=season_type.upper()),
    )
    bundle = AnalystApplication().investigate(request)
    typer.echo(f"{bundle.run.investigation_id}\n{bundle.summary}")


@investigate_app.command("show")
def investigate_show(investigation_id: str) -> None:
    bundle = AnalystApplication().store.get_investigation(investigation_id)
    typer.echo(bundle.model_dump_json(indent=2))


@investigate_app.command("export")
def investigate_export(investigation_id: str, format: str = typer.Option("html")) -> None:
    typer.echo(AnalystApplication().store.export_path(investigation_id, format))


@providers_app.command("check")
def providers_check() -> None:
    typer.echo(AnalystApplication().capabilities().model_dump_json(indent=2))


@app.command("capabilities")
def capabilities() -> None:
    typer.echo(AnalystApplication().capabilities().model_dump_json(indent=2))


@eval_app.command("run")
def eval_run() -> None:
    from sports_analyst.evaluation import evaluation_cases

    typer.echo(json.dumps({"cases": len(evaluation_cases()), "status": "definitions-valid"}, indent=2))


@app.command("serve")
def serve(host: str = "127.0.0.1", port: int = 8767) -> None:
    import uvicorn

    uvicorn.run("sports_analyst.api:app", host=host, port=port, reload=False)
