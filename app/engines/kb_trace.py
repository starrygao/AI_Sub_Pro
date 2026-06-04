"""Lightweight trace for translation prompt context usage."""
from dataclasses import dataclass, field


@dataclass
class TranslationContextTrace:
    memory_hits: list[dict] = field(default_factory=list)
    phrase_hits: list[dict] = field(default_factory=list)
    kb_hits: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "memory_hits": list(self.memory_hits),
            "phrase_hits": list(self.phrase_hits),
            "kb_hits": list(self.kb_hits),
        }
