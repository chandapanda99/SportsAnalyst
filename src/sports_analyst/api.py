from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from sports_analyst.models import (
    AnalysisOptions,
    AnalysisRequest,
    DatasetManifest,
    InvestigationBundle,
    InvestigationSummary,
    MetricDefinition,
    PlayerOption,
    RuntimeCapabilities,
    SportOption,
    ToolDefinition,
    stable_id,
)
from sports_analyst.service import AnalystApplication

logger = logging.getLogger("sports_analyst.api")


def bundled_frontend_directory() -> Path:
    """Resolve the production frontend in source and frozen desktop builds."""
    configured = os.getenv("SPORTS_ANALYST_FRONTEND_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    bundle_root = getattr(sys, "_MEIPASS", None)
    root = Path(bundle_root) if bundle_root else Path(__file__).resolve().parents[2]
    return root / "frontend" / "dist"


class SyncRequest(BaseModel):
    # NBA currently exposes 32 reviewed seasons and 31 bulk packages. Keep a
    # bounded payload without rejecting a valid full-catalog selection.
    seasons: list[int] = Field(min_length=1, max_length=64)
    datasets: list[str] | None = Field(default=None, min_length=1, max_length=64)


class FollowUpRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)


class EvidenceBatchRequest(BaseModel):
    evidence_ids: list[str] = Field(min_length=1, max_length=100)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def create_app(application: AnalystApplication | None = None, frontend_dir: Path | None = None) -> FastAPI:
    service = application or AnalystApplication()
    api = FastAPI(title="Open Sports Analyst", version="1.0.0")
    catalog_lock = RLock()
    catalog_version = None
    catalog_refreshed_at = float("-inf")

    def enqueue(key: str, kind: str, payload: dict) -> None:
        from sports_analyst.cloud_dispatch import ensure_dispatch
        from sports_analyst.jobs import QueueFull

        try:
            service.jobs.enqueue(key, kind, payload, service.settings.job_max_attempts,
                                 max_active=service.settings.max_active_jobs)
        except QueueFull as error:
            raise HTTPException(429, str(error), headers={"Retry-After": "30"}) from error
        except Exception as error:
            logger.error("job_enqueue_failed error_type=%s", type(error).__name__)
            raise HTTPException(503, "The job queue is unavailable. Please try again shortly.") from error
        ensure_dispatch(service.settings, service.jobs, key)

    def job_status(key: str) -> dict:
        if service.jobs is not None:
            from sports_analyst.cloud_dispatch import ensure_dispatch

            ensure_dispatch(service.settings, service.jobs, key)
            status = service.jobs.status(key)
            if status is None:
                raise HTTPException(404, "Job not found")
            if status.get("stage") == "complete":
                # Worker artifacts can be new to this replica's local index.
                refresh_catalog()
            return status
        events = service.events.events(key)
        return events[-1] if events else {"stage": "pending", "message": "Waiting for progress", "progress": 0}

    def refresh_catalog() -> None:
        nonlocal catalog_version, catalog_refreshed_at
        if service.jobs is not None:
            with catalog_lock:
                version = service.jobs.catalog_version()
                if version != catalog_version or monotonic() - catalog_refreshed_at > 60:
                    service.store._restore_durable_index()
                    catalog_version, catalog_refreshed_at = version, monotonic()

    @api.get("/api/health")
    def health() -> dict[str, str]:
        """Report readiness after application construction has completed."""
        return {"status": "ready"}

    @api.get("/api/capabilities", response_model=RuntimeCapabilities)
    def capabilities() -> RuntimeCapabilities:
        return service.capabilities()

    @api.get("/api/datasets", response_model=list[DatasetManifest])
    def datasets(sport: str | None = None) -> list[DatasetManifest]:
        refresh_catalog()
        return service.store.manifests(sport=sport)

    @api.get("/api/sports", response_model=list[SportOption])
    def sports() -> list[SportOption]:
        return service.sport_options()

    @api.get("/api/sports/{sport}/options", response_model=AnalysisOptions)
    def analysis_options(sport: str) -> AnalysisOptions:
        refresh_catalog()
        try:
            return service.analysis_options(sport)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/api/sports/{sport}/metrics/{metric}", response_model=MetricDefinition)
    def metric_definition(sport: str, metric: str) -> MetricDefinition:
        try:
            return service.explain_metric(metric, sport)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/api/sports/{sport}/tools", response_model=list[ToolDefinition])
    def tools(sport: str) -> list[ToolDefinition]:
        try:
            return service.tool_definitions(sport)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/api/sports/{sport}/players", response_model=list[PlayerOption])
    def players(sport: str, query: str = "") -> list[PlayerOption]:
        refresh_catalog()
        try:
            return service.resolve_players(query, sport)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.post("/api/datasets/{sport}/sync", status_code=202)
    def sync_datasets(sport: str, request: SyncRequest, background_tasks: BackgroundTasks) -> dict[str, str | int]:
        try:
            service._sport(sport)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        job_id = stable_id(
            "sync",
            {"sport": sport, "seasons": sorted(request.seasons), "datasets": request.datasets, "time": datetime.now(UTC).isoformat()},
        )
        timeout_seconds = service.dataset_sync_timeout_seconds(request.seasons, request.datasets, sport)

        if service.jobs is not None:
            enqueue(job_id, "sync", {**request.model_dump(mode="json"), "sport": sport})
            return {"job_id": job_id, "timeout_seconds": timeout_seconds}

        def execute() -> None:
            try:
                service.sync(request.seasons, job_id, request.datasets, sport)
            except Exception as error:
                logger.error("dataset_sync_failed job_id=%s error_type=%s", job_id, type(error).__name__)
                logger.debug("dataset_sync_failed_details job_id=%s", job_id, exc_info=True)
                service.events.emit(job_id, "failed", str(error), 1.0)

        background_tasks.add_task(execute)
        return {"job_id": job_id, "timeout_seconds": timeout_seconds}

    @api.post("/api/datasets/{sport}/sync-stream")
    async def sync_datasets_stream(sport: str, request: SyncRequest) -> StreamingResponse:
        """Keep cloud dataset work and progress on one request and one application instance."""
        try:
            service._sport(sport)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        job_id = stable_id(
            "sync",
            {"sport": sport, "seasons": sorted(request.seasons), "datasets": request.datasets, "time": datetime.now(UTC).isoformat()},
        )
        timeout_seconds = service.dataset_sync_timeout_seconds(request.seasons, request.datasets, sport)
        if service.jobs is not None:
            await asyncio.to_thread(enqueue, job_id, "sync", {**request.model_dump(mode="json"), "sport": sport})
            return StreamingResponse(
                _event_stream(service, job_id, timeout_seconds=timeout_seconds), media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Job-ID": job_id,
                         "X-Job-Timeout-Seconds": str(timeout_seconds)},
            )
        return StreamingResponse(
            _dataset_sync_stream(service, job_id, sport, request.seasons, request.datasets, timeout_seconds),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.get("/api/dataset-jobs/{job_id}/events")
    async def dataset_events(
            job_id: str, timeout_seconds: int | None = Query(default=None, ge=30, le=3_600),
            after: int = Query(default=0, ge=0), last_event_id: str | None = Header(default=None),
    ) -> StreamingResponse:
        return StreamingResponse(
            _event_stream(service, job_id, timeout_seconds=timeout_seconds, after=_cursor(after, last_event_id)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.get("/api/dataset-jobs/{job_id}/status")
    def dataset_job_status(job_id: str) -> dict:
        return job_status(job_id)

    @api.post("/api/investigations", status_code=202)
    def create_investigation(request: AnalysisRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
        investigation_id = stable_id("investigation", {"request": request.model_dump(), "time": datetime.now(UTC).isoformat()})
        if service.jobs is not None:
            enqueue(investigation_id, "investigation", request.model_dump(mode="json"))
            return {"investigation_id": investigation_id}

        def execute() -> None:
            try:
                service.investigate(request, investigation_id)
            except Exception as error:
                logger.error("investigation_failed investigation_id=%s error_type=%s", investigation_id, type(error).__name__)
                logger.debug("investigation_failed_details investigation_id=%s", investigation_id, exc_info=True)
                service.events.emit(investigation_id, "failed", str(error), 1.0)

        background_tasks.add_task(execute)
        return {"investigation_id": investigation_id}

    @api.post("/api/investigations/stream")
    async def create_investigation_stream(request: AnalysisRequest) -> StreamingResponse:
        """Run an investigation on the instance serving its progress stream."""
        investigation_id = stable_id("investigation", {"request": request.model_dump(), "time": datetime.now(UTC).isoformat()})
        if service.jobs is not None:
            await asyncio.to_thread(enqueue, investigation_id, "investigation", request.model_dump(mode="json"))
            return StreamingResponse(
                _event_stream(service, investigation_id, timeout_seconds=3600), media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Investigation-ID": investigation_id},
            )

        def execute() -> None:
            service.investigate(request, investigation_id)

        return StreamingResponse(
            _investigation_work_stream(service, investigation_id, execute, "investigation"),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Investigation-ID": investigation_id,
            },
        )

    @api.get("/api/investigations", response_model=list[InvestigationSummary])
    def investigations(
            limit: int | None = Query(default=None, ge=1, le=500),
            offset: int = Query(default=0, ge=0),
            sport: str | None = Query(default=None),
    ) -> list[InvestigationSummary]:
        page_size = limit or service.settings.investigation_history_limit
        refresh_catalog()
        return service.store.list_investigation_summaries(page_size, offset, sport)

    @api.get("/api/investigations/{investigation_id}", response_model=InvestigationBundle)
    def investigation(investigation_id: str) -> InvestigationBundle:
        try:
            return service.store.get_investigation(investigation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/api/investigations/{investigation_id}/thread", response_model=list[InvestigationBundle])
    def investigation_thread(investigation_id: str) -> list[InvestigationBundle]:
        try:
            return service.store.investigation_thread(investigation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.delete("/api/investigations/{investigation_id}", status_code=204)
    def delete_investigation(investigation_id: str) -> Response:
        try:
            service.store.delete_investigation(investigation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RuntimeError as error:
            logger.error("investigation_delete_rejected investigation_id=%s", investigation_id)
            raise HTTPException(status_code=500, detail=str(error)) from error
        logger.info("investigation_deleted investigation_id=%s", investigation_id)
        return Response(status_code=204)

    @api.get("/api/investigations/{investigation_id}/events")
    async def investigation_events(
            investigation_id: str, after: int = Query(default=0, ge=0), last_event_id: str | None = Header(default=None)
    ) -> StreamingResponse:
        return StreamingResponse(
            _event_stream(service, investigation_id, after=_cursor(after, last_event_id)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.get("/api/investigations/{investigation_id}/status")
    def investigation_status(investigation_id: str) -> dict[str, Any]:
        return job_status(investigation_id)

    @api.post("/api/investigations/{investigation_id}/follow-ups", status_code=202)
    def follow_up(investigation_id: str, request: FollowUpRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
        try:
            service.store.get_investigation(investigation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        child_id = stable_id(
            "investigation",
            {"parent": investigation_id, "question": request.question, "time": datetime.now(UTC).isoformat()},
        )
        if service.jobs is not None:
            enqueue(child_id, "follow_up", {"parent_id": investigation_id, "question": request.question})
            return {"investigation_id": child_id}

        def execute() -> None:
            try:
                service.follow_up(investigation_id, request.question, child_id)
            except Exception as error:
                logger.error("follow_up_failed investigation_id=%s error_type=%s", child_id, type(error).__name__)
                logger.debug("follow_up_failed_details investigation_id=%s", child_id, exc_info=True)
                service.events.emit(child_id, "failed", str(error), 1.0)

        background_tasks.add_task(execute)
        return {"investigation_id": child_id}

    @api.post("/api/investigations/{investigation_id}/follow-ups/stream")
    async def follow_up_stream(investigation_id: str, request: FollowUpRequest) -> StreamingResponse:
        """Run a follow-up on the instance serving its progress stream."""
        try:
            service.store.get_investigation(investigation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        child_id = stable_id(
            "investigation",
            {"parent": investigation_id, "question": request.question, "time": datetime.now(UTC).isoformat()},
        )
        if service.jobs is not None:
            await asyncio.to_thread(enqueue, child_id, "follow_up", {"parent_id": investigation_id, "question": request.question})
            return StreamingResponse(
                _event_stream(service, child_id, timeout_seconds=3600), media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Investigation-ID": child_id},
            )

        def execute() -> None:
            service.follow_up(investigation_id, request.question, child_id)

        return StreamingResponse(
            _investigation_work_stream(service, child_id, execute, "follow_up"),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Investigation-ID": child_id,
            },
        )

    @api.get("/api/investigations/{investigation_id}/evidence/{evidence_id}")
    def evidence(investigation_id: str, evidence_id: str) -> Any:
        try:
            return service.evidence(investigation_id, evidence_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.post("/api/investigations/{investigation_id}/evidence/batch")
    def evidence_batch(investigation_id: str, request: EvidenceBatchRequest) -> list[Any]:
        try:
            return service.evidence_many(investigation_id, request.evidence_ids)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/api/investigations/{investigation_id}/export")
    def export(investigation_id: str, export_format: str = "html") -> FileResponse:
        if export_format not in {"html", "markdown"}:
            raise HTTPException(status_code=400, detail="format must be html or markdown")
        try:
            path = service.store.export_path(investigation_id, export_format)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        is_html = export_format == "html"
        filename = f"{investigation_id}_analysis_report.html" if is_html else f"{investigation_id}_analysis_report.md"
        media_type = "text/html; charset=utf-8" if is_html else "text/markdown; charset=utf-8"
        return FileResponse(path, media_type=media_type, filename=filename)

    frontend = frontend_dir or bundled_frontend_directory()
    if frontend.exists():
        api.frontend("/", directory=str(frontend))
    return api


def _cursor(after: int, last_event_id: str | None) -> int:
    try:
        return max(after, int(last_event_id or 0), 0)
    except ValueError:
        raise HTTPException(400, "Last-Event-ID must be an integer") from None


async def _event_stream(
        service: AnalystApplication,
        key: str,
        timeout_seconds: float | None = None,
        poll_interval: float = 0.1,
        heartbeat_interval: float = 15.0,
        after: int = 0,
):
    offset = 0
    loop = asyncio.get_running_loop()
    timeout = timeout_seconds if timeout_seconds is not None else service.settings.event_stream_timeout_seconds
    deadline = loop.time() + timeout
    next_heartbeat = loop.time() + heartbeat_interval
    while loop.time() < deadline:
        if service.jobs is not None:
            try:
                events = await asyncio.to_thread(service.jobs.events, key, after)
                for event in events:
                    after = event["sequence"]
                    yield f"id: {after}\n" + _sse(event)
                    if event["stage"] in {"complete", "failed"}:
                        return
                if events:
                    deadline = loop.time() + timeout
                if not events:
                    status = await asyncio.to_thread(service.jobs.status, key)
                    if status and status.get("stage") in {"complete", "failed"}:
                        yield _sse(status)
                        return
            except Exception as error:
                logger.warning("job_progress_unavailable key=%s error_type=%s", key, type(error).__name__)
            if loop.time() >= next_heartbeat:
                yield ": keep-alive\n\n"
                next_heartbeat = loop.time() + heartbeat_interval
            await asyncio.sleep(max(2, poll_interval))
            continue
        events = service.events.events(key)
        while offset < len(events):
            event = events[offset]
            offset += 1
            yield _sse(event)
            deadline = loop.time() + timeout
            if event["stage"] in {"complete", "failed"}:
                return
        if loop.time() >= next_heartbeat:
            yield ": keep-alive\n\n"
            next_heartbeat = loop.time() + heartbeat_interval
        await asyncio.sleep(poll_interval)
    logger.info("event_stream_inactivity_timeout key=%s timeout_seconds=%s", key, timeout)
    yield _sse(
        {
            "stage": "timeout",
            "message": "Live progress timed out; checking for a completed result",
            "progress": 0.95,
        }
    )


async def _dataset_sync_stream(
        service: AnalystApplication,
        job_id: str,
        sport: str,
        seasons: list[int],
        datasets: list[str] | None,
        timeout_seconds: float,
):
    """Run a blocking dataset sync while its SSE response keeps the hosting instance active."""

    def execute() -> None:
        try:
            service.sync(seasons, job_id, datasets, sport)
        except Exception as error:
            logger.error("dataset_sync_failed job_id=%s error_type=%s", job_id, type(error).__name__)
            logger.debug("dataset_sync_failed_details job_id=%s", job_id, exc_info=True)
            service.events.emit(job_id, "failed", str(error), 1.0)

    task = asyncio.create_task(asyncio.to_thread(execute))
    try:
        async for event in _event_stream(service, job_id, timeout_seconds=timeout_seconds):
            yield event
    finally:
        if task.done():
            await task


async def _investigation_work_stream(service: AnalystApplication, investigation_id: str, execute: Callable[[], None], operation: str):
    """Keep model work attached to the same cloud request as its SSE progress."""

    def execute_safely() -> None:
        try:
            execute()
        except Exception as error:
            logger.error(
                "%s_failed investigation_id=%s error_type=%s",
                operation,
                investigation_id,
                type(error).__name__,
            )
            logger.debug("%s_failed_details investigation_id=%s", operation, investigation_id, exc_info=True)
            service.events.emit(investigation_id, "failed", str(error), 1.0)

    task = asyncio.create_task(asyncio.to_thread(execute_safely))
    try:
        async for event in _event_stream(service, investigation_id, timeout_seconds=3_600):
            yield event
    finally:
        if task.done():
            await task


app = create_app()
