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

## Example

```powershell
uv run sports-analyst ask "Why did Kansas City's passing efficiency change?" --team KC --compare 2024:2025
```

Investigations and datasets are stored below the operating system's user-data directory. Raw nflverse files and generated investigations are never committed.

## Analytical boundary

The agent can compose registered analytical tools and constrained read-only DuckDB SQL. It has no shell, filesystem, package-installation, network, or Python-execution tool.
Algorithms outside the registered catalog are reported as unsupported and should be added as tested plugin tools.

`CustomAnalysisRunner` is a documented extension protocol for future third-party sandbox implementations. Core v1 ships only `DisabledCustomAnalysisRunner`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for plugin contracts and [NOTICE](NOTICE) for data attribution.

## Verification

```powershell
uv run --extra test pytest
uv run ruff check .
Set-Location frontend
npm run check
npm run test
npm run build
```
