from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from typing import Any

from langsmith import Client, trace, tracing_context
from langsmith.run_trees import RunTree

from sports_analyst.config import Settings

logger = logging.getLogger("sports_analyst.telemetry")


class LangSmithTelemetry:
    """Optional, fail-open LangSmith tracing for application-level work."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: Client | None = None
        if not settings.langsmith_tracing:
            logger.debug("langsmith_tracing_disabled")
            return
        if settings.langsmith_api_key is None:
            logger.warning("langsmith_tracing_disabled reason=missing_api_key")
            return
        try:
            self.client = Client(
                api_url=settings.langsmith_endpoint or None,
                api_key=settings.langsmith_api_key.get_secret_value(),
                workspace_id=settings.langsmith_workspace_id or None,
            )
            logger.info("langsmith_tracing_enabled project=%s", settings.langsmith_project)
        except Exception as error:
            logger.warning("langsmith_tracing_disabled error_type=%s", type(error).__name__)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @contextmanager
    def span(
        self,
        name: str,
        *,
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        parent: RunTree | None = None,
        run_type: str = "chain",
    ) -> Iterator[RunTree | None]:
        """Create a span while preserving application behavior if telemetry fails."""
        if self.client is None:
            yield None
            return

        context_manager: AbstractContextManager[Any] | None = None
        trace_manager: AbstractContextManager[RunTree] | None = None
        try:
            context_manager = tracing_context(
                enabled=True,
                client=self.client,
                project_name=self.settings.langsmith_project,
                metadata=metadata,
                tags=tags,
            )
            context_manager.__enter__()
            trace_manager = trace(
                name,
                run_type=run_type,
                inputs=inputs or {},
                project_name=self.settings.langsmith_project,
                parent=parent,
                metadata=metadata,
                tags=tags,
                client=self.client,
            )
            run = trace_manager.__enter__()
        except Exception as error:
            logger.warning("langsmith_span_start_failed span=%s error_type=%s", name, type(error).__name__)
            if context_manager is not None:
                with suppress(Exception):
                    context_manager.__exit__(None, None, None)
            yield None
            return

        try:
            yield run
        except BaseException as application_error:
            try:
                trace_manager.__exit__(type(application_error), application_error, application_error.__traceback__)
            except Exception as trace_error:
                logger.warning("langsmith_span_finish_failed span=%s error_type=%s", name, type(trace_error).__name__)
            finally:
                with suppress(Exception):
                    context_manager.__exit__(type(application_error), application_error, application_error.__traceback__)
            raise
        else:
            try:
                trace_manager.__exit__(None, None, None)
            except Exception as error:
                logger.warning("langsmith_span_finish_failed span=%s error_type=%s", name, type(error).__name__)
            finally:
                with suppress(Exception):
                    context_manager.__exit__(None, None, None)

    @staticmethod
    def add_outputs(run: RunTree | None, outputs: dict[str, Any]) -> None:
        if run is None:
            return
        try:
            run.add_outputs(outputs)
        except Exception as error:
            logger.warning("langsmith_span_output_failed error_type=%s", type(error).__name__)
