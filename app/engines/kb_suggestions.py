"""Project-local knowledge-base suggestion extraction and persistence."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from app.engines.kb_models import ProjectKb
from app.utils.project_store import atomic_write_json


_CAPITALIZED_SPAN_RE = re.compile(
    r"\b(?:Dr\.|Mr\.|Mrs\.|Ms\.)?\s*[A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+){0,4}"
)
_FALSE_POSITIVES = {
    "A",
    "An",
    "And",
    "But",
    "He",
    "Her",
    "His",
    "I",
    "If",
    "It",
    "She",
    "So",
    "The",
    "They",
    "This",
    "We",
    "What",
    "When",
    "Where",
    "Who",
    "Why",
    "You",
    "Yes",
    "No",
    "Okay",
    "Right",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
}
_PLACE_HINT_WORDS = {
    "Acres",
    "Avenue",
    "Bay",
    "Beach",
    "Center",
    "Centre",
    "Clinic",
    "Club",
    "Court",
    "Heights",
    "Hospital",
    "House",
    "Inn",
    "Lake",
    "Oaks",
    "Park",
    "Road",
    "Room",
    "School",
    "Street",
    "Tower",
    "Valley",
}
_PLACE_PREPOSITIONS = {"at", "in", "inside", "into", "near", "from", "to", "toward", "towards"}

_SPECIAL_TARGETS = {
    "Hudson Oaks": "哈德逊奥克斯",
    "Brilliant Minds": "绝妙心灵",
    "Dr. Pierce": "皮尔斯医生",
    "Oliver Wolf": "奥利弗·沃尔夫",
    "Wolf": "沃尔夫",
    "Sofia": "索菲亚",
}


@dataclass
class KbSuggestion:
    id: str
    type: str
    source: str
    target: str
    notes: str = ""
    confidence: float = 0.5
    evidence: List[str] = field(default_factory=list)
    status: str = "pending"
    collision: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "KbSuggestion":
        if not isinstance(value, dict):
            return cls(id="", type="phrase", source="", target="")
        evidence = value.get("evidence")
        return cls(
            id=_clean_text(value.get("id")),
            type=_clean_text(value.get("type")) or "phrase",
            source=_clean_text(value.get("source")),
            target=_clean_text(value.get("target")),
            notes=_clean_text(value.get("notes")),
            confidence=_clean_confidence(value.get("confidence")),
            evidence=[_clean_text(item) for item in evidence if _clean_text(item)]
            if isinstance(evidence, list)
            else [],
            status=_clean_status(value.get("status")),
            collision=_clean_text(value.get("collision")),
            created_at=_clean_text(value.get("created_at")),
        )


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_status(value) -> str:
    text = _clean_text(value)
    return text if text in {"pending", "accepted", "rejected"} else "pending"


def _clean_confidence(value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.5
    if parsed < 0:
        return 0.0
    if parsed > 1:
        return 1.0
    return parsed


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).strip("-")
    return text or "suggestion"


def _suggestion_id(kind: str, source: str) -> str:
    return f"{kind}:{_slug(source)}"


def _iter_text_blocks(blocks: Iterable) -> Iterable[tuple[str, str]]:
    for pos, block in enumerate(blocks or [], start=1):
        if isinstance(block, dict):
            text = _clean_text(block.get("text"))
            raw_index = block.get("index", pos)
        else:
            text = _clean_text(getattr(block, "text", ""))
            raw_index = getattr(block, "index", pos)
        if text:
            yield str(raw_index), text


def _candidate_type(source: str, text: str, match_start: int, metadata_names: set[str]) -> str:
    if source in metadata_names:
        return "character"
    stripped = source.replace("Dr. ", "").replace("Mr. ", "").replace("Mrs. ", "").replace("Ms. ", "")
    if source.startswith(("Dr. ", "Mr. ", "Mrs. ", "Ms. ")):
        return "person"
    words = stripped.split()
    if words and words[-1] in _PLACE_HINT_WORDS:
        return "place"
    prefix = text[:match_start].lower().split()
    if prefix and prefix[-1].strip(".,!?;:") in _PLACE_PREPOSITIONS and len(words) >= 2:
        return "place"
    if len(words) >= 2:
        return "person"
    return "phrase"


def _target_for(source: str, kind: str) -> str:
    if source in _SPECIAL_TARGETS:
        return _SPECIAL_TARGETS[source]
    if source.startswith("Dr. "):
        return f"{source[4:]}医生"
    return source


def _existing_terms(kb: Optional[ProjectKb]) -> tuple[set[str], set[str]]:
    if kb is None:
        return set(), set()
    entries = []
    for attr in ("characters", "places", "brands", "slang"):
        entries.extend(getattr(kb, attr, []) or [])
    sources = {_clean_text(getattr(entry, "source", "")) for entry in entries}
    targets = {_clean_text(getattr(entry, "target", "")) for entry in entries}
    return {s for s in sources if s}, {t for t in targets if t}


def _collision_for(source: str, target: str, kb: Optional[ProjectKb]) -> str:
    sources, targets = _existing_terms(kb)
    if source in sources:
        return "source_exists"
    if target and target in targets:
        return "target_exists"
    return ""


def _metadata_names(project: dict) -> set[str]:
    names = set()
    if not isinstance(project, dict):
        return names
    for key in ("show_title", "name", "original_title", "title"):
        value = _clean_text(project.get(key))
        if value:
            names.add(value)
    cast = project.get("cast")
    if isinstance(cast, list):
        for item in cast:
            if isinstance(item, str):
                name = _clean_text(item)
            elif isinstance(item, dict):
                name = _clean_text(item.get("character")) or _clean_text(item.get("name"))
            else:
                name = ""
            if name:
                names.add(name)
    return names


def extract_kb_suggestions(
    project: dict,
    blocks: Iterable,
    *,
    existing_kb: Optional[ProjectKb] = None,
) -> list[KbSuggestion]:
    """Extract explainable KB suggestions from project metadata and subtitles."""
    metadata_names = _metadata_names(project)
    candidates: dict[str, KbSuggestion] = {}

    for name in metadata_names:
        if name in _FALSE_POSITIVES:
            continue
        kind = "character" if len(name.split()) >= 2 else "phrase"
        target = _target_for(name, kind)
        item = KbSuggestion(
            id=_suggestion_id(kind, name),
            type=kind,
            source=name,
            target=target,
            confidence=0.7,
            evidence=["metadata"],
            collision=_collision_for(name, target, existing_kb),
        )
        candidates[item.source] = item

    for idx, text in _iter_text_blocks(blocks):
        for match in _CAPITALIZED_SPAN_RE.finditer(text):
            source = re.sub(r"\s+", " ", match.group(0)).strip(" -")
            if not source or source in _FALSE_POSITIVES:
                continue
            if len(source) == 1 or source.lower() == source:
                continue
            kind = _candidate_type(source, text, match.start(), metadata_names)
            if kind == "phrase" and len(source.split()) < 2 and source not in metadata_names:
                continue
            target = _target_for(source, kind)
            evidence = f"subtitle:{idx}"
            current = candidates.get(source)
            confidence = 0.8 if kind in {"place", "person", "character"} else 0.55
            if current is None:
                candidates[source] = KbSuggestion(
                    id=_suggestion_id(kind, source),
                    type=kind,
                    source=source,
                    target=target,
                    confidence=confidence,
                    evidence=[evidence],
                    collision=_collision_for(source, target, existing_kb),
                )
            else:
                if evidence not in current.evidence:
                    current.evidence.append(evidence)
                current.confidence = max(current.confidence, min(1.0, confidence + 0.05))
                if current.type == "phrase" and kind != "phrase":
                    current.type = kind
                    current.id = _suggestion_id(kind, source)

    return sorted(
        [item for item in candidates.values() if item.source and item.target],
        key=lambda item: (-item.confidence, item.type, item.source.lower()),
    )


def load_suggestions(path: Path) -> list[KbSuggestion]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = raw.get("suggestions") if isinstance(raw, dict) else []
    if not isinstance(items, list):
        return []
    suggestions = [KbSuggestion.from_dict(item) for item in items]
    return [item for item in suggestions if item.id and item.source and item.target]


def save_suggestions(path: Path, suggestions: list[KbSuggestion]) -> None:
    atomic_write_json(
        Path(path),
        {"version": 1, "suggestions": [item.to_dict() for item in suggestions]},
    )


def update_suggestion_status(path: Path, suggestion_id: str, status: str) -> KbSuggestion:
    clean_status = _clean_status(status)
    if clean_status != status:
        raise ValueError("invalid suggestion status")
    suggestions = load_suggestions(path)
    for item in suggestions:
        if item.id == suggestion_id:
            item.status = clean_status
            save_suggestions(path, suggestions)
            return item
    raise KeyError(suggestion_id)
