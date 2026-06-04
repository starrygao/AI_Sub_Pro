"""Optional local colloquial phrase library retrieval."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.engines.translation_memory import _lang


def default_phrase_library_path() -> Path:
    from app import config

    return Path(config.DATA_DIR) / "phrase_library.sqlite3"


@dataclass
class PhraseExample:
    id: int
    source_text: str
    target_text: str
    source_language: str
    target_language: str
    source_name: str
    license: str
    quality: float = 0.5
    score: float = 0.0


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_quality(value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.5
    if parsed < 0:
        return 0.0
    if parsed > 1:
        return 1.0
    return parsed


def _tokens(value: str) -> set[str]:
    return {part for part in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", value.lower()) if part}


def _similarity(query: str, candidate: str) -> float:
    q = _tokens(query)
    c = _tokens(candidate)
    if not q or not c:
        return 0.0
    score = len(q & c) / max(len(q), len(c))
    if candidate.lower() in query.lower() or query.lower() in candidate.lower():
        score += 0.35
    return min(1.0, score)


class PhraseLibrary:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else default_phrase_library_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self):
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS phrase_examples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL,
                    target_text TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    source_name TEXT NOT NULL DEFAULT '',
                    license TEXT NOT NULL DEFAULT '',
                    quality REAL NOT NULL DEFAULT 0.5
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_phrase_examples_lang "
                "ON phrase_examples(source_language, target_language)"
            )

    def add_phrase(
        self,
        *,
        source_text: str,
        target_text: str,
        source_language: str,
        target_language: str,
        source_name: str = "",
        license: str = "",
        quality: float = 0.5,
    ) -> Optional[int]:
        source = _clean_text(source_text)
        target = _clean_text(target_text)
        if not source or not target:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO phrase_examples (
                    source_text, target_text, source_language, target_language,
                    source_name, license, quality
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    target,
                    _lang(source_language, "auto"),
                    _lang(target_language, "zh-CN"),
                    _clean_text(source_name),
                    _clean_text(license),
                    _clean_quality(quality),
                ),
            )
            return int(cur.lastrowid)

    def import_json(self, path: Path) -> int:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return 0
        if not isinstance(raw, dict):
            return 0
        source_name = _clean_text(raw.get("source"))
        license_text = _clean_text(raw.get("license"))
        rows = raw.get("phrases")
        if not isinstance(rows, list):
            return 0
        imported = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            entry_id = self.add_phrase(
                source_text=row.get("source_text", ""),
                target_text=row.get("target_text", ""),
                source_language=row.get("source_language", ""),
                target_language=row.get("target_language", ""),
                source_name=_clean_text(row.get("source_name")) or source_name,
                license=_clean_text(row.get("license")) or license_text,
                quality=row.get("quality", 0.5),
            )
            if entry_id is not None:
                imported += 1
        return imported

    def retrieve(
        self,
        source_text: str,
        *,
        source_language: str,
        target_language: str,
        limit: int = 5,
    ) -> list[PhraseExample]:
        query = _clean_text(source_text)
        if not query:
            return []
        try:
            max_results = max(1, min(20, int(limit)))
        except (TypeError, ValueError, OverflowError):
            max_results = 5
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM phrase_examples
                WHERE source_language = ? AND target_language = ?
                ORDER BY quality DESC, id DESC
                LIMIT 500
                """,
                (_lang(source_language, "auto"), _lang(target_language, "zh-CN")),
            ).fetchall()

        examples = []
        for row in rows:
            similarity = _similarity(query, row["source_text"] or "")
            if similarity <= 0:
                continue
            quality = _clean_quality(row["quality"])
            examples.append(PhraseExample(
                id=int(row["id"]),
                source_text=row["source_text"] or "",
                target_text=row["target_text"] or "",
                source_language=row["source_language"] or "",
                target_language=row["target_language"] or "",
                source_name=row["source_name"] or "",
                license=row["license"] or "",
                quality=quality,
                score=(similarity * 0.75) + (quality * 0.25),
            ))
        examples.sort(key=lambda item: (-item.score, -item.quality, -item.id))
        return examples[:max_results]
