"""Deterministic translation quality metrics."""
from __future__ import annotations

import re
from typing import Any

from app.evaluation.corpus import CorpusCase


_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _by_id(blocks: list[dict[str, str]], text_key: str) -> dict[str, str]:
    result = {}
    for block in blocks:
        block_id = str(block.get("id", "")).strip()
        if block_id:
            value = block.get(text_key, "")
            result[block_id] = value if isinstance(value, str) else ""
    return result


def _tags(text: str) -> list[str]:
    return _TAG_RE.findall(text if isinstance(text, str) else "")


def _round(value: float) -> float:
    return round(value, 4)


def terminology_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    combined = "\n".join(candidate_by_id.values())
    hits = []
    misses = []
    for term in case.expected_terms:
        target = term["target"]
        if target and target in combined:
            hits.append(term)
        else:
            misses.append(term)
    total = len(case.expected_terms)
    return {
        "hit_count": len(hits),
        "total": total,
        "hit_rate": _round(len(hits) / total) if total else 1.0,
        "misses": misses,
    }


def missing_translation_score(candidate_by_id: dict[str, str]) -> dict[str, Any]:
    missing_ids = [block_id for block_id, text in candidate_by_id.items() if not text.strip()]
    total = len(candidate_by_id)
    return {
        "missing_ids": missing_ids,
        "missing_count": len(missing_ids),
        "total": total,
        "rate": _round(len(missing_ids) / total) if total else 0.0,
    }


def row_alignment_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    source_ids = {str(block["id"]) for block in case.source_blocks}
    candidate_ids = set(candidate_by_id)
    missing = sorted(source_ids - candidate_ids)
    extra = sorted(candidate_ids - source_ids)
    aligned = len(source_ids) - len(missing)
    return {
        "source_count": len(source_ids),
        "candidate_count": len(candidate_ids),
        "missing_ids": missing,
        "extra_ids": extra,
        "rate": _round(aligned / len(source_ids)) if source_ids else 1.0,
    }


def format_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    source_by_id = _by_id(case.source_blocks, "text")
    broken = []
    for block_id, source_text in source_by_id.items():
        expected_tags = _tags(source_text)
        if expected_tags and _tags(candidate_by_id.get(block_id, "")) != expected_tags:
            broken.append(block_id)
    total_tagged = sum(1 for text in source_by_id.values() if _tags(text))
    return {
        "broken_ids": broken,
        "tagged_count": total_tagged,
        "breakage_rate": _round(len(broken) / total_tagged) if total_tagged else 0.0,
    }


def evaluate_case(case: CorpusCase) -> dict[str, Any]:
    candidate_by_id = _by_id(case.candidate_blocks, "translation")
    return {
        "case_id": case.id,
        "tags": list(case.tags),
        "terminology": terminology_score(case, candidate_by_id),
        "missing_translation": missing_translation_score(candidate_by_id),
        "row_alignment": row_alignment_score(case, candidate_by_id),
        "format": format_score(case, candidate_by_id),
    }
