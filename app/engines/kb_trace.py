"""Knowledge-base usage trace helpers."""
from pathlib import Path
from typing import Any

from app.engines.kb_models import ProjectKb
from app.utils.project_store import atomic_write_json


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

    for rule in kb.style_notes.rules:
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
