#!/usr/bin/env bash
# Run in Cloud Shell or Bash with gcloud authenticated as the project administrator.
set -euo pipefail
: "${PROJECT_ID:?Set PROJECT_ID}" "${BILLING_ACCOUNT:?Set BILLING_ACCOUNT}"
REGION=${REGION:-us-central1}
APP=${APP:-open-sports-analyst}
ENV_FILE=${ENV_FILE:-.env}
dotenv_value() {
  python3 deploy/cloud-run/read_dotenv.py "$ENV_FILE" "$1"
}
if [ -n "$ENV_FILE" ]; then
  [ -f "$ENV_FILE" ] || { echo "ENV_FILE does not exist: $ENV_FILE" >&2; exit 66; }
  if [ -z "${LANGSMITH_TRACING:-}" ]; then
    LANGSMITH_TRACING=$(dotenv_value LANGSMITH_TRACING 2>/dev/null || printf 'false')
  fi
  required_secret_keys='AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY FOUNDRY_API_KEY'
  if [ "$LANGSMITH_TRACING" = true ]; then required_secret_keys="$required_secret_keys LANGSMITH_API_KEY"; fi
  for secret_key in $required_secret_keys; do
    value=$(dotenv_value "$secret_key")
    [ -n "$value" ] || { echo "$secret_key is blank in $ENV_FILE" >&2; exit 65; }
    unset value
  done
fi

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  cloudtasks.googleapis.com secretmanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com \
  sts.googleapis.com billingbudgets.googleapis.com --project="$PROJECT_ID"
number=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud beta services identity create --service=cloudtasks.googleapis.com --project="$PROJECT_ID" >/dev/null

for role in api analysis sync tasks build deploy; do
  account="${APP}-${role}@${PROJECT_ID}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "$account" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${APP}-${role}" --project="$PROJECT_ID"
  fi
done

if ! gcloud artifacts repositories describe "$APP" --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$APP" --repository-format=docker --location="$REGION" --project="$PROJECT_ID"
fi
gcloud artifacts repositories set-cleanup-policies "$APP" --location="$REGION" --project="$PROJECT_ID" \
  --policy=deploy/cloud-run/cleanup.json --no-dry-run

suffixes='r2-key r2-secret model-key'
if [ "${LANGSMITH_TRACING:-false}" = true ]; then suffixes="$suffixes langsmith"; fi
for suffix in $suffixes; do
  secret="${APP}-${suffix}"
  if ! gcloud secrets describe "$secret" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud secrets create "$secret" --replication-policy=automatic --project="$PROJECT_ID"
  fi
  case "$suffix" in
    r2-key) secret_key=AWS_ACCESS_KEY_ID ; roles='api analysis sync' ;;
    r2-secret) secret_key=AWS_SECRET_ACCESS_KEY ; roles='api analysis sync' ;;
    model-key) secret_key=FOUNDRY_API_KEY ; roles='analysis' ;;
    langsmith) secret_key=LANGSMITH_API_KEY ; roles='analysis' ;;
  esac
  if [ -n "$ENV_FILE" ]; then
    value=$(dotenv_value "$secret_key")
    [ -n "$value" ] || { echo "$secret_key is blank in $ENV_FILE" >&2; exit 65; }
    printf '%s' "$value" | gcloud secrets versions add "$secret" --data-file=- --project="$PROJECT_ID"
    unset value
  elif ! gcloud secrets versions describe latest --secret="$secret" --project="$PROJECT_ID" >/dev/null 2>&1; then
    read -r -s -p "Value for ${secret}: " value
    printf '\n'
    printf '%s' "$value" | gcloud secrets versions add "$secret" --data-file=- --project="$PROJECT_ID"
    unset value
  fi
  for role in $roles; do
    gcloud secrets add-iam-policy-binding "$secret" --project="$PROJECT_ID" \
      --member="serviceAccount:${APP}-${role}@${PROJECT_ID}.iam.gserviceaccount.com" \
      --role=roles/secretmanager.secretAccessor
  done
done

for role in roles/run.admin roles/artifactregistry.writer roles/logging.logWriter roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${APP}-build@${PROJECT_ID}.iam.gserviceaccount.com" --role="$role"
done
for identity in api analysis sync; do
  gcloud iam service-accounts add-iam-policy-binding "${APP}-${identity}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --project="$PROJECT_ID" --member="serviceAccount:${APP}-build@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/iam.serviceAccountUser
done

dispatcher_role=openSportsAnalystJobDispatcher
if ! gcloud iam roles describe "$dispatcher_role" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam roles create "$dispatcher_role" --project="$PROJECT_ID" \
    --title='Open Sports Analyst job dispatcher' --stage=GA \
    --permissions=run.jobs.run,run.jobs.runWithOverrides
fi
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${APP}-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="projects/${PROJECT_ID}/roles/${dispatcher_role}"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${APP}-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/cloudtasks.enqueuer
gcloud iam service-accounts add-iam-policy-binding "${APP}-tasks@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" --member="serviceAccount:${APP}-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/iam.serviceAccountUser
gcloud iam service-accounts add-iam-policy-binding "${APP}-tasks@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" --member="serviceAccount:service-${number}@gcp-sa-cloudtasks.iam.gserviceaccount.com" \
  --role=roles/iam.serviceAccountTokenCreator

if gcloud tasks queues describe "${APP}-sync" --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud tasks queues update "${APP}-sync" --location="$REGION" --project="$PROJECT_ID" \
    --max-attempts=3 --max-retry-duration=3600s --max-concurrent-dispatches=1 --max-dispatches-per-second=1
else
  gcloud tasks queues create "${APP}-sync" --location="$REGION" --project="$PROJECT_ID" \
    --max-attempts=3 --max-retry-duration=3600s --max-concurrent-dispatches=1 --max-dispatches-per-second=1
fi

if gcloud tasks queues describe "${APP}-analysis" --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud tasks queues update "${APP}-analysis" --location="$REGION" --project="$PROJECT_ID" \
    --max-attempts=2 --max-retry-duration=3600s --max-concurrent-dispatches=1 --max-dispatches-per-second=1
else
  gcloud tasks queues create "${APP}-analysis" --location="$REGION" --project="$PROJECT_ID" \
    --max-attempts=2 --max-retry-duration=3600s --max-concurrent-dispatches=1 --max-dispatches-per-second=1
fi

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${APP}-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/cloudbuild.builds.editor
for role in roles/logging.viewer roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${APP}-deploy@${PROJECT_ID}.iam.gserviceaccount.com" --role="$role"
done
gcloud iam service-accounts add-iam-policy-binding "${APP}-build@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" --member="serviceAccount:${APP}-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/iam.serviceAccountUser

bucket="gs://${PROJECT_ID}-${APP}-builds"
if ! gcloud storage buckets describe "$bucket" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "$bucket" --project="$PROJECT_ID" --location="$REGION" --uniform-bucket-level-access
fi
for identity in deploy build; do
  gcloud storage buckets add-iam-policy-binding "$bucket" \
    --member="serviceAccount:${APP}-${identity}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/storage.objectAdmin
done

budget_name=$(gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" \
  --filter="displayName='${APP} monthly'" --format='value(name)' --limit=1)
if [ -n "$budget_name" ]; then
  gcloud billing budgets update "$budget_name" --budget-amount=1USD \
    --filter-projects="projects/${number}"
else
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" --display-name="${APP} monthly" \
    --budget-amount=1USD --filter-projects="projects/${number}" \
    --threshold-rule=percent=0.5 --threshold-rule=percent=1
fi

if [ -n "${GITHUB_REPOSITORY:-}" ]; then
  if ! gcloud iam workload-identity-pools describe "$APP" --location=global --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam workload-identity-pools create "$APP" --location=global --project="$PROJECT_ID"
  fi
  if ! gcloud iam workload-identity-pools providers describe github --workload-identity-pool="$APP" --location=global --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam workload-identity-pools providers create-oidc github --workload-identity-pool="$APP" --location=global --project="$PROJECT_ID" \
      --issuer-uri=https://token.actions.githubusercontent.com \
      --attribute-mapping='google.subject=assertion.sub,attribute.repository=assertion.repository' \
      --attribute-condition="assertion.repository == '${GITHUB_REPOSITORY}' && assertion.ref == 'refs/heads/main'"
  fi
  gcloud iam service-accounts add-iam-policy-binding "${APP}-deploy@${PROJECT_ID}.iam.gserviceaccount.com" \
    --project="$PROJECT_ID" --role=roles/iam.workloadIdentityUser \
    --member="principalSet://iam.googleapis.com/projects/${number}/locations/global/workloadIdentityPools/${APP}/attribute.repository/${GITHUB_REPOSITORY}"
  echo "GCP_WIF_PROVIDER=projects/${number}/locations/global/workloadIdentityPools/${APP}/providers/github"
fi
