from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb

from sports_analyst.config import Settings, get_settings
from sports_analyst.models import DatasetManifest, InvestigationBundle


class LocalStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._initialize()

    def connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.settings.database_path), read_only=read_only)

    def _initialize(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    manifest_id VARCHAR PRIMARY KEY, season INTEGER, acquired_at TIMESTAMPTZ, payload JSON
                );
                CREATE TABLE IF NOT EXISTS investigations (
                    investigation_id VARCHAR PRIMARY KEY, parent_id VARCHAR, created_at TIMESTAMPTZ,
                    status VARCHAR, question VARCHAR, bundle_path VARCHAR
                );
                """
            )

    def save_manifest(self, manifest: DatasetManifest) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO datasets VALUES (?, ?, ?, ?)",
                [manifest.manifest_id, manifest.season, manifest.acquired_at, manifest.model_dump_json()],
            )

    def manifests(self, dataset: str | None = None) -> list[DatasetManifest]:
        with self.connect(read_only=True) as db:
            rows = db.execute("SELECT payload FROM datasets ORDER BY season DESC").fetchall()
        manifests = [DatasetManifest.model_validate_json(row[0]) for row in rows]
        return [manifest for manifest in manifests if dataset is None or manifest.dataset == dataset]

    def manifest_for_season(self, season: int, dataset: str = "play_by_play") -> DatasetManifest:
        matches = [manifest for manifest in self.manifests(dataset) if manifest.season == season]
        if not matches:
            raise KeyError(f"{dataset} season {season} has not been synced")
        return matches[0]

    def save_investigation(self, bundle: InvestigationBundle) -> Path:
        directory = self.settings.investigations_dir / bundle.run.investigation_id
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "bundle.json"
        path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
        from sports_analyst.reports import render_html, render_markdown

        (directory / "report.md").write_text(render_markdown(bundle), encoding="utf-8")
        (directory / "report.html").write_text(render_html(bundle), encoding="utf-8")
        with self.connect() as db:
            db.execute(
                "INSERT INTO investigations VALUES (?, ?, ?, ?, ?, ?)",
                [
                    bundle.run.investigation_id,
                    bundle.run.parent_investigation_id,
                    bundle.run.created_at,
                    bundle.run.status.value,
                    bundle.run.question,
                    str(path.resolve()),
                ],
            )
        return path

    def get_investigation(self, investigation_id: str) -> InvestigationBundle:
        with self.connect(read_only=True) as db:
            row = db.execute("SELECT bundle_path FROM investigations WHERE investigation_id = ?", [investigation_id]).fetchone()
        if not row:
            raise KeyError(f"investigation not found: {investigation_id}")
        return InvestigationBundle.model_validate_json(Path(row[0]).read_text(encoding="utf-8"))

    def list_investigations(self) -> list[InvestigationBundle]:
        with self.connect(read_only=True) as db:
            rows = db.execute("SELECT bundle_path FROM investigations ORDER BY created_at DESC").fetchall()
        return [InvestigationBundle.model_validate_json(Path(row[0]).read_text(encoding="utf-8")) for row in rows]

    def export_path(self, investigation_id: str, output_format: str) -> Path:
        if output_format not in {"html", "markdown"}:
            raise ValueError("format must be html or markdown")
        suffix = "html" if output_format == "html" else "md"
        path = self.settings.investigations_dir / investigation_id / f"report.{suffix}"
        if not path.exists():
            raise KeyError(f"investigation not found: {investigation_id}")
        return path


class EventRegistry:
    """In-memory SSE history for local jobs and investigations."""

    def __init__(self) -> None:
        self._events: dict[str, list[dict[str, object]]] = {}

    def emit(self, key: str, stage: str, message: str, progress: float, **extra: object) -> None:
        self._events.setdefault(key, []).append(
            {"timestamp": datetime.now(UTC).isoformat(), "stage": stage, "message": message, "progress": progress, **extra}
        )

    def events(self, key: str) -> list[dict[str, object]]:
        return list(self._events.get(key, []))
