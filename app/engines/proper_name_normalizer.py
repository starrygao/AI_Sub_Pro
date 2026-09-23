"""Conservative deterministic cleanup for inferred proper-name variants."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable

from app.evaluation.metrics import proper_name_consistency_score


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_BAD_ANCHORS = {
    "今天",
    "他们",
    "什么",
    "你们",
    "你是",
    "她们",
    "她是",
    "我们",
    "怎么",
    "我是",
    "明天",
    "昨天",
    "知道",
    "这个",
    "这是",
    "那个",
    "那是",
}
def _cjk_compact(value: str) -> str:
    return "".join(_CJK_RE.findall(value or ""))


def _shared_majority_anchor(translations: list[str]) -> str:
    counts: dict[str, int] = {}
    positions: dict[str, int] = {}
    for compact in [_cjk_compact(text) for text in translations if _cjk_compact(text)]:
        seen: dict[str, int] = {}
        max_length = min(6, len(compact))
        for length in range(2, max_length + 1):
            for start in range(0, len(compact) - length + 1):
                chunk = compact[start:start + length]
                if chunk in _BAD_ANCHORS or "的" in chunk:
                    continue
                seen.setdefault(chunk, start)
        for chunk, start in seen.items():
            counts[chunk] = counts.get(chunk, 0) + 1
            positions[chunk] = positions.get(chunk, 0) + start
    candidates = [
        (count, len(chunk), -positions[chunk], chunk)
        for chunk, count in counts.items()
        if count >= 2
    ]
    if not candidates:
        return ""
    return max(candidates)[3]


def _canonical_span(spans: list[str]) -> str:
    by_span: dict[str, int] = {}
    for span in spans:
        by_span[span] = by_span.get(span, 0) + 1
    return sorted(by_span, key=lambda item: (-by_span[item], len(item), item))[0]


def normalize_inferred_proper_name_variants(blocks: Iterable, *, protected_terms: dict | None = None) -> list[dict]:
    """Normalize minority inferred proper-name variants when evidence is strong.

    This pass is intentionally narrow:
    - it only uses repeated source proper names already detected by the local
      QA metric;
    - it requires a strict majority target form;
    - it requires a unique bounded span and shared name characters;
    - it never shortens/expands a containing span, or reuses stale observations.
    """
    active_blocks = [
        block for block in (blocks or [])
        if not getattr(block, "filtered", False)
        and isinstance(getattr(block, "index", None), int)
    ]
    if not active_blocks:
        return []

    source_by_id = {
        str(getattr(block, "index")): getattr(block, "text", "")
        for block in active_blocks
    }
    translation_by_id = {
        str(getattr(block, "index")): getattr(block, "translation", "")
        for block in active_blocks
    }
    score = proper_name_consistency_score(source_by_id, translation_by_id)
    issues = score.get("issues") if isinstance(score, dict) else []
    if not isinstance(issues, list):
        return []

    by_id = {str(getattr(block, "index")): block for block in active_blocks}
    applied: list[dict] = []

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        source = issue.get("source")
        observations = issue.get("observations")
        if not isinstance(source, str) or not isinstance(observations, list):
            continue
        from app.engines.entity_registry import entity_matcher
        if any(entity_matcher(term).search(source) or entity_matcher(source).search(term)
               for term in protected_terms or {}):
            continue
        if len(source.split()) < 2:
            # Explicit single-word speaker labels are checked by the metric,
            # but do not establish safe replacement spans in surrounding text.
            continue

        translations = [
            item.get("translation", "")
            for item in observations
            if isinstance(item, dict) and isinstance(item.get("translation"), str)
        ]
        anchor = _shared_majority_anchor(translations)
        if not anchor:
            continue

        spans_by_signature: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for item in observations:
            if not isinstance(item, dict):
                continue
            block_id = str(item.get("block_id", "")).strip()
            translation = item.get("translation", "")
            if not block_id or not isinstance(translation, str):
                continue
            bounded_span = item.get("target_span", "")
            # A shared phrase is evidence for a QA warning, not permission
            # to rewrite a guessed name inside a sentence.
            if (item.get("evidence") not in {"bounded_lexical_span", "speaker_label", "standalone_address", "title_boundary"}
                    or not isinstance(bounded_span, str) or not bounded_span
                    or translation.count(bounded_span) != 1):
                continue
            text_span, signature = bounded_span, _cjk_compact(bounded_span)
            if len(signature) < 2:
                continue
            spans_by_signature[signature].append((block_id, text_span))

        counts = Counter({
            signature: len(items)
            for signature, items in spans_by_signature.items()
        })
        if len(counts) < 2:
            continue
        ranked = counts.most_common()
        observation_count = sum(counts.values())
        if (
            ranked[0][1] < 2
            or ranked[0][1] * 2 <= observation_count
            or (len(ranked) > 1 and ranked[0][1] == ranked[1][1])
        ):
            continue
        canonical_signature = ranked[0][0]
        canonical = _canonical_span([
            span for _block_id, span in spans_by_signature[canonical_signature]
        ])
        if not canonical or len(_cjk_compact(canonical)) < 2:
            continue

        for signature, items in spans_by_signature.items():
            if signature == canonical_signature:
                continue
            # Adding/removing a title is not a transliteration correction.
            # A shorter existing name may already have its title on the left.
            # Containment may reflect titles OR surrounding dialogue (e.g.
            # "得希尔克" in "我觉得希尔克教会"). Never delete that context.
            if signature in canonical_signature or canonical_signature in signature:
                continue
            # Unrelated names in one cue must not be unified merely because
            # a lexical guess paired them with the same source mention.
            if len(set(signature) & set(canonical_signature)) < 2:
                continue
            for block_id, span in items:
                block = by_id.get(block_id)
                if block is None:
                    continue
                current = getattr(block, "translation", "")
                if (not isinstance(current, str) or current.count(span) != 1
                        or current != translation_by_id.get(block_id)):
                    continue
                updated = current.replace(span, canonical, 1)
                if updated == current:
                    continue
                block.translation = updated
                applied.append({
                    "id": getattr(block, "index", None),
                    "source": source,
                    "from": span,
                    "to": canonical,
                    "reason": "proper_name_majority_variant",
                })

    return applied
