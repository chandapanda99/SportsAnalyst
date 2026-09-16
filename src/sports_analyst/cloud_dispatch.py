"""Optional Cloud Run launcher. No Google imports on desktop startup."""
import logging
from urllib.parse import quote

from sports_analyst.config import Settings

logger = logging.getLogger(__name__)


def launch(settings: Settings) -> None:
    import importlib

    google_auth = importlib.import_module("google.auth")
    transport = importlib.import_module("google.auth.transport.requests")
    credentials, _ = google_auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    path = "/".join(quote(value, safe="") for value in (
        settings.cloud_run_project, settings.cloud_run_region, settings.cloud_run_worker_job))
    project, region, job = path.split("/")
    with transport.AuthorizedSession(credentials) as session:
        response = session.post(
            f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job}:run",
            json={}, timeout=20)
        response.raise_for_status()


def ensure_dispatch(settings: Settings, jobs, key: str) -> None:
    if settings.job_dispatch_backend != "cloud_run":
        return
    try:
        attempt = jobs.reserve_dispatch(key)
        if attempt is None:
            return
        try:
            launch(settings)
        except Exception:
            jobs.complete_dispatch(key, attempt, False)
            raise
        jobs.complete_dispatch(key, attempt, True)
    except Exception as error:
        # The committed queue record survives; polling retries without resubmission.
        logger.warning("job_dispatch_pending job_id=%s error_type=%s", key, type(error).__name__)
