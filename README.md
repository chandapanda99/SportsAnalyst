# Open Sports Analyst

Open Sports Analyst is a local-first framework for answering analytical sports questions against reproducible local datasets. The first plugin diagnoses changes in NFL team
passing efficiency using nflverse play-by-play.

The language model plans and explains; versioned Python tools and read-only SQL produce the evidence. Every measured claim links to an aggregate result or source play. The
application never lets a model write or execute Python.

## Architecture

- **Svelte 5 + TypeScript** provides the investigation workbench.
- **FastAPI** exposes datasets, investigations, evidence, progress streams, follow-ups, and report exports.
- **Typer** supports repeatable data and analysis workflows.
- **Polars + DuckDB** handle local Parquet analytics and constrained SQL.
- **LangChain Deep Agents** coordinates efficiency, situational, and evidence-review specialists.
- **Azure Foundry** is the default model provider; **Ollama** is the local alternative.

The application produces deterministic reports when no model is configured.

## Development

Requirements: Python 3.13 or 3.14, Node.js 20+, and `uv`.

```powershell
Copy-Item .env.example .env
uv sync --extra test
uv run sports-analyst data sync nfl --season 2024 --season 2025
uv run sports-analyst serve
```

In another terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The API listens at `http://127.0.0.1:8767`.

For additional backend diagnostics, set `LOG_LEVEL=DEBUG` in `.env` and restart the API. The default is `INFO`. Logs include sync and investigation IDs, lifecycle stages, durations, result counts, model/fallback outcomes, citation-repair attempts, and event-stream timeouts. They intentionally exclude questions, prompts, evidence contents, SQL, filesystem paths, credentials, and raw model responses.

The web data manager can also sync supplemental packages used by player and context tools. The equivalent CLI form is:

```powershell
uv run sports-analyst data sync nfl --season 2024 --season 2025 `
  --dataset play_by_play --dataset rosters --dataset injuries `
  --dataset schedules --dataset nextgen_passing
```

Supplemental packages are optional. Investigations continue with play-by-play tools and record a capability caveat when a requested context package is unavailable. The
registered NFL tool catalog is available at `GET /api/sports/nfl/tools`; metric definitions and player resolution are available below `/api/sports/nfl/metrics` and
`/api/sports/nfl/players`.

The priority NFL tool set covers data-driven analysis options, typed time-window comparisons, weekly confidence intervals and three-week moving averages,
sustained-versus-outlier trend classification, game outlier ranking, league and conference benchmarks, situational splits, representative plays, and metric guidance.
League benchmarks report percentile, overall rank, conference rank, and distance from the league average. Tool catalog entries expose JSON input schemas so planners and
other clients can validate arguments before execution.

The web app's **Full season range** mode is inclusive: selecting 2022 through 2025 loads and measures 2022, 2023, 2024, and 2025. Its season-trend evidence covers the complete range, while situational decomposition and representative-play diagnostics compare the first and final seasons. **Custom week ranges** remains the two-window workflow for targeted season or week comparisons.

## Example

```powershell
uv run sports-analyst ask "Why did Kansas City's passing efficiency change?" --team KC --compare 2024:2025
```

Investigations and datasets are stored below the operating system's user-data directory. Raw nflverse files and generated investigations are never committed.

## Analytical boundary

The agent can compose registered analytical tools and constrained read-only DuckDB SQL. It has no shell, filesystem, package-installation, network, or Python-execution tool.
Algorithms outside the registered catalog are reported as unsupported and should be added as tested plugin tools.

`CustomAnalysisRunner` is a documented extension protocol for future third-party sandbox implementations. Core v1 ships only `DisabledCustomAnalysisRunner`.

## Verification

```powershell
uv run --extra test pytest
uv run ruff check .
Set-Location frontend
npm run check
npm run test
npm run build
```
