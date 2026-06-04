"""Local translation memory learned from user subtitle edits."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


def default_memory_path() -> Path:
    from app import config

    return Path(config.DATA_DIR) / "translation_memory.sqlite3"


@dataclass
class MemoryEntry:
    id: int
    source_text: str
    machine_translation: str
    final_translation: str
    source_language: str
    target_language: str
    project_name: str = ""
    tmdb_id: Optional[int] = None
    genre: str = ""
    speaker: str = ""
    context_before: str = ""
    context_after: str = ""
    created_at: str = ""
    usage_count: int = 0
    score: float = 0.0

    @classmethod
    def from_row(cls, row, *, score: float = 0.0) -> "MemoryEntry":
        return cls(
            id=int(row["id"]),
            source_text=row["source_text"] or "",
            machine_translation=row["machine_translation"] or "",
            final_translation=row["final_translation"] or "",
            source_language=row["source_language"] or "",
            target_language=row["target_language"] or "",
            project_name=row["project_name"] or "",
            tmdb_id=row["tmdb_id"],
            genre=row["genre"] or "",
            speaker=row["speaker"] or "",
            context_before=row["context_before"] or "",
            context_after=row["context_after"] or "",
            created_at=row["created_at"] or "",
            usage_count=int(row["usage_count"] or 0),
            score=score,
        )


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _lang(value, default: str) -> str:
    text = _clean_text(value) or default
    normalized = text.lower()
    if text in {"简体中文", "中文", "普通话"} or normalized in {"zh", "zh-cn", "chs", "zho", "cmn"}:
        return "zh-CN"
    if text in {"繁體中文", "繁体中文"} or normalized in {"zh-tw", "zh-hant", "cht"}:
        return "zh-TW"
    if text in {"English", "英语", "英文"} or normalized in {"en", "eng"}:
        return "en"
    return text


def _positive_int_or_none(value) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _tokens(value: str) -> set[str]:
    return {part for part in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", value.lower()) if part}


def _similarity(query: str, candidate: str) -> float:
    q = _tokens(query)
    c = _tokens(candidate)
    if not q or not c:
        return 0.0
    overlap = len(q & c)
    score = overlap / max(len(q), len(c))
    q_text = query.lower()
    c_text = candidate.lower()
    if q_text and c_text and (q_text in c_text or c_text in q_text):
        score += 0.35
    return min(1.0, score)


class TranslationMemoryStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else default_memory_path()
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
                CREATE TABLE IF NOT EXISTS translation_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_text TEXT NOT NULL,
                    machine_translation TEXT NOT NULL DEFAULT '',
                    final_translation TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_language TEXT NOT NULL,
                    project_name TEXT NOT NULL DEFAULT '',
                    tmdb_id INTEGER,
                    genre TEXT NOT NULL DEFAULT '',
                    speaker TEXT NOT NULL DEFAULT '',
                    context_before TEXT NOT NULL DEFAULT '',
                    context_after TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_translation_memory_lang "
                "ON translation_memory(source_language, target_language)"
            )

    def record_edit(
        self,
        *,
        source_text: str,
        machine_translation: str,
        final_translation: str,
        source_language: str,
        target_language: str,
        project_name: str = "",
        tmdb_id: Optional[int] = None,
        genre: str = "",
        speaker: str = "",
        context_before: str = "",
        context_after: str = "",
    ) -> Optional[int]:
        source = _clean_text(source_text)
        machine = _clean_text(machine_translation)
        final = _clean_text(final_translation)
        if not source or not final:
            return None
        if machine and machine == final:
            return None

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO translation_memory (
                    source_text, machine_translation, final_translation,
                    source_language, target_language, project_name, tmdb_id,
                    genre, speaker, context_before, context_after, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    machine,
                    final,
                    _lang(source_language, "auto"),
                    _lang(target_language, "简体中文"),
                    _clean_text(project_name),
                    _positive_int_or_none(tmdb_id),
                    _clean_text(genre),
                    _clean_text(speaker),
                    _clean_text(context_before),
                    _clean_text(context_after),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cur.lastrowid)

    def retrieve(
        self,
        source_text: str,
        *,
        source_language: str,
        target_language: str,
        limit: int = 5,
    ) -> list[MemoryEntry]:
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
                SELECT * FROM translation_memory
                WHERE source_language = ? AND target_language = ?
                ORDER BY id DESC
                LIMIT 500
                """,
                (_lang(source_language, "auto"), _lang(target_language, "简体中文")),
            ).fetchall()

        scored = []
        for row in rows:
            score = _similarity(query, row["source_text"] or "")
            if score > 0:
                scored.append(MemoryEntry.from_row(row, score=score))
        scored.sort(key=lambda item: (-item.score, -item.id))
        return scored[:max_results]


def record_edited_subtitles(
    *,
    project: dict,
    before_blocks: Iterable,
    after_blocks: Iterable,
    store: Optional[TranslationMemoryStore] = None,
) -> int:
    """Record user edits by comparing previous and newly saved translations."""
    if not isinstance(project, dict):
        project = {}
    before_by_index = {}
    for block in before_blocks or []:
        index = getattr(block, "index", None)
        translation = _clean_text(getattr(block, "text", ""))
        if isinstance(index, int) and translation:
            before_by_index[index] = translation

    memory = store or TranslationMemoryStore()
    count = 0
    for block in after_blocks or []:
        index = getattr(block, "index", None)
        machine = before_by_index.get(index, "")
        final = _clean_text(getattr(block, "translation", ""))
        if not machine or machine == final:
            continue
        entry_id = memory.record_edit(
            source_text=getattr(block, "text", ""),
            machine_translation=machine,
            final_translation=final,
            source_language=_lang(project.get("original_language"), "en"),
            target_language=_lang(project.get("target_language"), "简体中文"),
            project_name=_clean_text(project.get("show_title") or project.get("name") or ""),
            tmdb_id=_positive_int_or_none(project.get("tmdb_id")),
        )
        if entry_id is not None:
            count += 1
    return count
