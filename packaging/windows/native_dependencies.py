"""Collect runtime DLLs without importing providers during PyInstaller analysis."""
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def desktop_distributions():
    pending = [("open-sports-analyst", frozenset({"desktop"}))]
    visited = set()
    distributions = {}
    while pending:
        name, extras = pending.pop()
        name = canonicalize_name(name)
        key = (name, extras)
        if key in visited:
            continue
        visited.add(key)
        # Fail the build for a missing required dependency, rather than creating
        # an installer which will fail when the feature is first used.
        distribution = metadata.distribution(name)
        distributions[name] = distribution
        for raw in distribution.requires or []:
            requirement = Requirement(raw)
            if requirement.marker and not any(requirement.marker.evaluate({"extra": extra}) for extra in {"", *extras}):
                continue
            pending.append((requirement.name, frozenset(requirement.extras)))
    return distributions


def collect_runtime_dlls(distributions):
    binaries = set()
    for distribution in distributions.values():
        root = Path(distribution.locate_file("")).resolve()
        for relative in distribution.files or []:
            if Path(str(relative)).suffix.lower() != ".dll":
                continue
            source = Path(distribution.locate_file(relative)).resolve()
            if not source.is_file():
                raise FileNotFoundError(f"Required runtime DLL is missing: {source}")
            # Keep xgboost/lib, numpy.libs, etc. intact: native loaders resolve
            # sibling files relative to their bundled package directories.
            destination = source.relative_to(root).parent.as_posix()
            binaries.add((str(source), destination))
    if not any(Path(source).name.lower() == "xgboost.dll" for source, _ in binaries):
        raise FileNotFoundError("The desktop dependency tree must contain xgboost.dll")
    return sorted(binaries)


def collect_provider_resources(distributions):
    """Preserve provider assets which native-library collection cannot discover."""
    resources = set()
    for name in ("xgboost", "sportsdataverse", "nflreadpy"):
        if name not in distributions:
            continue
        distribution = distributions[name]
        root = Path(distribution.locate_file("")).resolve()
        for relative in distribution.files or []:
            relative = Path(str(relative))
            if relative.parts[0] != name or relative.suffix.lower() in {".py", ".pyc", ".pyi", ".pyd", ".dll", ".so"}:
                continue
            source = Path(distribution.locate_file(relative)).resolve()
            if not source.is_file():
                raise FileNotFoundError(f"Required provider resource is missing: {source}")
            resources.add((str(source), source.relative_to(root).parent.as_posix()))
    if not any(Path(source).name == "VERSION" and destination == "xgboost" for source, destination in resources):
        raise FileNotFoundError("The XGBoost package must contain its VERSION resource")
    return sorted(resources)
