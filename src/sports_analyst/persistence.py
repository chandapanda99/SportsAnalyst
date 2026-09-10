from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Protocol

from sports_analyst.config import Settings


class PersistenceBackend(Protocol):
    durable: bool

    def list_keys(self, prefix: str) -> list[str]: ...

    def read_bytes(self, key: str) -> bytes | None: ...

    def download_file(self, key: str, destination: Path) -> bool: ...

    def write_bytes(self, key: str, payload: bytes, content_type: str = "application/octet-stream") -> None: ...

    def upload_file(self, key: str, source: Path) -> None: ...

    def delete_prefix(self, prefix: str) -> None: ...


def normalize_object_key(value: str) -> str:
    normalized = str(PurePosixPath(value.replace("\\", "/"))).lstrip("/")
    if not normalized or normalized == "." or ".." in PurePosixPath(normalized).parts:
        raise ValueError(f"invalid object storage key: {value!r}")
    return normalized


class LocalPersistenceBackend:
    durable = False

    @staticmethod
    def list_keys(prefix: str) -> list[str]:
        del prefix
        return []

    @staticmethod
    def read_bytes(key: str) -> bytes | None:
        del key
        return None

    @staticmethod
    def download_file(key: str, destination: Path) -> bool:
        del key, destination
        return False

    @staticmethod
    def write_bytes(key: str, payload: bytes, content_type: str = "application/octet-stream") -> None:
        del key, payload, content_type

    @staticmethod
    def upload_file(key: str, source: Path) -> None:
        del key, source

    @staticmethod
    def delete_prefix(prefix: str) -> None:
        del prefix


class S3PersistenceBackend:
    """Durable object storage with a local, lazily populated filesystem cache."""

    durable = True

    def __init__(self, settings: Settings) -> None:
        if not settings.object_storage_bucket:
            raise ValueError("OBJECT_STORAGE_BUCKET is required when PERSISTENCE_BACKEND=s3")
        import boto3

        options = {}
        if settings.object_storage_endpoint_url:
            options["endpoint_url"] = settings.object_storage_endpoint_url
        if settings.object_storage_region:
            options["region_name"] = settings.object_storage_region
        self.client = boto3.client("s3", **options)
        self.bucket = settings.object_storage_bucket
        self.prefix = settings.object_storage_prefix.strip("/")

    def _remote_key(self, key: str) -> str:
        normalized = normalize_object_key(key)
        return f"{self.prefix}/{normalized}" if self.prefix else normalized

    def _local_key(self, key: str) -> str:
        remote = normalize_object_key(key)
        if self.prefix:
            prefix = f"{self.prefix}/"
            if not remote.startswith(prefix):
                raise ValueError(f"object key is outside the configured prefix: {key!r}")
            return remote[len(prefix) :]
        return remote

    def _remote_prefix(self, prefix: str) -> str:
        remote = self._remote_key(prefix)
        return f"{remote}/" if prefix.replace("\\", "/").endswith("/") else remote

    def list_keys(self, prefix: str) -> list[str]:
        remote_prefix = self._remote_prefix(prefix)
        paginator = self.client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=remote_prefix):
            keys.extend(self._local_key(item["Key"]) for item in page.get("Contents", []))
        return keys

    def read_bytes(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._remote_key(key))
        except Exception as error:
            code = str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return response["Body"].read()

    def download_file(self, key: str, destination: Path) -> bool:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(f"{destination.suffix}.part")
        try:
            self.client.download_file(self.bucket, self._remote_key(key), str(temporary))
        except Exception as error:
            temporary.unlink(missing_ok=True)
            code = str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        temporary.replace(destination)
        return True

    def write_bytes(self, key: str, payload: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._remote_key(key), Body=payload, ContentType=content_type)

    def upload_file(self, key: str, source: Path) -> None:
        self.client.upload_file(str(source), self.bucket, self._remote_key(key))

    def delete_prefix(self, prefix: str) -> None:
        keys = self.list_keys(prefix)
        for offset in range(0, len(keys), 1_000):
            batch = keys[offset : offset + 1_000]
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": self._remote_key(key)} for key in batch], "Quiet": True},
            )


def create_persistence_backend(settings: Settings) -> PersistenceBackend:
    if settings.persistence_backend == "local":
        return LocalPersistenceBackend()
    if settings.persistence_backend == "s3":
        return S3PersistenceBackend(settings)
    raise ValueError("PERSISTENCE_BACKEND must be local or s3")
