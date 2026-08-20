from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sports_analyst.models import AnalysisRequest, DatasetManifest, InvestigationBundle, RuntimeCapabilities, stable_id
from sports_analyst.service import AnalystApplication


class SyncRequest(BaseModel):
    seasons: list[int] = Field(min_length=1, max_length=27)


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

    @api.post("/api/datasets/nfl/sync", status_code=202)
    def sync_datasets(request: SyncRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
        job_id = stable_id("sync", {"seasons": sorted(request.seasons), "time": datetime.now(UTC).isoformat()})

        def execute() -> None:
            try:
                service.sync(request.seasons, job_id)
            except Exception as error:
                service.events.emit(job_id, "failed", str(error), 1.0)

        background_tasks.add_task(execute)
        return {"job_id": job_id}

    @api.get("/api/dataset-jobs/{job_id}/events")
    async def dataset_events(job_id: str) -> StreamingResponse:
        return StreamingResponse(_event_stream(service, job_id), media_type="text/event-stream")

    @api.post("/api/investigations", status_code=202)
    def create_investigation(request: AnalysisRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
        investigation_id = stable_id(
            "investigation", {"request": request.model_dump(), "time": datetime.now(UTC).isoformat()}
        )

        def execute() -> None:
            try:
                service.investigate(request, investigation_id)
            except Exception as error:
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

    @api.get("/api/investigations/{investigation_id}/events")
    async def investigation_events(investigation_id: str) -> StreamingResponse:
        return StreamingResponse(_event_stream(service, investigation_id), media_type="text/event-stream")

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
    def export(investigation_id: str, format: str = "html") -> FileResponse:
        try:
            path = service.store.export_path(investigation_id, format)
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=404 if isinstance(error, KeyError) else 400, detail=str(error)) from error
        return FileResponse(path, filename=path.name)

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.exists():
        api.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return api


async def _event_stream(service: AnalystApplication, key: str):
    offset = 0
    for _ in range(600):
        events = service.events.events(key)
        while offset < len(events):
            event = events[offset]
            offset += 1
            yield _sse(event)
            if event["stage"] in {"complete", "failed"}:
                return
        await asyncio.sleep(0.1)
    yield _sse({"stage": "failed", "message": "event stream timed out", "progress": 1.0})


app = create_app()
