"""
Smart content filter: removes interjections, repetitive content, merges short blocks.
"""
import logging
import math
from typing import List, Dict
from datetime import timedelta

from app.utils.srt import SubtitleBlock
from app.utils.text import clean_sdh, is_interjection, detect_repetitive

log = logging.getLogger(__name__)


def _coerce_bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _coerce_threshold(value, default: int = 3) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(1, min(100, int(parsed)))


def filter_subtitles(
    blocks: List[SubtitleBlock],
    language: str = "ja",
    filter_repetitive: bool = True,
    repetitive_threshold: int = 3,
    filter_interjections: bool = True,
) -> List[SubtitleBlock]:
    """
    Apply smart filtering to subtitle blocks.
    Marks blocks as filtered but does NOT remove them.
    """
    language = language if isinstance(language, str) and language.strip() else "ja"
    filter_repetitive = _coerce_bool(filter_repetitive, True)
    filter_interjections = _coerce_bool(filter_interjections, True)
    repetitive_threshold = _coerce_threshold(repetitive_threshold)

    # Step 1: Clean all text
    for b in blocks:
        cleaned = clean_sdh(b.text)
        if not cleaned:
            b.filtered = True
            b.filter_reason = "空内容"
        else:
            b.text = cleaned

    # Step 1.5: Filter garbage/noise (ASR hallucinations)
    for b in blocks:
        if b.filtered:
            continue
        if _is_garbage(b.text):
            b.filtered = True
            b.filter_reason = "ASR噪音/乱码"
            log.debug("Filtered garbage: '%s'", b.text[:50])

    # Step 2: Filter interjections
    if filter_interjections:
        for b in blocks:
            if b.filtered:
                continue
            if is_interjection(b.text, language):
                b.filtered = True
                b.filter_reason = "感叹词/无意义"
                log.debug("Filtered interjection: '%s'", b.text)

    # Step 3: Filter repetitive content
    if filter_repetitive:
        active_texts = [b.text for b in blocks if not b.filtered]
        repetitive = detect_repetitive(active_texts, threshold=repetitive_threshold)
        if repetitive:
            log.info("Found %d repetitive patterns", len(repetitive))
            # Keep first occurrence, filter the rest
            seen = set()
            for b in blocks:
                if b.filtered:
                    continue
                key = b.text.strip().lower()
                if key in repetitive:
                    if key in seen:
                        b.filtered = True
                        b.filter_reason = f"重复内容 (出现>={repetitive_threshold}次)"
                    else:
                        seen.add(key)

    # Step 4: Merge consecutive short blocks
    _merge_short_blocks(blocks)

    stats = get_filter_stats(blocks)
    log.info(
        "Filter stats: total=%d, active=%d, filtered=%d",
        stats["total"], stats["active"], stats["filtered"],
    )
    return blocks


def _is_garbage(text: str) -> bool:
    """Detect ASR hallucination / garbage output."""
    import re
    if not text:
        return True
    # Repeating pattern: "1,1,1,1" or "aaaa" or "。。。。"
    # High repetition ratio: if most chars are the same
    chars = [c for c in text if not c.isspace()]
    if len(chars) > 10:
        from collections import Counter
        counts = Counter(chars)
        most_common_ratio = counts.most_common(1)[0][1] / len(chars)
        if most_common_ratio > 0.5:
            return True
    # Repeating comma-separated numbers: "1,1,1,1"
    if re.match(r'^[\d,\s]+$', text) and len(text) > 10:
        return True
    # Very long single segment (>200 chars) with no punctuation variety = likely hallucination
    if len(text) > 200:
        unique_ratio = len(set(chars)) / len(chars) if chars else 0
        if unique_ratio < 0.05:
            return True
    return False


def _merge_short_blocks(blocks: List[SubtitleBlock], gap_ms: int = 1000, min_words: int = 3):
    """Merge consecutive short blocks that are close together."""
    i = 0
    while i < len(blocks) - 1:
        curr = blocks[i]
        nxt = blocks[i + 1]
        if curr.filtered or nxt.filtered:
            i += 1
            continue
        # Check if blocks are close enough and both short
        gap = (nxt.start - curr.end).total_seconds() * 1000
        curr_short = len(curr.text.split()) < min_words or len(curr.text) < 8
        nxt_short = len(nxt.text.split()) < min_words or len(nxt.text) < 8
        if gap < gap_ms and curr_short and nxt_short:
            curr.text = f"{curr.text} {nxt.text}"
            curr.end = nxt.end
            nxt.filtered = True
            nxt.filter_reason = "已合并到上一条"
        i += 1


def get_filter_stats(blocks: List[SubtitleBlock]) -> Dict:
    """Get filtering statistics."""
    total = len(blocks)
    filtered = sum(1 for b in blocks if b.filtered)
    reasons = {}
    for b in blocks:
        if b.filtered and b.filter_reason:
            reasons[b.filter_reason] = reasons.get(b.filter_reason, 0) + 1
    return {
        "total": total,
        "active": total - filtered,
        "filtered": filtered,
        "reasons": reasons,
    }
