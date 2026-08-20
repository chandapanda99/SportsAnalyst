from sports_analyst.providers.base import ModelProvider

_PROVIDERS: dict[str, ModelProvider] = {}


def register_provider(provider: ModelProvider) -> None:
    _PROVIDERS[provider.provider_id] = provider


def get_provider(provider_id: str) -> ModelProvider:
    try:
        return _PROVIDERS[provider_id]
    except KeyError as error:
        raise ValueError(f"unsupported provider {provider_id!r}; registered providers: {sorted(_PROVIDERS)}") from error


def provider_ids() -> list[str]:
    return sorted(_PROVIDERS)
