"""Knowledge base v2 — per-project typed categories + auto-migration from v1.

Instance-based KnowledgeBase. The module also exposes a process-wide singleton
(`_get_singleton()`) so FastAPI route handlers in `app/api/*.py` can share a
single in-memory copy without rebuilding it on every request.
"""
import json
import logging
import threading
from pathlib import Path
from typing import Dict, Optional

from app.config import KB_FILE as _DEFAULT_KB_FILE, BASE_DIR
from app.engines.kb_models import ProjectKb
from app.engines.kb_migration import is_v2_shape, migrate_v1_to_v2

log = logging.getLogger(__name__)

# Module-level constants — tests monkey-patch these to redirect I/O to tmp_path.
KB_FILE = _DEFAULT_KB_FILE
LEGACY_KB = Path(BASE_DIR) / "my_knowledge.json"


class KnowledgeBase:
    """Instance-based v2 knowledge base.

    Old classmethod call sites (`KnowledgeBase.load()` etc.) were migrated in
    Task 3 of the KB redesign to call into a module-level singleton via
    `_get_singleton()`. New code should simply instantiate `KnowledgeBase()`.
    """

    def __init__(self) -> None:
        self._projects: Dict[str, ProjectKb] = {}
        self._lock = threading.RLock()

    # ----- Load / Save -----

    def load(self) -> None:
        """Read knowledge.json into memory. Auto-migrates v1 → v2 on first
        encounter and backs up the original as `knowledge.v1.backup.json`.
        """
        with self._lock:
            path = Path(KB_FILE)
            raw: dict = {}
            source_is_kb_file = False

            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    source_is_kb_file = True
                except Exception as e:
                    log.warning("knowledge.json unreadable: %s; starting empty", e)
                    raw = {}
            elif Path(LEGACY_KB).exists():
                # First-run migration from repo-root my_knowledge.json
                try:
                    raw = json.loads(Path(LEGACY_KB).read_text(encoding="utf-8"))
                except Exception as e:
                    log.warning("legacy my_knowledge.json unreadable: %s", e)
                    raw = {}

            if not isinstance(raw, dict):
                raw = {}

            if raw and not is_v2_shape(raw):
                # Back up the v1 file before overwriting
                try:
                    if source_is_kb_file and path.exists():
                        backup = path.parent / "knowledge.v1.backup.json"
                        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception as e:
                    log.warning("v1 backup write failed: %s", e)
                raw = migrate_v1_to_v2(raw)
                self._projects = {k: ProjectKb.from_dict(v) for k, v in raw.items()}
                self.save()
                log.info("migrated knowledge.json from v1 to v2 (%d projects)", len(self._projects))
                return

            self._projects = {k: ProjectKb.from_dict(v) for k, v in raw.items()}

    def save(self) -> None:
        from app.utils.project_store import atomic_write_json
        with self._lock:
            data = {k: p.to_dict() for k, p in self._projects.items()}
            atomic_write_json(Path(KB_FILE), data)

    # ----- CRUD -----

    def get_project(self, key: str) -> Optional[ProjectKb]:
        with self._lock:
            return self._projects.get(key)

    def set_project(self, key: str, kb: ProjectKb) -> None:
        with self._lock:
            self._projects[key] = kb

    def put_project(self, key: str, kb: ProjectKb) -> None:
        """Set one project and persist the full KB under one process lock."""
        with self._lock:
            self._projects[key] = kb
            self.save()

    def delete_project(self, key: str) -> bool:
        with self._lock:
            return self._projects.pop(key, None) is not None

    def delete_project_and_save(self, key: str) -> bool:
        """Delete one project and persist the full KB under one process lock."""
        with self._lock:
            removed = self._projects.pop(key, None) is not None
            if removed:
                self.save()
            return removed

    def list_projects(self) -> Dict[str, ProjectKb]:
        with self._lock:
            return dict(self._projects)

    # ----- Selection -----

    def select_for_project(self, project: dict) -> Optional[ProjectKb]:
        """Pick the best-matching ProjectKb for the given project dict.

        Matching precedence:
          1. exact `tmdb_id` match
          2. `show_title` (case-insensitive) appears as substring of project name
          3. None
        """
        if not isinstance(project, dict):
            return None
        tmdb_id = project.get("tmdb_id")
        if isinstance(tmdb_id, bool) or not isinstance(tmdb_id, int) or tmdb_id < 1:
            tmdb_id = None
        raw_name = project.get("name")
        name = raw_name.lower() if isinstance(raw_name, str) else ""

        with self._lock:
            projects = list(self._projects.values())

        if tmdb_id is not None:
            for kb in projects:
                if kb.tmdb_id is not None and kb.tmdb_id == tmdb_id:
                    return kb

        if name:
            for kb in projects:
                if kb.show_title and kb.show_title.lower() in name:
                    return kb

        return None

    # ----- Legacy compat (old callers) -----

    def get_all(self) -> Dict[str, dict]:
        """Return all projects as a dict-of-dicts (used by settings.py
        `GET /api/knowledge`)."""
        with self._lock:
            return {k: p.to_dict() for k, p in self._projects.items()}

    def update_all(self, data: dict) -> None:
        """Replace all projects (used by settings.py `POST /api/knowledge`).
        Accepts both v1 and v2 shapes; v1 is migrated in-memory before load."""
        if not isinstance(data, dict):
            return
        if data and not is_v2_shape(data):
            data = migrate_v1_to_v2(data)
        with self._lock:
            self._projects = {k: ProjectKb.from_dict(v) for k, v in data.items()}
            self.save()

# ----- Module-level singleton for legacy classmethod-style call sites -----

_singleton: Optional[KnowledgeBase] = None


def _get_singleton() -> KnowledgeBase:
    """Return the process-wide shared KnowledgeBase, loading on first access."""
    global _singleton
    if _singleton is None:
        _singleton = KnowledgeBase()
        try:
            _singleton.load()
        except Exception as e:
            log.warning("KB singleton load failed: %s", e)
    return _singleton


def _reset_singleton() -> None:
    """Testing hook — forget the cached singleton."""
    global _singleton
    _singleton = None


def invalidate_translator_kb() -> None:
    """Reload the translator's shared KB after KB mutations.

    The translator module holds its own `_shared_kb` instance (see
    `app/engines/translator.py`) that caches loaded KB data. After any write
    through a CRUD endpoint or the legacy bulk POST, callers should invoke
    this helper so the next translation request sees the fresh data.
    """
    try:
        import app.engines.translator as tmod
        if hasattr(tmod, "_shared_kb"):
            tmod._shared_kb.load()
    except Exception as e:
        log.warning("translator KB reload failed: %s", e)


def build_prompt_snippet(kb) -> str:
    """Build a system-prompt-ready snippet from a ProjectKb (or None).

    Returns an empty string when kb is None or all-empty. Otherwise produces:

        Show context: <title>

        Use EXACTLY these translations (do not paraphrase or substitute):
        [CHARACTERS]
          - Source → Target
          - ...
        [PLACES]
          - ...
        [BRANDS/SLANG/etc.]

        Style: <tone>
        Perspective: <perspective>
        Rules:
          - ...
    """
    from app.engines.kb_models import ProjectKb

    if kb is None:
        return ""
    if isinstance(kb, ProjectKb) and kb.is_empty():
        return ""

    lines = []
    if kb.show_title:
        lines.append(f"Show context: {kb.show_title}")
        lines.append("")

    has_terms = any([kb.characters, kb.places, kb.brands, kb.slang])
    if has_terms:
        lines.append("Use EXACTLY these translations (do not paraphrase or substitute):")
        lines.append("")
        for label, entries in (
            ("CHARACTERS", kb.characters),
            ("PLACES", kb.places),
            ("BRANDS", kb.brands),
            ("SLANG", kb.slang),
        ):
            if not entries:
                continue
            lines.append(f"[{label}]")
            for e in entries:
                note_suffix = f"  ({e.notes})" if e.notes else ""
                lines.append(f"  - {e.source} → {e.target}{note_suffix}")

    sn = kb.style_notes
    if sn.tone or sn.perspective or sn.rules:
        lines.append("")
        if sn.tone:
            lines.append(f"Style: {sn.tone}")
        if sn.perspective:
            lines.append(f"Perspective: {sn.perspective}")
        if sn.rules:
            lines.append("Rules:")
            for r in sn.rules:
                lines.append(f"  - {r}")

    return "\n".join(lines)
