from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from platformdirs import user_data_path
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Field(default_factory=lambda: user_data_path("open-sports-analyst", appauthor=False, ensure_exists=True))
    model_provider: str = "azure_foundry"
    model: str = "gpt-5.6-luna"
    chat_model: str | None = None
    foundry_endpoint: str = ""
    foundry_api_key: SecretStr | None = Field(default=None, repr=False)
    reasoning_effort: str | None = "medium"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    sql_row_limit: int = Field(default=10_000, ge=1, le=100_000)
    event_stream_timeout_seconds: int = Field(default=120, ge=30, le=3_600)
    dataset_cache_mb: int = Field(default=384, ge=0, le=4_096)
    verify_dataset_checksums_on_load: bool = False
    investigation_history_limit: int = Field(default=50, ge=1, le=500)
    persistence_backend: str = "local"
    job_backend: str = "local"
    job_dispatch_backend: str = "none"
    job_progress_transport: str = "stream"
    cloud_run_project: str = ""
    cloud_run_region: str = "us-central1"
    cloud_run_worker_job: str = ""
    max_active_jobs: int = Field(default=0, ge=0, le=100)
    database_url: SecretStr | None = Field(default=None, repr=False)
    database_migration_url: SecretStr | None = Field(default=None, repr=False)
    job_poll_seconds: float = Field(default=5, ge=1, le=60)
    job_idle_poll_seconds: float = Field(default=60, ge=5, le=3600)
    job_lease_seconds: int = Field(default=300, ge=30, le=3600)
    job_heartbeat_seconds: int = Field(default=20, ge=1, le=120)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_timeout_seconds: int = Field(default=7200, ge=60, le=86400)
    object_storage_bucket: str = ""
    object_storage_prefix: str = "open-sports-analyst"
    object_storage_endpoint_url: str = ""
    object_storage_region: str = ""
    log_level: str = "INFO"
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: SecretStr | None = Field(default=None, repr=False)
    langsmith_project: str = "open-sports-analyst-local"
    langsmith_workspace_id: str = ""

    @field_validator("model_provider", "log_level", "persistence_backend", "job_backend", mode="before")
    @classmethod
    def normalize_token(cls, value: object) -> str:
        return str(value).strip().lower()

    @model_validator(mode="after")
    def validate_jobs(self) -> Settings:
        if self.job_dispatch_backend not in {"none", "cloud_run"}:
            raise ValueError("JOB_DISPATCH_BACKEND must be none or cloud_run")
        if self.job_progress_transport not in {"stream", "poll"}:
            raise ValueError("JOB_PROGRESS_TRANSPORT must be stream or poll")
        if (self.job_dispatch_backend == "cloud_run"
                and (self.job_backend != "postgres" or not self.cloud_run_project or not self.cloud_run_worker_job)
        ):
            raise ValueError("Cloud Run dispatch requires Postgres jobs, CLOUD_RUN_PROJECT and CLOUD_RUN_WORKER_JOB")
        if self.job_backend not in {"local", "postgres"}:
            raise ValueError("JOB_BACKEND must be local or postgres")
        if self.job_backend == "postgres" and (not self.database_url or self.persistence_backend != "s3"):
            raise ValueError("Postgres jobs require DATABASE_URL and PERSISTENCE_BACKEND=s3 for shared artifacts")
        if self.job_heartbeat_seconds * 3 >= self.job_lease_seconds:
            raise ValueError("JOB_LEASE_SECONDS must exceed three heartbeat intervals")
        return self

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw" / "nflverse"

    @property
    def investigations_dir(self) -> Path:
        return self.data_dir / "investigations"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "catalog.duckdb"

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.raw_dir, self.investigations_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
