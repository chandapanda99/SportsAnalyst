# Local environment settings

Copy `.env.example` to `.env` for development and set your model-provider values.
The application reads `.env` and process environment variables; process values take
precedence. Never commit a populated env file or put credentials in frontend/Vite
variables. Hosting deployment files are intentionally not part of the current setup.

## What you need

For open soccer events and SPADL/xT in a development or hosted installation,
install the optional extra with `uv sync --extra soccer-events --inexact`
(retain any other extras used by your deployment). The desktop extra includes
these dependencies, and the packaging smoke check loads the bundled xT model.
This adds event-reading libraries, not a hosted service or model API. Source
availability and data-use terms still apply independently of library installation.

- **Azure Foundry:** `MODEL_PROVIDER=azure_foundry`, `MODEL`, `FOUNDRY_ENDPOINT`,
  and `FOUNDRY_API_KEY` (or an explicitly configured supported identity).
  Model calls can still incur provider charges.
- **Message formatting:** optionally set `CHAT_MODEL` for summaries and follow-up
  wording only. Omit it to reuse `MODEL`. `REASONING_EFFORT` controls analysis
  reasoning; `CHAT_REASONING_EFFORT` independently controls the Azure Foundry
  wording model when `CHAT_MODEL` is set. Omit it or leave it blank to use that
  model's default. Use an effort supported by the selected deployment; Ollama
  does not currently apply these reasoning settings.
- **Ollama instead:** set `MODEL_PROVIDER=ollama`, `OLLAMA_BASE_URL` and
  `OLLAMA_MODEL`. Foundry credentials are unnecessary for that provider.
- **Soccer enrichment:** `SOCCER_UNDERSTAT_ENABLED=true` enables optional Understat
  team-match xG, native player-match statistics and shot locations through the
  locked SoccerData parser for the five configured European domestic leagues.
  Source availability is verified during acquisition. xG models stay separate;
  ESPN player comparisons require a verified identity mapping. Understat downloads
  run in workers with bounded HTTP transport; no browser is launched. Disable the
  flag to keep existing data readable while preventing new Understat acquisition.
- **WhoScored event recaps:** enabled by default; select
  `whoscored_events` in soccer Data Management for a configured European domestic
  league. The worker uses bounded, cached HTTP acquisition with SoccerData's
  parser, without launching Chrome. Source blocks (including HTTP 403) are
  reported as unavailable enrichment; static event cards and commentary zones
  continue to work. Coverage is not guaranteed. Only uniquely corroborated
  events enrich the selected ESPN timeline event; source streams remain separate.
  Set `SOCCER_WHOSCORED_ENABLED=false` only to disable new acquisition.
- **Data location:** omit `DATA_DIR` for the standard per-user folder, or choose a
  path deliberately. Changing it does not migrate datasets or investigation history.
- **Performance:** `DATASET_CACHE_MB` and `DATASET_SYNC_CONCURRENCY` control cache
  and bounded downloads. Start with the template values and tune when necessary.
- **Optional CFB sources:** review [source terms](cfb-source-terms.md) before setting
  `CFB_NCAA_ENABLED` or `CFB_CFBD_ENABLED`. Either requires
  `CFB_SECONDARY_USAGE_CONFIRMED=true`; template defaults do not acknowledge terms
  on another operator's behalf.
- **Diagnostics:** `LOG_LEVEL` controls logging. `LANGSMITH_*` configures optional
  tracing; tracing is not required.

## Local server versus Windows desktop

The standalone development server uses `PERSISTENCE_BACKEND=local`,
`JOB_BACKEND=local` and `JOB_PROGRESS_TRANSPORT=stream`. No separate worker or
external database is needed.

The Windows launcher configures `JOB_BACKEND=sqlite` and manages its sibling worker
automatically. Do not manually select SQLite for a standalone server without
starting `sports-analyst-worker`, or its jobs will remain queued.

SQL row limits, history limits, checksums, event timeouts, job admission and
worker polling/lease/heartbeat/retry settings already have defaults in
`src/sports_analyst/config.py`. Existing intentional private overrides are retained.
`MAX_ACTIVE_JOBS` limits queued/running work, not worker concurrency.

`SPORTS_ANALYST_DATA_ADMIN_TOKEN` is an optional deletion-protection setting.
It is not required for a trusted local installation and is not general authentication.
Do not expose an unauthenticated development server to the public internet.

## Windows signing

`WINDOWS_SIGNING_*` belongs to installer builds, not analysis or dataset syncing.
The PowerShell scripts read process environment variables, not `.env`. Export
signing values to the build process and never distribute private signing material.
See the [desktop build guide](desktop.md#build-the-installer).

## Provider examples

The application supports Azure Foundry and Ollama. Provider settings remain in the backend and are never sent to the browser or analysis tools.

### Azure Foundry

Azure Foundry is the default provider and uses the OpenAI-compatible `/openai/v1/` endpoint with the Responses API.

```dotenv
MODEL_PROVIDER=azure_foundry
MODEL=gpt-5.6-luna
FOUNDRY_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com/openai/v1/
FOUNDRY_API_KEY=
REASONING_EFFORT=medium
```

If `FOUNDRY_API_KEY` is empty, authentication uses `DefaultAzureCredential`. For local development, sign in with a supported Azure developer credential such as Azure CLI
before starting the API.

### Ollama

```dotenv
MODEL_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b
```

The selected Ollama model must support the structured output and tool-calling behavior needed by the agent workflow.

Check the active configuration with:

```powershell
uv run sports-analyst providers check
```

If provider construction or model synthesis fails, the completed deterministic evidence remains available and the saved report is marked as a fallback.

### LangSmith tracing

LangSmith tracing is opt-in. Add the following to `.env` to trace the deterministic pipeline and Deep Agent activity:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=open-sports-analyst-local
# LANGSMITH_WORKSPACE_ID=
```

Each investigation is a root trace with child spans for planning, data loading, deterministic analysis, synthesis, and persistence. Follow-ups use the original investigation
ID as their `thread_id`, while retaining their own `investigation_id`. Trace metadata contains scope identifiers and counts, not raw datasets or credentials. Tracing is
fail-open: configuration or delivery failures are logged but do not fail an investigation.

## Settings reference

All settings use the following environment variables and may be placed in `.env`.

|              Variable              |              Default              | Purpose                                                         |
|:----------------------------------:|:---------------------------------:|-----------------------------------------------------------------|
|             `DATA_DIR`             |   Platform user-data directory    | Local catalog, Parquet, and investigation root                  |
|          `MODEL_PROVIDER`          |          `azure_foundry`          | Active provider: `azure_foundry` or `ollama`                    |
|              `MODEL`               |          `gpt-5.6-luna`           | Azure Foundry model/deployment name                             |
|            `CHAT_MODEL`            |               Empty               | Optional summary/follow-up wording model; falls back to `MODEL` |
|      `CHAT_REASONING_EFFORT`       |               Empty               | Azure wording model reasoning; blank uses its default, independently of analysis |
|         `FOUNDRY_ENDPOINT`         |               Empty               | HTTPS endpoint ending in `/openai/v1/`                          |
|         `FOUNDRY_API_KEY`          |               Empty               | Optional API key; empty uses `DefaultAzureCredential`           |
|         `REASONING_EFFORT`         |             `medium`              | Provider reasoning setting                                      |
|         `OLLAMA_BASE_URL`          |     `http://127.0.0.1:11434`      | Ollama server                                                   |
|           `OLLAMA_MODEL`           |            `qwen3:8b`             | Ollama model                                                    |
|          `SQL_ROW_LIMIT`           |              `10000`              | Maximum constrained-SQL result rows                             |
|   `EVENT_STREAM_TIMEOUT_SECONDS`   |               `120`               | SSE inactivity timeout before frontend recovery                 |
|         `DATASET_CACHE_MB`         |               `384`               | In-memory analytical dataset cache; `0` disables it             |
| `VERIFY_DATASET_CHECKSUMS_ON_LOAD` |              `false`              | Recalculate SHA-256 whenever a manifest is loaded               |
|   `INVESTIGATION_HISTORY_LIMIT`    |               `50`                | Default compact history page size                               |
|            `LOG_LEVEL`             |              `INFO`               | Backend logging level                                           |
|        `LANGSMITH_TRACING`         |              `false`              | Enable LangSmith tracing                                        |
|        `LANGSMITH_ENDPOINT`        | `https://api.smith.langchain.com` | LangSmith API endpoint                                          |
|        `LANGSMITH_API_KEY`         |               Empty               | LangSmith API key                                               |
|        `LANGSMITH_PROJECT`         |    `open-sports-analyst-local`    | Destination LangSmith project                                   |
|      `LANGSMITH_WORKSPACE_ID`      |               Empty               | Optional workspace for scoped API keys                          |

Set `LOG_LEVEL=DEBUG` for lightweight diagnostics. Logs include IDs, lifecycle stages, timings, result counts, model/fallback outcomes, citation repair, and event timeouts.
They intentionally exclude prompts, questions, evidence contents, SQL text, managed paths, credentials, and raw model responses.

## Mobile development testing

The web workbench reflows for narrow screens. NFL/college-football fields and NBA courts offer an expanded view with zoom buttons, touch pan/pinch, a play-focus shortcut, and a full-view reset. Tap a marker or use the player/event picker for persistent details; recorded, projected, and inferred labels are preserved. Escape closes the expanded view and restores focus.

On phones, mixed-metric comparisons show exact values and first-to-last numeric differences before the optional chart. Rate differences use percentage points, not relative percentage changes. Metric filters and expanded charts remain available. College-football comparison tables scroll inside their own labeled region.

For mobile QA, check 320px and 390px portrait layouts, landscape, the on-screen keyboard, marker selection, expand/zoom/reset, and report navigation. Desktop browser emulation is useful but does not replace Android Chrome and iPhone Safari checks, especially for pinch gestures, safe areas, and keyboard behavior.

### Testing over cellular with ngrok

Use `ngrok.yml.example` as the template for a private `ngrok.local.yml` (the local file is excluded from Git and Docker build contexts). Replace the authtoken with your ngrok dashboard authtoken and replace the entire password placeholder with a long, unique password. The browser username is `mobile`. Do not put model-provider credentials in this file. If you need a particular endpoint URL, uncomment `url` and use the exact HTTPS dev domain assigned in your ngrok dashboard.

From the repository root, build the frontend and start the API:

```cmd
npm --prefix frontend run build
uv run sports-analyst serve
```

Confirm `http://127.0.0.1:8767` opens the built app, then in a separate terminal:

```cmd
ngrok config check --config .\ngrok.local.yml
ngrok start sports-analyst --config .\ngrok.local.yml
```

Open the HTTPS forwarding address on your phone over cellular and authenticate as `mobile` with your chosen password. Both the frontend and `/api` use this single protected endpoint; Vite is not needed. Keep the API and tunnel running while testing; Ctrl+C stops the tunnel. Anyone with the browser credentials has access to the local app's data and operations, including model-backed requests, so do not share them. ngrok transports your requests through its service; use test data where possible. Do not commit the local configuration or copy it into deployment/installer artifacts.
