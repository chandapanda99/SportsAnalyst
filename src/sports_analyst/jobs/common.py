"""Shared durable-job behavior that does not depend on a queue provider."""
from __future__ import annotations


class QueueFull(RuntimeError):
    """Raised when the public deployment has reached its admission limit."""


def retryable_job_error(error: Exception) -> bool:
    """Return whether infrastructure should retry a failed application attempt."""
    status = getattr(error, "status_code", None)
    return (
        isinstance(error, (ConnectionError, TimeoutError))
        or status in {408, 429, 500, 502, 503, 504}
        or type(error).__name__
        in {"APIConnectionError", "APITimeoutError", "OperationalError", "ReadTimeout"}
    )
