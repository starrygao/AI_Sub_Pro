"""Per-project KB CRUD endpoints (v2). Legacy /api/knowledge GET/POST remains in settings.py."""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StrictInt

from app.engines.knowledge import KnowledgeBase, _get_singleton, invalidate_translator_kb
from app.engines.kb_models import ProjectKb, TermEntry, StyleNotes
from app.engines.kb_suggestions import (
    extract_kb_suggestions,
    load_suggestions,
    save_suggestions,
    suggest_kb_entries,
    update_suggestion_status,
)
from app.utils.project_store import atomic_write_json, project_dir, validate_pid
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


def _validate_kb_key_or_http(key: str) -> str:
    if not key:
        raise HTTPException(status_code=400, detail="key must not be empty")
    try:
        validate_pid(key)
    except ValueError:
        raise HTTPException(status_code=400, detail="key must be path-safe")
    return key


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


def _clean_source_list(sources: list) -> list[str]:
    cleaned_sources = []
    seen = set()
    for source in sources:
        cleaned = _clean_text(source)
        if not cleaned:
            continue
        folded = cleaned.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        cleaned_sources.append(cleaned)
    return cleaned_sources


def _load_rejected_sources(pdir) -> list[str]:
    path = pdir / "kb_suggestion_decisions.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    raw_sources = data.get("rejected_sources", [])
    if not isinstance(raw_sources, list):
        return []
    return _clean_source_list(raw_sources)


def _merge_rejected_sources(existing_sources: list[str], new_sources: list[str]) -> list[str]:
    merged = _clean_source_list(existing_sources)
    seen = {source.casefold() for source in merged}
    for source in _clean_source_list(new_sources):
        folded = source.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        merged.append(source)
    return merged


def _normalize_usage_trace(data: dict) -> dict:
    normalized = dict(data)
    project = normalized.get("project")
    matches = normalized.get("matches")
    normalized["project"] = project if isinstance(project, dict) else {}
    normalized["matches"] = [
        item for item in matches
        if isinstance(item, dict)
    ] if isinstance(matches, list) else []
    return normalized


def _project_suggestions_path(pdir) -> object:
    return pdir / "kb_suggestions.json"


def _kb_key_for_project(pid: str, project: dict) -> str:
    import re

    raw = project.get("show_title") or project.get("name") or pid
    key = _clean_text(raw) if isinstance(raw, str) else ""
    if not key:
        return pid
    key = re.sub(r"[^A-Za-z0-9_-]+", "-", key).strip("-").lower()
    return key[:64] or pid


def _append_term_once(entries: list[TermEntry], source: str, target: str, notes: str = "") -> None:
    folded = _clean_text(source).casefold()
    if not folded or not _clean_text(target):
        return
    for entry in entries:
        if _clean_text(entry.source).casefold() == folded:
            return
    entries.append(TermEntry(source=_clean_text(source), target=_clean_text(target), notes=_clean_text(notes)))


def _accept_status_suggestion_into_kb(pid: str, project: dict, suggestion) -> None:
    if not _clean_text(getattr(suggestion, "target", "")):
        return
    key = _kb_key_for_project(pid, project)
    kb_store = _get_kb()
    proj = kb_store.get_project(key)
    if proj is None:
        proj = ProjectKb(
            show_title=_clean_text(project.get("show_title") or project.get("name") or ""),
            tmdb_id=project.get("tmdb_id") if isinstance(project.get("tmdb_id"), int) else None,
        )

    category = _clean_text(getattr(suggestion, "category", "")).casefold()
    if category == "characters":
        _append_term_once(proj.characters, suggestion.source, suggestion.target, suggestion.notes)
    elif category == "places":
        _append_term_once(proj.places, suggestion.source, suggestion.target, suggestion.notes)
    elif category == "brands":
        _append_term_once(proj.brands, suggestion.source, suggestion.target, suggestion.notes)
    else:
        _append_term_once(proj.slang, suggestion.source, suggestion.target, suggestion.notes)

    kb_store.put_project(key, proj)
    _invalidate_translator_kb()


@router.get("/projects")
def list_kb_projects():
    return {"projects": [
        {"key": k, "show_title": p.show_title, "tmdb_id": p.tmdb_id}
        for k, p in _get_kb().list_projects().items()
    ]}


@router.get("/projects/{pid}/suggestions")
def get_kb_project_suggestions(pid: str):
    pdir, project = _load_project_or_http(pid)
    persisted = load_suggestions(_project_suggestions_path(pdir))
    if persisted:
        return {
            "project_id": pid,
            "suggestions": [item.to_dict() for item in persisted],
        }
    subtitles = _subtitle_dicts_for_project(pdir)
    existing_kb = _get_kb().select_for_project(project)
    suggestions = suggest_kb_entries(project, subtitles, existing_kb)
    rejected = {source.casefold() for source in _load_rejected_sources(pdir)}
    if rejected:
        suggestions = [
            item for item in suggestions
            if _clean_text(getattr(item, "source", "")).casefold() not in rejected
        ]
    return {
        "project_id": pid,
        "suggestions": [item.to_dict() for item in suggestions],
    }


@router.post("/projects/{pid}/suggestions/generate")
def generate_kb_project_suggestions(pid: str):
    pdir, project = _load_project_or_http(pid)
    subtitles = _subtitle_dicts_for_project(pdir)
    existing_kb = _get_kb().select_for_project(project)
    suggestions = extract_kb_suggestions(project, subtitles, existing_kb)
    save_suggestions(_project_suggestions_path(pdir), suggestions)
    return {
        "project_id": pid,
        "suggestions": [item.to_dict() for item in suggestions],
    }


@router.post("/projects/{pid}/suggestions/{suggestion_id}/status")
def update_kb_project_suggestion_status(pid: str, suggestion_id: str, body: SuggestionStatusIn):
    pdir, project = _load_project_or_http(pid)
    try:
        suggestion = update_suggestion_status(
            _project_suggestions_path(pdir),
            suggestion_id,
            body.status,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid suggestion status")
    except KeyError:
        raise HTTPException(status_code=404, detail="suggestion not found")
    if suggestion.status == "accepted":
        _accept_status_suggestion_into_kb(pid, project, suggestion)
    return {"ok": True, "suggestion": suggestion.to_dict()}


@router.get("/projects/{pid}/usage-trace")
def get_kb_project_usage_trace(pid: str):
    pdir, _project = _load_project_or_http(pid)
    trace_path = pdir / "kb_usage_trace.json"
    if not trace_path.is_file():
        return {"project": {}, "matches": []}

    try:
        data = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="KB usage trace file is invalid")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="KB usage trace file is invalid")
    return _normalize_usage_trace(data)


@router.post("/projects/{pid}/suggestions/accept")
def accept_kb_project_suggestions(pid: str, body: SuggestionAcceptIn):
    _load_project_or_http(pid)
    key = _validate_kb_key_or_http(_clean_text(body.key))
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
    rejected_sources = _merge_rejected_sources(
        _load_rejected_sources(pdir),
        body.sources,
    )

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
