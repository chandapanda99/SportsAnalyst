"""Durable investigation budget and immutable research artifacts."""
from __future__ import annotations

import gzip
import io
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from urllib.parse import urlparse

from sports_analyst.models import stable_id

ACTIVE_BUDGET = ContextVar("research_budget", default=None)


class ResearchLimit(RuntimeError):
    pass


class ContextPool(ThreadPoolExecutor):
    """Propagate the budget to provider threads; unrelated jobs keep their own context."""
    def submit(self, fn, /, *args, **kwargs):
        return super().submit(copy_context().run, fn, *args, **kwargs)


class ResearchState:
    def __init__(self, app, identifier):
        self.app, self.identifier = app, identifier
        self.root = app.settings.data_dir / "research" / stable_id("scope", identifier)
        self.root.mkdir(parents=True, exist_ok=True)
        self.remote = "research/" + self.root.name + "/"
        self.lock = RLock()

    def read(self, name):
        if self.app.store.persistence.durable:
            value = self.app.store.persistence.read_bytes(self.remote + name + ".json")
            return json.loads(value) if value else None
        path = self.root / (name + ".json")
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def write(self, name, payload):
        from sports_analyst.datasets.cfb_source import CFBSource

        data = json.dumps(payload, sort_keys=True, default=str, allow_nan=False).encode()
        CFBSource._write_local(self.root / (name + ".json"), data)
        if self.app.store.persistence.durable:
            self.app.store.persistence.write_bytes(self.remote + name + ".json", data, "application/json")

    def consume(self, *, requests=0, transferred=0, attempt=None, round=1):
        from sports_analyst.application.preparation import coordinator

        settings = self.app.settings
        with self.lock, coordinator(self.app).lease(f"research-budget:{self.root.name}", seconds=60):
            saved = self.read("budget")
            state = saved or {"started": time.time(), "requests": 0, "bytes": 0, "attempts": []}
            if state.get("blocked"):
                raise ResearchLimit(state["blocked"])
            if time.time() - state["started"] > settings.research_elapsed_seconds:
                state["blocked"] = "Research time budget exhausted; use scoped Data Management and rerun"
                self.write("budget", state)
                raise ResearchLimit("Research time budget exhausted. Download the missing package in Data Management, then rerun.")
            if round > settings.research_rounds:
                raise ResearchLimit("Acquisition/replanning round limit exceeded")
            if (state["requests"] + requests > settings.research_source_requests
                    or state["bytes"] + transferred > settings.research_transfer_bytes
                    or (attempt and len(state["attempts"]) >= settings.research_package_attempts)):
                state["blocked"] = "Research request/transfer/package budget exhausted; use scoped Data Management and rerun"
                self.write("budget", state)
                raise ResearchLimit("Research request/transfer/package budget exhausted. Use scoped Data Management, then rerun.")
            state["requests"] += requests
            state["bytes"] = max(0, state["bytes"] + transferred)
            if attempt:
                state["attempts"].append(attempt)
            if saved is None or requests or transferred or attempt:
                self.write("budget", state)
            return state

    def fetch(self, url, destination=None, max_bytes=None, headers=None, cookie_jar=None):
        """Only adapters supply URLs. Charge redirects and reserve bytes BEFORE reading."""
        owner = self

        def checked(url):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.username or parsed.password or parsed.hostname not in {
                "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
                "api.github.com", "raw.githubusercontent.com",
                "sports.core.api.espn.com", "site.api.espn.com", "site.web.api.espn.com",
                "understat.com",
                  "www.whoscored.com",
                  "www.fotmob.com",
            }:
                raise ValueError("Research adapter requested an unapproved source host")
            return url

        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                checked(newurl)
                owner.consume(requests=1)
                return super().redirect_request(request, fp, code, msg, headers, newurl)

        url = checked(url)
        self.consume(requests=1)
        request = urllib.request.Request(url, headers={"User-Agent": "Open-Sports-Analyst/1.1", **(headers or {})})
        chunks, output = [], None
        try:
            if destination:
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                output = destination.open("wb")
            handlers = [Redirect()]
            if cookie_jar is not None:
                handlers.append(urllib.request.HTTPCookieProcessor(cookie_jar))
            with urllib.request.build_opener(*handlers).open(request, timeout=30) as response:
                length = response.headers.get("Content-Length")
                current = self.consume()
                if length and int(length) > self.app.settings.research_transfer_bytes - current["bytes"]:
                    raise ResearchLimit("Asset exceeds remaining transfer budget; use Data Management explicitly")
                if max_bytes and length and int(length) > max_bytes:
                    raise ResearchLimit("Source JSON exceeds the response-memory bound")
                received = 0
                reserved = int(length) if length else 0
                if reserved:
                    self.consume(transferred=reserved)
                while not length or received < int(length):
                    # Reserve pessimistically; interrupted reads cannot undercount retries.
                    if time.time() - current["started"] > self.app.settings.research_elapsed_seconds:
                        self.consume()  # Persist the timeout before aborting.
                    remaining = (reserved - received if length else
                                 self.app.settings.research_transfer_bytes - self.consume()["bytes"])
                    size = min(1024 * 1024, remaining)
                    if size <= 0:
                        raise ResearchLimit("Transfer budget exhausted")
                    if not length:
                        self.consume(transferred=size)
                    data = response.read(size)
                    if not length:
                        self.consume(transferred=-(size - len(data)))
                    if not data:
                        if length and received != reserved:
                            raise OSError("Source body ended before its declared size")
                        break
                    received += len(data)
                    if max_bytes and received > max_bytes:
                        raise ResearchLimit("Source JSON exceeds the response-memory bound")
                    if output:
                        output.write(data)
                    else:
                        chunks.append(data)
            return b"".join(chunks) if not output else None
        finally:
            if output:
                output.close()


def budget_json(url):
    budget = ACTIVE_BUDGET.get()
    if budget is None:
        raise RuntimeError("Budgeted transport needs an active research budget")
    return json.loads(budget.fetch(url, max_bytes=16 * 1024**2))


def budget_public_json(url):
    budget = ACTIVE_BUDGET.get()
    raw = budget.fetch(url, max_bytes=16 * 1024**2)
    if url.endswith(".gz"):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(4 * 1024**2 + 1)
        if len(raw) > 4 * 1024**2:
            raise ResearchLimit("Decompressed provider payload exceeds its bound")
    return json.loads(raw)


@contextmanager
def budget_opener(request, **kwargs):
    """File-backed response for existing validated secondary-asset adapters."""
    url = request.full_url
    cap = 2 * 1024**2 + 1 if "/schedules/parquet/" in url else 160 * 1024**2
    with TemporaryDirectory(prefix="sports-provider-", dir=ACTIVE_BUDGET.get().root) as directory:
        path = Path(directory) / "asset"
        ACTIVE_BUDGET.get().fetch(url, path, max_bytes=cap)
        with path.open("rb") as stream:
            yield stream
