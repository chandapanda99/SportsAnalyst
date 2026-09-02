from __future__ import annotations

from typing import Any

from sports_analyst.providers.base import ProviderModel


class OllamaProvider:
    provider_id = "ollama"
    display_name = "Ollama"

    def build(self, settings: Any, model_name: str | None = None, include_reasoning: bool = True) -> ProviderModel:
        from langchain_ollama import ChatOllama

        del include_reasoning
        resolved_name = model_name or settings.ollama_model
        model = ChatOllama(model=resolved_name, base_url=settings.ollama_base_url)
        return ProviderModel(model, f"ollama:{resolved_name}", "local")
