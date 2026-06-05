"""Deterministic translation quality metrics."""
from __future__ import annotations

import re
from typing import Any

from app.evaluation.corpus import CorpusCase


_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_PROPER_NAME_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:['-][A-Za-z]+)*)(?:\s+(?:[A-Z][a-z]+(?:['-][A-Za-z]+)*)){1,}\b"
)
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")
_LEADING_NAME_STOPWORDS = {"A", "An", "The", "This", "That", "These", "Those"}
_COMMON_TITLE_PHRASES = {
    "Good Morning",
    "Good Afternoon",
    "Good Evening",
    "Good Night",
    "Thank You",
    "Excuse Me",
    "I Love You",
}
_COMMON_TITLE_WORDS = {
    "good",
    "morning",
    "afternoon",
    "evening",
    "night",
    "thank",
    "you",
    "excuse",
    "me",
    "please",
    "sorry",
    "hello",
    "hi",
    "welcome",
}
_SHORT_NAME_CONTEXT_CHARS = {
    "了",
    "到",
    "看",
    "见",
    "来",
    "跑",
    "走",
    "说",
    "在",
    "去",
    "是",
    "有",
    "会",
    "想",
    "要",
    "让",
    "把",
    "被",
    "很",
    "真",
    "太",
    "都",
    "也",
    "还",
    "又",
    "呢",
    "吗",
}


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


def _clean_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", _clean_text(text))


def _is_sentence_start(source_text: str, start: int) -> bool:
    if start <= 0:
        return True
    prefix = _clean_text(source_text)[:start].rstrip()
    if not prefix:
        return True
    return prefix[-1] in ".!?;:\n\r\"'()[]{}"


def _looks_like_common_title_phrase(source_text: str, start: int, name: str) -> bool:
    if name in _COMMON_TITLE_PHRASES:
        return True
    if not _is_sentence_start(source_text, start):
        return False
    tokens = [token.lower() for token in name.split()]
    return bool(tokens) and all(token in _COMMON_TITLE_WORDS for token in tokens)


def _is_supported_proper_name(source_text: str, start: int, name: str) -> bool:
    tokens = name.split()
    if len(tokens) < 2:
        return False
    if any(len(token) < 2 for token in tokens):
        return False
    if tokens[0] in _LEADING_NAME_STOPWORDS and len(tokens) < 3:
        return False
    if _looks_like_common_title_phrase(source_text, start, name):
        return False
    return True


def _extract_proper_names(source_text: str) -> list[str]:
    return [
        match.group(0)
        for match in _PROPER_NAME_RE.finditer(_clean_text(source_text))
        if _is_supported_proper_name(source_text, match.start(), match.group(0))
    ]


def _repeated_proper_names(source_by_id: dict[str, str]) -> list[str]:
    counts: dict[str, int] = {}
    for source_text in source_by_id.values():
        for name in _extract_proper_names(source_text):
            counts[name] = counts.get(name, 0) + 1
    return sorted(name for name, count in counts.items() if count > 1)


def _is_short_source_name(proper_name: str) -> bool:
    tokens = proper_name.split()
    return (
        len(tokens) == 2
        and sum(len(token) for token in tokens) <= 6
        and max((len(token) for token in tokens), default=0) <= 3
    )


def _cjk_compact_text(text: str) -> str:
    return "".join(_CJK_RE.findall(_compact_whitespace(text)))


def _cjk_substrings(text: str, min_length: int = 2) -> set[str]:
    if len(text) < min_length:
        return set()
    limit = min(len(text), 12)
    substrings = set()
    for start in range(len(text)):
        max_end = min(len(text), start + limit)
        for end in range(start + min_length, max_end + 1):
            substrings.add(text[start:end])
    return substrings


def _common_cjk_substrings(translations: list[str], min_length: int = 2) -> list[str]:
    if not translations:
        return []
    shared = _cjk_substrings(translations[0], min_length=min_length)
    for translation in translations[1:]:
        shared &= _cjk_substrings(translation, min_length=min_length)
        if not shared:
            return []
    return sorted(shared, key=lambda item: (-len(item), item))


def _anchor_neighbors(text: str, anchor: str) -> tuple[str, str]:
    index = text.find(anchor)
    if index < 0:
        return "", ""
    before = text[index - 1] if index > 0 else ""
    after_index = index + len(anchor)
    after = text[after_index] if after_index < len(text) else ""
    return before, after


def _has_conflicting_neighbor(chars: list[str]) -> bool:
    return len({char for char in chars if char}) > 1


def _is_unsafe_shared_anchor(anchor: str, translations: list[str]) -> bool:
    before_chars = []
    after_chars = []
    for translation in translations:
        before, after = _anchor_neighbors(translation, anchor)
        before_chars.append(before)
        after_chars.append(after)
    return _has_conflicting_neighbor(before_chars) or _has_conflicting_neighbor(after_chars)


def _contains_context_chars(anchor: str) -> bool:
    return any(char in _SHORT_NAME_CONTEXT_CHARS for char in anchor)


def _is_context_boundary(char: str) -> bool:
    return not char or char in _SHORT_NAME_CONTEXT_CHARS


def _source_name_boundaries(source_text: str, proper_name: str) -> tuple[bool, bool]:
    match = re.search(rf"\b{re.escape(proper_name)}\b", _clean_text(source_text))
    if not match:
        return False, False
    before = source_text[:match.start()].strip()
    after = source_text[match.end():].strip()
    start_boundary = not before or not re.search(r"[A-Za-z0-9]", before)
    end_boundary = not after or not re.search(r"[A-Za-z0-9]", after)
    return start_boundary, end_boundary


def _shared_cjk_anchor(translations: list[str]) -> str:
    common = _common_cjk_substrings(translations, min_length=2)
    if not common:
        return ""

    unsafe = {
        anchor for anchor in common if _is_unsafe_shared_anchor(anchor, translations)
    }
    for anchor in common:
        if anchor in unsafe:
            continue
        if any(anchor != other and anchor in other for other in unsafe):
            continue
        return anchor
    return ""


def _long_name_cjk_anchor(translations: list[str]) -> str:
    common = _common_cjk_substrings(translations, min_length=4)
    for anchor in common:
        if not _contains_context_chars(anchor):
            return anchor
    return ""


def _short_name_cjk_anchor(translations: list[str]) -> str:
    common = _common_cjk_substrings(translations, min_length=2)
    for anchor in common:
        if len(anchor) <= 3 and not _contains_context_chars(anchor):
            return anchor
    return ""


def _target_signature(translation: str, shared_anchor: str = "") -> str:
    cjk_text = _cjk_compact_text(translation)
    if shared_anchor and shared_anchor in cjk_text:
        return shared_anchor
    if cjk_text:
        return cjk_text
    return _compact_whitespace(translation)


def _long_name_signature(source_text: str, proper_name: str, translation: str, shared_anchor: str) -> str:
    cjk_text = _cjk_compact_text(translation)
    if not shared_anchor or shared_anchor not in cjk_text:
        return cjk_text or _compact_whitespace(translation)
    before, after = _anchor_neighbors(cjk_text, shared_anchor)
    source_starts_with_name, source_ends_with_name = _source_name_boundaries(source_text, proper_name)
    if source_ends_with_name and not after:
        return shared_anchor
    if source_starts_with_name and not before:
        return shared_anchor
    if _is_context_boundary(before) and _is_context_boundary(after):
        return shared_anchor
    return cjk_text or _compact_whitespace(translation)


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


def proper_name_consistency_score(
    source_by_id: dict[str, str], candidate_by_id: dict[str, str]
) -> dict[str, Any]:
    normalized_source_by_id = {
        str(block_id).strip(): _clean_text(source_text)
        for block_id, source_text in source_by_id.items()
        if str(block_id).strip()
    }
    normalized_candidate_by_id = {
        str(block_id).strip(): _clean_text(translation)
        for block_id, translation in candidate_by_id.items()
        if str(block_id).strip()
    }

    issues = []
    for proper_name in _repeated_proper_names(normalized_source_by_id):
        matcher = re.compile(rf"\b{re.escape(proper_name)}\b")
        observations = []

        for block_id, source_text in normalized_source_by_id.items():
            if not matcher.search(source_text):
                continue
            translation = normalized_candidate_by_id.get(block_id, "")
            if not translation.strip():
                continue
            observations.append({
                "block_id": block_id,
                "source_text": source_text,
                "translation": translation,
            })

        if len(observations) < 2:
            continue

        cjk_translations = [
            cjk_text
            for cjk_text in (_cjk_compact_text(item["translation"]) for item in observations)
            if cjk_text
        ]
        shared_anchor = ""
        if _is_short_source_name(proper_name):
            shared_anchor = _short_name_cjk_anchor(cjk_translations)
        else:
            shared_anchor = _long_name_cjk_anchor(cjk_translations)
        if not shared_anchor and not _is_short_source_name(proper_name):
            shared_anchor = _shared_cjk_anchor(cjk_translations)

        target_forms = []
        for item in observations:
            if _is_short_source_name(proper_name):
                signature = _target_signature(item["translation"], shared_anchor)
            else:
                signature = _long_name_signature(
                    item["source_text"],
                    proper_name,
                    item["translation"],
                    shared_anchor,
                )
            item["target_signature"] = signature
            item["target_anchor"] = shared_anchor
            if signature not in target_forms:
                target_forms.append(signature)

        if len(target_forms) > 1:
            issues.append({
                "source": proper_name,
                "target_forms": target_forms,
                "observations": observations,
            })

    return {
        "issue_count": len(issues),
        "issues": issues,
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
