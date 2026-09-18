"""Private Cloud Tasks target for low-latency dataset synchronization."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request

from sports_analyst.config import get_settings
from sports_analyst.job_common import retryable_job_error
from sports_analyst.log_config import configure_logging
from sports_analyst.object_jobs import ObjectJobStore
from sports_analyst.service import AnalystApplication

logger = logging.getLogger("sports_analyst.sync_api")
settings = get_settings()
configure_logging(settings.log_level)
app = FastAPI(title="Open Sports Analyst Sync Worker", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ready"}


@app.post("/internal/jobs/{job_id}")
def execute_sync(job_id: str, request: Request) -> dict[str, str]:
    """Run one authenticated Cloud Task and return non-2xx to request a retry."""
    application = AnalystApplication(settings)
    jobs = ObjectJobStore(application.store.persistence)
    job = jobs.request(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job["kind"] != "sync":
        raise HTTPException(409, "Only dataset sync jobs are accepted")
    status = jobs.status(job_id)
    if status and status.get("stage") == "complete":
        return {"status": "complete"}
    application.jobs = jobs
    application.events = jobs
    payload = job["payload"]
    jobs.emit(job_id, "starting", "Starting your data download", 0.03)
    try:
        application.sync(payload["seasons"], job_id, payload.get("datasets"), payload["sport"])
    except Exception as error:
        logger.error("sync_task_failed job_id=%s error_type=%s", job_id, type(error).__name__)
        logger.debug("sync_task_failed_details job_id=%s", job_id, exc_info=True)
        retry_count = int(request.headers.get("X-CloudTasks-TaskRetryCount", "0"))
        retryable = retryable_job_error(error) and retry_count < int(job.get("max_attempts", 3)) - 1
        jobs.emit(
            job_id,
            "retrying" if retryable else "failed",
            "Temporary failure; waiting to retry." if retryable else "Data download failed. Check worker logs, then try again.",
            0 if retryable else 1,
        )
        if retryable:
            raise HTTPException(503, "Temporary sync failure") from error
        return {"status": "failed"}
    return {"status": "complete"}
