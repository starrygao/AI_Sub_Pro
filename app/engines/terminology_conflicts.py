"""Detect conflicting terminology guidance across KB, memory, phrases, and curated terms."""
from __future__ import annotations

import re
from typing import Any


_SCOPE_PRIORITY = {
    "project": 0,
    "curated_domain": 1,
    "translation_memory": 2,
    "phrase_library": 3,
}


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalize_source(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _normalize_target(value: str) -> str:
    return re.sub(r"\s+", "", value.strip()).casefold()


def _project_entries(project_kb) -> list[dict]:
    if project_kb is None:
        return []
    entries: list[dict] = []
    for category in ("characters", "places", "brands", "slang"):
        for entry in getattr(project_kb, category, []) or []:
            source = _clean_text(getattr(entry, "source", ""))
            target = _clean_text(getattr(entry, "target", ""))
            if source and target:
                entries.append({
                    "source": source,
                    "target": target,
                    "scope": "project",
                    "category": category,
                })
    return entries


def _trace_entries(trace: dict | None) -> list[dict]:
    if not isinstance(trace, dict):
        return []
    entries: list[dict] = []
    for hit in trace.get("kb_hits", []) or []:
        if not isinstance(hit, dict):
            continue
        source = _clean_text(hit.get("source"))
        target = _clean_text(hit.get("target"))
        if source and target:
            entries.append({
                "source": source,
                "target": target,
                "scope": _clean_text(hit.get("scope")) or "curated_domain",
                "category": "kb_hits",
            })
    for hit in trace.get("memory_hits", []) or []:
        if not isinstance(hit, dict):
            continue
        source = _clean_text(hit.get("source_text"))
        target = _clean_text(hit.get("final_translation"))
        if source and target:
            entries.append({
                "source": source,
                "target": target,
                "scope": "translation_memory",
                "category": "memory_hits",
            })
    for hit in trace.get("phrase_hits", []) or []:
        if not isinstance(hit, dict):
            continue
        source = _clean_text(hit.get("source_text"))
        target = _clean_text(hit.get("target_text"))
        if source and target:
            entries.append({
                "source": source,
                "target": target,
                "scope": "phrase_library",
                "category": "phrase_hits",
                "pack_id": _clean_text(hit.get("pack_id")),
            })
    return entries


def _sort_key(entry: dict) -> tuple[int, str, str]:
    scope = _clean_text(entry.get("scope"))
    return (_SCOPE_PRIORITY.get(scope, 99), scope, _clean_text(entry.get("target")))


def collect_terminology_conflicts(*, project_kb=None, trace: dict | None = None) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    display_source: dict[str, str] = {}
    for entry in [*_project_entries(project_kb), *_trace_entries(trace)]:
        source = _clean_text(entry.get("source"))
        target = _clean_text(entry.get("target"))
        if not source or not target:
            continue
        key = _normalize_source(source)
        grouped.setdefault(key, []).append(entry)
        display_source.setdefault(key, source)

    conflicts: list[dict] = []
    for source_key, entries in grouped.items():
        targets: dict[str, dict] = {}
        for entry in entries:
            target_key = _normalize_target(_clean_text(entry.get("target")))
            if not target_key:
                continue
            existing = targets.get(target_key)
            if existing is None:
                targets[target_key] = {
                    "target": _clean_text(entry.get("target")),
                    "scopes": sorted({_clean_text(entry.get("scope"))}),
                }
            else:
                existing["scopes"] = sorted({
                    *existing.get("scopes", []),
                    _clean_text(entry.get("scope")),
                })
        if len(targets) < 2:
            continue
        preferred = sorted(entries, key=_sort_key)[0]
        conflicts.append({
            "source": display_source[source_key],
            "preferred_target": _clean_text(preferred.get("target")),
            "preferred_scope": _clean_text(preferred.get("scope")),
            "targets": sorted(targets.values(), key=lambda item: item["target"]),
        })
    return sorted(conflicts, key=lambda item: item["source"].casefold())
