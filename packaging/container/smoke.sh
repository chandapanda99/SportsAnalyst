#!/usr/bin/env bash
set -euo pipefail

image="${1:-open-sports-analyst:smoke}"
container="open-sports-analyst-smoke-$$"
port="${SPORTS_ANALYST_SMOKE_PORT:-18080}"

cleanup() {
  docker rm --force "${container}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker build --target runtime --tag "${image}" .
docker run --detach --name "${container}" \
  --publish "127.0.0.1:${port}:8080" \
  --env JOB_BACKEND=local \
  --env PERSISTENCE_BACKEND=local \
  "${image}" >/dev/null

for _ in $(seq 1 60); do
  if curl --fail --silent "http://127.0.0.1:${port}/api/health" >/dev/null \
    && curl --fail --silent "http://127.0.0.1:${port}/" >/dev/null; then
    echo "Container smoke test passed: API health and compiled frontend are available."
    exit 0
  fi
  if [ "$(docker inspect --format '{{.State.Running}}' "${container}")" != "true" ]; then
    docker logs "${container}"
    exit 1
  fi
  sleep 1
done

docker logs "${container}"
echo "Container smoke test timed out after 60 seconds." >&2
exit 1
