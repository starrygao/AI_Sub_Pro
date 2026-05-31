"""Provider registry and factory."""
from typing import Dict, List, Type

from .base import BaseProvider

_REGISTRY: Dict[str, Type[BaseProvider]] = {}


def register(name: str, cls: Type[BaseProvider]) -> None:
    _REGISTRY[name] = cls


def get_provider(name: str, config: dict) -> BaseProvider:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown provider: {name!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name](config)


def list_providers() -> List[str]:
    return sorted(_REGISTRY)
