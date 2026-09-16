"""Run one investigation at a time, isolated from the API and other attempts."""
from __future__ import annotations

import argparse
import logging
import multiprocessing
import signal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
from typing import Any

from sports_analyst.config import Settings, get_settings
from sports_analyst.jobs import LeaseLost, PostgresJobStore, WorkerEvents

logger = logging.getLogger("sports_analyst.worker")


def execute_job(settings: Settings, job: dict) -> None:
    # Import the service only in the child. The supervisor stays small and can
    # renew leases while Polars, the model client, or an exporter is busy.
    from sports_analyst.models import AnalysisRequest
    from sports_analyst.service import AnalystApplication

    jobs = PostgresJobStore(settings.database_url.get_secret_value())
    key, token = job["job_id"], job["lease_token"]
    events = WorkerEvents(jobs, key, token)
    try:
        application = AnalystApplication(settings)
        application.events = events
        application.store.publication_guard = lambda: jobs.publication(key, token, settings.job_lease_seconds)
        payload = job["payload"]
        if job["kind"] != "sync":
            # R2 may have committed successfully just before a previous worker
            # died. Reuse that result instead of repeating a model call.
            try:
                application.store.get_investigation(key)
            except KeyError:
                pass
            else:
                jobs.finish(key, token, dict(stage="complete", message="Investigation ready", progress=1,
                                             investigation_id=key))
                return
        if job["kind"] == "investigation":
            application.investigate(AnalysisRequest.model_validate(payload), key)
        elif job["kind"] == "follow_up":
            application.follow_up(payload["parent_id"], payload["question"], key)
        elif job["kind"] == "sync":
            application.sync(payload["seasons"], key, payload.get("datasets"), payload["sport"])
        else:
            raise ValueError("Unsupported job kind")
        if events.completion is None:
            raise RuntimeError("The job returned without completing")
        jobs.finish(key, token, events.completion)
    except LeaseLost:
        logger.warning("job_lease_lost job_id=%s", key)
    except Exception as error:
        # Do not publish provider exception strings (which may contain URLs or
        # credentials) into browser-visible events.
        logger.error("job_failed job_id=%s error_type=%s", key, type(error).__name__)
        logger.debug("job_failed_details job_id=%s", key, exc_info=True)
        status = getattr(error, "status_code", None)
        retryable = isinstance(error, (ConnectionError, TimeoutError)) or status in {408, 429, 500, 502, 503, 504}
        retryable |= type(error).__name__ in {"APIConnectionError", "APITimeoutError", "OperationalError", "ReadTimeout"}
        try:
            jobs.fail(key, token, retryable)
        except Exception:
            logger.warning("job_failure_update_unavailable job_id=%s; lease will expire", key)


def run_worker(settings: Settings, *, once: bool = False, drain: bool = False, stop_event: Any | None = None) -> None:
    from sports_analyst.log_config import configure_logging

    configure_logging(settings.log_level)
    if settings.job_backend != "postgres":
        raise ValueError("The worker requires JOB_BACKEND=postgres")
    jobs = PostgresJobStore(settings.database_url.get_secret_value())
    stop = stop_event or Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    context = multiprocessing.get_context("spawn")
    idle = settings.job_poll_seconds
    # Each attempt owns a disposable DuckDB/cache directory. Shared artifacts
    # live in R2; cleanup prevents large NBA downloads filling the worker disk.
    worker_root = settings.data_dir / "workers"
    worker_root.mkdir(parents=True, exist_ok=True)
    while not stop.is_set():
        try:
            job = jobs.claim(settings.job_lease_seconds)
        except Exception as error:
            logger.error("job_claim_unavailable error_type=%s", type(error).__name__)
            if once or drain:
                raise
            stop.wait(settings.job_idle_poll_seconds)
            continue
        if job is None:
            if once or (drain and not jobs.has_active_work()):
                return
            stop.wait(idle)
            idle = min(settings.job_idle_poll_seconds, idle * 2)
            continue
        idle = settings.job_poll_seconds
        cache = TemporaryDirectory(prefix="attempt-", dir=worker_root)
        worker_settings = settings.model_copy(update={"data_dir": Path(cache.name)})
        child = context.Process(target=execute_job, args=(worker_settings, job))
        child.start()
        deadline = monotonic() + settings.job_timeout_seconds
        next_heartbeat = monotonic() + settings.job_heartbeat_seconds
        try:
            while child.is_alive():
                # Check desktop shutdown promptly while retaining the longer
                # database heartbeat interval.
                child.join(timeout=1)
                if not child.is_alive():
                    break
                if stop.is_set():
                    break
                if monotonic() >= deadline:
                    logger.error("job_execution_timeout job_id=%s", job["job_id"])
                    break
                if monotonic() < next_heartbeat:
                    continue
                try:
                    owned = jobs.heartbeat(job["job_id"], job["lease_token"], settings.job_lease_seconds)
                except Exception:
                    owned = False
                if not owned:
                    logger.warning("worker_stopping_unleased_attempt job_id=%s", job["job_id"])
                    break
                next_heartbeat = monotonic() + settings.job_heartbeat_seconds
        finally:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
                if child.is_alive():
                    child.kill()
                    child.join(timeout=5)
            child.close()
            cache.cleanup()
        if once:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process at most one available job and exit")
    parser.add_argument("--drain", action="store_true", help="Process queued jobs and delayed retries, then exit")
    args = parser.parse_args()
    if args.once and args.drain:
        parser.error("--once and --drain are mutually exclusive")
    run_worker(get_settings(), once=args.once, drain=args.drain)


if __name__ == "__main__":
    main()
