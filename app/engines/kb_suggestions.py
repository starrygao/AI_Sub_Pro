"""Generate candidate knowledge base entries from project metadata and subtitles."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.engines.kb_models import ProjectKb


KB_CATEGORIES = ("characters", "places", "brands", "slang")

_TITLE_CASE_PHRASE_RE = re.compile(
    r"\b[A-Z][A-Za-z]+(?:['-][A-Z]?[A-Za-z]+)?"
    r"(?:\s+[A-Z][A-Za-z]+(?:['-][A-Z]?[A-Za-z]+)?)*\b"
)
_WHITESPACE_RE = re.compile(r"\s+")
_LEADING_ARTICLE_RE = re.compile(r"^(?:The|A|An)\s+", re.IGNORECASE)

_NOISE_TERMS = {
    "a",
    "ai",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "in",
    "it",
    "of",
    "ok",
    "on",
    "or",
    "the",
    "to",
    "tv",
    "uk",
    "us",
}

_PLACE_HINTS = {
    "airport",
    "avenue",
    "bar",
    "beach",
    "bridge",
    "building",
    "cafe",
    "center",
    "centre",
    "church",
    "city",
    "club",
    "college",
    "county",
    "court",
    "empire",
    "hospital",
    "hotel",
    "house",
    "island",
    "kingdom",
    "lake",
    "mall",
    "museum",
    "park",
    "plaza",
    "restaurant",
    "river",
    "road",
    "school",
    "station",
    "street",
    "theater",
    "theatre",
    "town",
    "university",
    "village",
}

_BRAND_HINTS = {
    "bank",
    "channel",
    "corp",
    "corporation",
    "inc",
    "labs",
    "llc",
    "ltd",
    "motors",
    "network",
    "news",
    "pictures",
    "records",
    "studio",
    "studios",
    "tech",
    "technologies",
}


@dataclass
class KbSuggestion:
    source: str
    target: str
    category: str
    notes: str
    evidence: list[str]
    confidence: float
    collision: str = "new"

    def to_dict(self) -> dict:
        return asdict(self)


def suggest_kb_entries(
    project: dict,
    subtitles: list[dict] | None,
    existing_kb: ProjectKb | None,
) -> list[KbSuggestion]:
    """Suggest candidate KB entries from project metadata and subtitle text."""
    existing_sources = _existing_sources(existing_kb)
    suggestions: dict[str, KbSuggestion] = {}

    for source, category, evidence, confidence in _iter_candidates(project, subtitles):
        term = _normalize_source(source)
        if not _is_useful_term(term):
            continue

        key = term.casefold()
        collision = "existing" if key in existing_sources else "new"
        if key in suggestions:
            suggestion = suggestions[key]
            if evidence not in suggestion.evidence:
                suggestion.evidence.append(evidence)
            suggestion.confidence = max(suggestion.confidence, confidence)
            if suggestion.collision != "existing" and collision == "existing":
                suggestion.collision = "existing"
            continue

        suggestions[key] = KbSuggestion(
            source=term,
            target="",
            category=category,
            notes="",
            evidence=[evidence],
            confidence=confidence,
            collision=collision,
        )

    return list(suggestions.values())


def _iter_candidates(project: dict, subtitles: list[dict] | None):
    project = project if isinstance(project, dict) else {}

    for source, evidence in _cast_names(project.get("cast")):
        yield source, "characters", evidence, 0.95 if evidence == "cast" else 0.9

    for field, evidence in (
        ("title", "title"),
        ("name", "title"),
        ("original_title", "title"),
        ("overview", "overview"),
    ):
        for phrase in _title_case_phrases(project.get(field)):
            yield phrase, _category_for_phrase(phrase), evidence, 0.75 if evidence == "title" else 0.6

    for subtitle in subtitles or []:
        if not isinstance(subtitle, dict):
            continue
        index = subtitle.get("index")
        evidence = f"subtitle:{index}" if index is not None else "subtitle"
        for phrase in _title_case_phrases(subtitle.get("text")):
            yield phrase, _category_for_phrase(phrase), evidence, 0.55


def _cast_names(cast):
    if not isinstance(cast, list):
        return

    for item in cast:
        if isinstance(item, str):
            yield item, "cast"
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        character = item.get("character")
        if isinstance(name, str):
            yield name, "cast"
        if isinstance(character, str):
            yield character, "character"


def _title_case_phrases(value) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []
    return [_normalize_source(match.group(0)) for match in _TITLE_CASE_PHRASE_RE.finditer(text)]


def _category_for_phrase(source: str) -> str:
    words = [word.strip(".,:;!?()[]{}\"'").casefold() for word in source.split()]
    if not words:
        return "slang"
    last = words[-1]
    if last in _PLACE_HINTS:
        return "places"
    if last in _BRAND_HINTS:
        return "brands"
    return "slang"


def _existing_sources(existing_kb: ProjectKb | None) -> set[str]:
    if existing_kb is None:
        return set()

    sources: set[str] = set()
    for category in KB_CATEGORIES:
        for entry in getattr(existing_kb, category, []) or []:
            source = _normalize_source(getattr(entry, "source", ""))
            if source:
                sources.add(source.casefold())
    return sources


def _normalize_source(value) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = _WHITESPACE_RE.sub(" ", text)
    text = text.strip(" \t\r\n.,:;!?()[]{}\"'")
    text = _LEADING_ARTICLE_RE.sub("", text)
    return text.strip()


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_useful_term(source: str) -> bool:
    if not source:
        return False
    folded = source.casefold()
    if folded in _NOISE_TERMS:
        return False
    letters = [char for char in source if char.isalpha()]
    if len(letters) <= 2:
        return False
    if source.isupper():
        return False
    return True
