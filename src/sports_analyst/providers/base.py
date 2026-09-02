from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderModel:
    chat_model: Any
    model_id: str
    authentication: str


class ModelProvider(Protocol):
    provider_id: str
    display_name: str

    def build(self, settings: Any, model_name: str | None = None, include_reasoning: bool = True) -> ProviderModel: ...
