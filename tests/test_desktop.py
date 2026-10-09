from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from sports_analyst.api import bundled_frontend_directory
from sports_analyst.desktop import app as desktop
from sports_analyst.desktop.app import DesktopController, _run_desktop_worker
from sports_analyst.desktop.config import DesktopConfigStore


def test_windows_packaging_collects_runtime_dlls_and_preserves_loader_paths(tmp_path, monkeypatch):
    import importlib.util

    source = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "native_dependencies.py"
    spec = importlib.util.spec_from_file_location("desktop_native_dependencies", source)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    root = tmp_path / "site-packages"
    dlls = ["xgboost/lib/xgboost.dll", "numpy.libs/math.dll", "webview/lib/bridge.dll"]
    assets = ["xgboost/VERSION", "xgboost/data/example.json"]
    for relative in [*dlls, *assets]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"native fixture")
    distributions = {
        "open-sports-analyst": types.SimpleNamespace(
            requires=["xgboost>=2", "pywebview; extra == 'desktop'", "pytest; extra == 'test'"], files=[]),
        "xgboost": types.SimpleNamespace(requires=["numpy>=2"], files=[Path(dlls[0]), *map(Path, assets)]),
        "numpy": types.SimpleNamespace(requires=[], files=[Path(dlls[1])]),
        "pywebview": types.SimpleNamespace(requires=[], files=[Path(dlls[2])]),
    }
    for distribution in distributions.values():
        distribution.locate_file = lambda relative: root / relative
    monkeypatch.setattr(collector.metadata, "distribution", distributions.__getitem__)
    runtime = collector.desktop_distributions()
    assert set(runtime) == set(distributions)  # Build/test/cloud extras do not enter the runtime bundle.
    binaries = collector.collect_runtime_dlls(runtime)
    assert (str((root / dlls[0]).resolve()), "xgboost/lib") in binaries
    assert (str((root / dlls[1]).resolve()), "numpy.libs") in binaries
    assert (str((root / dlls[2]).resolve()), "webview/lib") in binaries
    resources = collector.collect_provider_resources(runtime)
    assert (str((root / assets[0]).resolve()), "xgboost") in resources
    assert (str((root / assets[1]).resolve()), "xgboost/data") in resources
    # A stale/incomplete installation must fail packaging rather than shipping.
    distributions["xgboost"].files = [Path("xgboost/lib/missing.dll")]
    with pytest.raises(FileNotFoundError, match="Required runtime DLL is missing"):
        collector.collect_runtime_dlls(runtime)


def test_public_entrypoints_open_without_optional_sports_providers(tmp_path: Path) -> None:
    """Exercise the reorganized package in a fresh interpreter, not cached imports."""
    environment = {**os.environ, "DATA_DIR": str(tmp_path), "JOB_BACKEND": "local",
                   "PERSISTENCE_BACKEND": "local", "SPORTS_ANALYST_RUNTIME_ROLE": "api", "LANGSMITH_TRACING": "false"}
    probe = '''
import importlib.abc
import importlib.util
import sys

class BlockedLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise ImportError('Optional provider deliberately unavailable during startup')

class BlockProviders(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'nflreadpy', 'sportsdataverse', 'pandas', 'scipy', 'sklearn'}:
            return importlib.util.spec_from_loader(fullname, BlockedLoader())

sys.meta_path.insert(0, BlockProviders())
from sports_analyst import api, cli, desktop, worker
from sports_analyst.application.service import AnalystApplication
from sports_analyst.datasets.nfl import NFLVerseConnector
from sports_analyst.datasets.nba import SportsDataverseNBAConnector
from sports_analyst.datasets.soccer.connector import SportsDataverseSoccerConnector
assert callable(desktop.main) and callable(worker.main)
assert callable(api.create_app) and cli.app is not None
assert all(name not in sys.modules for name in ('nflreadpy', 'sportsdataverse', 'pandas', 'scipy', 'sklearn'))
'''
    result = subprocess.run([sys.executable, "-c", probe], env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_desktop_configuration_persists_settings_and_loads_secrets_securely(tmp_path: Path, monkeypatch) -> None:
    secrets: dict[str, str] = {}
    monkeypatch.setattr(DesktopConfigStore, "_set_secret", staticmethod(secrets.__setitem__))
    monkeypatch.setattr(DesktopConfigStore, "_get_secret", staticmethod(secrets.get))
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("FOUNDRY_API_KEY", raising=False)
    store = DesktopConfigStore(tmp_path)

    store.save(
        {
            "MODEL_PROVIDER": "azure_foundry",
            "MODEL": "analysis-model",
            "CHAT_MODEL": "chat-model",
            "FOUNDRY_API_KEY": "not-in-json",
        }
    )
    store.load_environment()

    persisted = json.loads(store.path.read_text(encoding="utf-8"))
    assert persisted["setup_complete"] is True
    assert persisted["settings"]["MODEL"] == "analysis-model"
    assert "FOUNDRY_API_KEY" not in store.path.read_text(encoding="utf-8")
    assert os.environ["MODEL"] == "analysis-model"
    assert os.environ["FOUNDRY_API_KEY"] == "not-in-json"


def test_frozen_frontend_resolves_from_pyinstaller_bundle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert bundled_frontend_directory() == tmp_path / "frontend" / "dist"


def test_desktop_owns_appdata_worker_lifecycle(tmp_path: Path) -> None:
    class FakeEvent:
        def __init__(self) -> None:
            self.stopped = False

        def set(self) -> None:
            self.stopped = True

    class FakeProcess:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.started = False
            self.terminated = False
            self.closed = False

        def start(self) -> None:
            self.started = True

        def is_alive(self) -> bool:
            return self.started and not self.terminated and not self.kwargs["args"][1].stopped

        def join(self, timeout=None) -> None:
            del timeout

        def terminate(self) -> None:
            self.terminated = True

        def close(self) -> None:
            self.closed = True

    class FakeContext:
        def __init__(self) -> None:
            self.process = None

        @staticmethod
        def Event():
            return FakeEvent()

        def Process(self, **kwargs):
            self.process = FakeProcess(**kwargs)
            return self.process

    context = FakeContext()
    controller = DesktopController(DesktopConfigStore(tmp_path), worker_context=context)
    local_settings = type("Settings", (), {"job_backend": "local"})()
    durable_settings = type("Settings", (), {"job_backend": "sqlite"})()

    controller._start_worker_if_configured(local_settings)
    assert context.process is None
    controller._start_worker_if_configured(durable_settings)
    assert context.process.started is True
    assert context.process.kwargs == {
        "target": _run_desktop_worker,
        "args": (durable_settings, controller.worker_stop),
        "name": "sports-analyst-worker",
        "daemon": False,
    }
    first_process = context.process
    controller._start_worker_if_configured(durable_settings)
    assert context.process is first_process
    controller.stop()
    assert first_process.kwargs["args"][1].stopped is True
    assert first_process.closed is True


def test_desktop_opens_startup_screen_before_starting_service(monkeypatch) -> None:
    events: list[str] = []

    class FakeConfigStore:
        setup_complete = True

        def load_environment(self) -> None:
            pass

    class FakeController:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start_server(self) -> str:
            events.append("service started")
            return "http://127.0.0.1:1234"

        def stop(self) -> None:
            pass

    class FakeClosedEvent:
        def __iadd__(self, callback):
            return self

    class FakeWindow:
        events = types.SimpleNamespace(closed=FakeClosedEvent())

    def create_window(*args, **kwargs):
        assert "Preparing your workspace" in kwargs["html"]
        assert "url" not in kwargs
        events.append("window created")
        return FakeWindow()

    monkeypatch.setattr(desktop, "DesktopConfigStore", FakeConfigStore)
    monkeypatch.setattr(desktop, "DesktopController", FakeController)
    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(create_window=create_window, start=lambda **kwargs: None))
    desktop.main([])
    assert events == ["window created"]
