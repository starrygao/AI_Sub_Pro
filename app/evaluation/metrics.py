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


def missing_translation_score(
    candidate_by_id: dict[str, str], source_ids: list[str] | None = None
) -> dict[str, Any]:
    missing_ids = [
        block_id for block_id, text in candidate_by_id.items() if not text.strip()
    ]
    if source_ids is None:
        source_missing_ids = []
        missing_count = len(missing_ids)
        total = len(candidate_by_id)
    else:
        source_missing_ids = [
            block_id
            for block_id in source_ids
            if not candidate_by_id.get(block_id, "").strip()
        ]
        missing_count = len(source_missing_ids)
        total = len(source_ids)
    return {
        "missing_ids": missing_ids,
        "source_missing_ids": source_missing_ids,
        "missing_count": missing_count,
        "source_missing_count": len(source_missing_ids),
        "candidate_missing_count": len(missing_ids),
        "total": total,
        "rate": _round(missing_count / total) if total else 0.0,
    }


def row_alignment_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    source_ids = {str(block["id"]) for block in case.source_blocks}
    candidate_ids = set(candidate_by_id)
    missing = sorted(source_ids - candidate_ids)
    extra = sorted(candidate_ids - source_ids)
    aligned = len(source_ids & candidate_ids)
    total_ids = len(source_ids | candidate_ids)
    return {
        "source_count": len(source_ids),
        "candidate_count": len(candidate_ids),
        "missing_ids": missing,
        "extra_ids": extra,
        "rate": _round(aligned / total_ids) if total_ids else 1.0,
    }


def format_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    source_by_id = _by_id(case.source_blocks, "text")
    broken = []
    for block_id, source_text in source_by_id.items():
        expected_tags = _tags(source_text)
        candidate_tags = _tags(candidate_by_id.get(block_id, ""))
        if candidate_tags != expected_tags:
            broken.append(block_id)
    total_tagged = sum(
        1
        for block_id, source_text in source_by_id.items()
        if _tags(source_text) or _tags(candidate_by_id.get(block_id, ""))
    )
    return {
        "broken_ids": broken,
        "tagged_count": total_tagged,
        "breakage_rate": _round(len(broken) / total_tagged) if total_tagged else 0.0,
    }


def evaluate_case(case: CorpusCase) -> dict[str, Any]:
    candidate_by_id = _by_id(case.candidate_blocks, "translation")
    source_ids = list(_by_id(case.source_blocks, "text"))
    return {
        "case_id": case.id,
        "tags": list(case.tags),
        "terminology": terminology_score(case, candidate_by_id),
        "missing_translation": missing_translation_score(candidate_by_id, source_ids),
        "row_alignment": row_alignment_score(case, candidate_by_id),
        "format": format_score(case, candidate_by_id),
    }
