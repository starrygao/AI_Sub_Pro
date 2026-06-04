"""Per-project KB CRUD endpoints (v2). Legacy /api/knowledge GET/POST remains in settings.py."""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StrictInt

from app.engines.knowledge import KnowledgeBase, _get_singleton, invalidate_translator_kb
from app.engines.kb_models import ProjectKb, TermEntry, StyleNotes
from app.utils.project_store import load_project as _ps_load_project, project_dir as _ps_project_dir

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


class SuggestionStatusIn(BaseModel):
    status: str


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


def _project_suggestions_path(pid: str):
    return _ps_project_dir(pid) / "kb_suggestions.json"


def _load_project_for_suggestions(pid: str) -> dict:
    try:
        return _ps_load_project(pid)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid project id")


def _load_project_subtitle_blocks(pid: str) -> list:
    from app.utils.srt import parse_srt_file

    pdir = _ps_project_dir(pid)
    for name in ("filtered.srt", "raw.srt", "native.srt"):
        path = pdir / name
        if path.exists():
            try:
                return parse_srt_file(str(path))
            except Exception as e:
                log.warning("could not parse subtitles for suggestion extraction %s/%s: %s",
                            pid, name, e)
                return []
    return []


def _kb_key_for_project(pid: str, project: dict) -> str:
    raw = project.get("show_title") or project.get("name") or pid
    key = _clean_text(raw) if isinstance(raw, str) else ""
    if not key:
        return pid
    import re

    key = re.sub(r"[^A-Za-z0-9_-]+", "-", key).strip("-").lower()
    return key[:64] or pid


def _append_term_once(entries: list[TermEntry], source: str, target: str, notes: str = "") -> None:
    for entry in entries:
        if entry.source == source:
            return
    entries.append(TermEntry(source=source, target=target, notes=notes))


def _accept_suggestion_into_kb(pid: str, project: dict, suggestion) -> None:
    key = _kb_key_for_project(pid, project)
    kb = _get_kb()
    current = kb.get_project(key)
    if current is None:
        current = ProjectKb(
            show_title=_clean_text(project.get("show_title") or project.get("name") or ""),
            tmdb_id=project.get("tmdb_id") if isinstance(project.get("tmdb_id"), int) else None,
        )

    if suggestion.type in {"character", "person"}:
        _append_term_once(current.characters, suggestion.source, suggestion.target, suggestion.notes)
    elif suggestion.type == "place":
        _append_term_once(current.places, suggestion.source, suggestion.target, suggestion.notes)
    elif suggestion.type in {"organization", "title"}:
        _append_term_once(current.brands, suggestion.source, suggestion.target, suggestion.notes)
    elif suggestion.type == "style":
        if suggestion.notes and suggestion.notes not in current.style_notes.rules:
            current.style_notes.rules.append(suggestion.notes)
    else:
        _append_term_once(current.slang, suggestion.source, suggestion.target, suggestion.notes)

    kb.put_project(key, current)
    _invalidate_translator_kb()


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


@router.get("/projects/{pid}/suggestions")
def list_project_suggestions(pid: str):
    from app.engines.kb_suggestions import load_suggestions

    _load_project_for_suggestions(pid)
    return {"suggestions": [s.to_dict() for s in load_suggestions(_project_suggestions_path(pid))]}


@router.post("/projects/{pid}/suggestions/generate")
def generate_project_suggestions(pid: str):
    from app.engines.kb_suggestions import extract_kb_suggestions, save_suggestions

    project = _load_project_for_suggestions(pid)
    blocks = _load_project_subtitle_blocks(pid)
    existing_kb = _get_kb().select_for_project(project)
    suggestions = extract_kb_suggestions(project, blocks, existing_kb=existing_kb)
    save_suggestions(_project_suggestions_path(pid), suggestions)
    return {"suggestions": [s.to_dict() for s in suggestions]}


@router.post("/projects/{pid}/suggestions/{suggestion_id}/status")
def update_project_suggestion_status(pid: str, suggestion_id: str, body: SuggestionStatusIn):
    from app.engines.kb_suggestions import update_suggestion_status

    project = _load_project_for_suggestions(pid)
    try:
        suggestion = update_suggestion_status(
            _project_suggestions_path(pid),
            suggestion_id,
            body.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="suggestion not found")

    if suggestion.status == "accepted":
        _accept_suggestion_into_kb(pid, project, suggestion)
    return {"suggestion": suggestion.to_dict()}
