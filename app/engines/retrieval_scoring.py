"""Shared deterministic retrieval scoring helpers."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_TOKEN_RE = re.compile(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+")
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def normalize_text(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def token_set(value: str) -> set[str]:
    tokens: set[str] = set()
    for part in _TOKEN_RE.findall(normalize_text(value)):
        tokens.add(part)
        if _CJK_RE.search(part):
            for size in (2, 3):
                if len(part) >= size:
                    tokens.update(part[index:index + size] for index in range(len(part) - size + 1))
    return {token for token in tokens if token}


def ngram_similarity(query: str, candidate: str) -> float:
    q = token_set(query)
    c = token_set(candidate)
    if not q or not c:
        return 0.0
    score = len(q & c) / max(len(q), len(c))
    q_text = normalize_text(query)
    c_text = normalize_text(candidate)
    if q_text and c_text and (q_text in c_text or c_text in q_text):
        score += 0.35
    return min(1.0, score)


def clamp(value: float, low: float = 0, high: float = 1) -> float:
    return max(low, min(high, value))


def bounded_retrieval_score(
    *,
    lexical_score: float,
    quality: float = 0.5,
    tag_matches: int = 0,
    priority: float = 0.0,
    recency_boost: float = 0.0,
    usage_boost: float = 0.0,
) -> float:
    score = (
        clamp(float(lexical_score)) * 0.68
        + clamp(float(quality)) * 0.16
        + min(0.10, max(0, int(tag_matches)) * 0.04)
        + clamp(float(priority)) * 0.10
        + min(0.04, max(0.0, float(recency_boost)))
        + min(0.04, max(0.0, float(usage_boost)))
    )
    return round(clamp(score), 6)


def sqlite_supports_fts5(path: str | Path) -> bool:
    try:
        db = Path(path)
        db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db)) as conn:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.__fts5_probe USING fts5(value)")
            conn.execute("DROP TABLE temp.__fts5_probe")
        return True
    except sqlite3.Error:
        return False
