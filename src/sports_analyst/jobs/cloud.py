"""Dispatch durable object jobs onto Google Cloud without desktop imports."""
from __future__ import annotations

import base64
import importlib
import logging
from urllib.parse import quote

from sports_analyst.config import Settings

logger = logging.getLogger(__name__)


def _authorized_session():
    google_auth = importlib.import_module("google.auth")
    transport = importlib.import_module("google.auth.transport.requests")
    credentials, _ = google_auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return transport.AuthorizedSession(credentials)


def launch_analysis(settings: Settings, key: str) -> None:
    """Create one long-running Cloud Run Job execution for one app job."""
    path = "/".join(quote(value, safe="") for value in (
        settings.cloud_run_project,
        settings.cloud_run_region,
        settings.cloud_run_worker_job,
    ))
    project, region, job = path.split("/")
    with _authorized_session() as session:
        response = session.post(
            f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job}:run",
            json={
                "overrides": {
                    "containerOverrides": [{"env": [{"name": "JOB_ID", "value": key}]}],
                }
            },
            timeout=20,
        )
        response.raise_for_status()


def launch_sync(settings: Settings, key: str) -> None:
    """Create an authenticated Cloud Task targeting the private sync service."""
    _launch_task(settings, key, settings.cloud_tasks_queue, settings.cloud_run_sync_service_url)


def launch_analysis_task(settings: Settings, key: str) -> None:
    """Create an authenticated Cloud Task targeting the private analysis service."""
    _launch_task(settings, key, settings.cloud_tasks_analysis_queue, settings.cloud_run_analysis_service_url)


def _launch_task(settings: Settings, key: str, queue_name: str, service_url: str) -> None:
    project = quote(settings.cloud_run_project, safe="")
    region = quote(settings.cloud_run_region, safe="")
    queue = quote(queue_name, safe="")
    task_id = quote(key, safe="")
    parent = f"projects/{project}/locations/{region}/queues/{queue}"
    url = f"{service_url.rstrip('/')}/internal/jobs/{quote(key, safe='')}"
    with _authorized_session() as session:
        response = session.post(
            f"https://cloudtasks.googleapis.com/v2/{parent}/tasks",
            json={
                "task": {
                    "name": f"{parent}/tasks/{task_id}",
                    "dispatchDeadline": "1800s",
                    "httpRequest": {
                        "httpMethod": "POST",
                        "url": url,
                        "headers": {"Content-Type": "application/json"},
                        "body": base64.b64encode(b"{}").decode(),
                        "oidcToken": {
                            "serviceAccountEmail": settings.cloud_tasks_service_account,
                            "audience": service_url.rstrip("/"),
                        },
                    },
                }
            },
            timeout=20,
        )
        # A deterministic task name makes submission retries idempotent.
        if response.status_code != 409:
            response.raise_for_status()


def launch(settings: Settings, key: str, kind: str) -> None:
    if settings.job_backend == "object" and kind == "sync":
        launch_sync(settings, key)
    elif settings.job_backend == "object" and kind in {"investigation", "follow_up"} and settings.cloud_run_analysis_service_url:
        launch_analysis_task(settings, key)
    else:
        launch_analysis(settings, key)


def ensure_dispatch(settings: Settings, jobs, key: str, kind: str | None = None) -> None:
    if settings.job_dispatch_backend != "cloud_run":
        return
    if kind is None:
        request = jobs.request(key) if hasattr(jobs, "request") else None
        kind = request.get("kind") if request else "investigation"
    try:
        attempt = jobs.reserve_dispatch(key, settings.job_dispatch_startup_seconds)
        if attempt is None:
            return
        try:
            launch(settings, key, kind)
        except Exception:
            jobs.complete_dispatch(
                key,
                attempt,
                False,
                retry_seconds=settings.job_dispatch_retry_seconds,
                startup_seconds=settings.job_dispatch_startup_seconds,
            )
            raise
        jobs.complete_dispatch(
            key,
            attempt,
            True,
            retry_seconds=settings.job_dispatch_retry_seconds,
            startup_seconds=settings.job_dispatch_startup_seconds,
        )
    except Exception as error:
        logger.warning("job_dispatch_pending job_id=%s error_type=%s", key, type(error).__name__, exc_info=True)
