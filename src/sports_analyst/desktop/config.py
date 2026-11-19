from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

APPLICATION_NAME = "Open Sports Analyst"
KEYRING_SERVICE = "open-sports-analyst"
SECRET_KEYS = ("FOUNDRY_API_KEY", "LANGSMITH_API_KEY")
SETTING_KEYS = (
    "MODEL_PROVIDER",
    "MODEL",
    "CHAT_MODEL",
    "CHAT_REASONING_EFFORT",
    "FOUNDRY_ENDPOINT",
    "REASONING_EFFORT",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "LANGSMITH_TRACING",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_PROJECT",
    "LANGSMITH_WORKSPACE_ID",
)


class DesktopConfigStore:
    """Persist desktop preferences while keeping API keys in Windows Credential Manager."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or user_config_path("open-sports-analyst", ensure_exists=True)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "desktop.json"

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @property
    def setup_complete(self) -> bool:
        return self.read().get("setup_complete") is True

    def save(self, payload: dict[str, Any]) -> None:
        provider = str(payload.get("MODEL_PROVIDER") or "azure_foundry").strip().lower()
        if provider not in {"azure_foundry", "ollama"}:
            raise ValueError("Model provider must be azure_foundry or ollama")

        existing = self.read()
        settings = dict(existing.get("settings") or {})
        for key in SETTING_KEYS:
            if key not in payload:
                continue
            value = payload[key]
            if isinstance(value, bool):
                settings[key] = "true" if value else "false"
            else:
                settings[key] = str(value).strip()
        settings["MODEL_PROVIDER"] = provider

        for key in SECRET_KEYS:
            if key in payload and str(payload[key]).strip():
                self._set_secret(key, str(payload[key]).strip())

        document = {"setup_complete": True, "settings": settings}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def load_environment(self, *, overwrite: bool = False) -> None:
        settings = self.read().get("settings") or {}
        if isinstance(settings, dict):
            for key in SETTING_KEYS:
                value = settings.get(key)
                if value is not None and (overwrite or key not in os.environ):
                    os.environ[key] = str(value)
        for key in SECRET_KEYS:
            value = self._get_secret(key)
            if value and (overwrite or key not in os.environ):
                os.environ[key] = value

    def forget_secret(self, key: str) -> None:
        if key in SECRET_KEYS:
            self._delete_secret(key)

    @staticmethod
    def _delete_secret(key: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(KEYRING_SERVICE, key)
        except PasswordDeleteError:
            pass

    @staticmethod
    def _set_secret(key: str, value: str) -> None:
        import keyring

        keyring.set_password(KEYRING_SERVICE, key, value)

    @staticmethod
    def _get_secret(key: str) -> str | None:
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, key)
        except Exception:
            return None


class DesktopModelSettingsStore:
    """Remember provider changes made in the app for the next desktop launch."""

    description = ("Saved for the next launch: settings in your desktop.json, the API key in Windows Credential Manager. "
                   "Variables set in your shell environment still take priority at startup.")

    def __init__(self, store: DesktopConfigStore) -> None:
        self.store = store

    def save(self, values: dict[str, str], api_key: str | None, clear_api_key: bool) -> None:
        payload: dict[str, Any] = {key.upper(): value for key, value in values.items()}
        if api_key:
            payload["FOUNDRY_API_KEY"] = api_key
        self.store.save(payload)
        if clear_api_key and not api_key:
            self.store.forget_secret("FOUNDRY_API_KEY")
