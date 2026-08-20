from __future__ import annotations

from typing import Any

from sports_analyst.providers.base import ProviderModel


class OllamaProvider:
    provider_id = "ollama"
    display_name = "Ollama"

    def build(self, settings: Any) -> ProviderModel:
        from langchain_ollama import ChatOllama

        model = ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url)
        return ProviderModel(model, f"ollama:{settings.ollama_model}", "local")
