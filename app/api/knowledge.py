"""Per-project KB CRUD endpoints (v2). Legacy /api/knowledge GET/POST remains in settings.py."""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StrictInt

from app.engines.knowledge import KnowledgeBase, _get_singleton, invalidate_translator_kb
from app.engines.kb_models import ProjectKb, TermEntry, StyleNotes

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class TermEntryIn(BaseModel):
    source: str
    target: str
    notes: str = ""


class StyleNotesIn(BaseModel):
    tone: str = ""
    perspective: str = ""
    rules: List[str] = Field(default_factory=list)


class ProjectKbIn(BaseModel):
    key: str
    show_title: str = ""
    tmdb_id: Optional[StrictInt] = None
    characters: List[TermEntryIn] = Field(default_factory=list)
    places: List[TermEntryIn] = Field(default_factory=list)
    brands: List[TermEntryIn] = Field(default_factory=list)
    slang: List[TermEntryIn] = Field(default_factory=list)
    style_notes: StyleNotesIn = Field(default_factory=StyleNotesIn)


def _get_kb() -> KnowledgeBase:
    """Return the shared singleton (lazy-loaded)."""
    return _get_singleton()


# Backward-compatible alias — the canonical helper now lives in
# `app.engines.knowledge.invalidate_translator_kb` and is shared with the
# legacy `POST /api/knowledge` route in `app/api/settings.py`.
_invalidate_translator_kb = invalidate_translator_kb


def _clean_text(value: str) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_terms(items: List[TermEntryIn]) -> List[TermEntry]:
    terms = []
    for item in items:
        source = _clean_text(item.source)
        target = _clean_text(item.target)
        if not source or not target:
            continue
        terms.append(TermEntry(
            source=source,
            target=target,
            notes=_clean_text(item.notes),
        ))
    return terms


@router.get("/projects")
def list_kb_projects():
    return {"projects": [
        {"key": k, "show_title": p.show_title, "tmdb_id": p.tmdb_id}
        for k, p in _get_kb().list_projects().items()
    ]}


@router.get("/projects/{key}")
def get_kb_project(key: str):
    p = _get_kb().get_project(key)
    if p is None:
        raise HTTPException(status_code=404, detail="project KB not found")
    return p.to_dict()


@router.put("/projects/{key}")
def put_kb_project(key: str, body: ProjectKbIn):
    if not _clean_text(key) or key != key.strip():
        raise HTTPException(status_code=400, detail="key must not be empty")
    if body.key != key:
        raise HTTPException(status_code=400, detail="body key must match path key")
    if body.tmdb_id is not None and body.tmdb_id < 1:
        raise HTTPException(status_code=400, detail="tmdb_id must be positive")

    proj = ProjectKb(
        show_title=_clean_text(body.show_title),
        tmdb_id=body.tmdb_id,
        characters=_clean_terms(body.characters),
        places=_clean_terms(body.places),
        brands=_clean_terms(body.brands),
        slang=_clean_terms(body.slang),
        style_notes=StyleNotes(
            tone=_clean_text(body.style_notes.tone),
            perspective=_clean_text(body.style_notes.perspective),
            rules=[r for r in (_clean_text(rule) for rule in body.style_notes.rules) if r],
        ),
    )
    _get_kb().put_project(key, proj)
    _invalidate_translator_kb()
    return {"ok": True}


@router.delete("/projects/{key}")
def delete_kb_project(key: str):
    removed = _get_kb().delete_project_and_save(key)
    if not removed:
        raise HTTPException(status_code=404, detail="not found")
    _invalidate_translator_kb()
    return {"ok": True}
