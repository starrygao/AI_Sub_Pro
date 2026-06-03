"""Generate candidate knowledge base entries from project metadata and subtitles."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.engines.kb_models import ProjectKb


KB_CATEGORIES = ("characters", "places", "brands", "slang")

_WORD_RE = re.compile(r"\b[A-Za-z]+(?:['-][A-Za-z]+)*\b")
_WHITESPACE_RE = re.compile(r"\s+")

_TITLE_CONNECTORS = {"a", "an", "at", "for", "in", "of", "on", "the", "to"}
_RELATION_CONNECTORS = {"at", "in", "on", "to"}
_PROTECTED_CONNECTED_TITLES = {
    ("lord", "of", "the", "rings"),
    ("once", "upon", "a", "time"),
    ("only", "murders", "in", "the", "building"),
    ("the", "last", "of", "us"),
}
_DENIED_PROSE_STARTERS = {
    "he",
    "i",
    "it",
    "later",
    "meanwhile",
    "she",
    "that",
    "these",
    "they",
    "this",
    "those",
    "today",
    "tomorrow",
    "tonight",
    "we",
    "yesterday",
}

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
    existing_entries: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def suggest_kb_entries(
    project: dict,
    subtitles: list[dict] | None,
    existing_kb: ProjectKb | None,
) -> list[KbSuggestion]:
    """Suggest candidate KB entries from project metadata and subtitle text."""
    existing_entries = _existing_entries_by_source(existing_kb)
    suggestions: dict[str, KbSuggestion] = {}

    for source, category, evidence, confidence, origin in _iter_candidates(project, subtitles):
        term = _normalize_source(source)
        if not _is_useful_term(term, origin):
            continue

        key = term.casefold()
        matches = existing_entries.get(key, [])
        collision = _collision_status(matches)
        if key in suggestions:
            suggestion = suggestions[key]
            if evidence not in suggestion.evidence:
                suggestion.evidence.append(evidence)
            suggestion.confidence = max(suggestion.confidence, confidence)
            suggestion.collision = collision
            suggestion.existing_entries = list(matches)
            continue

        suggestions[key] = KbSuggestion(
            source=term,
            target="",
            category=category,
            notes="",
            evidence=[evidence],
            confidence=confidence,
            collision=collision,
            existing_entries=list(matches),
        )

    return list(suggestions.values())


def _iter_candidates(project: dict, subtitles: list[dict] | None):
    project = project if isinstance(project, dict) else {}

    for source, evidence in _cast_names(project.get("cast")):
        confidence = 0.95 if evidence == "cast" else 0.9
        yield source, "characters", evidence, confidence, evidence

    for field in ("title", "name", "show_title", "original_title"):
        title = _normalize_source(project.get(field))
        if title:
            yield title, _category_for_phrase(title), "title", 0.75, field

    for phrase in _title_case_phrases(project.get("overview")):
        yield phrase, _category_for_phrase(phrase), "overview", 0.6, "overview"

    for subtitle in subtitles or []:
        if not isinstance(subtitle, dict):
            continue
        index = subtitle.get("index")
        evidence = f"subtitle:{index}" if index is not None else "subtitle"
        for phrase in _title_case_phrases(subtitle.get("text")):
            yield phrase, _category_for_phrase(phrase), evidence, 0.55, "subtitle"


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

    tokens = [(match.group(0), match.start(), match.end()) for match in _WORD_RE.finditer(text)]
    phrases: list[str] = []
    i = 0
    while i < len(tokens):
        word = tokens[i][0]
        if not _is_title_word(word):
            i += 1
            continue

        phrase_words = [word]
        pending_connectors: list[str] = []
        j = i + 1
        while j < len(tokens):
            if not _is_soft_phrase_gap(text[tokens[j - 1][2]:tokens[j][1]]):
                break

            next_word = tokens[j][0]
            if _is_title_word(next_word):
                if pending_connectors and _is_acronym_span(phrase_words) and _is_acronym_word(next_word):
                    break
                phrase_words.extend(pending_connectors)
                pending_connectors = []
                phrase_words.append(next_word)
                j += 1
                continue
            if _is_title_connector(next_word):
                pending_connectors.append(next_word)
                j += 1
                continue
            break

        phrase_words = _drop_denied_starter(phrase_words, text, tokens[i][1])
        for split_words in _split_relational_phrases(phrase_words):
            phrase = _normalize_source(" ".join(split_words))
            if phrase:
                phrases.append(phrase)
        i = j

    return phrases


def _is_title_word(word: str) -> bool:
    if _is_title_connector(word):
        return False
    letters = [char for char in word if char.isalpha()]
    if len(letters) < 2:
        return False
    if "".join(letters).isupper():
        return True
    return word[0].isupper() and any(char.islower() for char in word)


def _is_title_connector(word: str) -> bool:
    return word == word.casefold() and word.casefold() in _TITLE_CONNECTORS


def _is_soft_phrase_gap(gap: str) -> bool:
    return bool(gap) and all(char in " \t" for char in gap)


def _drop_denied_starter(phrase_words: list[str], text: str, start: int) -> list[str]:
    if not phrase_words:
        return []
    if phrase_words[0].casefold() not in _DENIED_PROSE_STARTERS:
        return phrase_words
    if not _starts_sentence(text, start):
        return phrase_words

    remaining = phrase_words[1:]
    if _has_multiword_title_phrase(remaining) or any(_is_acronym_word(word) for word in remaining):
        return remaining
    return []


def _split_relational_phrases(phrase_words: list[str]) -> list[list[str]]:
    if not phrase_words:
        return []
    if _is_protected_connected_title(phrase_words):
        return [phrase_words]

    for index, word in enumerate(phrase_words):
        if not _is_relation_connector(word):
            continue
        left = _trim_edge_connectors(phrase_words[:index])
        right = _trim_edge_connectors(phrase_words[index + 1:])
        if _has_title_word(left) and _has_title_word(right):
            return [left, right]

    return [phrase_words]


def _is_protected_connected_title(words: list[str]) -> bool:
    return tuple(word.casefold() for word in words) in _PROTECTED_CONNECTED_TITLES


def _is_relation_connector(word: str) -> bool:
    return word == word.casefold() and word.casefold() in _RELATION_CONNECTORS


def _trim_edge_connectors(words: list[str]) -> list[str]:
    start = 0
    end = len(words)
    while start < end and _is_title_connector(words[start]):
        start += 1
    while end > start and _is_title_connector(words[end - 1]):
        end -= 1
    return words[start:end]


def _starts_sentence(text: str, start: int) -> bool:
    prefix = text[:start].rstrip()
    return not prefix or prefix[-1] in ".!?"


def _has_multiword_title_phrase(words: list[str]) -> bool:
    return sum(1 for word in words if _is_title_word(word)) >= 2


def _has_title_word(words: list[str]) -> bool:
    return any(_is_title_word(word) for word in words)


def _is_acronym_span(words: list[str]) -> bool:
    title_words = [word for word in words if _is_title_word(word)]
    return bool(title_words) and all(_is_acronym_word(word) for word in title_words)


def _is_acronym_word(word: str) -> bool:
    letters = "".join(char for char in word if char.isalpha())
    return len(letters) >= 2 and letters.isupper()


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


def _existing_entries_by_source(existing_kb: ProjectKb | None) -> dict[str, list[dict]]:
    if existing_kb is None:
        return {}

    matches: dict[str, list[dict]] = {}
    for category in KB_CATEGORIES:
        for entry in getattr(existing_kb, category, []) or []:
            source = _normalize_source(getattr(entry, "source", ""))
            if source:
                matches.setdefault(source.casefold(), []).append(
                    {
                        "category": category,
                        "source": source,
                        "target": _clean_text(getattr(entry, "target", "")),
                        "notes": _clean_text(getattr(entry, "notes", "")),
                    }
                )
    return matches


def _collision_status(existing_entries: list[dict]) -> str:
    if not existing_entries:
        return "new"
    distinct_matches = {(entry["category"], entry["target"]) for entry in existing_entries}
    if len(distinct_matches) == 1:
        return "existing"
    return "ambiguous"


def _normalize_source(value) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = _WHITESPACE_RE.sub(" ", text)
    text = text.strip(" \t\r\n.,:;!?()[]{}\"'")
    return text.strip()


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_useful_term(source: str, origin: str) -> bool:
    if not source:
        return False
    folded = source.casefold()
    is_high_confidence_origin = origin in {"cast", "character", "title", "name", "show_title", "original_title"}
    if folded in _NOISE_TERMS and (not is_high_confidence_origin or len(folded) == 1):
        return False
    letters = [char for char in source if char.isalpha()]
    if len(letters) <= 2 and not is_high_confidence_origin:
        return False
    return True
