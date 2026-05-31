"""Typed data model for per-project knowledge base entries."""
from dataclasses import dataclass, field, asdict
from typing import List, Optional


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_string_list(value) -> List[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = []
    return [text for text in (_clean_text(item) for item in items) if text]


@dataclass
class TermEntry:
    source: str
    target: str
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TermEntry":
        if not isinstance(d, dict):
            return cls(source="", target="", notes="")
        return cls(
            source=_clean_text(d.get("source")),
            target=_clean_text(d.get("target")),
            notes=_clean_text(d.get("notes")),
        )


@dataclass
class StyleNotes:
    tone: str = ""
    perspective: str = ""
    rules: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StyleNotes":
        if not isinstance(d, dict) or not d:
            return cls()
        return cls(
            tone=_clean_text(d.get("tone")),
            perspective=_clean_text(d.get("perspective")),
            rules=_clean_string_list(d.get("rules")),
        )


@dataclass
class ProjectKb:
    show_title: str = ""
    tmdb_id: Optional[int] = None
    characters: List[TermEntry] = field(default_factory=list)
    places: List[TermEntry] = field(default_factory=list)
    brands: List[TermEntry] = field(default_factory=list)
    slang: List[TermEntry] = field(default_factory=list)
    style_notes: StyleNotes = field(default_factory=StyleNotes)
    legacy_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "show_title": self.show_title,
            "tmdb_id": self.tmdb_id,
            "characters": [t.to_dict() for t in self.characters],
            "places": [t.to_dict() for t in self.places],
            "brands": [t.to_dict() for t in self.brands],
            "slang": [t.to_dict() for t in self.slang],
            "style_notes": self.style_notes.to_dict(),
            "legacy_keywords": list(self.legacy_keywords),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectKb":
        if not isinstance(d, dict) or not d:
            return cls()
        # Accept both "legacy_keywords" (v2 round-trip) and "_legacy_keywords"
        # (output of migrate_v1_to_v2, which prefixes with an underscore).
        lk = _clean_string_list(d.get("legacy_keywords") or d.get("_legacy_keywords") or [])
        tmdb_id = d.get("tmdb_id")
        if isinstance(tmdb_id, bool) or not isinstance(tmdb_id, int) or tmdb_id < 1:
            tmdb_id = None

        def terms(field: str) -> List[TermEntry]:
            raw = d.get(field, [])
            if not isinstance(raw, list):
                return []
            cleaned = [TermEntry.from_dict(t) for t in raw]
            return [t for t in cleaned if t.source and t.target]

        return cls(
            show_title=_clean_text(d.get("show_title")),
            tmdb_id=tmdb_id,
            characters=terms("characters"),
            places=terms("places"),
            brands=terms("brands"),
            slang=terms("slang"),
            style_notes=StyleNotes.from_dict(d.get("style_notes", {})),
            legacy_keywords=lk,
        )

    def is_empty(self) -> bool:
        return not (
            self.characters
            or self.places
            or self.brands
            or self.slang
            or self.style_notes.tone
            or self.style_notes.perspective
            or self.style_notes.rules
        )
