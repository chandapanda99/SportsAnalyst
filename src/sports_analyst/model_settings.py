"""View, validate, test and apply the LLM provider settings while the app runs.

Secrets never leave this module in a response: views report only whether a key
is stored, and error text is scrubbed of any key before it is returned or logged.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr

logger = logging.getLogger("sports_analyst.model_settings")

# Settings fields owned by the provider panel. Everything else stays as configured.
MODEL_FIELDS = (
    "model_provider",
    "model",
    "chat_model",
    "reasoning_effort",
    "chat_reasoning_effort",
    "foundry_endpoint",
    "foundry_api_key",
    "ollama_base_url",
    "ollama_model",
)
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
PROVIDER_LABELS = {"azure_foundry": "Azure AI Foundry", "ollama": "Ollama"}
CHECK_TIMEOUT_SECONDS = 45
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ModelSettingsUpdate(BaseModel):
    provider: Literal["azure_foundry", "ollama"]
    model: str | None = Field(default=None, max_length=128)
    chat_model: str | None = Field(default=None, max_length=128)
    reasoning_effort: str | None = Field(default=None, max_length=16)
    chat_reasoning_effort: str | None = Field(default=None, max_length=16)
    foundry_endpoint: str | None = Field(default=None, max_length=512)
    # Write-only. Omit or leave blank to keep the stored key.
    foundry_api_key: SecretStr | None = Field(default=None, repr=False)
    # Switch Azure Foundry to Microsoft Entra sign-in and forget the stored key.
    clear_api_key: bool = False
    ollama_base_url: str | None = Field(default=None, max_length=512)
    ollama_model: str | None = Field(default=None, max_length=128)


class ModelSettingsError(ValueError):
    """A readable problem with the requested settings, safe to show the user."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class ModelSettingsStore(Protocol):
    """Where applied settings are remembered for the next launch."""

    description: str

    def save(self, values: dict[str, str], api_key: str | None, clear_api_key: bool) -> None: ...


def _text(value: str | None) -> str:
    return (value or "").strip()


def _effort(value: str | None, field: str) -> str | None:
    effort = _text(value).lower()
    if effort and effort not in REASONING_EFFORTS:
        raise ModelSettingsError(f"Reasoning effort must be one of: {', '.join(REASONING_EFFORTS)}, or blank.", field)
    return effort or None


def _name(value: str | None, field: str, label: str, *, required: bool) -> str | None:
    name = _text(value)
    if not name:
        if required:
            raise ModelSettingsError(f"Enter the {label}.", field)
        return None
    if not _NAME.match(name):
        raise ModelSettingsError(f"The {label} can use letters, numbers, '.', '_', ':', '/' and '-' only.", field)
    return name


def _host(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{(parsed.hostname or '').lower()}:{parsed.port or ''}"


def public_view(settings: Any) -> dict[str, Any]:
    """The current provider settings with every secret masked."""
    provider = settings.model_provider
    has_key = bool(settings.foundry_api_key and settings.foundry_api_key.get_secret_value())
    return {
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "configured": provider == "ollama" or bool(settings.foundry_endpoint),
        "model": settings.model,
        "chat_model": settings.chat_model or "",
        "reasoning_effort": settings.reasoning_effort or "",
        "chat_reasoning_effort": settings.chat_reasoning_effort or "",
        "foundry_endpoint": settings.foundry_endpoint,
        "foundry_api_key_set": has_key,
        "foundry_authentication": "api_key" if has_key else "azure_identity",
        "ollama_base_url": settings.ollama_base_url,
        "ollama_model": settings.ollama_model,
    }


def merge(current: Any, update: ModelSettingsUpdate) -> tuple[Any, dict[str, str], str | None]:
    """Validate ``update`` against ``current``.

    Returns the new settings, the non-secret values to persist and the new key
    (``None`` when the key is unchanged or cleared).
    """
    values: dict[str, Any] = {"model_provider": update.provider}
    new_key = update.foundry_api_key.get_secret_value().strip() if update.foundry_api_key else ""
    if update.provider == "azure_foundry":
        endpoint = _text(update.foundry_endpoint)
        if not endpoint:
            raise ModelSettingsError("Enter the Azure AI Foundry endpoint.", "foundry_endpoint")
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ModelSettingsError("The endpoint must be an https:// address.", "foundry_endpoint")
        if not parsed.path.rstrip("/").endswith("/openai/v1"):
            raise ModelSettingsError("The endpoint must end with /openai/v1/, for example "
                                     "https://your-resource.openai.azure.com/openai/v1/.", "foundry_endpoint")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ModelSettingsError("The endpoint cannot include a query, fragment or credentials.", "foundry_endpoint")
        if not endpoint.endswith("/"):
            endpoint += "/"
        values.update(
            foundry_endpoint=endpoint,
            model=_name(update.model, "model", "model deployment name", required=True),
            chat_model=_name(update.chat_model, "chat_model", "wording deployment name", required=False),
            reasoning_effort=_effort(update.reasoning_effort, "reasoning_effort"),
            chat_reasoning_effort=_effort(update.chat_reasoning_effort, "chat_reasoning_effort"),
        )
        had_key = bool(current.foundry_api_key and current.foundry_api_key.get_secret_value())
        moved = bool(current.foundry_endpoint) and _host(current.foundry_endpoint) != _host(endpoint)
        if new_key:
            values["foundry_api_key"] = SecretStr(new_key)
        elif update.clear_api_key:
            values["foundry_api_key"] = None
        elif had_key and moved:
            # Never send a stored key to a different server than the one it was entered for.
            raise ModelSettingsError("The endpoint's server changed. Enter the API key for the new endpoint, "
                                     "or choose Microsoft Entra sign-in.", "foundry_api_key")
    else:
        base_url = _text(update.ollama_base_url) or "http://127.0.0.1:11434"
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ModelSettingsError("The Ollama address must start with http:// or https://.", "ollama_base_url")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ModelSettingsError("The Ollama address cannot include a query, fragment or credentials.", "ollama_base_url")
        values.update(
            ollama_base_url=base_url.rstrip("/"),
            ollama_model=_name(update.ollama_model, "ollama_model", "Ollama model name", required=True),
            # The wording model names an Azure deployment; Ollama uses its one model for both.
            chat_model=None,
            chat_reasoning_effort=None,
        )
        if update.clear_api_key:
            values["foundry_api_key"] = None
    candidate = current.model_copy(update=values)
    persisted = {key: ("" if value is None else str(value)) for key, value in values.items() if key != "foundry_api_key"}
    return candidate, persisted, new_key or None


def scrub(text: str, secrets: tuple[str | None, ...]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "••••")
    return re.sub(r"(?i)(api[-_ ]?key|bearer|authorization)([\"']?\s*[:=]\s*[\"']?|\s+)[^\s\"',}]+", r"\1\2••••", text)


def describe_failure(error: BaseException, secrets: tuple[str | None, ...] = ()) -> str:
    """Turn a provider exception into a short message the user can act on."""
    name = type(error).__name__
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(error, ModelSettingsError):
        return str(error)
    if isinstance(error, (FutureTimeout, TimeoutError)) or "Timeout" in name:
        return "The model did not answer in time. Check the endpoint address and that the service is running."
    if status in (401, 403) or "Authentication" in name or "PermissionDenied" in name or "ClientAuthentication" in name \
            or "CredentialUnavailable" in name:
        return "The service rejected the credentials. Check the API key, or sign in with the Azure CLI for Entra access."
    if status == 404 or "NotFound" in name:
        return "The service could not find that model. Check the deployment or model name."
    if status == 429 or "RateLimit" in name:
        return "The service is rate limiting requests. Wait a moment and try again."
    if "Connect" in name or isinstance(error, (ConnectionError, OSError)):
        return "Could not reach the service. Check the address and your network connection."
    if isinstance(error, ImportError):
        return "This provider's client library is not installed in this build."
    detail = scrub(" ".join(str(error).split()), secrets)[:240]
    return f"The connection check failed ({name}){': ' + detail if detail else ''}."


def check_connection(settings: Any, timeout: float = CHECK_TIMEOUT_SECONDS) -> str:
    """Build the configured models and make one tiny request to each.

    Returns the analysis model id; raises on any failure.
    """
    from sports_analyst.providers import get_provider

    provider = get_provider(settings.model_provider)

    def probe() -> str:
        resolved = provider.build(settings)
        resolved.chat_model.invoke("Reply with the single word OK.")
        if settings.chat_model:
            wording = provider.build(settings.model_copy(update={"reasoning_effort": settings.chat_reasoning_effort}),
                                     settings.chat_model)
            wording.chat_model.invoke("Reply with the single word OK.")
        return resolved.model_id

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-check")
    try:
        return executor.submit(probe).result(timeout=timeout)
    finally:
        # A stuck request must not hold the caller; the thread ends with its HTTP timeout.
        executor.shutdown(wait=False, cancel_futures=True)
