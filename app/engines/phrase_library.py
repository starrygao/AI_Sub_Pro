"""Optional local colloquial phrase library retrieval."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from app.engines.translation_memory import _lang

_TOKEN_RE = re.compile(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+")
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


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


def _tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for part in _TOKEN_RE.findall(value.lower()):
        if not part:
            continue
        tokens.add(part)
        if not _CJK_RE.search(part):
            continue
        for size in (2, 3):
            if len(part) < size:
                continue
            tokens.update(part[index:index + size] for index in range(len(part) - size + 1))
    return tokens


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
            return int(cur.lastrowid)

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
    ) -> list[PhraseExample]:
        query = _clean_text(source_text)
        if not query:
            return []
        preferred = _tag_set(preferred_tags)
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
            tags = row["tags"] or ""
            tag_matches = len(preferred & _tag_set(tags))
            tag_boost = min(0.12, tag_matches * 0.04)
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
                score=(similarity * 0.75) + (quality * 0.25) + tag_boost,
            ))
        examples.sort(key=lambda item: (-item.score, -item.quality, -item.id))
        return examples[:max_results]


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
