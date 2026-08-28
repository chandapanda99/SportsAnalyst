from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
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


def create_app(application: AnalystApplication | None = None) -> FastAPI:
    service = application or AnalystApplication()
    api = FastAPI(title="Open Sports Analyst", version="1.0.0")

    @api.get("/api/capabilities", response_model=RuntimeCapabilities)
    def capabilities() -> RuntimeCapabilities:
        return service.capabilities()

    @api.get("/api/datasets", response_model=list[DatasetManifest])
    def datasets(sport: str | None = None) -> list[DatasetManifest]:
        return service.store.manifests(sport=sport)

    @api.get("/api/sports", response_model=list[SportOption])
    def sports() -> list[SportOption]:
        return service.sport_options()

    @api.get("/api/sports/{sport}/options", response_model=AnalysisOptions)
    def analysis_options(sport: str) -> AnalysisOptions:
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
        try:
            return service.resolve_players(query, sport)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.post("/api/datasets/{sport}/sync", status_code=202)
    def sync_datasets(sport: str, request: SyncRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
        try:
            service._sport(sport)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        job_id = stable_id(
            "sync",
            {"sport": sport, "seasons": sorted(request.seasons), "datasets": request.datasets, "time": datetime.now(UTC).isoformat()},
        )

        def execute() -> None:
            try:
                service.sync(request.seasons, job_id, request.datasets, sport)
            except Exception as error:
                logger.error("dataset_sync_failed job_id=%s error_type=%s", job_id, type(error).__name__)
                logger.debug("dataset_sync_failed_details job_id=%s", job_id, exc_info=True)
                service.events.emit(job_id, "failed", str(error), 1.0)

        background_tasks.add_task(execute)
        return {"job_id": job_id}

    @api.get("/api/dataset-jobs/{job_id}/events")
    async def dataset_events(job_id: str) -> StreamingResponse:
        return StreamingResponse(
            _event_stream(service, job_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.post("/api/investigations", status_code=202)
    def create_investigation(request: AnalysisRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
        investigation_id = stable_id("investigation", {"request": request.model_dump(), "time": datetime.now(UTC).isoformat()})

        def execute() -> None:
            try:
                service.investigate(request, investigation_id)
            except Exception as error:
                logger.error(
                    "investigation_failed investigation_id=%s error_type=%s",
                    investigation_id,
                    type(error).__name__,
                )
                logger.debug("investigation_failed_details investigation_id=%s", investigation_id, exc_info=True)
                service.events.emit(investigation_id, "failed", str(error), 1.0)

        background_tasks.add_task(execute)
        return {"investigation_id": investigation_id}

    @api.get("/api/investigations", response_model=list[InvestigationSummary])
    def investigations(
        limit: int | None = Query(default=None, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        sport: str | None = Query(default=None),
    ) -> list[InvestigationSummary]:
        page_size = limit or service.settings.investigation_history_limit
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
    async def investigation_events(investigation_id: str) -> StreamingResponse:
        return StreamingResponse(
            _event_stream(service, investigation_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.get("/api/investigations/{investigation_id}/status")
    def investigation_status(investigation_id: str) -> dict[str, Any]:
        events = service.events.events(investigation_id)
        if not events:
            return {"stage": "pending", "message": "Investigation is queued", "progress": 0.0}
        return events[-1]

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

        def execute() -> None:
            try:
                service.follow_up(investigation_id, request.question, child_id)
            except Exception as error:
                logger.error("follow_up_failed investigation_id=%s error_type=%s", child_id, type(error).__name__)
                logger.debug("follow_up_failed_details investigation_id=%s", child_id, exc_info=True)
                service.events.emit(child_id, "failed", str(error), 1.0)

        background_tasks.add_task(execute)
        return {"investigation_id": child_id}

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
    def export(investigation_id: str, format: str = "html") -> FileResponse:
        if format not in {"html", "markdown"}:
            raise HTTPException(status_code=400, detail="format must be html or markdown")
        try:
            path = service.store.export_path(investigation_id, format)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        is_html = format == "html"
        filename = "report.html" if is_html else "report.md"
        media_type = "text/html; charset=utf-8" if is_html else "text/markdown; charset=utf-8"
        return FileResponse(path, media_type=media_type, filename=filename)

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.exists():
        api.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return api


async def _event_stream(
    service: AnalystApplication,
    key: str,
    timeout_seconds: float | None = None,
    poll_interval: float = 0.1,
    heartbeat_interval: float = 15.0,
):
    offset = 0
    loop = asyncio.get_running_loop()
    timeout = timeout_seconds if timeout_seconds is not None else service.settings.event_stream_timeout_seconds
    deadline = loop.time() + timeout
    next_heartbeat = loop.time() + heartbeat_interval
    while loop.time() < deadline:
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


app = create_app()
