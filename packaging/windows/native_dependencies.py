"""Prepare native provider assets, then collect them without provider imports."""
import ast
import re
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def tls_runtime_requirement(distribution):
    """Read the locked package's version requirement without importing its code."""
    source = Path(distribution.locate_file("tls_requests/models/libraries.py"))
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "LATEST_VERSION_TAG_NAME"
                                               for target in node.targets):
            tag = ast.literal_eval(node.value)
            if isinstance(tag, str) and re.fullmatch(r"v?\d+\.\d+\.\d+", tag):
                return tag.removeprefix("v"), source.parent.parent / "bin"
    raise RuntimeError("Cannot determine the installed TLS client's required binary version")


def tls_runtime_libraries(distribution, *, required=True):
    version, directory = tls_runtime_requirement(distribution)
    libraries = sorted(directory.glob(f"*-{version}-windows-amd64.dll"))
    if required and not libraries:
        raise FileNotFoundError(f"TLS client {version} Windows x64 DLL is missing; run packaging/windows/build.ps1 "
                                "to prepare provider assets before freezing")
    return libraries


def prepare_tls_runtime():
    """Acquire the package-required binary at build time, never at app startup."""
    try:
        distribution = metadata.distribution("wrapper-tls-requests")
    except metadata.PackageNotFoundError:
        return  # Older SoccerData releases do not use this transport.
    version, _ = tls_runtime_requirement(distribution)
    if not tls_runtime_libraries(distribution, required=False):
        from tls_requests.models.libraries import TLSLibrary

        if TLSLibrary.download(version=version) is None:
            raise RuntimeError(f"Could not prepare the TLS client {version} Windows x64 DLL")
    libraries = tls_runtime_libraries(distribution)
    print(f"TLS provider runtime prepared: {', '.join(path.name for path in libraries)}")


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
    for name, distribution in distributions.items():
        root = Path(distribution.locate_file("")).resolve()
        files = list(distribution.files or [])
        if name == "wrapper-tls-requests":
            # The upstream transport downloads these into bin/ after wheel
            # installation, so they are absent from distribution.files/RECORD.
            files.extend(path.resolve().relative_to(root) for path in tls_runtime_libraries(distribution))
        for relative in files:
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
    for name, package in (("xgboost", "xgboost"), ("sportsdataverse", "sportsdataverse"),
                          ("nflreadpy", "nflreadpy"), ("soccerdata", "soccerdata"),
                          ("wrapper-tls-requests", "tls_requests"), ("seleniumbase", "seleniumbase")):
        if name not in distributions:
            continue
        distribution = distributions[name]
        root = Path(distribution.locate_file("")).resolve()
        for relative in distribution.files or []:
            relative = Path(str(relative))
            if relative.parts[0] != package or relative.suffix.lower() in {".py", ".pyc", ".pyi", ".pyd", ".dll", ".so"}:
                continue
            source = Path(distribution.locate_file(relative)).resolve()
            if not source.is_file():
                raise FileNotFoundError(f"Required provider resource is missing: {source}")
            resources.add((str(source), source.relative_to(root).parent.as_posix()))
    if not any(Path(source).name == "VERSION" and destination == "xgboost" for source, destination in resources):
        raise FileNotFoundError("The XGBoost package must contain its VERSION resource")
    return sorted(resources)


if __name__ == "__main__":
    prepare_tls_runtime()
