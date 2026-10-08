"""Keep optional data-provider failures scoped to the feature using them."""
from __future__ import annotations

import importlib
from contextlib import contextmanager


class OptionalDependencyError(RuntimeError):
    """A provider cannot run; the core app and existing local data remain usable."""


@contextmanager
def optional_dependencies(feature: str):
    try:
        yield
    except (ImportError, OSError) as error:
        detail = str(error)
        blocked = any(term in detail.lower() for term in (
            "application control", "blocked", "dll load failed", "code integrity", "winerror 577",
        ))
        if not isinstance(error, ImportError) and not blocked:
            raise  # Network and file errors are not dependency failures.
        reason = "Windows blocked a required native library" if blocked else "a required data-provider library could not load"
        raise OptionalDependencyError(
            f"{feature} is unavailable because {reason}. "
            "The app can still open and use existing downloaded data. "
            "Repair or reinstall the provider dependencies (or ask your administrator to review the block), "
            f"then retry this operation. Technical detail: {detail}"
        ) from error


def load_optional_module(module: str, feature: str):
    with optional_dependencies(feature):
        return importlib.import_module(module)
