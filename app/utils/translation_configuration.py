"""Deterministic identity for every translation-affecting input."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Optional


_AUTO = object()
_SECRET_KEY_PARTS = ("api_key", "apikey", "token", "secret", "password")


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {
            str(key): _safe_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not any(
                part in str(key).casefold()
                for part in _SECRET_KEY_PARTS
            )
        }
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if hasattr(value, "to_dict"):
        return _safe_json(value.to_dict())
    return str(value)


def _manual_terms(project: dict) -> list[dict]:
    from app.engines.project_metadata import manual_term_pairs

    return [
        {"source": source, "target": target}
        for source, target in manual_term_pairs(project)
    ]


def _style_profile(project: dict) -> dict:
    from app.engines.subtitle_style_profiles import (
        infer_subtitle_style_profile,
    )

    target = _clean_text(project.get("target_language")) or "简体中文"
    profile = infer_subtitle_style_profile(target, project)
    if profile is None:
        return {}
    return {
        "id": profile.id,
        "label": profile.label,
        "max_line_chars": profile.max_line_chars,
        "max_lines": profile.max_lines,
        "max_chars_per_second": profile.max_chars_per_second,
        "rules": list(profile.rules),
    }


def _selected_kb(project: dict) -> dict:
    try:
        from app.engines.knowledge import _get_singleton

        kb = _get_singleton().select_for_project(project)
    except Exception:
        kb = None
    return {
        "schema_version": 2,
        "selection": _safe_json(kb.to_dict()) if kb is not None else None,
    }


def _candidate_terms(project_path: Optional[Path]) -> list:
    if project_path is None:
        return []
    suggestions_path = Path(project_path) / "kb_suggestions.json"
    decisions_path = Path(project_path) / "kb_suggestion_decisions.json"
    values = []
    for path in (suggestions_path, decisions_path):
        if path.is_symlink() or not path.is_file():
            values.append(None)
            continue
        try:
            values.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            values.append({"invalid": True})
    return values


def translation_configuration_snapshot(
    project: dict,
    *,
    config: Optional[dict] = None,
    project_path: Optional[Path] = None,
    effective_kb: Any = _AUTO,
    candidate_terms: Any = _AUTO,
) -> dict:
    """Return the normalized, secret-free context consumed by translation."""
    source = project if isinstance(project, dict) else {}
    cfg = config if isinstance(config, dict) else {}
    translation_cfg = cfg.get("translation", {})
    if not isinstance(translation_cfg, dict):
        translation_cfg = {}
    mode = _clean_text(translation_cfg.get("quality_mode")).casefold()
    target_language = (
        _clean_text(source.get("target_language"))
        or _clean_text(translation_cfg.get("target_language"))
        or "简体中文"
    )
    kb_snapshot = (
        _selected_kb(source)
        if effective_kb is _AUTO
        else _safe_json(effective_kb)
    )
    candidates = (
        _candidate_terms(project_path)
        if candidate_terms is _AUTO
        else _safe_json(candidate_terms)
    )
    return {
        "schema_version": 1,
        "target_language": target_language,
        "manual_terms": _manual_terms(source),
        "content": {
            "content_type": _clean_text(source.get("content_type")) or "auto",
            "academic_field": _clean_text(source.get("academic_field")),
            "content_notes": _clean_text(source.get("content_notes")),
            "metadata_source": _clean_text(source.get("metadata_source")),
            "name": _clean_text(source.get("name")),
            "show_title": _clean_text(source.get("show_title")),
            "tmdb_id": (
                source.get("tmdb_id")
                if isinstance(source.get("tmdb_id"), int)
                and not isinstance(source.get("tmdb_id"), bool)
                else None
            ),
            "original_language": _clean_text(source.get("original_language")),
            "source_language": _clean_text(source.get("source_language")),
        },
        "style_profile": _style_profile({**source, "target_language": target_language}),
        "quality_policy": "strict" if mode == "professional" else "fast",
        "translation": _safe_json(translation_cfg),
        "providers": _safe_json(cfg.get("providers", {})),
        "effective_kb": kb_snapshot,
        "candidate_terms": candidates,
    }


def translation_configuration_hash(
    project: dict,
    *,
    config: Optional[dict] = None,
    project_path: Optional[Path] = None,
    effective_kb: Any = _AUTO,
    candidate_terms: Any = _AUTO,
) -> str:
    snapshot = translation_configuration_snapshot(
        project,
        config=config,
        project_path=project_path,
        effective_kb=effective_kb,
        candidate_terms=candidate_terms,
    )
    payload = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"

