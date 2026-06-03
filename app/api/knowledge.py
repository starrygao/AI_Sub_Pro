"""Per-project KB CRUD endpoints (v2). Legacy /api/knowledge GET/POST remains in settings.py."""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StrictInt

from app.engines.knowledge import KnowledgeBase, _get_singleton, invalidate_translator_kb
from app.engines.kb_models import ProjectKb, TermEntry, StyleNotes
from app.engines.kb_suggestions import suggest_kb_entries
from app.utils.project_store import atomic_write_json, project_dir
from app.utils.srt import parse_srt_file

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


class SuggestionAcceptEntryIn(BaseModel):
    source: str
    target: str = ""
    category: str
    notes: str = ""


class SuggestionAcceptIn(BaseModel):
    key: str
    show_title: str = ""
    tmdb_id: Optional[StrictInt] = None
    entries: List[SuggestionAcceptEntryIn] = Field(default_factory=list)


class SuggestionRejectIn(BaseModel):
    sources: List[str] = Field(default_factory=list)


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


def _append_term(target: list[TermEntry], entry: SuggestionAcceptEntryIn) -> None:
    source = _clean_text(entry.source)
    term_target = _clean_text(entry.target)
    if not source or not term_target:
        return

    existing_sources = {_clean_text(term.source).casefold() for term in target}
    if source.casefold() in existing_sources:
        return

    target.append(TermEntry(
        source=source,
        target=term_target,
        notes=_clean_text(entry.notes),
    ))


def _load_project_or_http(pid: str) -> tuple:
    try:
        pdir = project_dir(pid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project id")

    pfile = pdir / "project.json"
    if not pfile.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        project = json.loads(pfile.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Project file is invalid")
    except ValueError:
        raise HTTPException(status_code=400, detail="Project file is invalid")
    except OSError:
        raise HTTPException(status_code=400, detail="Project file is invalid")

    if not isinstance(project, dict):
        raise HTTPException(status_code=400, detail="Project file is invalid")
    return pdir, project


def _subtitle_dicts_for_project(pdir) -> list[dict]:
    for name in ("filtered.srt", "raw.srt", "native.srt"):
        path = pdir / name
        if not path.is_file():
            continue
        try:
            return [block.to_dict() for block in parse_srt_file(str(path))]
        except OSError as e:
            log.warning("failed to parse project SRT %s: %s", path, e)
            return []
    return []


@router.get("/projects")
def list_kb_projects():
    return {"projects": [
        {"key": k, "show_title": p.show_title, "tmdb_id": p.tmdb_id}
        for k, p in _get_kb().list_projects().items()
    ]}


@router.get("/projects/{pid}/suggestions")
def get_kb_project_suggestions(pid: str):
    pdir, project = _load_project_or_http(pid)
    subtitles = _subtitle_dicts_for_project(pdir)
    existing_kb = _get_kb().select_for_project(project)
    suggestions = suggest_kb_entries(project, subtitles, existing_kb)
    return {
        "project_id": pid,
        "suggestions": [item.to_dict() for item in suggestions],
    }


@router.post("/projects/{pid}/suggestions/accept")
def accept_kb_project_suggestions(pid: str, body: SuggestionAcceptIn):
    _load_project_or_http(pid)
    key = _clean_text(body.key)
    if not key:
        raise HTTPException(status_code=400, detail="key must not be empty")
    if body.tmdb_id is not None and body.tmdb_id < 1:
        raise HTTPException(status_code=400, detail="tmdb_id must be positive")

    kb_store = _get_kb()
    proj = kb_store.get_project(key) or ProjectKb()
    show_title = _clean_text(body.show_title)
    if show_title:
        proj.show_title = show_title
    if body.tmdb_id is not None:
        proj.tmdb_id = body.tmdb_id

    categories = {
        "characters": proj.characters,
        "places": proj.places,
        "brands": proj.brands,
        "slang": proj.slang,
    }
    accepted = 0
    for entry in body.entries:
        target = categories.get(_clean_text(entry.category).casefold())
        if target is None:
            continue
        before = len(target)
        _append_term(target, entry)
        accepted += len(target) - before

    kb_store.put_project(key, proj)
    _invalidate_translator_kb()
    return {"ok": True, "key": key, "accepted": accepted}


@router.post("/projects/{pid}/suggestions/reject")
def reject_kb_project_suggestions(pid: str, body: SuggestionRejectIn):
    pdir, _project = _load_project_or_http(pid)
    rejected_sources = []
    seen = set()
    for source in body.sources:
        cleaned = _clean_text(source)
        if not cleaned:
            continue
        folded = cleaned.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        rejected_sources.append(cleaned)

    atomic_write_json(pdir / "kb_suggestion_decisions.json", {
        "rejected_sources": rejected_sources,
    })
    return {"ok": True, "rejected": rejected_sources}


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
