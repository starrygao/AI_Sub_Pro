"""Knowledge-base usage trace helpers."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.engines.kb_models import ProjectKb
from app.utils.project_store import atomic_write_json


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


def trace_for_project_kb(kb: ProjectKb | None) -> dict[str, Any]:
    """Build a serializable trace for the KB entries available to translation."""
    if kb is None:
        return {"project": {}, "matches": []}

    matches: list[dict[str, Any]] = []
    for category in ("characters", "places", "brands", "slang"):
        entries = getattr(kb, category, [])
        for entry in entries:
            matches.append({
                "category": category,
                "source": getattr(entry, "source", ""),
                "target": getattr(entry, "target", ""),
                "notes": getattr(entry, "notes", ""),
                "scope": "project",
            })

    style = kb.style_notes
    if style.tone:
        matches.append({
            "category": "style_notes",
            "source": style.tone,
            "target": "",
            "notes": "tone",
            "scope": "style",
        })
    if style.perspective:
        matches.append({
            "category": "style_notes",
            "source": style.perspective,
            "target": "",
            "notes": "perspective",
            "scope": "style",
        })
    for rule in style.rules:
        matches.append({
            "category": "style_notes",
            "source": rule,
            "target": "",
            "notes": "style rule",
            "scope": "style",
        })

    return {
        "project": {
            "show_title": kb.show_title,
            "tmdb_id": kb.tmdb_id,
        },
        "matches": matches,
    }


def write_kb_usage_trace(project_dir: Path, trace: dict[str, Any]) -> None:
    """Persist the KB usage trace inside a project directory."""
    atomic_write_json(Path(project_dir) / "kb_usage_trace.json", trace)
