import json
import pickle
import queue
from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from sports_analyst.api import create_app
from sports_analyst.application.service import AnalystApplication
from sports_analyst.config import Settings
from sports_analyst.model_settings import ModelSettingsUpdate, describe_failure
from sports_analyst.providers import registry
from sports_analyst.providers.base import ProviderModel

ENDPOINT = "https://old-resource.openai.azure.com/openai/v1/"
OLD_KEY = "old-secret-key-123"


class FakeChat:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return "OK"


class FakeProvider:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.display_name = provider_id
        self.error: Exception | None = None
        self.built: list[tuple[str, str | None]] = []

    def build(self, settings, model_name=None, include_reasoning=True):
        del include_reasoning
        name = model_name or (settings.ollama_model if self.provider_id == "ollama" else settings.model)
        key = settings.foundry_api_key.get_secret_value() if settings.foundry_api_key else None
        self.built.append((name, key))
        return ProviderModel(FakeChat(self.error), f"{self.provider_id}:{name}", "fake")


@pytest.fixture
def providers(monkeypatch):
    fakes = {name: FakeProvider(name) for name in ("azure_foundry", "ollama")}
    for name, fake in fakes.items():
        monkeypatch.setitem(registry._PROVIDERS, name, fake)
    return fakes


def application(tmp_path: Path, **overrides) -> AnalystApplication:
    values = dict(data_dir=tmp_path, _env_file=None, foundry_endpoint=ENDPOINT,
                  foundry_api_key=OLD_KEY, model="analysis-old")
    values.update(overrides)
    return AnalystApplication(Settings(**values))


def test_view_masks_secrets(tmp_path: Path) -> None:
    client = TestClient(create_app(application(tmp_path)))
    response = client.get("/api/model-settings")
    assert response.status_code == 200
    body = response.json()
    assert OLD_KEY not in response.text
    assert "foundry_api_key" not in body
    assert body["foundry_api_key_set"] is True
    assert body["provider"] == "azure_foundry" and body["configured"] is True
    assert body["editable"] is True and body["persistence"] == "session"


def test_validation_rejects_bad_values_without_changing_settings(tmp_path: Path, providers) -> None:
    app = application(tmp_path)
    client = TestClient(create_app(app))
    bad = [
        ({"provider": "azure_foundry", "foundry_endpoint": "http://x.openai.azure.com/openai/v1/", "model": "m"}, "foundry_endpoint"),
        ({"provider": "azure_foundry", "foundry_endpoint": "https://x.openai.azure.com/", "model": "m"}, "foundry_endpoint"),
        ({"provider": "azure_foundry", "foundry_endpoint": ENDPOINT, "model": ""}, "model"),
        ({"provider": "azure_foundry", "foundry_endpoint": ENDPOINT, "model": "m", "reasoning_effort": "max"}, "reasoning_effort"),
        ({"provider": "ollama", "ollama_base_url": "ftp://host", "ollama_model": "q"}, "ollama_base_url"),
        # A stored key is never sent to a different server.
        ({"provider": "azure_foundry", "foundry_endpoint": "https://evil.example.com/openai/v1/", "model": "m"}, "foundry_api_key"),
    ]
    for payload, field in bad:
        response = client.put("/api/model-settings", json=payload)
        assert response.status_code == 200
        assert response.json()["ok"] is False and response.json()["field"] == field, payload
    assert client.put("/api/model-settings", json={"provider": "openai"}).status_code == 422
    assert providers["azure_foundry"].built == []
    assert app.settings.model == "analysis-old"


def test_rejects_cross_site_requests(tmp_path: Path, providers) -> None:
    client = TestClient(create_app(application(tmp_path)))
    payload = {"provider": "ollama", "ollama_model": "qwen3:8b"}
    response = client.put("/api/model-settings", json=payload, headers={"Origin": "https://attacker.example"})
    assert response.status_code == 403
    # TestClient's host is "testserver", so a local origin is still another site here.
    assert client.put("/api/model-settings", json=payload, headers={"Origin": "http://localhost:5173"}).status_code == 403
    local = client.put("/api/model-settings", json=payload,
                       headers={"Origin": "http://localhost:5173", "Host": "127.0.0.1:8767"})
    assert local.status_code == 200 and local.json()["ok"] is True
    providers["ollama"].built.clear()
    assert client.put("/api/model-settings", content=json.dumps(payload), headers={"Content-Type": "text/plain"}).status_code in {415, 422}
    assert providers["ollama"].built == []


def test_failed_check_keeps_previous_configuration(tmp_path: Path, providers) -> None:
    app = application(tmp_path)
    agent = app.agent
    new_key = "brand-new-secret-456"
    providers["azure_foundry"].error = RuntimeError(f"401 rejected api_key={new_key}")
    client = TestClient(create_app(app))
    response = client.put("/api/model-settings", json={
        "provider": "azure_foundry", "foundry_endpoint": "https://new.openai.azure.com/openai/v1",
        "model": "analysis-new", "foundry_api_key": new_key})
    body = response.json()
    assert body["ok"] is False and body["error"]
    assert new_key not in response.text and OLD_KEY not in response.text
    assert app.settings.model == "analysis-old" and app.settings.foundry_endpoint == ENDPOINT
    assert app.settings.foundry_api_key.get_secret_value() == OLD_KEY
    assert app.agent is agent


def test_successful_swap_applies_live_and_notifies_worker(tmp_path: Path, providers) -> None:
    app = application(tmp_path)
    old_agent = app.agent
    saved: list = []
    sent: list = []

    class Store:
        description = "test store"

        def save(self, values, api_key, clear):
            saved.append((values, api_key, clear))

    app.model_settings_store = Store()
    app.model_settings_listeners.append(sent.append)
    client = TestClient(create_app(app))
    response = client.put("/api/model-settings", json={
        "provider": "azure_foundry", "foundry_endpoint": "https://new.openai.azure.com/openai/v1",
        "model": "analysis-new", "chat_model": "wording", "reasoning_effort": "low", "foundry_api_key": "new-key-789"})
    body = response.json()
    assert body["ok"] is True, body
    assert "new-key-789" not in response.text
    assert body["settings"]["model"] == "analysis-new" and body["settings"]["persistence"] == "saved"
    assert body["settings"]["status"]["state"] == "ready"
    assert app.settings.foundry_endpoint == "https://new.openai.azure.com/openai/v1/"
    assert app.agent is not old_agent and app.agent.settings is app.settings
    # Both the analysis and wording deployments were checked with the new key.
    assert providers["azure_foundry"].built == [("analysis-new", "new-key-789"), ("wording", "new-key-789")]
    values, api_key, clear = saved[0]
    assert api_key == "new-key-789" and clear is False
    assert "new-key-789" not in json.dumps(values) and values["model"] == "analysis-new"
    assert sent[0] is app.settings
    assert client.get("/api/capabilities").json()["configured_provider"] == "azure_foundry"

    # Switching to Ollama and back to the same server keeps the stored key.
    assert client.put("/api/model-settings", json={"provider": "ollama", "ollama_model": "qwen3:8b"}).json()["ok"]
    assert client.get("/api/capabilities").json()["configured_provider"] == "ollama"
    assert app.settings.chat_model is None and providers["ollama"].built == [("qwen3:8b", "new-key-789")]
    again = client.put("/api/model-settings", json={
        "provider": "azure_foundry", "foundry_endpoint": "https://new.openai.azure.com/openai/v1/", "model": "analysis-new"})
    assert again.json()["ok"] is True
    assert app.settings.foundry_api_key.get_secret_value() == "new-key-789"


def test_running_investigation_keeps_its_provider(tmp_path: Path, providers) -> None:
    app = application(tmp_path)
    started, release = Event(), Event()
    seen: dict = {}

    def run() -> None:
        with app.pinned_model_runtime():
            seen["before"] = (app.settings.model, app.agent)
            started.set()
            release.wait(5)
            seen["after"] = (app.settings.model, app.agent)

    worker = Thread(target=run)
    worker.start()
    started.wait(5)
    assert app.update_model_settings(ModelSettingsUpdate(
        provider="azure_foundry", foundry_endpoint=ENDPOINT, model="analysis-new"))["ok"] is True
    release.set()
    worker.join(5)
    assert seen["after"] == seen["before"] and seen["before"][0] == "analysis-old"
    assert app.settings.model == "analysis-new"


def test_read_only_when_analyses_run_elsewhere(tmp_path: Path, providers) -> None:
    app = application(tmp_path, job_backend="sqlite")
    client = TestClient(create_app(app))
    assert client.get("/api/model-settings").json()["editable"] is False
    assert client.put("/api/model-settings", json={"provider": "ollama", "ollama_model": "q"}).status_code == 403
    app.model_settings_listeners.append(lambda _settings: None)
    assert client.get("/api/model-settings").json()["editable"] is True


def test_worker_adopts_updates_between_jobs() -> None:
    from sports_analyst.worker import _apply_settings_updates

    settings = Settings(_env_file=None, foundry_api_key="a")
    updates: queue.Queue = queue.Queue()
    updates.put({"model": "next", "foundry_api_key": SecretStr("b")})
    updated = _apply_settings_updates(settings, updates)
    assert updated.model == "next" and updated.foundry_api_key.get_secret_value() == "b"
    assert _apply_settings_updates(updated, None) is updated
    # Settings cross the process boundary by pickling.
    assert pickle.loads(pickle.dumps(updated)).foundry_api_key.get_secret_value() == "b"


def test_desktop_store_keeps_key_out_of_the_settings_file(tmp_path: Path, monkeypatch) -> None:
    from sports_analyst.desktop.config import DesktopConfigStore, DesktopModelSettingsStore

    secrets: dict[str, str] = {}
    monkeypatch.setattr(DesktopConfigStore, "_set_secret", staticmethod(secrets.__setitem__))
    monkeypatch.setattr(DesktopConfigStore, "_delete_secret", staticmethod(lambda key: secrets.pop(key, None)))
    store = DesktopModelSettingsStore(DesktopConfigStore(tmp_path))
    store.save({"model_provider": "azure_foundry", "model": "m", "foundry_endpoint": ENDPOINT, "chat_reasoning_effort": "low"},
               "desktop-secret", False)
    text = (tmp_path / "desktop.json").read_text(encoding="utf-8")
    assert "desktop-secret" not in text and json.loads(text)["settings"]["CHAT_REASONING_EFFORT"] == "low"
    assert secrets == {"FOUNDRY_API_KEY": "desktop-secret"}
    store.save({"model_provider": "azure_foundry", "model": "m", "foundry_endpoint": ENDPOINT}, None, True)
    assert secrets == {}


def test_failure_messages_are_readable_and_scrubbed() -> None:
    class AuthenticationError(Exception):
        status_code = 401

    class ConnectError(Exception):
        pass

    assert "credentials" in describe_failure(AuthenticationError("bad key sk-123"))
    assert describe_failure(ConnectError("refused")).startswith("Could not reach the service")
    message = describe_failure(RuntimeError("boom with secret-value-1 api_key=abc"), ("secret-value-1",))
    assert "secret-value-1" not in message and "abc" not in message
