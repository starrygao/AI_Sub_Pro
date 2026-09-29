"""Abstract base class for translation providers."""
from abc import ABC, abstractmethod
from typing import List, Dict


class ProviderUnavailableError(RuntimeError):
    """The provider cannot serve this task; per-subtitle retries cannot help."""


class BaseProvider(ABC):
    @abstractmethod
    def translate_batch(self, items: List[Dict], system_prompt: str, retries: int = 3) -> List[Dict]:
        """Return equal-length [{id, translation, error}]; service failures may raise ProviderUnavailableError."""

    @abstractmethod
    def test_connection(self) -> bool: ...

    @property
    @abstractmethod
    def supports_full_document_mode(self) -> bool: ...

    @property
    @abstractmethod
    def context_window_tokens(self) -> int: ...
