from __future__ import annotations

import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

import duckdb

from sports_analyst.config import Settings, get_settings
from sports_analyst.models import DatasetManifest, InvestigationBundle, InvestigationSummary


class LocalStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._initialize()

    def connect(self, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        # DuckDB requires every simultaneous connection to a file to use the
        # same configuration. API reads can overlap a completed investigation
        # write, so use one access mode and enforce read-only behavior in SQL.
        del read_only
        return duckdb.connect(str(self.settings.database_path))

    def _initialize(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    manifest_id VARCHAR PRIMARY KEY, season INTEGER, acquired_at TIMESTAMPTZ, payload JSON,
                    dataset VARCHAR, sport VARCHAR
                );
                CREATE TABLE IF NOT EXISTS investigations (
                    investigation_id VARCHAR PRIMARY KEY, parent_id VARCHAR, created_at TIMESTAMPTZ,
                    status VARCHAR, question VARCHAR, bundle_path VARCHAR, sport VARCHAR
                );
                """
            )
            db.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS dataset VARCHAR")
            db.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS sport VARCHAR")
            db.execute("UPDATE datasets SET dataset = json_extract_string(payload, '$.dataset') WHERE dataset IS NULL")
            db.execute("UPDATE datasets SET sport = coalesce(json_extract_string(payload, '$.sport'), 'nfl') WHERE sport IS NULL")
            db.execute(
                """
                DELETE FROM datasets
                WHERE manifest_id IN (
                    SELECT manifest_id
                    FROM (
                        SELECT manifest_id,
                               row_number() OVER (
                                   PARTITION BY sport, dataset, season
                                   ORDER BY acquired_at DESC, manifest_id DESC
                               ) AS version_rank
                        FROM datasets
                    ) versions
                    WHERE version_rank > 1
                )
                """
            )
            # DuckDB secondary unique indexes retain a just-deleted key until commit,
            # so logical package/season uniqueness is enforced by save_manifest instead.
            db.execute("DROP INDEX IF EXISTS datasets_package_season")
            db.execute("ALTER TABLE investigations ADD COLUMN IF NOT EXISTS summary_payload JSON")
            db.execute("ALTER TABLE investigations ADD COLUMN IF NOT EXISTS sport VARCHAR")
            db.execute(
                "UPDATE investigations SET sport = coalesce(json_extract_string(summary_payload, '$.run.sport'), 'nfl') WHERE sport IS NULL"
            )

    def save_manifest(self, manifest: DatasetManifest) -> None:
        with self.connect() as db:
            db.execute("BEGIN TRANSACTION")
            db.execute(
                "DELETE FROM datasets WHERE sport = ? AND dataset = ? AND season = ?",
                [manifest.sport, manifest.dataset, manifest.season],
            )
            db.execute(
                """
                INSERT INTO datasets (manifest_id, season, acquired_at, payload, dataset, sport)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    manifest.manifest_id,
                    manifest.season,
                    manifest.acquired_at,
                    manifest.model_dump_json(),
                    manifest.dataset,
                    manifest.sport,
                ],
            )
            db.execute("COMMIT")

    def manifests(self, dataset: str | None = None, sport: str | None = None) -> list[DatasetManifest]:
        with self.connect(read_only=True) as db:
            clauses, parameters = [], []
            if dataset is not None:
                clauses.append("dataset = ?")
                parameters.append(dataset)
            if sport is not None:
                clauses.append("sport = ?")
                parameters.append(sport)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = db.execute(f"SELECT payload FROM datasets{where} ORDER BY season DESC, acquired_at DESC", parameters).fetchall()
        manifests = [DatasetManifest.model_validate_json(row[0]) for row in rows]
        return manifests

    def manifest_for_season(self, season: int, dataset: str = "play_by_play", sport: str = "nfl") -> DatasetManifest:
        matches = [manifest for manifest in self.manifests(dataset, sport) if manifest.season == season]
        if not matches:
            raise KeyError(f"{sport} {dataset} season {season} has not been synced")
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
            summary = InvestigationSummary(
                run=bundle.run,
                summary=bundle.summary,
                model_id=bundle.model_id,
                fallback_used=bundle.fallback_used,
            )
            db.execute(
                """INSERT INTO investigations
                   (investigation_id, parent_id, created_at, status, question, bundle_path, summary_payload, sport)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    bundle.run.investigation_id,
                    bundle.run.parent_investigation_id,
                    bundle.run.created_at,
                    bundle.run.status.value,
                    bundle.run.question,
                    str(path.resolve()),
                    summary.model_dump_json(),
                    bundle.run.sport,
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

    def list_investigation_summaries(self, limit: int = 50, offset: int = 0, sport: str | None = None) -> list[InvestigationSummary]:
        with self.connect(read_only=True) as db:
            where = "WHERE sport = ?" if sport else ""
            parameters: list[object] = [sport, limit, offset] if sport else [limit, offset]
            rows = db.execute(
                f"""SELECT summary_payload, bundle_path FROM investigations {where}
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                parameters,
            ).fetchall()
        summaries = []
        for payload, bundle_path in rows:
            if payload:
                summaries.append(InvestigationSummary.model_validate_json(payload))
                continue
            bundle = InvestigationBundle.model_validate_json(Path(bundle_path).read_text(encoding="utf-8"))
            summaries.append(
                InvestigationSummary(
                    run=bundle.run,
                    summary=bundle.summary,
                    model_id=bundle.model_id,
                    fallback_used=bundle.fallback_used,
                )
            )
        return summaries

    def investigation_thread(self, investigation_id: str) -> list[InvestigationBundle]:
        root = self.get_investigation(investigation_id)
        while root.run.parent_investigation_id:
            root = self.get_investigation(root.run.parent_investigation_id)
        with self.connect(read_only=True) as db:
            rows = db.execute(
                """
                WITH RECURSIVE thread(investigation_id, bundle_path, created_at) AS (
                    SELECT investigation_id, bundle_path, created_at
                    FROM investigations WHERE investigation_id = ?
                    UNION ALL
                    SELECT child.investigation_id, child.bundle_path, child.created_at
                    FROM investigations child
                    JOIN thread parent ON child.parent_id = parent.investigation_id
                )
                SELECT bundle_path FROM thread ORDER BY created_at
                """,
                [root.run.investigation_id],
            ).fetchall()
        return [InvestigationBundle.model_validate_json(Path(row[0]).read_text(encoding="utf-8")) for row in rows]

    def delete_investigation(self, investigation_id: str) -> None:
        with self.connect(read_only=True) as db:
            rows = db.execute(
                """
                WITH RECURSIVE descendants(investigation_id, bundle_path) AS (
                    SELECT investigation_id, bundle_path FROM investigations WHERE investigation_id = ?
                    UNION ALL
                    SELECT child.investigation_id, child.bundle_path FROM investigations child
                    JOIN descendants parent ON child.parent_id = parent.investigation_id
                )
                SELECT investigation_id, bundle_path FROM descendants
                """,
                [investigation_id],
            ).fetchall()
        if not rows:
            raise KeyError(f"investigation not found: {investigation_id}")

        root = self.settings.investigations_dir.resolve()
        directories = [(identifier, Path(bundle_path).parent.resolve()) for identifier, bundle_path in rows]
        for identifier, directory in directories:
            if directory.parent != root or directory.name != identifier:
                raise RuntimeError(f"invalid investigation storage path: {identifier}")

        with self.connect() as db:
            db.executemany("DELETE FROM investigations WHERE investigation_id = ?", [[identifier] for identifier, _ in directories])
        for _identifier, directory in directories:
            if directory.exists():
                shutil.rmtree(directory)

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
        self._completed_at: dict[str, float] = {}
        self._lock = RLock()
        self._retention_seconds = 900.0
        self._max_events_per_key = 200

    def emit(self, key: str, stage: str, message: str, progress: float, **extra: object) -> None:
        with self._lock:
            self._purge_expired()
            events = self._events.setdefault(key, [])
            events.append({"timestamp": datetime.now(UTC).isoformat(), "stage": stage, "message": message, "progress": progress, **extra})
            if len(events) > self._max_events_per_key:
                del events[: -self._max_events_per_key]
            if stage in {"complete", "failed"}:
                self._completed_at[key] = time.monotonic()

    def events(self, key: str) -> list[dict[str, object]]:
        with self._lock:
            self._purge_expired()
            return list(self._events.get(key, []))

    def _purge_expired(self) -> None:
        cutoff = time.monotonic() - self._retention_seconds
        expired = [key for key, completed_at in self._completed_at.items() if completed_at < cutoff]
        for key in expired:
            self._events.pop(key, None)
            self._completed_at.pop(key, None)
