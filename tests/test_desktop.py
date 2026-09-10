from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sports_analyst.api import bundled_frontend_directory
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
