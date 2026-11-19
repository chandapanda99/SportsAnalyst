# Open Sports Analyst

A local-first sports analysis workbench for **NFL, NBA, NCAA College Football (FBS/FCS),
and some of the world's top soccer leagues**. Ask natural-language questions, compare teams or players, inspect
recorded game/play evidence, and save or export reports.

The model plans and explains; validated analytical tools, Polars and DuckDB
calculate measurements. Findings cite stored evidence. Missing data stay missing,
and reconstructed schematics are not tracking footage. Deterministic reports
remain available without a configured model.

## Documentation

|                        Guide                         | Contents                                                                          |
|:----------------------------------------------------:|-----------------------------------------------------------------------------------|
| [Environment and configuration](docs/environment.md) | Provider setup, settings, local workers and mobile testing                        |
|          [Windows desktop](docs/desktop.md)          | Installation behavior, diagnostics, builds, signing and GitHub Releases           |
|      [Data management](docs/data-downloads.md)       | Scoped preparation, packages, storage, refresh, availability and performance      |
|        [Sports and tools](docs/tool-guide.md)        | Four-sport capabilities, metrics, evidence tablets, CLI and HTTP API              |
|    [Analysis workflow](docs/research-workflow.md)    | Model roles, interpreter, acquisition, validated joins, evidence and verification |
|       [CFB sources](docs/cfb-source-terms.md)        | Optional provider settings, usage review, matching and coverage limits            |

## Quick start

### Requirements

- Python `>=3.13,<3.15`
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 or newer
- npm

### Install

```powershell
git clone https://github.com/chandapanda99/SportsAnalyst.git
Set-Location SportsAnalyst

Copy-Item .env.example .env
uv sync --extra test

Set-Location frontend
npm ci
Set-Location ..
```

### Run

Start the API in one terminal:

```powershell
uv run sports-analyst serve
```

Start the web application in a second terminal:

```powershell
Set-Location frontend
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies `/api` requests to the FastAPI server at `http://127.0.0.1:8767`.

## Using the workbench

Build an analysis in five numbered steps: the report type (a team or a player, change over
time or head-to-head), the subject, the time frame, the metrics to focus on, and a question.
A head-to-head comparison measures two teams or two players over the same season, or over a
range of up to six seasons where each season is compared on its own. In college football the
second subject is found by browsing to its school. Follow-up questions on a head-to-head report
can run additional research, which is repeated for both subjects. Soccer adds competition
selection; college football uses season-specific subdivision, conference and school discovery.
Conference selection organizes navigation rather than limiting analysis to conference games.
**How it works** reopens the short guide shown on first use.

Running an analysis downloads any missing supported data through the worker, so downloading
ahead is optional. The **Data library** (in the sidebar, or at `#/data`) handles explicit
downloads, current-season refreshes and clearing downloaded data. Successful historical
snapshots are reused; current seasons refresh, and incomplete coverage remains visible.
An analysis or download keeps running while you open saved reports, the setup page or the Data
library: the Film Room shows it as a live entry, and a report that finishes while you are
elsewhere waits behind a **Report ready** notice. One analysis, download or follow-up runs at a
time.

Reports open with the answer and a stat sheet of key metrics, followed by findings, charts and
recorded evidence. A bar at the top links to each section, switches between the report and its
follow-ups, and offers **Edit and rerun** (the setup page filled in from the report),
**Export report** and **Ask a follow-up**. Open a tablet to inspect a cited event or browse its
game where supported. The Film Room saves reports and their follow-up questions; exports
preserve evidence and provenance. Saved reports are not retroactively rewritten by updates.

## Architecture

The Svelte/TypeScript workbench and Typer CLI use the same FastAPI application
service. Sport connectors normalize provider data into scoped Parquet snapshots;
plugins produce deterministic measurements. LangChain planning/synthesis uses
validated host tools and a bounded JavaScript interpreter. `MODEL` performs
analysis; optional `CHAT_MODEL` only edits user-facing wording.

Desktop uses the same service inside WebView2 with a managed SQLite worker.
Development runs the API and frontend separately. Credentials belong in private
server settings or desktop credential storage, never frontend bundles.

## Development and verification

```powershell
# Backend
uv run ruff check .
uv run --extra test pytest

# Frontend
Set-Location frontend
npm run check
npm run test
npm run build
```

The maintained suite intentionally focuses on major workflows and compatibility contracts: sport-isolated sync and investigation behavior, four-sport analysis, API persistence
and recovery, frontend sport/subject state, and evidence rendering. Backend tests use synthetic fixtures and do not require model credentials or network access. Live provider
and external dataset download tests remain opt-in.

## License

Open Sports Analyst uses the [MIT License](LICENSE). Source datasets and third-party assets retain their own attribution and terms; the software license does not grant rights
to redistribute underlying data.
