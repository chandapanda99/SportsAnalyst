from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

from sports_analyst.api import bundled_frontend_directory
from sports_analyst import desktop
from sports_analyst.desktop import DesktopController, _run_desktop_worker
from sports_analyst.desktop_config import DesktopConfigStore


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
