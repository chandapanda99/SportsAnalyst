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

echo "[deploy] Submitting Open Sports Analyst to Cloud Build"
build_id=$(gcloud builds submit . --project="$PROJECT_ID" --region="$REGION" \
  --config=deploy/cloud-run/cloudbuild.yaml \
  --service-account="projects/${PROJECT_ID}/serviceAccounts/${APP}-build@${PROJECT_ID}.iam.gserviceaccount.com" \
  --gcs-source-staging-dir="gs://${PROJECT_ID}-${APP}-builds/source" \
  --substitutions="_REGION=${REGION},_APP=${APP},_R2_ENDPOINT=${R2_ENDPOINT},_R2_BUCKET=${R2_BUCKET:-open-sports-analyst},_R2_PREFIX=${R2_PREFIX:-production},_FOUNDRY_ENDPOINT=${FOUNDRY_ENDPOINT},_MODEL=${MODEL:-gpt-5.6-luna},_LANGSMITH_TRACING=${LANGSMITH_TRACING:-false}" \
  --async --format='value(id)')

[ -n "$build_id" ] || { echo "[deploy] Cloud Build did not return a build ID" >&2; exit 1; }
build_url="https://console.cloud.google.com/cloud-build/builds;region=${REGION}/${build_id}?project=${PROJECT_ID}"
echo "[deploy] Build ${build_id} accepted"
echo "[deploy] Detailed logs: ${build_url}"

stage_label() {
  case "$1" in
    build-analysis-image) echo "Building the analysis image" ;;
    push-analysis-image) echo "Uploading the analysis image" ;;
    build-sync-image) echo "Building the lightweight dataset-sync image" ;;
    push-sync-image) echo "Uploading the dataset-sync image" ;;
    build-api-image) echo "Building the lightweight API and frontend image" ;;
    push-api-image) echo "Uploading the API and frontend image" ;;
    deploy-analysis) echo "Deploying the fallback analysis job" ;;
    deploy-analysis-service) echo "Deploying the private analysis service" ;;
    deploy-sync) echo "Deploying the private dataset-sync service" ;;
    deploy-service) echo "Deploying the API and frontend" ;;
    smoke-test) echo "Verifying health and frontend responses" ;;
    *) echo "Finalizing the Cloud Build" ;;
  esac
}

last_stage=""
while true; do
  read -r build_status active_stage <<< "$(
    gcloud builds describe "$build_id" --project="$PROJECT_ID" --region="$REGION" \
      --format=json | python3 deploy/cloud-run/build_status.py
  )"
  stage_message=$(stage_label "$active_stage")
  if [ "$active_stage" != "$last_stage" ]; then
    echo "[deploy] ${stage_message} (${build_status})"
    last_stage=$active_stage
  else
    echo "[deploy] $(date '+%H:%M:%S') ${stage_message} is still in progress"
  fi

  case "$build_status" in
    SUCCESS)
      echo "[deploy] Deployment completed successfully"
      service_url=$(
        gcloud run services describe "$APP" --project="$PROJECT_ID" --region="$REGION" \
          --format='value(status.url)'
      )
      echo "[deploy] Open Sports Analyst: ${service_url}"
      exit 0
      ;;
    FAILURE|INTERNAL_ERROR|TIMEOUT|CANCELLED|EXPIRED)
      echo "[deploy] Build ended with status ${build_status}" >&2
      echo "[deploy] Inspect the failed stage at ${build_url}" >&2
      exit 1
      ;;
  esac
  sleep 15
done
