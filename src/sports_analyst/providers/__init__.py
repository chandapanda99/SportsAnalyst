from sports_analyst.providers.azure_foundry import AzureFoundryProvider
from sports_analyst.providers.ollama import OllamaProvider
from sports_analyst.providers.registry import get_provider, provider_ids, register_provider

register_provider(AzureFoundryProvider())
register_provider(OllamaProvider())

__all__ = ["get_provider", "provider_ids"]
