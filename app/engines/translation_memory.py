"""Local translation memory learned from user subtitle edits."""
from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from app.engines.retrieval_scoring import (
    bounded_retrieval_score,
    ngram_similarity,
    normalize_text,
    sqlite_supports_fts5,
)

_VALID_BACKENDS = {"auto", "fts5", "ngram"}
_FTS_SYNC_NAME = "translation_memory_fts"


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


def _is_latin_character(value: str) -> bool:
    return unicodedata.name(value, "").startswith("LATIN")


def _fold_fts_character(value: str) -> str:
    if unicodedata.combining(value):
        return ""
    if not _is_latin_character(value):
        return value.lower()
    return "".join(
        part.lower()
        for part in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(part) and part.isalnum()
    )


def _fold_fts_text(value: str) -> str:
    return "".join(
        _fold_fts_character(char)
        for char in unicodedata.normalize("NFKC", normalize_text(value))
    )


def _fts_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for char in _fold_fts_text(value):
        if char.isalnum():
            current.append(char)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def _table_columns(conn, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row["name"]) for row in rows}


def _fts_match_query(value: str) -> str:
    tokens = sorted(set(_fts_tokens(value)))
    if tokens:
        return " OR ".join(f'"{token}"' for token in tokens)
    return ""


def _lexical_similarity(query: str, candidate: str) -> float:
    return max(
        ngram_similarity(query, candidate),
        ngram_similarity(_fold_fts_text(query), _fold_fts_text(candidate)),
    )


def _dedupe_rows(*row_groups) -> list:
    rows_by_id = {}
    for rows in row_groups:
        for row in rows:
            row_id = int(row["id"])
            if row_id not in rows_by_id:
                rows_by_id[row_id] = row
    return list(rows_by_id.values())


def _parse_created_at(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _usage_boost(value: object) -> float:
    try:
        usage_count = max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return min(1.0, usage_count / 5.0)


def _recency_boost(value: object, *, now: datetime) -> float:
    created_at = _parse_created_at(value)
    if created_at is None:
        return 0.0
    age_seconds = max(0.0, (now - created_at).total_seconds())
    age_days = age_seconds / 86400.0
    return 1.0 / (1.0 + age_days / 30.0)


class TranslationMemoryStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else default_memory_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.last_retrieval_backend = "ngram"
        self._fts_available = False
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
            self._migrate_translation_memory_columns(conn)
            self._ensure_fts_schema(conn)

    def _migrate_translation_memory_columns(self, conn) -> None:
        columns = _table_columns(conn, "translation_memory")
        if "usage_count" not in columns:
            conn.execute(
                "ALTER TABLE translation_memory ADD COLUMN usage_count INTEGER NOT NULL DEFAULT 0"
            )

    def _ensure_fts_schema(self, conn) -> None:
        self._fts_available = False
        if not sqlite_supports_fts5(self.path):
            return
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS translation_memory_fts
                USING fts5(
                    source_text,
                    final_translation,
                    content='translation_memory',
                    content_rowid='id'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_memory_fts_sync (
                    name TEXT PRIMARY KEY,
                    last_rowid INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._fts_available = True
            self._sync_fts_rows(conn)
        except sqlite3.Error:
            self._fts_available = False

    def _fts_table_available(self, conn) -> bool:
        if not self._fts_available:
            return False
        try:
            conn.execute("SELECT rowid FROM translation_memory_fts LIMIT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def _get_fts_sync_rowid(self, conn) -> int:
        row = conn.execute(
            "SELECT last_rowid FROM translation_memory_fts_sync WHERE name = ?",
            (_FTS_SYNC_NAME,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO translation_memory_fts_sync(name, last_rowid) VALUES (?, 0)",
                (_FTS_SYNC_NAME,),
            )
            return 0
        try:
            return max(0, int(row["last_rowid"] or 0))
        except (TypeError, ValueError, OverflowError):
            return 0

    def _set_fts_sync_rowid(self, conn, row_id: int) -> None:
        conn.execute(
            """
            INSERT INTO translation_memory_fts_sync(name, last_rowid)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET last_rowid = MAX(last_rowid, excluded.last_rowid)
            """,
            (_FTS_SYNC_NAME, max(0, int(row_id))),
        )

    def _fts_sync_marker_valid(self, conn, last_rowid: int) -> bool:
        if last_rowid <= 0:
            return True
        try:
            expected_ids = [
                int(row["id"])
                for row in conn.execute(
                    """
                    SELECT id
                    FROM translation_memory
                    WHERE id <= ?
                    ORDER BY id
                    """,
                    (last_rowid,),
                ).fetchall()
            ]
            indexed_ids = [
                int(row["id"])
                for row in conn.execute(
                    """
                    SELECT id
                    FROM translation_memory_fts_docsize
                    WHERE id <= ?
                    ORDER BY id
                    """,
                    (last_rowid,),
                ).fetchall()
            ]
        except (sqlite3.Error, TypeError, ValueError, OverflowError):
            return False
        return expected_ids == indexed_ids

    def _sync_fts_rows(self, conn) -> None:
        if not self._fts_available:
            return
        last_rowid = self._get_fts_sync_rowid(conn)
        if not self._fts_sync_marker_valid(conn, last_rowid):
            conn.execute("INSERT INTO translation_memory_fts(translation_memory_fts) VALUES('rebuild')")
            last_rowid = conn.execute(
                "SELECT COALESCE(MAX(id), 0) AS max_id FROM translation_memory"
            ).fetchone()["max_id"]
            self._set_fts_sync_rowid(conn, int(last_rowid or 0))
            return
        rows = conn.execute(
            """
            SELECT id, source_text, final_translation
            FROM translation_memory
            WHERE id > ?
            ORDER BY id
            """,
            (last_rowid,),
        ).fetchall()
        synced_rowid = last_rowid
        for row in rows:
            row_id = int(row["id"])
            source_text = row["source_text"] or ""
            final_translation = row["final_translation"] or ""
            conn.execute(
                "INSERT INTO translation_memory_fts(rowid, source_text, final_translation) VALUES (?, ?, ?)",
                (row_id, source_text, final_translation),
            )
            synced_rowid = row_id
        if synced_rowid != last_rowid:
            self._set_fts_sync_rowid(conn, synced_rowid)

    def _insert_fts_row(self, conn, row_id: int, source_text: str, final_translation: str) -> None:
        if not self._fts_table_available(conn):
            return
        try:
            conn.execute(
                "INSERT INTO translation_memory_fts(rowid, source_text, final_translation) VALUES (?, ?, ?)",
                (row_id, source_text, final_translation),
            )
            self._set_fts_sync_rowid(conn, row_id)
            self._fts_available = True
        except sqlite3.Error:
            self._fts_available = False

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
            entry_id = int(cur.lastrowid)
            self._insert_fts_row(conn, entry_id, source, final)
            return entry_id

    def retrieve(
        self,
        source_text: str,
        *,
        source_language: str,
        target_language: str,
        limit: int = 5,
        backend: str = "auto",
    ) -> list[MemoryEntry]:
        query = _clean_text(source_text)
        if not query:
            return []
        try:
            max_results = max(1, min(20, int(limit)))
        except (TypeError, ValueError, OverflowError):
            max_results = 5
        normalized_source_language = _lang(source_language, "auto")
        normalized_target_language = _lang(target_language, "简体中文")
        requested_backend = _clean_text(backend).lower()
        if requested_backend not in _VALID_BACKENDS:
            requested_backend = "auto"

        with self._connect() as conn:
            rows, backend_used = self._select_candidate_rows(
                conn,
                query=query,
                source_language=normalized_source_language,
                target_language=normalized_target_language,
                requested_backend=requested_backend,
            )
            entries = self._score_rows(rows, query=query)
            entries.sort(key=lambda item: (-item.score, -item.id))
            selected = entries[:max_results]
            if selected:
                conn.executemany(
                    "UPDATE translation_memory SET usage_count = usage_count + 1 WHERE id = ?",
                    [(entry.id,) for entry in selected],
                )

        self.last_retrieval_backend = backend_used
        return selected

    def _select_candidate_rows(
        self,
        conn,
        *,
        query: str,
        source_language: str,
        target_language: str,
        requested_backend: str,
    ):
        use_fts = requested_backend in {"auto", "fts5"} and self._fts_table_available(conn)
        if not use_fts:
            return self._select_ngram_rows(
                conn,
                source_language=source_language,
                target_language=target_language,
            ), "ngram"

        fts_query = _fts_match_query(query)
        if not fts_query:
            return self._select_ngram_rows(
                conn,
                source_language=source_language,
                target_language=target_language,
            ), "ngram"

        try:
            fts_rows = self._select_fts_rows(
                conn,
                fts_query=fts_query,
                source_language=source_language,
                target_language=target_language,
            )
            if requested_backend == "auto":
                ngram_rows = self._select_ngram_rows(
                    conn,
                    source_language=source_language,
                    target_language=target_language,
                )
                return _dedupe_rows(fts_rows, ngram_rows), "fts5"
            return fts_rows, "fts5"
        except sqlite3.Error:
            self._fts_available = False
            return self._select_ngram_rows(
                conn,
                source_language=source_language,
                target_language=target_language,
            ), "ngram"

    def _select_fts_rows(self, conn, *, fts_query: str, source_language: str, target_language: str):
        return conn.execute(
            """
            SELECT tm.*, bm25(translation_memory_fts) AS rank
            FROM translation_memory_fts
            JOIN translation_memory tm ON tm.id = translation_memory_fts.rowid
            WHERE translation_memory_fts MATCH ?
              AND tm.source_language = ?
              AND tm.target_language = ?
            ORDER BY rank, tm.id DESC
            LIMIT 500
            """,
            (fts_query, source_language, target_language),
        ).fetchall()

    def _select_ngram_rows(self, conn, *, source_language: str, target_language: str):
        return conn.execute(
            """
            SELECT *
            FROM translation_memory
            WHERE source_language = ? AND target_language = ?
            ORDER BY id DESC
            LIMIT 500
            """,
            (source_language, target_language),
        ).fetchall()

    def _score_rows(self, rows, *, query: str) -> list[MemoryEntry]:
        now = datetime.now(timezone.utc)
        entries = []
        for row in rows:
            lexical_score = _lexical_similarity(query, row["source_text"] or "")
            if lexical_score <= 0:
                continue
            usage_count = int(row["usage_count"] or 0)
            entries.append(
                MemoryEntry.from_row(
                    row,
                    score=bounded_retrieval_score(
                        lexical_score=lexical_score,
                        quality=1.0,
                        priority=1.0,
                        recency_boost=_recency_boost(row["created_at"], now=now),
                        usage_boost=_usage_boost(usage_count),
                    ),
                )
            )
        return entries


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
