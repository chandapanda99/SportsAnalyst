from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sports_analyst.api import bundled_frontend_directory
from sports_analyst.desktop import SETUP_HTML, SETUP_ICON_DATA_URI, DesktopController, _run_desktop_worker
from sports_analyst.desktop_config import DesktopConfigStore


def test_setup_form_marks_requirements_and_switches_provider_fields() -> None:
    assert SETUP_ICON_DATA_URI.startswith("data:image/svg+xml;base64,")
    assert 'alt="Open Sports Analyst logo"' in SETUP_HTML
    assert "__SETUP_ICON_DATA_URI__" not in SETUP_HTML
    assert 'data-provider="azure_foundry"' in SETUP_HTML
    assert 'data-provider="ollama" hidden' in SETUP_HTML
    assert "group.hidden=!active" in SETUP_HTML
    assert "control.disabled=!active" in SETUP_HTML
    assert "Required unless already authenticated" in SETUP_HTML
    assert "this specific Azure Foundry resource" in SETUP_HTML
    assert 'name="FOUNDRY_ENDPOINT" type="url"' in SETUP_HTML
    assert 'name="OLLAMA_BASE_URL" type="url"' in SETUP_HTML


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
