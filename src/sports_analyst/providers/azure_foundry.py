from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sports_analyst.providers.base import ProviderModel


class AzureFoundryProvider:
    provider_id = "azure_foundry"
    display_name = "Azure Foundry"

    def build(self, settings: Any) -> ProviderModel:
        from langchain_openai import ChatOpenAI

        parsed = urlparse(settings.foundry_endpoint)
        if parsed.scheme != "https" or not parsed.path.rstrip("/").endswith("/openai/v1"):
            raise ValueError("FOUNDRY_ENDPOINT must be HTTPS and end with /openai/v1/")
        credential: Any = settings.foundry_api_key.get_secret_value() if settings.foundry_api_key else None
        authentication = "api_key"
        if not credential:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            credential = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
            authentication = "default_azure_credential"
        options: dict[str, Any] = {}
        if settings.reasoning_effort:
            options["reasoning"] = {"effort": settings.reasoning_effort}
        model = ChatOpenAI(
            model=settings.model,
            base_url=settings.foundry_endpoint,
            api_key=credential,
            use_responses_api=True,
            **options,
        )
        return ProviderModel(model, f"azure_foundry:{settings.model}", authentication)
