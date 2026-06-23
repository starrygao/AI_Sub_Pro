"""Conservative deterministic cleanup for inferred proper-name variants."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable

from app.evaluation.metrics import proper_name_consistency_score


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_NAME_JOINERS = {"·", "・", "-"}
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
_RIGHT_CONTEXT_STOPS = set(
    "的了呢吗啊呀吧哦嘛么着过在从到去来给把被将让为就时后前上下一些"
    "这那哪谁什么怎很太都也还又会能要想说问看见听帮派传发走入出先等首"
)


def _cjk_compact(value: str) -> str:
    return "".join(_CJK_RE.findall(value or ""))


def _source_target_cjk_limit(source: str) -> int:
    letter_count = sum(1 for char in (source or "") if char.isalpha())
    return max(3, min(8, (letter_count * 3 + 4) // 5))


def _shared_majority_anchor(translations: list[str]) -> str:
    counts: dict[str, int] = {}
    positions: dict[str, int] = {}
    for compact in [_cjk_compact(text) for text in translations if _cjk_compact(text)]:
        seen: dict[str, int] = {}
        max_length = min(6, len(compact))
        for length in range(2, max_length + 1):
            for start in range(0, len(compact) - length + 1):
                chunk = compact[start:start + length]
                if chunk in _BAD_ANCHORS:
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


def _span_for_anchor(text: str, anchor: str, source: str) -> tuple[str, str] | None:
    cjk_chars = []
    cjk_positions = []
    for idx, char in enumerate(text or ""):
        if _CJK_RE.match(char):
            cjk_chars.append(char)
            cjk_positions.append(idx)
    compact = "".join(cjk_chars)
    anchor_start = compact.find(anchor)
    if anchor_start < 0:
        return None

    start = cjk_positions[anchor_start]
    end = cjk_positions[anchor_start + len(anchor) - 1] + 1
    cjk_count = len(anchor)
    cjk_limit = _source_target_cjk_limit(source)

    idx = end
    while idx < len(text) and cjk_count < cjk_limit:
        char = text[idx]
        if char in _NAME_JOINERS:
            end = idx + 1
            idx += 1
            continue
        if _CJK_RE.match(char):
            if char in _RIGHT_CONTEXT_STOPS:
                break
            end = idx + 1
            idx += 1
            cjk_count += 1
            continue
        break

    span = text[start:end]
    signature = _cjk_compact(span)
    if len(signature) < 2:
        return None
    return span, signature


def _canonical_span(spans: list[str]) -> str:
    by_span: dict[str, int] = {}
    for span in spans:
        by_span[span] = by_span.get(span, 0) + 1
    return sorted(by_span, key=lambda item: (-by_span[item], len(item), item))[0]


def normalize_inferred_proper_name_variants(blocks: Iterable) -> list[dict]:
    """Normalize minority inferred proper-name variants when evidence is strong.

    This pass is intentionally narrow:
    - it only uses repeated source proper names already detected by the local
      QA metric;
    - it requires a strict majority target form;
    - it only replaces an exact extracted name span inside the affected block.
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
            span = _span_for_anchor(translation, anchor, source)
            if span is None:
                continue
            text_span, signature = span
            spans_by_signature[signature].append((block_id, text_span))

        counts = Counter({
            signature: len(items)
            for signature, items in spans_by_signature.items()
        })
        if len(counts) < 2:
            continue
        ranked = counts.most_common()
        if ranked[0][1] < 2 or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
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
            if signature.startswith(canonical_signature):
                continue
            for block_id, span in items:
                block = by_id.get(block_id)
                if block is None:
                    continue
                current = getattr(block, "translation", "")
                if not isinstance(current, str) or span not in current:
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
