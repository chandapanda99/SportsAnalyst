"""Private Cloud Tasks target for investigations and follow-ups."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request

from sports_analyst.config import get_settings
from sports_analyst.job_common import retryable_job_error
from sports_analyst.log_config import configure_logging
from sports_analyst.service import AnalystApplication
from sports_analyst.worker import run_object_analysis

logger = logging.getLogger("sports_analyst.analysis_api")
settings = get_settings()
configure_logging(settings.log_level)
app = FastAPI(title="Open Sports Analyst Analysis Worker", docs_url=None, redoc_url=None, openapi_url=None)
def analysis_application() -> AnalystApplication:
    """Load the latest R2 catalog for each task, including post-start syncs."""
    return AnalystApplication(settings)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ready"}


@app.post("/internal/jobs/{job_id}")
def execute_analysis(job_id: str, request: Request) -> dict[str, str]:
    """Acknowledge terminal work; ask Cloud Tasks to retry transient failures."""
    application = analysis_application()
    jobs = application.jobs
    if jobs is None:
        raise HTTPException(503, "Durable job storage is unavailable")
    job = jobs.request(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    kind = job["kind"]
    if kind not in {"investigation", "follow_up"}:
        raise HTTPException(409, "Only analysis jobs are accepted")
    status = jobs.status(job_id)
    if status and status.get("stage") == "complete":
        return {"status": "complete"}
    application.jobs = jobs
    application.events = jobs
    jobs.emit(job_id, "starting", "Starting your analysis", 0.03)
    logger.info("analysis_task_started job_id=%s kind=%s", job_id, kind)
    try:
        run_object_analysis(application, job_id, kind, job["payload"])
    except Exception as error:
        logger.error("analysis_task_failed job_id=%s error_type=%s", job_id, type(error).__name__)
        logger.debug("analysis_task_failed_details job_id=%s", job_id, exc_info=True)
        retry_count = int(request.headers.get("X-CloudTasks-TaskRetryCount", "0"))
        retryable = retryable_job_error(error) and retry_count < int(job.get("max_attempts", 2)) - 1
        jobs.emit(job_id, "retrying" if retryable else "failed",
                  "Temporary failure; waiting to retry." if retryable else "Analysis failed. Check worker logs, then try again.",
                  0 if retryable else 1)
        if retryable:
            raise HTTPException(503, "Temporary analysis failure") from error
        return {"status": "failed"}
    logger.info("analysis_task_completed job_id=%s kind=%s", job_id, kind)
    return {"status": "complete"}
