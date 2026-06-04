"""Deterministic metrics for golden translation corpus outputs."""
from __future__ import annotations

import re

from app.evaluation.corpus import GoldenCorpus


_ENGLISH_RE = re.compile(r"[A-Za-z]{3,}")


def _is_chinese_target(value: str) -> bool:
    text = (value or "").strip().lower()
    return text in {"zh-cn", "zh", "chs", "简体中文", "中文"}


def _candidate_map(case) -> dict[str, str]:
    return {
        str(block.get("id")): (block.get("translation") or "")
        for block in case.candidate_blocks
        if isinstance(block, dict)
    }


def evaluate_case(case, *, max_chars: int = 32) -> dict:
    candidates = _candidate_map(case)
    source_ids = [str(block.get("id")) for block in case.source_blocks]
    missing = 0
    english_residue = 0
    length_violations = 0
    term_hits = 0
    term_total = 0

    source_text = "\n".join(block.get("text", "") for block in case.source_blocks)
    translation_text = "\n".join(candidates.values())
    for source_id in source_ids:
        translation = candidates.get(source_id, "")
        if not translation.strip():
            missing += 1
        if _is_chinese_target(case.target_language) and _ENGLISH_RE.search(translation):
            english_residue += 1
        if max_chars > 0 and len(re.sub(r"\s+", "", translation)) > max_chars:
            length_violations += 1

    for term in case.expected_terms:
        source = term.get("source", "")
        target = term.get("target", "")
        if not source or not target:
            continue
        if source.lower() not in source_text.lower():
            continue
        term_total += 1
        if target in translation_text:
            term_hits += 1

    aligned = len(candidates) == len(source_ids) and set(candidates) == set(source_ids)
    return {
        "id": case.id,
        "tags": list(case.tags),
        "missing_translation_count": missing,
        "english_residue_count": english_residue,
        "length_violation_count": length_violations,
        "terminology_hits": term_hits,
        "terminology_total": term_total,
        "alignment_ok": aligned,
    }


def evaluate_corpus(corpus: GoldenCorpus, *, max_chars: int = 32) -> dict:
    cases = [evaluate_case(case, max_chars=max_chars) for case in corpus.cases]
    term_hits = sum(case["terminology_hits"] for case in cases)
    term_total = sum(case["terminology_total"] for case in cases)
    aligned = sum(1 for case in cases if case["alignment_ok"])
    case_count = len(cases)
    metrics = {
        "terminology_hit_rate": (term_hits / term_total) if term_total else 1.0,
        "missing_translation_count": sum(case["missing_translation_count"] for case in cases),
        "english_residue_count": sum(case["english_residue_count"] for case in cases),
        "length_violation_count": sum(case["length_violation_count"] for case in cases),
        "alignment_rate": (aligned / case_count) if case_count else 1.0,
    }
    return {
        "version": corpus.version,
        "case_count": case_count,
        "metrics": metrics,
        "cases": cases,
    }
