"""Optional local colloquial phrase library retrieval."""
from __future__ import annotations

import json
import re
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
from app.engines.translation_memory import _lang

_VALID_BACKENDS = {"auto", "fts5", "ngram"}
_FTS_SYNC_NAME = "phrase_examples_fts"


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
    pack_id: str = ""
    pack_version: int = 0
    tags: str = ""
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


def _clean_pack_version(value) -> int:
    if isinstance(value, bool):
        return 1
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 1
    return max(1, parsed)


def _clean_tags(value) -> str:
    if isinstance(value, list):
        return ",".join(part for part in (_clean_text(item) for item in value) if part)
    return _clean_text(value)


def _tag_set(value: str | Iterable[str] | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        raw_parts = re.split(r"[,;\s]+", value)
    else:
        raw_parts = list(value)
    return {
        cleaned.lower()
        for cleaned in (_clean_text(part) for part in raw_parts)
        if cleaned
    }


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


class PhraseLibrary:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else default_phrase_library_path()
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
            existing_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(phrase_examples)").fetchall()
            }
            migrations = {
                "pack_id": "ALTER TABLE phrase_examples ADD COLUMN pack_id TEXT NOT NULL DEFAULT ''",
                "pack_version": "ALTER TABLE phrase_examples ADD COLUMN pack_version INTEGER NOT NULL DEFAULT 0",
                "tags": "ALTER TABLE phrase_examples ADD COLUMN tags TEXT NOT NULL DEFAULT ''",
            }
            for column, statement in migrations.items():
                if column not in existing_columns:
                    conn.execute(statement)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_phrase_examples_lang "
                "ON phrase_examples(source_language, target_language)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_phrase_examples_pack "
                "ON phrase_examples(pack_id, pack_version)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS phrase_pack_imports (
                    pack_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    imported_at TEXT NOT NULL,
                    imported_count INTEGER NOT NULL
                )
                """
            )
            self._ensure_fts_schema(conn)

    def _ensure_fts_schema(self, conn) -> None:
        self._fts_available = False
        if not sqlite_supports_fts5(self.path):
            return
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS phrase_examples_fts
                USING fts5(source_text, target_text, content='phrase_examples', content_rowid='id')
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS phrase_examples_fts_sync (
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
            conn.execute("SELECT rowid FROM phrase_examples_fts LIMIT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def _insert_fts_row(self, conn, row_id: int, source: str, target: str) -> None:
        if not self._fts_table_available(conn):
            return
        try:
            conn.execute(
                "INSERT INTO phrase_examples_fts(rowid, source_text, target_text) VALUES (?, ?, ?)",
                (row_id, source, target),
            )
            self._set_fts_sync_rowid(conn, row_id)
            self._fts_available = True
        except sqlite3.Error:
            self._fts_available = False

    def _get_fts_sync_rowid(self, conn) -> int:
        row = conn.execute(
            "SELECT last_rowid FROM phrase_examples_fts_sync WHERE name = ?",
            (_FTS_SYNC_NAME,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO phrase_examples_fts_sync(name, last_rowid) VALUES (?, 0)",
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
            INSERT INTO phrase_examples_fts_sync(name, last_rowid)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET last_rowid = MAX(last_rowid, excluded.last_rowid)
            """,
            (_FTS_SYNC_NAME, max(0, int(row_id))),
        )

    def _reset_fts_sync_rowid(self, conn) -> None:
        conn.execute(
            """
            INSERT INTO phrase_examples_fts_sync(name, last_rowid)
            VALUES (?, 0)
            ON CONFLICT(name) DO UPDATE SET last_rowid = 0
            """,
            (_FTS_SYNC_NAME,),
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
                    FROM phrase_examples
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
                    FROM phrase_examples_fts_docsize
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
            self._reset_fts_sync_rowid(conn)
            last_rowid = 0
        rows = conn.execute(
            """
            SELECT id, source_text, target_text
            FROM phrase_examples
            WHERE id > ?
            ORDER BY id
            """,
            (last_rowid,),
        ).fetchall()
        synced_rowid = last_rowid
        for row in rows:
            row_id = int(row["id"])
            conn.execute(
                "INSERT INTO phrase_examples_fts(rowid, source_text, target_text) VALUES (?, ?, ?)",
                (row_id, row["source_text"] or "", row["target_text"] or ""),
            )
            synced_rowid = row_id
        if synced_rowid != last_rowid:
            self._set_fts_sync_rowid(conn, synced_rowid)

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
        pack_id: str = "",
        pack_version: int = 0,
        tags: str | list[str] = "",
    ) -> Optional[int]:
        source = _clean_text(source_text)
        target = _clean_text(target_text)
        if not source or not target:
            return None
        normalized_source_language = _lang(source_language, "auto")
        normalized_target_language = _lang(target_language, "zh-CN")
        normalized_source_name = _clean_text(source_name)
        normalized_license = _clean_text(license)
        with self._connect() as conn:
            duplicate = conn.execute(
                """
                SELECT id FROM phrase_examples
                WHERE source_text = ?
                  AND target_text = ?
                  AND source_language = ?
                  AND target_language = ?
                  AND source_name = ?
                LIMIT 1
                """,
                (
                    source,
                    target,
                    normalized_source_language,
                    normalized_target_language,
                    normalized_source_name,
                ),
            ).fetchone()
            if duplicate is not None:
                return None
            cur = conn.execute(
                """
                INSERT INTO phrase_examples (
                    source_text, target_text, source_language, target_language,
                    source_name, license, quality, pack_id, pack_version, tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    target,
                    normalized_source_language,
                    normalized_target_language,
                    normalized_source_name,
                    normalized_license,
                    _clean_quality(quality),
                    _clean_text(pack_id),
                    int(pack_version or 0),
                    _clean_tags(tags),
                ),
            )
            entry_id = int(cur.lastrowid)
            self._insert_fts_row(conn, entry_id, source, target)
            return entry_id

    def import_json(self, path: Path) -> int:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return 0
        return self._import_payload(raw) if isinstance(raw, dict) else 0

    def import_pack(self, path: Path) -> int:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return 0
        if not isinstance(raw, dict):
            return 0
        pack_id = _clean_text(raw.get("id")) or _clean_text(raw.get("pack_id"))
        if not pack_id:
            return self._import_payload(raw)
        pack_version = _clean_pack_version(raw.get("version") or raw.get("pack_version"))
        with self._connect() as conn:
            current = conn.execute(
                "SELECT version FROM phrase_pack_imports WHERE pack_id = ?",
                (pack_id,),
            ).fetchone()
            if current is not None and int(current["version"] or 0) >= pack_version:
                return 0

        imported = self._import_payload(
            raw,
            pack_id=pack_id,
            pack_version=pack_version,
        )
        imported_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT pack_id FROM phrase_pack_imports WHERE pack_id = ?",
                (pack_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO phrase_pack_imports (
                        pack_id, version, imported_at, imported_count
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (pack_id, pack_version, imported_at, imported),
                )
            else:
                conn.execute(
                    """
                    UPDATE phrase_pack_imports
                    SET version = ?, imported_at = ?, imported_count = ?
                    WHERE pack_id = ?
                    """,
                    (pack_version, imported_at, imported, pack_id),
                )
        return imported

    def _import_payload(
        self,
        raw: dict,
        *,
        pack_id: str = "",
        pack_version: int = 0,
    ) -> int:
        source_name = _clean_text(raw.get("source"))
        license_text = _clean_text(raw.get("license"))
        default_source_language = raw.get("source_language", "")
        default_target_language = raw.get("target_language", "")
        default_quality = raw.get("quality", 0.5)
        default_tags = raw.get("tags", "")
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
                source_language=row.get("source_language", default_source_language),
                target_language=row.get("target_language", default_target_language),
                source_name=_clean_text(row.get("source_name")) or source_name,
                license=_clean_text(row.get("license")) or license_text,
                quality=row.get("quality", default_quality),
                pack_id=pack_id,
                pack_version=pack_version,
                tags=row.get("tags", default_tags),
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
        preferred_tags: Optional[Iterable[str]] = None,
        backend: str = "auto",
    ) -> list[PhraseExample]:
        query = _clean_text(source_text)
        if not query:
            return []
        preferred = _tag_set(preferred_tags)
        try:
            max_results = max(1, min(20, int(limit)))
        except (TypeError, ValueError, OverflowError):
            max_results = 5
        normalized_source_language = _lang(source_language, "auto")
        normalized_target_language = _lang(target_language, "zh-CN")
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
            examples = self._score_rows(rows, query=query, preferred_tags=preferred)
            if not examples and backend_used == "fts5" and requested_backend == "auto":
                rows = self._select_ngram_rows(
                    conn,
                    source_language=normalized_source_language,
                    target_language=normalized_target_language,
                )
                backend_used = "ngram"
                examples = self._score_rows(rows, query=query, preferred_tags=preferred)

        self.last_retrieval_backend = backend_used
        examples.sort(key=lambda item: (-item.score, -item.quality, -item.id))
        return examples[:max_results]

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
            SELECT pe.*, bm25(phrase_examples_fts) AS rank
            FROM phrase_examples_fts
            JOIN phrase_examples pe ON pe.id = phrase_examples_fts.rowid
            WHERE phrase_examples_fts MATCH ?
              AND pe.source_language = ?
              AND pe.target_language = ?
            ORDER BY rank, pe.quality DESC, pe.id DESC
            LIMIT 500
            """,
            (fts_query, source_language, target_language),
        ).fetchall()

    def _select_ngram_rows(self, conn, *, source_language: str, target_language: str):
        return conn.execute(
            """
            SELECT * FROM phrase_examples
            WHERE source_language = ? AND target_language = ?
            ORDER BY quality DESC, id DESC
            LIMIT 500
            """,
            (source_language, target_language),
        ).fetchall()

    def _score_rows(
        self,
        rows,
        *,
        query: str,
        preferred_tags: set[str],
    ) -> list[PhraseExample]:
        examples = []
        for row in rows:
            lexical_score = _lexical_similarity(query, row["source_text"] or "")
            if lexical_score <= 0:
                continue
            quality = _clean_quality(row["quality"])
            tags = row["tags"] or ""
            tag_matches = len(preferred_tags & _tag_set(tags))
            examples.append(PhraseExample(
                id=int(row["id"]),
                source_text=row["source_text"] or "",
                target_text=row["target_text"] or "",
                source_language=row["source_language"] or "",
                target_language=row["target_language"] or "",
                source_name=row["source_name"] or "",
                license=row["license"] or "",
                pack_id=row["pack_id"] or "",
                pack_version=int(row["pack_version"] or 0),
                tags=tags,
                quality=quality,
                score=bounded_retrieval_score(
                    lexical_score=lexical_score,
                    quality=quality,
                    tag_matches=tag_matches,
                    priority=0,
                ),
            ))
        return examples


def bundled_phrase_pack_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "resources" / "phrase_packs"


def bundled_phrase_pack_paths(root: Optional[Path] = None) -> list[Path]:
    base = Path(root) if root is not None else bundled_phrase_pack_dir()
    if not base.exists() or not base.is_dir():
        return []

    manifest = base / "manifest.json"
    paths: list[Path] = []
    if manifest.exists():
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        packs = raw.get("packs") if isinstance(raw, dict) else None
        if isinstance(packs, list):
            base_resolved = base.resolve()
            for item in packs:
                rel = item.get("file") if isinstance(item, dict) else item
                rel_text = _clean_text(rel)
                if not rel_text:
                    continue
                candidate = (base / rel_text).resolve()
                try:
                    candidate.relative_to(base_resolved)
                except ValueError:
                    continue
                if candidate.exists() and candidate.is_file():
                    paths.append(candidate)

    if not paths:
        paths = sorted(path for path in base.glob("*.json") if path.name != "manifest.json")

    seen = set()
    unique_paths = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def import_bundled_phrase_packs(
    library: Optional[PhraseLibrary] = None,
    root: Optional[Path] = None,
) -> dict:
    phrase_library = library or PhraseLibrary()
    packs = []
    total = 0
    for path in bundled_phrase_pack_paths(root):
        imported = phrase_library.import_pack(path)
        total += imported
        packs.append({"file": path.name, "imported": imported})
    return {"imported": total, "packs": packs}
