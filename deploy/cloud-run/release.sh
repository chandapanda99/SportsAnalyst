#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT_ID:?}" "${REGION:?}" "${APP:?}" "${IMAGE:?}" "${R2_ENDPOINT:?}" "${FOUNDRY_ENDPOINT:?}"
common="DATA_DIR=/tmp/open-sports-analyst,PERSISTENCE_BACKEND=s3,JOB_BACKEND=postgres,DATASET_CACHE_MB=256,OBJECT_STORAGE_ENDPOINT_URL=${R2_ENDPOINT},OBJECT_STORAGE_BUCKET=${R2_BUCKET},OBJECT_STORAGE_PREFIX=${R2_PREFIX},OBJECT_STORAGE_REGION=auto,FOUNDRY_ENDPOINT=${FOUNDRY_ENDPOINT},MODEL=${MODEL},LANGSMITH_TRACING=false"
secrets="DATABASE_URL=${APP}-database:latest,AWS_ACCESS_KEY_ID=${APP}-r2-key:latest,AWS_SECRET_ACCESS_KEY=${APP}-r2-secret:latest,FOUNDRY_API_KEY=${APP}-model-key:latest"
if [ "${LANGSMITH_TRACING:-false}" = true ]; then
  common="${common/LANGSMITH_TRACING=false/LANGSMITH_TRACING=true}"
  secrets="${secrets},LANGSMITH_API_KEY=${APP}-langsmith:latest"
fi
gcloud run jobs deploy "${APP}-migrate" --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
  --service-account="${APP}-migrate@${PROJECT_ID}.iam.gserviceaccount.com" \
  --command=alembic --args=upgrade,head --tasks=1 --max-retries=0 --task-timeout=600s \
  --set-secrets="DATABASE_MIGRATION_URL=${APP}-migration:latest"
gcloud run jobs execute "${APP}-migrate" --project="$PROJECT_ID" --region="$REGION" --wait
gcloud run jobs deploy "${APP}-worker" --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
  --service-account="${APP}-worker@${PROJECT_ID}.iam.gserviceaccount.com" \
  --command=sports-analyst-worker --args=--drain --tasks=1 --parallelism=1 --max-retries=1 \
  --task-timeout=21600s --cpu=2 --memory=8Gi --set-env-vars="$common" --set-secrets="$secrets"
gcloud run jobs add-iam-policy-binding "${APP}-worker" --project="$PROJECT_ID" --region="$REGION" \
  --member="serviceAccount:${APP}-api@${PROJECT_ID}.iam.gserviceaccount.com" --role=roles/run.invoker
gcloud run deploy "$APP" --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
  --service-account="${APP}-api@${PROJECT_ID}.iam.gserviceaccount.com" --allow-unauthenticated \
  --port=8080 --cpu=2 --memory=4Gi --concurrency=8 --min=0 --max=1 --timeout=300s \
  --set-env-vars="${common},JOB_DISPATCH_BACKEND=cloud_run,JOB_PROGRESS_TRANSPORT=poll,CLOUD_RUN_PROJECT=${PROJECT_ID},CLOUD_RUN_REGION=${REGION},CLOUD_RUN_WORKER_JOB=${APP}-worker,MAX_ACTIVE_JOBS=3" \
  --set-secrets="$secrets"
url=$(gcloud run services describe "$APP" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
curl --fail --retry 8 --retry-all-errors --retry-delay 5 "${url}/api/health"
curl --fail --retry 3 "${url}/" --output /dev/null
