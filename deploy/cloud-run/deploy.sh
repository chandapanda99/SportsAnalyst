#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT_ID:?}"
REGION=${REGION:-us-central1}
APP=${APP:-open-sports-analyst}
ENV_FILE=${ENV_FILE:-.env}
dotenv_value() {
  python3 deploy/cloud-run/read_dotenv.py "$ENV_FILE" "$1"
}
load_from_dotenv() {
  local target=$1 source=$2 value
  if [ -n "${!target:-}" ] || [ -z "$ENV_FILE" ]; then return; fi
  value=$(dotenv_value "$source")
  export "$target=$value"
}
if [ -n "$ENV_FILE" ]; then
  [ -f "$ENV_FILE" ] || { echo "ENV_FILE does not exist: $ENV_FILE" >&2; exit 66; }
  load_from_dotenv R2_ENDPOINT OBJECT_STORAGE_ENDPOINT_URL
  load_from_dotenv R2_BUCKET OBJECT_STORAGE_BUCKET
  load_from_dotenv R2_PREFIX OBJECT_STORAGE_PREFIX
  load_from_dotenv FOUNDRY_ENDPOINT FOUNDRY_ENDPOINT
  load_from_dotenv MODEL MODEL
  load_from_dotenv LANGSMITH_TRACING LANGSMITH_TRACING
fi
: "${R2_ENDPOINT:?Set R2_ENDPOINT or provide OBJECT_STORAGE_ENDPOINT_URL in ENV_FILE}"
: "${FOUNDRY_ENDPOINT:?Set FOUNDRY_ENDPOINT or provide it in ENV_FILE}"
gcloud builds submit . --project="$PROJECT_ID" --region="$REGION" \
  --config=deploy/cloud-run/cloudbuild.yaml \
  --service-account="projects/${PROJECT_ID}/serviceAccounts/${APP}-build@${PROJECT_ID}.iam.gserviceaccount.com" \
  --gcs-source-staging-dir="gs://${PROJECT_ID}-${APP}-builds/source" \
  --substitutions="_REGION=${REGION},_APP=${APP},_R2_ENDPOINT=${R2_ENDPOINT},_R2_BUCKET=${R2_BUCKET:-open-sports-analyst},_R2_PREFIX=${R2_PREFIX:-production},_FOUNDRY_ENDPOINT=${FOUNDRY_ENDPOINT},_MODEL=${MODEL:-gpt-5.6-luna},_LANGSMITH_TRACING=${LANGSMITH_TRACING:-false}"
