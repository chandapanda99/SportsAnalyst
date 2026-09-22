"""Run one investigation at a time, isolated from the API and other attempts."""
from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import signal
from threading import Event
from time import monotonic, perf_counter
from typing import Any

from sports_analyst.config import Settings, get_settings
from sports_analyst.job_common import retryable_job_error

logger = logging.getLogger("sports_analyst.worker")


def execute_job(settings: Settings, job: dict) -> None:
    # Import the service only in the child. The supervisor stays small and can
    # renew leases while Polars, the model client, or an exporter is busy.
    from sports_analyst.jobs import LeaseLost, SQLiteJobStore, WorkerEvents
    from sports_analyst.models import AnalysisRequest
    from sports_analyst.service import AnalystApplication

    jobs = SQLiteJobStore(settings.job_database_path)
    key, token = job["job_id"], job["lease_token"]
    events = WorkerEvents(jobs, key, token)
    try:
        application = AnalystApplication(settings)
        application.events = events
        application.store.publication_guard = lambda: jobs.publication(key, token, settings.job_lease_seconds)
        payload = job["payload"]
        logger.info("job_attempt_started job_id=%s kind=%s attempt=%s", key, job["kind"], job.get("attempts", "unknown"))
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
        logger.info("job_work_completed job_id=%s kind=%s", key, job["kind"])
        if events.completion is None:
            raise RuntimeError("The job returned without completing")
        jobs.finish(key, token, events.completion)
        logger.info("job_result_published job_id=%s kind=%s", key, job["kind"])
    except LeaseLost:
        logger.warning("job_lease_lost job_id=%s", key)
    except Exception as error:
        # Do not publish provider exception strings (which may contain URLs or
        # credentials) into browser-visible events.
        logger.error("job_failed job_id=%s error_type=%s", key, type(error).__name__)
        logger.debug("job_failed_details job_id=%s", key, exc_info=True)
        try:
            jobs.fail(key, token, retryable_job_error(error))
        except Exception:
            logger.warning("job_failure_update_unavailable job_id=%s; lease will expire", key)


def run_worker(settings: Settings, *, once: bool = False, drain: bool = False, stop_event: Any | None = None) -> None:
    from sports_analyst.jobs import SQLiteJobStore
    from sports_analyst.log_config import configure_logging

    configure_logging(settings.log_level)
    if settings.job_backend != "sqlite":
        raise ValueError("The desktop worker requires JOB_BACKEND=sqlite")
    jobs = SQLiteJobStore(settings.job_database_path)
    stop = stop_event or Event()
    logger.info(
        "worker_started mode=%s lease_seconds=%s attempt_timeout_seconds=%s",
        "once" if once else "drain" if drain else "continuous",
        settings.job_lease_seconds,
        settings.job_timeout_seconds,
    )
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    context = multiprocessing.get_context("spawn")
    idle = settings.job_poll_seconds
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
                logger.info("worker_queue_drained mode=%s", "once" if once else "drain")
                return
            stop.wait(idle)
            idle = min(settings.job_idle_poll_seconds, idle * 2)
            continue
        logger.info(
            "job_claimed job_id=%s kind=%s attempt=%s",
            job["job_id"],
            job.get("kind", "unknown"),
            job.get("attempts", "unknown"),
        )
        idle = settings.job_poll_seconds
        child = context.Process(target=execute_job, args=(settings, job))
        attempt_started_at = perf_counter()
        child.start()
        logger.info("job_child_started job_id=%s pid=%s", job["job_id"], child.pid)
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
            logger.info(
                "job_child_exited job_id=%s exit_code=%s duration_ms=%s",
                job["job_id"],
                child.exitcode,
                round((perf_counter() - attempt_started_at) * 1000),
            )
            child.close()
        # A hard child exit cannot publish a terminal event. Release its lease
        # immediately so this worker—or the next desktop launch—can recover it.
        jobs.release(job["job_id"], job["lease_token"])
        if once:
            return


def execute_object_job(settings: Settings, key: str) -> None:
    """Execute one R2-backed request; Cloud Run owns process retries."""
    from sports_analyst.models import AnalysisRequest
    from sports_analyst.service import AnalystApplication

    application = AnalystApplication(settings)
    jobs = application.jobs
    if jobs is None:
        raise RuntimeError("Durable object jobs are not configured")
    request = jobs.request(key)
    if request is None:
        raise KeyError(f"job not found: {key}")
    status = jobs.status(key)
    if status and status.get("stage") == "complete":
        logger.info("object_job_already_complete job_id=%s", key)
        return
    kind, payload = request["kind"], request["payload"]
    application.jobs = jobs
    application.events = jobs
    jobs.emit(key, "starting", "Starting your analysis" if kind != "sync" else "Starting your data download", 0.03)
    logger.info("object_job_started job_id=%s kind=%s", key, kind)
    try:
        if kind == "investigation":
            try:
                application.store.get_investigation(key)
            except KeyError:
                application.investigate(AnalysisRequest.model_validate(payload), key)
            else:
                jobs.emit(key, "complete", "Investigation ready", 1, investigation_id=key)
        elif kind == "follow_up":
            try:
                application.store.get_investigation(key)
            except KeyError:
                application.follow_up(payload["parent_id"], payload["question"], key)
            else:
                jobs.emit(key, "complete", "Follow-up ready", 1, investigation_id=key)
        elif kind == "sync":
            application.sync(payload["seasons"], key, payload.get("datasets"), payload["sport"])
        else:
            raise ValueError(f"unsupported job kind: {kind}")
    except Exception as error:
        logger.error("object_job_failed job_id=%s error_type=%s", key, type(error).__name__)
        logger.debug("object_job_failed_details job_id=%s", key, exc_info=True)
        attempt = int(os.getenv("CLOUD_RUN_TASK_ATTEMPT", "0"))
        retryable = retryable_job_error(error) and attempt < int(request.get("max_attempts", 2)) - 1
        jobs.emit(
            key,
            "retrying" if retryable else "failed",
            "Temporary failure; waiting to retry." if retryable else "Job failed. Check worker logs, then try again.",
            0 if retryable else 1,
        )
        if retryable:
            raise
        return
    logger.info("object_job_completed job_id=%s kind=%s", key, kind)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process at most one available job and exit")
    parser.add_argument("--drain", action="store_true", help="Process queued jobs and delayed retries, then exit")
    parser.add_argument("--object-job", action="store_true", help="Process JOB_ID from durable object storage")
    args = parser.parse_args()
    if sum((args.once, args.drain, args.object_job)) > 1:
        parser.error("--once, --drain and --object-job are mutually exclusive")
    settings = get_settings()
    if args.object_job:
        from sports_analyst.log_config import configure_logging

        configure_logging(settings.log_level)
        key = os.getenv("JOB_ID")
        if not key:
            parser.error("--object-job requires JOB_ID")
        execute_object_job(settings, key)
    else:
        run_worker(settings, once=args.once, drain=args.drain)


if __name__ == "__main__":
    main()
