# Google Cloud Run deployment

Cloud Run is the recommended managed hosting path. One service serves the frontend and API; an on-demand job drains the existing Neon queue. R2 retains datasets and reports. The Windows installer uses its existing build scripts and local defaults.

## First deployment

Use Google Cloud Shell (Bash, Git and gcloud are already installed). Select a billing-enabled project, clone this repository, and work from its root. No local Docker installation is required.

```bash
export PROJECT_ID=your-project
export BILLING_ACCOUNT=000000-000000-000000
export REGION=us-central1
# Optional: enable the GitHub deployment identity at the same time.
export GITHUB_REPOSITORY=your-user/your-repository
ENV_FILE=.env bash deploy/cloud-run/bootstrap.sh
```

With `ENV_FILE=.env`, bootstrap imports an explicit credential allowlist into Secret Manager: pooled `DATABASE_URL`, direct `DATABASE_MIGRATION_URL`, the two R2 credentials, the Foundry key, and the LangSmith key when tracing is enabled. It never executes the dotenv file as shell code. Each explicit import creates a new secret version; omit `ENV_FILE` to reuse existing versions or receive private prompts for missing secrets. The script rejects a pooled migration URL and a non-pooled runtime URL.

Local-only values—including `DATA_DIR`, persistence/job backends, dispatch settings, and desktop settings—are never imported. Google recommends Secret Manager rather than ordinary Cloud Run environment variables for credentials.

Bootstrap creates dedicated API, worker, migration, build and deployment identities, an image repository, a source staging bucket, and a $5 monthly alert budget. The runtime accounts do not receive build or administration permissions.

Use a development Neon branch and a separate R2 prefix for the first trial. The migration adds dispatch columns and preserves existing records. Do not run competing desktop workers against the trial database while testing cloud execution.

```bash
ENV_FILE=.env bash deploy/cloud-run/deploy.sh
```

The deploy script maps the following non-secret dotenv values when their shell equivalents are not already set: `OBJECT_STORAGE_ENDPOINT_URL` → `R2_ENDPOINT`, `OBJECT_STORAGE_BUCKET` → `R2_BUCKET`, `OBJECT_STORAGE_PREFIX` → `R2_PREFIX`, plus `FOUNDRY_ENDPOINT`, `MODEL`, and `LANGSMITH_TRACING`. Explicit exported values take precedence, which is useful for a trial prefix:

```bash
export R2_PREFIX=cloud-run-trial
ENV_FILE=.env bash deploy/cloud-run/deploy.sh
```

Cloud Build builds linux/amd64, pushes the image, runs Alembic using the direct URL, deploys the worker and public service, and checks the health endpoint and frontend. Migrations must succeed before either runtime is updated. The printed `run.app` URL is the web app. To use production data, configure the production Neon secret versions and R2 prefix and repeat deployment after trial validation.

## GitHub deployment

Set repository variables `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER` (printed by bootstrap), `GCP_REGION`, `R2_ENDPOINT`, `R2_BUCKET`, `R2_PREFIX`, `FOUNDRY_ENDPOINT`, and `MODEL`. The separate **Cloud Run deployment** workflow runs on relevant pushes to `main` or manual dispatch. Its `cloud-run` environment can use GitHub deployment protections. Federation accepts only this repository's `main` branch; no Google service-account key is stored in GitHub. Both deployment paths use the same Cloud Build configuration.

## Runtime behavior and limits

- `JOB_DISPATCH_BACKEND=cloud_run` launches the configured worker after committing a queue record. Defaults remain `none` elsewhere.
- `JOB_PROGRESS_TRANSPORT=poll` uses short status requests; the current job ID is retained in browser session storage for refresh recovery. Desktop defaults to streaming.
- `MAX_ACTIVE_JOBS=3` bounds queued/running requests across API replicas with a PostgreSQL transaction lock. A full queue returns HTTP 429.
- Dispatch reservations throttle launches across replicas. A failed launch is eligible again after 30 seconds; an unclaimed successful launch after 120 seconds. Submission and status polling drive recovery. If every browser closes before a failed launch is recovered, the record remains queued until a status check resumes or a worker is executed manually.
- `--drain` waits for delayed retries and expired leases and exits when all work is terminal. Each attempt retains its own lease and temporary directory; completed and interrupted attempts remove that directory. Existing continuous and `--once` worker modes remain available.
- The API uses 2 CPUs/4 GiB, concurrency 8, and 0–1 instances. Worker executions use one task, 2 CPUs/8 GiB, a six-hour timeout and one infrastructure retry. Task parallelism does not limit simultaneous executions; database leases prevent duplicate ownership of an individual job.
- Cloud Run's writable filesystem consumes RAM. Attempt cleanup bounds retained data between jobs, but peak memory must still fit the largest selected dataset. Begin with small syncs and monitor before importing many seasons. API caches are ephemeral and can be recreated from R2.

There is no authentication, as requested: anyone reaching the URL can submit work, view reports, or use existing deletion endpoints. Admission limits bound simultaneous work, not total use or spending.

## Verification and recovery

Run one small NFL sync, one NBA sync, a team and player investigation, and a follow-up. Refresh during work; verify completion without resubmission. Verify reports and manifests appear in R2. Let the service scale to zero and check that history returns on the next visit. On a development branch, interrupt a worker execution and confirm lease-based recovery and bounded attempts.

```bash
gcloud run jobs execute open-sports-analyst-worker --project="$PROJECT_ID" --region="$REGION"
gcloud run services logs read open-sports-analyst --project="$PROJECT_ID" --region="$REGION" --limit=50
gcloud run jobs executions list --job=open-sports-analyst-worker --project="$PROJECT_ID" --region="$REGION"
```

Keep the previous host until these checks pass. Retirement of that deployment is a separate manual action. Roll back the Cloud Run service to its previous revision if necessary; use the matching prior image for the worker. The additive migration can remain installed.

## Costs and secrets

Free-tier usage is not a guaranteed zero bill. Builds, image storage, internet uploads to R2, runtime resources, model calls, and Neon usage have independent limits. The budget is an alert, not a hard spending cap. The image cleanup policy retains three recent versions and removes older images after seven days. Periodically remove obsolete source archives in the build staging bucket.

Secret bindings use `latest` at deployment/startup; rotate a secret by adding a version and redeploying both runtimes. For optional LangSmith tracing, export `LANGSMITH_TRACING=true` before bootstrap and deployment; bootstrap prompts for its separate secret and grants API/worker access. Use the same GitHub variable if deploying through Actions. Never place credentials in build substitutions or GitHub variables.

References: [Cloud Run pricing](https://cloud.google.com/run/pricing), [container contract](https://cloud.google.com/run/docs/container-contract), [Artifact Registry pricing](https://cloud.google.com/artifact-registry/pricing).
