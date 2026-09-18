# Google Cloud Run deployment

Cloud Run is the recommended managed hosting path. It keeps the Windows desktop build independent and uses four managed pieces:

- the public `open-sports-analyst` service for the compiled frontend and API;
- the private `open-sports-analyst-sync` service, invoked by Cloud Tasks for low-latency dataset downloads;
- the `open-sports-analyst-analysis` Cloud Run Job for long investigations and follow-ups;
- Cloudflare R2 for datasets, reports, request records, and progress events.

The cloud path does **not** require Neon, PostgreSQL, Alembic migrations, Redis, or a continuously running worker. Cloud Tasks retries sync requests, while Cloud Run Jobs provide the longer execution window required by investigations.

## First deployment

Use Google Cloud Shell, or Git Bash with an authenticated `gcloud` installation. Clone the repository and run these commands from its root:

```bash
export PROJECT_ID=your-project
export BILLING_ACCOUNT=000000-000000-000000
export REGION=us-central1
# Optional: create the GitHub deployment identity too.
export GITHUB_REPOSITORY=your-user/your-repository
ENV_FILE=.env bash deploy/cloud-run/bootstrap.sh
ENV_FILE=.env bash deploy/cloud-run/deploy.sh
```

Bootstrap enables Cloud Run, Cloud Build, Cloud Tasks, Artifact Registry, Secret Manager, and IAM; creates narrowly scoped service accounts; creates the sync queue and image repository; and imports an explicit credential allowlist from `.env`. It imports only the R2 credentials, model-provider key, and optional LangSmith key. The dotenv file is parsed as data and is never executed as shell code.

The deploy script maps these non-secret dotenv values when an exported shell value is absent: `OBJECT_STORAGE_ENDPOINT_URL` to `R2_ENDPOINT`, `OBJECT_STORAGE_BUCKET` to `R2_BUCKET`, `OBJECT_STORAGE_PREFIX` to `R2_PREFIX`, plus `FOUNDRY_ENDPOINT`, `MODEL`, and `LANGSMITH_TRACING`. Exported values take precedence, so a safe trial can use a separate prefix:

```bash
export R2_PREFIX=cloud-run-trial
ENV_FILE=.env bash deploy/cloud-run/deploy.sh
```

Cloud Build creates a Linux AMD64 image, deploys the analysis job, deploys the private sync service, deploys the public service, and performs health and frontend smoke checks. There is no database migration stage.

## Runtime behavior

- The API writes a small job request and initial progress record to R2.
- A sync request becomes an authenticated Cloud Task. Cloud Tasks calls the private sync service and retries transient failures. Its 30-minute HTTP deadline is suitable for ordinary package/season sync units; completed manifests are published incrementally, so a retry skips already stored data.
- An investigation or follow-up starts one Cloud Run Job execution with its R2 job ID supplied as an execution override. Cloud Run retries the task once for transient failures.
- The browser polls durable R2-backed status and survives API scale-to-zero, refreshes, and replica replacement.
- R2 is authoritative. `/tmp` on each Cloud Run instance is only a bounded disposable cache.
- Accepted Cloud Tasks and Job executions are not re-dispatched by browser polling. Google Cloud owns their delivery after acceptance.

Current deployment limits are intentionally conservative for a personal project:

| Runtime | CPU / memory | Scaling and timeout |
|---|---|---|
| Public API/frontend | 2 vCPU / 4 GiB | concurrency 8, 0–1 instances, 5 minutes |
| Private sync service | 1 vCPU / 4 GiB | concurrency 1, 0–1 instances, 30 minutes |
| Analysis job | 1 vCPU / 4 GiB | one task, one retry, 6 hours |

The first sync request may still incur a normal service cold start, but it avoids the several-minute Cloud Run Job scheduling delay previously seen for downloads. Analyses remain Jobs because they can exceed the Cloud Tasks request deadline.

The public URL has no authentication. Anyone with the URL can submit work or view reports. `MAX_ACTIVE_JOBS=3`, one API instance, one sync instance, payload validation, and queue rate limits reduce accidental abuse but are not access control or a hard spending cap.

## GitHub deployment

Set repository variables `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER` (printed by bootstrap), `GCP_REGION`, `R2_ENDPOINT`, `R2_BUCKET`, `R2_PREFIX`, `FOUNDRY_ENDPOINT`, `MODEL`, and optionally `LANGSMITH_TRACING`. The **Cloud Run deployment** workflow uses Workload Identity Federation and the same Cloud Build configuration as manual deployment; it stores no Google service-account key.

## Verification and cleanup

After deployment, test one small NFL sync, one NBA sync, a team investigation, a player investigation, and a follow-up. Refresh the page during both a sync and investigation, then let the API scale to zero and confirm history returns. Verify the corresponding dataset and investigation objects exist in R2.

Useful diagnostics:

```bash
gcloud run services logs read open-sports-analyst-sync --project="$PROJECT_ID" --region="$REGION" --limit=100
gcloud run jobs executions list --job=open-sports-analyst-analysis --project="$PROJECT_ID" --region="$REGION"
gcloud tasks queues describe open-sports-analyst-sync --project="$PROJECT_ID" --location="$REGION"
```

Keep the old deployment and any existing Neon resources until these checks pass. Afterward, the old `open-sports-analyst-worker` and `open-sports-analyst-migrate` Jobs, their obsolete service accounts and database secrets, and the Neon project can be removed manually. The application no longer contains a PostgreSQL runtime or migration path. R2 remains required because Cloud Run's filesystem is ephemeral.

Free-tier usage is not a guaranteed zero bill. Cloud Run, Cloud Tasks, builds, image storage, internet transfer to R2, R2 operations/storage, and model calls have separate allowances. The bootstrap-created budget is an alert, not a spending cap.

References: [Cloud Tasks with Cloud Run](https://cloud.google.com/run/docs/triggering/using-tasks), [Cloud Tasks HTTP deadlines](https://cloud.google.com/tasks/docs/creating-http-target-tasks), [executing Cloud Run Jobs](https://cloud.google.com/run/docs/execute/jobs), and [Cloud Run pricing](https://cloud.google.com/run/pricing).
