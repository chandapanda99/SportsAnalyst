from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sports_analyst.models import (
    AnalysisOptions,
    AnalysisRequest,
    DatasetManifest,
    InvestigationBundle,
    MetricDefinition,
    PlayerOption,
    RuntimeCapabilities,
    ToolDefinition,
    stable_id,
)
from sports_analyst.service import AnalystApplication

logger = logging.getLogger("sports_analyst.api")


class SyncRequest(BaseModel):
    seasons: list[int] = Field(min_length=1, max_length=27)
    datasets: list[str] = Field(default_factory=lambda: ["play_by_play"], min_length=1, max_length=7)


class FollowUpRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def create_app(application: AnalystApplication | None = None) -> FastAPI:
    service = application or AnalystApplication()
    api = FastAPI(title="Open Sports Analyst", version="0.1.0")

    @api.get("/api/capabilities", response_model=RuntimeCapabilities)
    def capabilities() -> RuntimeCapabilities:
        return service.capabilities()

    @api.get("/api/datasets", response_model=list[DatasetManifest])
    def datasets() -> list[DatasetManifest]:
        return service.store.manifests()

    @api.get("/api/sports/nfl/options", response_model=AnalysisOptions)
    def nfl_analysis_options() -> AnalysisOptions:
        return service.analysis_options()

    @api.get("/api/sports/nfl/metrics/{metric}", response_model=MetricDefinition)
    def metric_definition(metric: str) -> MetricDefinition:
        try:
            return service.explain_metric(metric)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/api/sports/nfl/tools", response_model=list[ToolDefinition])
    def nfl_tools() -> list[ToolDefinition]:
        return service.tool_definitions()

    @api.get("/api/sports/nfl/players", response_model=list[PlayerOption])
    def players(query: str = "") -> list[PlayerOption]:
        return service.resolve_players(query)

    @api.post("/api/datasets/nfl/sync", status_code=202)
    def sync_datasets(request: SyncRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
        job_id = stable_id(
            "sync",
            {"seasons": sorted(request.seasons), "datasets": request.datasets, "time": datetime.now(UTC).isoformat()},
        )

        def execute() -> None:
            try:
                service.sync(request.seasons, job_id, request.datasets)
            except Exception as error:
                logger.error("dataset_sync_failed job_id=%s error_type=%s", job_id, type(error).__name__)
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
                service.events.emit(investigation_id, "failed", str(error), 1.0)

        background_tasks.add_task(execute)
        return {"investigation_id": investigation_id}

    @api.get("/api/investigations", response_model=list[InvestigationBundle])
    def investigations() -> list[InvestigationBundle]:
        return service.store.list_investigations()

    @api.get("/api/investigations/{investigation_id}", response_model=InvestigationBundle)
    def investigation(investigation_id: str) -> InvestigationBundle:
        try:
            return service.store.get_investigation(investigation_id)
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

    @api.post("/api/investigations/{investigation_id}/follow-ups", response_model=InvestigationBundle)
    def follow_up(investigation_id: str, request: FollowUpRequest) -> InvestigationBundle:
        try:
            return service.follow_up(investigation_id, request.question)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/api/investigations/{investigation_id}/evidence/{evidence_id}")
    def evidence(investigation_id: str, evidence_id: str) -> Any:
        try:
            return service.evidence(investigation_id, evidence_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/api/investigations/{investigation_id}/export")
    def export(investigation_id: str, format: str = "html") -> Response:
        if format not in {"html", "markdown"}:
            raise HTTPException(status_code=400, detail="format must be html or markdown")
        try:
            bundle = service.store.get_investigation(investigation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        from sports_analyst.reports import render_html, render_markdown

        is_html = format == "html"
        content = render_html(bundle) if is_html else render_markdown(bundle)
        filename = "report.html" if is_html else "report.md"
        media_type = "text/html; charset=utf-8" if is_html else "text/markdown; charset=utf-8"
        return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

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
            if event["stage"] in {"complete", "failed"}:
                return
        if loop.time() >= next_heartbeat:
            yield ": keep-alive\n\n"
            next_heartbeat = loop.time() + heartbeat_interval
        await asyncio.sleep(poll_interval)
    logger.warning("event_stream_timeout key=%s timeout_seconds=%s", key, timeout)
    yield _sse(
        {
            "stage": "timeout",
            "message": "Live progress timed out; checking for a completed result",
            "progress": 0.95,
        }
    )


app = create_app()
