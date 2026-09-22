#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT_ID:?}" "${REGION:?}" "${APP:?}" "${IMAGE:?}" "${R2_ENDPOINT:?}" "${FOUNDRY_ENDPOINT:?}"
phase=${1:-all}
storage="DATA_DIR=/tmp/open-sports-analyst,PERSISTENCE_BACKEND=s3,JOB_BACKEND=object,JOB_MAX_ATTEMPTS=2,JOB_PROGRESS_TRANSPORT=poll,DATASET_CACHE_MB=256,DATASET_SYNC_CONCURRENCY=2,OBJECT_STORAGE_TRANSFER_CONCURRENCY=4,OBJECT_STORAGE_ENDPOINT_URL=${R2_ENDPOINT},OBJECT_STORAGE_BUCKET=${R2_BUCKET},OBJECT_STORAGE_PREFIX=${R2_PREFIX},OBJECT_STORAGE_REGION=auto,LANGSMITH_TRACING=false"
analysis_env="${storage},JOB_TIMEOUT_SECONDS=21600,FOUNDRY_ENDPOINT=${FOUNDRY_ENDPOINT},MODEL=${MODEL}"
storage_secrets="AWS_ACCESS_KEY_ID=${APP}-r2-key:latest,AWS_SECRET_ACCESS_KEY=${APP}-r2-secret:latest"
analysis_secrets="${storage_secrets},FOUNDRY_API_KEY=${APP}-model-key:latest"
if [ "${LANGSMITH_TRACING:-false}" = true ]; then
  analysis_env="${analysis_env/LANGSMITH_TRACING=false/LANGSMITH_TRACING=true}"
  analysis_secrets="${analysis_secrets},LANGSMITH_API_KEY=${APP}-langsmith:latest"
fi

deploy_analysis() {
  echo "[release] Deploying fallback long-running analysis job"
  gcloud run jobs deploy "${APP}-analysis" --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
    --service-account="${APP}-analysis@${PROJECT_ID}.iam.gserviceaccount.com" \
    --command=sports-analyst-worker --args=--object-job --tasks=1 --parallelism=1 --max-retries=1 \
    --task-timeout=21600s --cpu=1 --memory=4Gi --set-env-vars="$analysis_env" --set-secrets="$analysis_secrets"
}

deploy_analysis_service() {
  echo "[release] Deploying private low-latency analysis service"
  service_analysis_env="${analysis_env/JOB_TIMEOUT_SECONDS=21600/JOB_TIMEOUT_SECONDS=1800}"
  gcloud run deploy "${APP}-analysis-service" --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
    --service-account="${APP}-analysis@${PROJECT_ID}.iam.gserviceaccount.com" --no-allow-unauthenticated \
    --command=uvicorn --args=sports_analyst.analysis_api:app,--host,0.0.0.0,--port,8080 \
    --port=8080 --cpu=1 --memory=4Gi --concurrency=1 --min=0 --max=1 --timeout=1800s --cpu-boost \
    --set-env-vars="$service_analysis_env" --set-secrets="$analysis_secrets"
  gcloud run services add-iam-policy-binding "${APP}-analysis-service" --project="$PROJECT_ID" --region="$REGION" \
    --member="serviceAccount:${APP}-tasks@${PROJECT_ID}.iam.gserviceaccount.com" --role=roles/run.invoker
}

deploy_sync() {
  echo "[release] Deploying private low-latency sync service"
  gcloud run deploy "${APP}-sync" --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
    --service-account="${APP}-sync@${PROJECT_ID}.iam.gserviceaccount.com" --no-allow-unauthenticated \
    --command=uvicorn --args=sports_analyst.sync_api:app,--host,0.0.0.0,--port,8080 \
    --port=8080 --cpu=1 --memory=4Gi --concurrency=1 --min=0 --max=1 --timeout=1800s --cpu-boost \
    --set-env-vars="$storage" --set-secrets="$storage_secrets"
  gcloud run services add-iam-policy-binding "${APP}-sync" --project="$PROJECT_ID" --region="$REGION" \
    --member="serviceAccount:${APP}-tasks@${PROJECT_ID}.iam.gserviceaccount.com" --role=roles/run.invoker
}

deploy_service() {
  echo "[release] Deploying public API and frontend service"
  sync_url=$(gcloud run services describe "${APP}-sync" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
  analysis_url=$(gcloud run services describe "${APP}-analysis-service" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
  gcloud run deploy "$APP" --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
    --service-account="${APP}-api@${PROJECT_ID}.iam.gserviceaccount.com" --allow-unauthenticated \
    --port=8080 --cpu=2 --memory=4Gi --concurrency=8 --min=0 --max=1 --timeout=300s --cpu-boost \
    --set-env-vars="${storage},JOB_DISPATCH_BACKEND=cloud_run,JOB_DISPATCH_RETRY_SECONDS=30,JOB_DISPATCH_STARTUP_SECONDS=900,CLOUD_RUN_PROJECT=${PROJECT_ID},CLOUD_RUN_REGION=${REGION},CLOUD_RUN_WORKER_JOB=${APP}-analysis,CLOUD_RUN_SYNC_SERVICE_URL=${sync_url},CLOUD_RUN_ANALYSIS_SERVICE_URL=${analysis_url},CLOUD_TASKS_QUEUE=${APP}-sync,CLOUD_TASKS_ANALYSIS_QUEUE=${APP}-analysis,CLOUD_TASKS_SERVICE_ACCOUNT=${APP}-tasks@${PROJECT_ID}.iam.gserviceaccount.com,MAX_ACTIVE_JOBS=3,FOUNDRY_ENDPOINT=${FOUNDRY_ENDPOINT},MODEL=${MODEL}" \
    --set-secrets="$storage_secrets"
}

smoke_test() {
  echo "[release] Running health and frontend smoke checks"
  url=$(gcloud run services describe "$APP" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
  curl --fail --retry 8 --retry-all-errors --retry-delay 5 "${url}/api/health"
  curl --fail --retry 3 "${url}/" --output /dev/null
  echo "[release] Deployment verified at ${url}"
}

case "$phase" in
  analysis) deploy_analysis ;;
  analysis-service) deploy_analysis_service ;;
  sync) deploy_sync ;;
  service) deploy_service ;;
  smoke) smoke_test ;;
  all)
    deploy_analysis
    deploy_analysis_service
    deploy_sync
    deploy_service
    smoke_test
    ;;
  *) echo "Unknown release phase: $phase" >&2; exit 64 ;;
esac
