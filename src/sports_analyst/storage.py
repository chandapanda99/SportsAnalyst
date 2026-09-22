from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

import duckdb

from sports_analyst.config import Settings, get_settings
from sports_analyst.models import DatasetManifest, InvestigationBundle, InvestigationSummary
from sports_analyst.persistence import PersistenceBackend, create_persistence_backend, normalize_object_key

logger = logging.getLogger("sports_analyst.storage")


class LocalStore:
    DATASET_CATALOG_KEY = "metadata/catalog/datasets.json"
    INVESTIGATION_CATALOG_KEY = "metadata/catalog/investigations.json"
    CATALOG_VERSION_KEY = "metadata/catalog/version.json"

    def __init__(
        self,
        settings: Settings | None = None,
        persistence: PersistenceBackend | None = None,
        *,
        restore_durable_index: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.persistence = persistence or create_persistence_backend(self.settings)
        self._persistence_lock = RLock()
        self.publication_guard = nullcontext
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        if self.persistence.durable:
            # DuckDB is a disposable local index in cloud mode. Rebuilding it
            # prevents stale cache state from outranking durable metadata.
            self.settings.database_path.unlink(missing_ok=True)
        self._initialize()
        if self.persistence.durable and restore_durable_index:
            self._restore_durable_index()

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
                    dataset VARCHAR, sport VARCHAR, object_path VARCHAR
                );
                CREATE TABLE IF NOT EXISTS investigations (
                    investigation_id VARCHAR PRIMARY KEY, parent_id VARCHAR, created_at TIMESTAMPTZ,
                    status VARCHAR, question VARCHAR, bundle_path VARCHAR, sport VARCHAR, object_path VARCHAR
                );
                """
            )
            db.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS dataset VARCHAR")
            db.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS sport VARCHAR")
            db.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS object_path VARCHAR")
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
            db.execute("ALTER TABLE investigations ADD COLUMN IF NOT EXISTS object_path VARCHAR")
            db.execute(
                "UPDATE investigations SET sport = coalesce(json_extract_string(summary_payload, '$.run.sport'), 'nfl') WHERE sport IS NULL"
            )

    def _managed_relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        root = self.settings.data_dir.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"persistent file is outside DATA_DIR: {resolved}")
        return normalize_object_key(resolved.relative_to(root).as_posix())

    def _local_object_path(self, object_path: str) -> Path:
        normalized = normalize_object_key(object_path)
        target = (self.settings.data_dir / Path(*normalized.split("/"))).resolve()
        root = self.settings.data_dir.resolve()
        if root not in target.parents:
            raise ValueError(f"persistent object path is outside DATA_DIR: {object_path!r}")
        return target

    @staticmethod
    def _dataset_metadata_key(manifest: DatasetManifest) -> str:
        return normalize_object_key(f"metadata/datasets/{manifest.sport}/{manifest.dataset}/{manifest.season}.json")

    @staticmethod
    def _dataset_metadata_lookup_key(sport: str, dataset: str, season: int) -> str:
        return normalize_object_key(f"metadata/datasets/{sport}/{dataset}/{season}.json")

    @staticmethod
    def _investigation_metadata_key(investigation_id: str) -> str:
        return normalize_object_key(f"metadata/investigations/{investigation_id}.json")

    def _register_durable_dataset(self, payload: bytes, db: duckdb.DuckDBPyConnection) -> None:
        record = json.loads(payload)
        object_path = normalize_object_key(record["object_path"])
        manifest = DatasetManifest.model_validate(record["manifest"]).model_copy(
            update={"local_path": str(self._local_object_path(object_path))}
        )
        db.execute(
            """INSERT OR REPLACE INTO datasets
               (manifest_id, season, acquired_at, payload, dataset, sport, object_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                manifest.manifest_id,
                manifest.season,
                manifest.acquired_at,
                manifest.model_dump_json(),
                manifest.dataset,
                manifest.sport,
                object_path,
            ],
        )

    def _register_durable_investigation(self, payload: bytes, db: duckdb.DuckDBPyConnection) -> None:
        record = json.loads(payload)
        object_path = normalize_object_key(record["object_path"])
        bundle_path = self._local_object_path(object_path)
        db.execute(
            """INSERT OR REPLACE INTO investigations
               (investigation_id, parent_id, created_at, status, question, bundle_path, summary_payload, sport, object_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                record["investigation_id"],
                record.get("parent_id"),
                record["created_at"],
                record["status"],
                record["question"],
                str(bundle_path),
                json.dumps(record["summary"]),
                record["sport"],
                object_path,
            ],
        )

    def _refresh_durable_record(
        self, key: str, register: Callable[[bytes, duckdb.DuckDBPyConnection], None]
    ) -> bool:
        if not self.persistence.durable:
            return False
        with self._persistence_lock:
            payload = self.persistence.read_bytes(key)
            if payload is None:
                return False
            with self.connect() as db:
                register(payload, db)
        return True

    @staticmethod
    def _catalog_payload(records: list[dict]) -> bytes:
        return json.dumps({"format": 1, "records": records}, separators=(",", ":"), default=str).encode()

    def _read_catalog(self, key: str) -> tuple[list[dict], str | None, bool]:
        reader = getattr(self.persistence, "read_versioned_bytes", None)
        if reader is None:
            payload, version = self.persistence.read_bytes(key), None
        else:
            payload, version = reader(key)
        if payload is None:
            return [], version, False
        document = json.loads(payload)
        return list(document.get("records", [])), version, True

    def _mutate_catalog(self, key: str, mutate: Callable[[list[dict]], list[dict]]) -> None:
        conditional_write = getattr(self.persistence, "write_bytes_if_version", None)
        for attempt in range(8):
            records, version, _exists = self._read_catalog(key)
            updated = mutate(records)
            payload = self._catalog_payload(updated)
            if conditional_write is None:
                self.persistence.write_bytes(key, payload, "application/json")
                break
            if conditional_write(key, payload, version, "application/json"):
                break
            time.sleep(0.025 * (attempt + 1))
        else:
            raise RuntimeError(f"catalog update contention did not settle: {key}")
        self._publish_catalog_version()

    def _publish_catalog_version(self) -> None:
        payload = json.dumps({"generation": time.time_ns()}, separators=(",", ":")).encode()
        self.persistence.write_bytes(self.CATALOG_VERSION_KEY, payload, "application/json")

    def catalog_version(self) -> str | None:
        payload = self.persistence.read_bytes(self.CATALOG_VERSION_KEY) if self.persistence.durable else None
        return payload.decode() if payload is not None else None

    @staticmethod
    def _dataset_catalog_record(manifest: DatasetManifest, object_path: str) -> dict:
        return {"manifest": manifest.model_dump(mode="json"), "object_path": object_path}

    @staticmethod
    def _dataset_record_key(record: dict) -> tuple[str, str, int]:
        manifest = record["manifest"]
        return str(manifest.get("sport", "nfl")), str(manifest["dataset"]), int(manifest["season"])

    def publish_dataset_catalog(self, manifests: list[DatasetManifest]) -> None:
        if not self.persistence.durable or not manifests:
            return
        replacements = {
            (manifest.sport, manifest.dataset, manifest.season): self._dataset_catalog_record(
                manifest, self._managed_relative_path(Path(manifest.local_path))
            )
            for manifest in manifests
        }

        def merge(records: list[dict]) -> list[dict]:
            merged = {self._dataset_record_key(record): record for record in records}
            merged.update(replacements)
            return [merged[key] for key in sorted(merged)]

        self._mutate_catalog(self.DATASET_CATALOG_KEY, merge)

    def refresh_durable_datasets(self, sport: str, seasons: list[int], datasets: list[str]) -> None:
        """Restore only packages relevant to one sync instead of scanning the whole bucket."""
        if not self.persistence.durable:
            return
        keys = {
            self._dataset_metadata_lookup_key(sport, dataset, season)
            for dataset in datasets
            for season in {*seasons, 0}
        }
        with self._persistence_lock, self.connect() as db:
            for key in sorted(keys):
                payload = self.persistence.read_bytes(key)
                if payload is not None:
                    self._register_durable_dataset(payload, db)

    def _restore_durable_index(self) -> None:
        started_at = time.perf_counter()
        dataset_records, _dataset_version, has_dataset_catalog = self._read_catalog(self.DATASET_CATALOG_KEY)
        investigation_records, _investigation_version, has_investigation_catalog = self._read_catalog(
            self.INVESTIGATION_CATALOG_KEY
        )
        with self._persistence_lock, self.connect() as db:
            db.execute("BEGIN TRANSACTION")
            db.execute("DELETE FROM datasets")
            db.execute("DELETE FROM investigations")
            if has_dataset_catalog:
                for record in dataset_records:
                    self._register_durable_dataset(json.dumps(record).encode(), db)
            else:
                for key in self.persistence.list_keys("metadata/datasets/"):
                    payload = self.persistence.read_bytes(key)
                    if payload is not None:
                        self._register_durable_dataset(payload, db)
                        dataset_records.append(json.loads(payload))
            if has_investigation_catalog:
                for record in investigation_records:
                    self._register_durable_investigation(json.dumps(record).encode(), db)
            else:
                for key in self.persistence.list_keys("metadata/investigations/"):
                    payload = self.persistence.read_bytes(key)
                    if payload is not None:
                        self._register_durable_investigation(payload, db)
                        investigation_records.append(json.loads(payload))
            db.execute("COMMIT")
        # Upgrade legacy per-record metadata lazily. Conditional creation keeps
        # simultaneous cold starts from overwriting one another.
        if not has_dataset_catalog and dataset_records:
            self._mutate_catalog(self.DATASET_CATALOG_KEY, lambda _records: dataset_records)
        if not has_investigation_catalog and investigation_records:
            self._mutate_catalog(self.INVESTIGATION_CATALOG_KEY, lambda _records: investigation_records)
        logger.info(
            "durable_catalog_restored datasets=%d investigations=%d compact=%s duration_ms=%d",
            len(dataset_records),
            len(investigation_records),
            has_dataset_catalog and has_investigation_catalog,
            round((time.perf_counter() - started_at) * 1000),
        )

    def save_manifest(self, manifest: DatasetManifest, *, publish_catalog: bool = True) -> None:
        with self.publication_guard():
            self._save_manifest(manifest, publish_catalog=publish_catalog)

    def _save_manifest(self, manifest: DatasetManifest, *, publish_catalog: bool = True) -> None:
        source = Path(manifest.local_path)
        object_path = self._managed_relative_path(source)
        if self.persistence.durable:
            # Managed transfers can overlap across package workers; only the
            # small local catalog transaction needs process-level serialization.
            self.persistence.upload_file(object_path, source)
        with self._persistence_lock:
            with self.connect() as db:
                db.execute("BEGIN TRANSACTION")
                db.execute(
                    "DELETE FROM datasets WHERE sport = ? AND dataset = ? AND season = ?",
                    [manifest.sport, manifest.dataset, manifest.season],
                )
                db.execute(
                    """
                    INSERT INTO datasets (manifest_id, season, acquired_at, payload, dataset, sport, object_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        manifest.manifest_id,
                        manifest.season,
                        manifest.acquired_at,
                        manifest.model_dump_json(),
                        manifest.dataset,
                        manifest.sport,
                        object_path,
                    ],
                )
                db.execute("COMMIT")
            if self.persistence.durable:
                metadata = {"manifest": manifest.model_dump(mode="json"), "object_path": object_path}
                self.persistence.write_bytes(
                    self._dataset_metadata_key(manifest),
                    json.dumps(metadata, separators=(",", ":")).encode(),
                    "application/json",
                )
        if publish_catalog:
            self.publish_dataset_catalog([manifest])

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
        if not matches and self._refresh_durable_record(
            self._dataset_metadata_lookup_key(sport, dataset, season), self._register_durable_dataset
        ):
            matches = [manifest for manifest in self.manifests(dataset, sport) if manifest.season == season]
        if not matches:
            raise KeyError(f"{sport} {dataset} season {season} has not been synced")
        return matches[0]

    def materialize_manifest(self, manifest: DatasetManifest) -> DatasetManifest:
        path = Path(manifest.local_path)
        if path.exists() or not self.persistence.durable:
            return manifest
        with self.connect(read_only=True) as db:
            row = db.execute("SELECT object_path FROM datasets WHERE manifest_id = ?", [manifest.manifest_id]).fetchone()
        if not row or not row[0]:
            raise FileNotFoundError(f"no persistent object is registered for dataset {manifest.manifest_id}")
        path = self._local_object_path(row[0])
        with self._persistence_lock:
            if not path.exists() and not self.persistence.download_file(row[0], path):
                raise FileNotFoundError(f"persistent dataset object is missing: {row[0]}")
        return manifest.model_copy(update={"local_path": str(path)})

    def save_investigation(self, bundle: InvestigationBundle) -> Path:
        with self.publication_guard():
            return self._save_investigation(bundle)

    def _save_investigation(self, bundle: InvestigationBundle) -> Path:
        directory = self.settings.investigations_dir / bundle.run.investigation_id
        # A desktop worker can be interrupted after creating the directory but
        # before registering the completed bundle. Retrying the same durable
        # job safely replaces those deterministic artifacts.
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "bundle.json"
        path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
        from sports_analyst.reports import render_html, render_markdown

        (directory / "report.md").write_text(render_markdown(bundle), encoding="utf-8")
        (directory / "report.html").write_text(render_html(bundle), encoding="utf-8")
        summary = InvestigationSummary(
            run=bundle.run,
            summary=bundle.summary,
            model_id=bundle.model_id,
            fallback_used=bundle.fallback_used,
        )
        object_path = self._managed_relative_path(path)
        with self._persistence_lock:
            if self.persistence.durable:
                for artifact in (path, directory / "report.md", directory / "report.html"):
                    self.persistence.upload_file(self._managed_relative_path(artifact), artifact)
            with self.connect() as db:
                db.execute(
                    """INSERT INTO investigations
                       (investigation_id, parent_id, created_at, status, question, bundle_path, summary_payload, sport, object_path)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        bundle.run.investigation_id,
                        bundle.run.parent_investigation_id,
                        bundle.run.created_at,
                        bundle.run.status.value,
                        bundle.run.question,
                        str(path.resolve()),
                        summary.model_dump_json(),
                        bundle.run.sport,
                        object_path,
                    ],
                )
            if self.persistence.durable:
                metadata = {
                    "investigation_id": bundle.run.investigation_id,
                    "parent_id": bundle.run.parent_investigation_id,
                    "created_at": bundle.run.created_at.isoformat(),
                    "status": bundle.run.status.value,
                    "question": bundle.run.question,
                    "sport": bundle.run.sport,
                    "summary": summary.model_dump(mode="json"),
                    "object_path": object_path,
                }
                self.persistence.write_bytes(
                    self._investigation_metadata_key(bundle.run.investigation_id),
                    json.dumps(metadata, separators=(",", ":")).encode(),
                    "application/json",
                )
                def merge(records: list[dict]) -> list[dict]:
                    retained = [record for record in records if record.get("investigation_id") != bundle.run.investigation_id]
                    retained.append(metadata)
                    return sorted(retained, key=lambda record: str(record.get("created_at", "")), reverse=True)

                self._mutate_catalog(self.INVESTIGATION_CATALOG_KEY, merge)
        return path

    def _materialize_file(self, path: Path, object_path: str | None) -> Path:
        if path.exists() or not self.persistence.durable:
            return path
        if not object_path:
            raise FileNotFoundError(f"no persistent object is registered for {path.name}")
        target = self._local_object_path(object_path)
        with self._persistence_lock:
            if not target.exists() and not self.persistence.download_file(object_path, target):
                raise FileNotFoundError(f"persistent object is missing: {object_path}")
        return target

    def get_investigation(self, investigation_id: str) -> InvestigationBundle:
        with self.connect(read_only=True) as db:
            row = db.execute(
                "SELECT bundle_path, object_path FROM investigations WHERE investigation_id = ?", [investigation_id]
            ).fetchone()
        if not row and self._refresh_durable_record(
            self._investigation_metadata_key(investigation_id), self._register_durable_investigation
        ):
            with self.connect(read_only=True) as db:
                row = db.execute(
                    "SELECT bundle_path, object_path FROM investigations WHERE investigation_id = ?", [investigation_id]
                ).fetchone()
        if not row:
            raise KeyError(f"investigation not found: {investigation_id}")
        path = self._materialize_file(Path(row[0]), row[1])
        return InvestigationBundle.model_validate_json(path.read_text(encoding="utf-8"))

    def list_investigations(self) -> list[InvestigationBundle]:
        with self.connect(read_only=True) as db:
            rows = db.execute("SELECT bundle_path, object_path FROM investigations ORDER BY created_at DESC").fetchall()
        return [
            InvestigationBundle.model_validate_json(self._materialize_file(Path(row[0]), row[1]).read_text(encoding="utf-8"))
            for row in rows
        ]

    def list_investigation_summaries(self, limit: int = 50, offset: int = 0, sport: str | None = None) -> list[InvestigationSummary]:
        with self.connect(read_only=True) as db:
            where = "WHERE sport = ?" if sport else ""
            parameters: list[object] = [sport, limit, offset] if sport else [limit, offset]
            rows = db.execute(
                f"""SELECT summary_payload, bundle_path, object_path FROM investigations {where}
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                parameters,
            ).fetchall()
        summaries = []
        for payload, bundle_path, object_path in rows:
            if payload:
                summaries.append(InvestigationSummary.model_validate_json(payload))
                continue
            path = self._materialize_file(Path(bundle_path), object_path)
            bundle = InvestigationBundle.model_validate_json(path.read_text(encoding="utf-8"))
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
                SELECT bundle_path, investigation_id FROM thread ORDER BY created_at
                """,
                [root.run.investigation_id],
            ).fetchall()
        bundles = []
        for bundle_path, identifier in rows:
            object_path = normalize_object_key(f"investigations/{identifier}/bundle.json")
            path = self._materialize_file(Path(bundle_path), object_path)
            bundles.append(InvestigationBundle.model_validate_json(path.read_text(encoding="utf-8")))
        return bundles

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

        if self.persistence.durable:
            with self._persistence_lock:
                for identifier, _directory in directories:
                    self.persistence.delete_prefix(self._investigation_metadata_key(identifier))
                    self.persistence.delete_prefix(f"investigations/{identifier}/")
        with self.connect() as db:
            db.executemany("DELETE FROM investigations WHERE investigation_id = ?", [[identifier] for identifier, _ in directories])
        if self.persistence.durable:
            removed = {identifier for identifier, _directory in directories}
            self._mutate_catalog(
                self.INVESTIGATION_CATALOG_KEY,
                lambda records: [record for record in records if record.get("investigation_id") not in removed],
            )
        for _identifier, directory in directories:
            if directory.exists():
                shutil.rmtree(directory)

    def export_path(self, investigation_id: str, output_format: str) -> Path:
        if output_format not in {"html", "markdown"}:
            raise ValueError("format must be html or markdown")
        suffix = "html" if output_format == "html" else "md"
        path = self.settings.investigations_dir / investigation_id / f"report.{suffix}"
        try:
            path = self._materialize_file(path, self._managed_relative_path(path))
        except FileNotFoundError as exc:
            raise KeyError(f"investigation not found: {investigation_id}") from exc
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
