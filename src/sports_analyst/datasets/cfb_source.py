"""Bounded, shared ESPN transport for selective college-football acquisition."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore, Lock
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

from sports_analyst.datasets.acquisition import bounded_results, timed_stage
from sports_analyst.datasets.optional import load_optional_module, optional_dependencies
from sports_analyst.storage.persistence import LocalPersistenceBackend

logger = logging.getLogger(__name__)

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
WEB = "https://site.web.api.espn.com/apis/common/v3/sports/football/college-football"


def checked_url(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"sports.core.api.espn.com", "site.api.espn.com", "site.web.api.espn.com"}
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 80, 443}
        or "college-football" not in parsed.path
        or ".." in parsed.path.split("/")
    ):
        raise ValueError("Unsupported college-football source reference")
    return urlunparse(parsed._replace(scheme="https", netloc=parsed.hostname, fragment=""))


def query_url(url: str, **params) -> str:
    parsed = urlparse(checked_url(url))
    query = dict(parse_qsl(parsed.query))
    query.update({key: str(value) for key, value in params.items() if value is not None})
    return urlunparse(parsed._replace(query=urlencode(sorted(query.items()))))


class CFBSource:
    def __init__(self, root: Path, persistence=None, concurrency: int = 4, namespace: str = "cfb"):
        self.root = root
        self.namespace = namespace
        self.persistence = persistence or LocalPersistenceBackend()
        self.cache_hits = 0
        self.requests = 0
        self.concurrency = max(1, min(16, concurrency))
        # Nested game/identity workers share one provider request budget.
        self._request_slots = BoundedSemaphore(self.concurrency)
        self._generation_lock = Lock()
        self._generations = {}

    @staticmethod
    def _request(url: str) -> dict:
        from sports_analyst.analysis.research.state import ACTIVE_BUDGET, budget_json

        if ACTIVE_BUDGET.get() is not None:
            return budget_json(checked_url(url))
        with optional_dependencies("College football data"):
            try:
                download = load_optional_module("sportsdataverse.dl_utils", "College football data").download
            except Exception as error:
                from sports_analyst.datasets.optional import OptionalDependencyError

                raise OptionalDependencyError("College-football data-provider libraries could not initialize. Check worker logs.") from error
            response = download(url, timeout=12, num_retries=1)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict) or data.get("error") or data.get("code") == 404:
            raise ValueError("College-football source returned an unavailable response")
        return data

    def _cached(self, key: str, ttl: float) -> dict | None:
        path = self.root / key
        generation = self._reset_generation(key)

        def decode(payload):
            try:
                document = json.loads(payload)
                if not isinstance(document, dict):
                    return None
                if (document.get("reset_generation") == generation
                        and time.time() - document["acquired_at"] <= ttl):
                    return document["data"]
            except (ValueError, KeyError, TypeError):
                pass
            return None

        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            payload = None
        if payload is not None:
            result = decode(payload)
            if result is not None:
                logger.debug("dataset_cache namespace=%s tier=local hit=true", self.namespace)
                return result
        if self.persistence.durable:
            with timed_stage("durable_cache_read", namespace=self.namespace):
                payload = self.persistence.read_bytes(f"raw/{self.namespace}/{key}")
            if payload is not None:
                result = decode(payload)
                if result is not None:
                    self._write_local(path, payload)
                    logger.debug("dataset_cache namespace=%s tier=durable hit=true", self.namespace)
                    return result
        return None

    def _reset_generation(self, key):
        if not self.persistence.durable or self.namespace not in {"cfb", "soccer"}:
            return None
        scope = key.split("/", 1)[0] if self.namespace == "soccer" else "all"
        # Explicit sync entry points also invalidate disk caches immediately.
        # Direct discovery/tablet reads observe cross-replica resets within 5s.
        with self._generation_lock:
            checked, generation = self._generations.get(scope, (float("-inf"), None))
            if time.monotonic() - checked >= 5:
                payload = self.persistence.read_bytes(f"metadata/dataset-resets/{self.namespace}/{scope}.txt")
                generation = payload.decode() if payload else None
                self._generations[scope] = (time.monotonic(), generation)
            return generation

    @staticmethod
    def _write_local(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def lease(self, name: str, seconds: int = 60):
        """Single-flight across threads/processes, and across durable replicas."""
        digest = hashlib.sha256(name.encode()).hexdigest()
        remote = f"raw/{self.namespace}/leases/{digest}.json"
        local = self.root / "leases" / f"{digest}.json"
        token = uuid4().hex
        deadline = time.monotonic() + 45
        local.parent.mkdir(parents=True, exist_ok=True)
        while True:
            document = json.dumps({"token": token, "expires": time.time() + seconds}).encode()
            if self.persistence.durable:
                payload, version = self.persistence.read_versioned_bytes(remote)
                owner = json.loads(payload) if payload else {}
                if owner.get("expires", 0) < time.time() and self.persistence.write_bytes_if_version(remote, document, version):
                    break
            else:
                try:
                    descriptor = os.open(local, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(document)
                    break
                except FileExistsError:
                    try:
                        owner = json.loads(local.read_bytes())
                        if owner.get("expires", 0) < time.time():
                            local.unlink(missing_ok=True)
                    except (OSError, ValueError):
                        # The creating process may not have finished writing yet.
                        pass
            if time.monotonic() >= deadline:
                raise TimeoutError("Another worker is preparing this resource; retry shortly")
            time.sleep(0.1)
        try:
            yield
        finally:
            if self.persistence.durable:
                payload, version = self.persistence.read_versioned_bytes(remote)
                if payload and json.loads(payload).get("token") == token:
                    self.persistence.write_bytes_if_version(remote, b'{"expires":0}', version)
            else:
                if local.exists() and json.loads(local.read_bytes()).get("token") == token:
                    local.unlink(missing_ok=True)

    def get(self, url: str, ttl: float = 86400, key: str | None = None) -> dict:
        url = checked_url(url)
        key = key or f"cache/{hashlib.sha256(url.encode()).hexdigest()}.json"
        result = self._cached(key, ttl)
        if result is not None:
            self.cache_hits += 1
            return result
        with self.lease(url):
            result = self._cached(key, ttl)
            if result is not None:
                self.cache_hits += 1
                return result
            with self._request_slots, timed_stage("source_request", namespace=self.namespace):
                self.requests += 1
                result = self._request(url)
            self.store(key, result)
            return result

    def store(self, key: str, data: dict):
        document = json.dumps({"acquired_at": time.time(), "data": data,
                               "reset_generation": self._reset_generation(key)}, separators=(",", ":")).encode()
        path = self.root / key
        if self.persistence.durable:
            with timed_stage("durable_cache_write", namespace=self.namespace):
                self.persistence.write_bytes(f"raw/{self.namespace}/{key}", document, "application/json")
        self._write_local(path, document)

    def collection(self, url: str, ttl: float = 86400, maximum: int = 500) -> list[dict]:
        """Follow up to ten bounded collection pages; reject truncation."""
        rows = []
        for page in range(1, 11):
            document = self.get(query_url(url, limit=100, page=page), ttl)
            rows.extend(document.get("items") or [])
            if len(rows) > maximum:
                raise ValueError("College-football source collection exceeds its supported bound")
            if page >= int(document.get("pageCount", 1)):
                return rows
        raise ValueError("College-football source pagination is incomplete")

    def references(self, url: str, ttl: float = 86400, maximum: int = 500) -> list[dict]:
        entries = self.collection(url, ttl, maximum)

        def resolve(item):
            return self.get(item["$ref"], ttl) if "$ref" in item else item

        resolved = {}
        for indexed, future in bounded_results(lambda pair: resolve(pair[1]), enumerate(entries), self.concurrency):
            resolved[indexed[0]] = future.result()
        return [resolved[index] for index in range(len(entries))]
