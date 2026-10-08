"""Browser-safe dataset failures, separate from private provider diagnostics."""
from __future__ import annotations

from sports_analyst.datasets.optional import OptionalDependencyError


class FixtureDiscoveryError(ValueError):
    """No usable fixtures could be retrieved for the selected season."""


class SyncFailure(RuntimeError):
    def __init__(self, context: dict, error: Exception):
        self.context = dict(context)
        self.context["error_type"] = type(error).__name__
        self.retryable_cause = error
        if isinstance(error, OptionalDependencyError):
            reason = "A required data-provider library could not load; it may be missing or blocked by Windows."
        elif isinstance(error, FixtureDiscoveryError):
            reason = "No usable match fixtures could be retrieved from the source."
        elif isinstance(error, TimeoutError) or type(error).__name__ in {"Timeout", "ReadTimeout", "ConnectTimeout"}:
            reason = "The data source did not respond in time."
        elif isinstance(error, ConnectionError) or type(error).__name__ in {"ConnectionError", "APIConnectionError"}:
            reason = "The data source could not be reached."
        elif isinstance(error, PermissionError):
            reason = "The data library could not be accessed. Check its permissions."
        elif type(error).__name__ in {"ComputeError", "SchemaError"}:
            reason = "The source data has an unexpected format."
        else:
            reason = "The source data could not be downloaded, processed, or saved."
        scope = context["league"]
        season = context.get("season_label")
        if season:
            scope += f" · {season}"
        super().__init__(f"Data sync failed for {scope} during {context['step']}. {reason} "
                         "Check worker logs for details, then retry.")


def safe_sync_message(error: Exception) -> str:
    return str(error) if isinstance(error, SyncFailure) else "Data sync failed. Check worker logs for details, then retry."
