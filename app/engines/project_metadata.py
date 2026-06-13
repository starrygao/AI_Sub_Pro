"""Project-level content metadata inference and prompt helpers."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


CONTENT_TYPE_OPTIONS = (
    "auto",
    "movie",
    "series",
    "documentary",
    "interview",
    "academic_lecture",
    "technical_tutorial",
    "legal_adult",
    "other",
)

CONTENT_TYPE_LABELS = {
    "auto": "auto",
    "movie": "movie",
    "series": "series",
    "documentary": "documentary",
    "interview": "interview",
    "academic_lecture": "academic lecture",
    "technical_tutorial": "technical tutorial",
    "legal_adult": "legal adult content",
    "other": "other",
}

_ACADEMIC_FIELD_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "computer science",
        (
            "cs229",
            "computer science",
            "machine learning",
            "deep learning",
            "algorithm",
            "algorithms",
            "programming",
            "neural",
            "transformer",
            "gradient descent",
        ),
    ),
    ("physics", ("physics", "quantum", "relativity", "mechanics", "thermodynamics")),
    (
        "mathematics",
        (
            "math",
            "mathematics",
            "calculus",
            "algebra",
            "geometry",
            "probability",
            "statistics",
        ),
    ),
    ("biology", ("biology", "genetics", "genome", "cell", "evolution")),
    ("medicine", ("medicine", "medical", "clinical", "neuroscience", "patient")),
    ("economics", ("economics", "economy", "macroeconomics", "microeconomics", "causal inference")),
    ("law", ("law", "legal", "jurisprudence")),
)

_ACADEMIC_HINTS = (
    "lecture",
    "seminar",
    "colloquium",
    "keynote",
    "conference talk",
    "research talk",
    "paper",
    "university",
    "course",
    "lesson",
    "mit",
    "stanford",
    "yale",
    "harvard",
    "coursera",
    "edx",
    "cs229",
)

_TECHNICAL_HINTS = (
    "tutorial",
    "how to",
    "how-to",
    "coding",
    "programming",
    "developer",
    "workshop",
)

_TEXT_LIMITS = {
    "academic_field": 80,
    "content_notes": 1200,
    "manual_terms": 2400,
    "metadata_source": 40,
    "source_title": 160,
    "source_uploader": 160,
    "source_channel": 160,
    "source_language": 32,
    "subtitle_source": 40,
    "native_subtitle_language": 32,
}


def _clean_text(value: Any, *, limit: int | None = None) -> str:
    text = value.strip() if isinstance(value, str) else ""
    text = re.sub(r"\s+", " ", text) if "\n" not in text else text.strip()
    if limit is not None:
        return text[:limit]
    return text


def normalize_content_type(value: Any) -> str:
    text = value.strip().casefold() if isinstance(value, str) else ""
    return text if text in CONTENT_TYPE_OPTIONS else "auto"


def normalize_project_metadata(meta_info: dict) -> dict:
    meta = dict(meta_info) if isinstance(meta_info, dict) else {}
    meta["content_type"] = normalize_content_type(meta.get("content_type"))
    for field, limit in _TEXT_LIMITS.items():
        meta[field] = _clean_text(meta.get(field), limit=limit)
    return meta


def _filename_blob(name: str) -> str:
    stem = Path(str(name or "")).stem
    text = re.sub(r"[._\-\[\]()]+", " ", stem)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _contains_any(blob: str, needles: tuple[str, ...]) -> bool:
    return any(needle in blob for needle in needles)


def _infer_academic_field(blob: str) -> str:
    for field, keywords in _ACADEMIC_FIELD_KEYWORDS:
        if _contains_any(blob, keywords):
            return field
    return ""


def infer_content_metadata_from_filename(name: str) -> dict:
    blob = _filename_blob(name)
    if not blob:
        return {
            "content_type": "auto",
            "academic_field": "",
            "metadata_source": "",
        }

    academic_field = _infer_academic_field(blob)
    if academic_field or _contains_any(blob, _ACADEMIC_HINTS):
        return {
            "content_type": "academic_lecture",
            "academic_field": academic_field,
            "metadata_source": "filename",
        }

    if _contains_any(blob, _TECHNICAL_HINTS):
        return {
            "content_type": "technical_tutorial",
            "academic_field": "",
            "metadata_source": "filename",
        }

    return {
        "content_type": "auto",
        "academic_field": "",
        "metadata_source": "",
    }


def should_skip_tmdb_enrichment(meta_info: dict) -> bool:
    content_type = normalize_content_type((meta_info or {}).get("content_type"))
    return content_type in {"academic_lecture", "technical_tutorial", "legal_adult", "other"}


def manual_term_pairs(meta_info: dict) -> list[tuple[str, str]]:
    raw = (meta_info or {}).get("manual_terms")
    if not isinstance(raw, str) or not raw.strip():
        return []
    pairs: list[tuple[str, str]] = []
    seen = set()
    for line in raw.splitlines():
        text = line.strip()
        if not text:
            continue
        source = target = ""
        for delimiter in ("->", "=>", "=", ":", "：", "→"):
            if delimiter in text:
                left, right = text.split(delimiter, 1)
                source = left.strip()
                target = right.strip()
                break
        if not source or not target:
            continue
        key = (source.casefold(), target)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((source[:120], target[:120]))
        if len(pairs) >= 80:
            break
    return pairs


def build_project_metadata_prompt_snippet(meta_info: dict) -> tuple[str, list[dict]]:
    raw_meta = meta_info if isinstance(meta_info, dict) else {}
    meta = normalize_project_metadata(raw_meta)
    content_type = meta["content_type"]
    academic_field = meta.get("academic_field", "")
    notes = meta.get("content_notes", "")
    source_title = meta.get("source_title", "")
    source_uploader = meta.get("source_uploader", "")
    source_channel = meta.get("source_channel", "")
    source_language = meta.get("source_language", "")
    subtitle_source = meta.get("subtitle_source", "")
    native_subtitle_language = meta.get("native_subtitle_language", "")
    source_has_subtitles = bool(raw_meta.get("source_has_subtitles"))
    terms = manual_term_pairs(raw_meta)

    lines: list[str] = []
    hits: list[dict] = []
    has_source_metadata = bool(
        source_title
        or source_uploader
        or source_channel
        or source_language
        or subtitle_source
        or native_subtitle_language
        or source_has_subtitles
    )
    has_metadata = content_type != "auto" or bool(academic_field or notes) or has_source_metadata
    if has_metadata:
        lines.append("Project content metadata (user/file supplied; higher priority than generic content profiles):")
        if content_type != "auto":
            lines.append(f"- Content type: {CONTENT_TYPE_LABELS.get(content_type, content_type)}")
        if academic_field:
            lines.append(f"- Academic field: {academic_field}")
        if notes:
            lines.append(f"- Notes: {notes}")
        if source_title:
            lines.append(f"- Source title: {source_title}")
        if source_uploader:
            lines.append(f"- Source uploader: {source_uploader}")
        if source_channel and source_channel != source_uploader:
            lines.append(f"- Source channel: {source_channel}")
        if source_language:
            lines.append(f"- Source language: {source_language}")
        if native_subtitle_language:
            lines.append(f"- Native subtitle language: {native_subtitle_language}")
        elif subtitle_source:
            lines.append(f"- Subtitle source: {subtitle_source}")
        elif source_has_subtitles:
            lines.append("- Source subtitles: available")
        hits.append({
            "id": "project_content_metadata",
            "scope": "project_metadata",
            "content_type": content_type,
            "academic_field": academic_field,
            "source_title": source_title,
        })

    if terms:
        if not lines:
            lines.append("Project content metadata (user/file supplied; higher priority than generic content profiles):")
        lines.append("Manual terminology (strict):")
        for source, target in terms:
            lines.append(f"- {source} -> {target}")
        hits.extend({
            "id": f"manual_term:{source.casefold()}",
            "scope": "manual_terms",
            "source": source,
            "target": target,
        } for source, target in terms)

    return "\n".join(lines), hits
