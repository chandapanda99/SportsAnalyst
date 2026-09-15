# Durable cloud jobs with PostgreSQL and R2

The API submits work to PostgreSQL. A separate Python worker runs one job at a time, updates progress, and saves artifacts to the existing R2 bucket.

For the repository's ARM64/AMD64 API, worker, and Cloudflare Tunnel deployment, see [Container deployment on an Oracle Cloud VM](container-deployment.md). The Compose worker
uses the same queue behavior described here; its local volume is only a disposable attempt cache.
No Redis/Valkey service is required. This is optional: `JOB_BACKEND=local` retains the desktop and development behavior.

## 1. Prepare Neon

Create a project/database near the API and worker. Obtain its pooled runtime connection string and direct migration connection string from **Connect**.
Keep TLS parameters from the provided URLs. Use an isolated development branch to test the migration before applying it to production.
The Python application uses SQLAlchemy with Psycopg; Neon Auth, the Data API, and Neon Functions are not required.

Add these server-side secrets to your local migration environment (never to frontend/Vite variables):

```dotenv
DATABASE_URL=postgresql://ROLE:PASSWORD@ENDPOINT-pooler.REGION.neon.tech/sports_analyst?sslmode=require
DATABASE_MIGRATION_URL=postgresql://ROLE:PASSWORD@ENDPOINT.REGION.neon.tech/sports_analyst?sslmode=require
```

Use a migration role that can create tables. Runtime API/worker roles need SELECT, INSERT, UPDATE on `jobs` and `job_events`, plus usage on the event sequence.
Do not use migration credentials in the frontend. The runtime does not automatically create or migrate tables.

## 2. Install and migrate

From the repository root:

```powershell
uv sync
uv run alembic upgrade head
```

The migration creates `jobs` and `job_events`, or adopts the original normalized schema from the earlier setup guidance after verifying every required column.
That existing schema uses `lease_owner` and separate event columns (`stage`, `message`, `progress`, and `details`) and is directly supported.
The baseline deliberately refuses automatic downgrade because it cannot safely distinguish adopted tables from tables it created.
If your tables differ, the migration stops and reports the missing columns rather than changing or dropping stored jobs.
`DATABASE_MIGRATION_URL` is required only on the machine executing migrations. Pooled Neon migration URLs are rejected.

## 3. Configure the API and worker

Set these on **both** services:

```dotenv
JOB_BACKEND=postgres
DATABASE_URL='postgresql://...pooled runtime URL...'
PERSISTENCE_BACKEND=s3
# Reuse the same existing R2 endpoint, bucket, prefix and credentials:
OBJECT_STORAGE_ENDPOINT_URL=https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
OBJECT_STORAGE_BUCKET=open-sports-analyst
OBJECT_STORAGE_PREFIX=production
OBJECT_STORAGE_REGION=auto
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

The worker also needs the existing model-provider configuration and credentials (`MODEL_PROVIDER`, `FOUNDRY_ENDPOINT`, `FOUNDRY_API_KEY`, etc.).
Use the same application revision for API and worker. Each job attempt gets a separate disposable local cache, avoiding DuckDB file contention.
R2 remains the durable source of analytical datasets, reports, and history. PostgreSQL does not store full datasets.

Worker settings (defaults):

|                Variable | Default | Meaning                                              |
|------------------------:|:-------:|------------------------------------------------------|
|      `JOB_POLL_SECONDS` |    5    | Initial interval while waiting for work              |
| `JOB_IDLE_POLL_SECONDS` |   60    | Maximum idle interval after exponential backoff      |
|     `JOB_LEASE_SECONDS` |   300   | Time before an unresponsive attempt can be reclaimed |
| `JOB_HEARTBEAT_SECONDS` |   20    | Lease renewal interval                               |
|      `JOB_MAX_ATTEMPTS` |    3    | Maximum attempts, including the initial attempt      |
|   `JOB_TIMEOUT_SECONDS` |  7200   | Maximum runtime of a single attempt                  |

Polling every minute keeps Neon's compute active; low job volume alone does **not** guarantee staying inside its free compute allowance.
For occasional use, run the worker while using the app, or set a longer idle interval such as 600 seconds and accept delayed starts.
See [Neon scale to zero](https://neon.com/docs/introduction/scale-to-zero).

## 4. Start a worker, then enable the API

```powershell
uv run sports-analyst-worker
```

For a one-job smoke test:

```powershell
uv run sports-analyst-worker --once
```

`--once` processes at most one currently eligible job. An empty queue causes a successful exit; a scheduled retry may not be eligible yet.
For continuous availability, supervise this command using your host's process manager with automatic restart. A personal PC must remain awake and connected.
The worker initiates outbound connections to PostgreSQL, R2, dataset sources, and the model provider; it needs no public listening port.
Run it separately from the FastAPI web process, on a host with enough RAM and temporary disk for your selected NBA/NFL datasets.

The Windows desktop launcher manages this automatically when `JOB_BACKEND=postgres`: it starts the API and worker as sibling processes and stops both when the window closes.
Do not also start `sports-analyst-worker` manually for that desktop session. With the default `JOB_BACKEND=local`, the desktop keeps its existing in-process execution path and
does not start a PostgreSQL worker.

After migrating and starting the worker, deploy the API with `JOB_BACKEND=postgres`.
If no worker is online, submissions remain queued in PostgreSQL. Switching back to local mode does not execute existing PostgreSQL jobs.

## Reliability and recovery

- Claiming uses a short transaction with `FOR UPDATE SKIP LOCKED`. Analytical computation happens outside that transaction.
- The worker supervisor renews a unique attempt token while a child process executes the job. It stops the child if ownership is lost or runtime exceeds the limit.
- R2 publication takes a lock on the owned job row. A replacement attempt cannot claim that row during publication. Long publication renews the lease before releasing the
  lock.
- Progress events are ordered by sequence. Reconnect with `Last-Event-ID` or `?after=SEQUENCE`; status endpoints return the latest durable event.
- Temporary connection failures and selected provider HTTP errors retry with bounded backoff. Invalid inputs and other non-transient errors fail immediately.
- A killed worker leaves a lease that expires. Another worker reclaims it, up to the attempt limit. No separate reaper service is required.
- A result already committed to R2 is reused on retry. A crash before publication can repeat computation or a billable model call; this is at-least-once execution, not exactly
  once.
- Errors exposed to the browser are generic; worker logs include job IDs and exception types. Debug logs may include provider details.
- Each finished attempt removes its temporary cache. A machine-level crash can leave orphaned cache folders under `DATA_DIR/workers` for later cleanup.
- PostgreSQL events currently remain until an operator removes them; monitor database storage and retain the final job record if pruning historical progress events.

Status endpoints:

```text
GET /api/investigations/{id}/status
GET /api/investigations/{id}/events?after=42
GET /api/dataset-jobs/{id}/status
GET /api/dataset-jobs/{id}/events?after=42
```

## Validate before production

Run the high-level tests:

```powershell
uv run pytest tests/test_jobs.py tests/test_service_api.py tests/test_data_catalog.py
```

For the real PostgreSQL migration/lease test, set `TEST_DATABASE_URL` to a **direct** connection for a disposable local database or isolated Neon development branch:

```powershell
$env:TEST_DATABASE_URL = 'postgresql://...'
uv run pytest tests/test_jobs.py -m postgres
```

The test creates a uniquely named `test_jobs_*` schema, migrates it, verifies lease recovery and stale-attempt rejection, then removes only that schema.
Finally, submit an investigation, restart the API, and verify that progress and results remain retrievable.
Stop a worker mid-job and restart it; the job should be reclaimed after the lease expires. Repeat with a dataset sync and a follow-up.
