# Knowledge Base Redesign Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Replace the dead-code knowledge base (currently `KnowledgeBase.match([])` always returns the "通用" fallback → KB never actually applied) with a typed, per-project KB that:
1. Stores entries by **category** (characters / places / brands / slang / style_notes) instead of flat term→translation dict
2. Scopes by **project/show** (not global) via `tmdb_id` or `show_title` match
3. **Injects as hard constraints** into translator system prompts (explicit "use EXACTLY these translations for these terms")
4. Supports **CRUD** via API (the view-only UI stays; edit UI lives in Plan 4)
5. Auto-migrates existing `data/knowledge.json` to v2 shape on load

**Not in this plan** (defer):
- `learn()` AI-assisted term extraction from existing SRT → separate future plan
- UI for add/edit/delete → Plan 4 (KB editor page)
- Import/export as files → can be added later

**Architecture:**
- `app/engines/knowledge.py` refactored:
  - `KnowledgeBase` holds `List[KbEntry]` (global) + `Dict[str, ProjectKb]` keyed by `project_key` (tmdb_id or show_title)
  - New dataclasses: `TermEntry`, `StyleNotes`, `KbCategory`, `ProjectKb`
  - `select_for_project(project) -> ProjectKb | None` replaces `match(tags)`
  - `build_prompt_snippet(project_kb) -> str` for injection into translator prompt
- `app/engines/translator.py` `_build_prompt`: replace dead KB call with `KnowledgeBase.select_for_project(project)` + injection
- `app/api/knowledge.py` extended: CRUD routes for categories/entries
- Migration: `_migrate_v1_to_v2(old_dict)` automatically on load; preserve v1 file as `knowledge.v1.backup.json`

**Tech Stack:** Python 3.9, pytest, pydantic (already in use for FastAPI models).

**Spec reference:** Phase 2 "知识库重设计" track in `docs/superpowers/specs/2026-04-19-trailer-translation-and-foundations-design.md` + Phase 1 audit agent 2 findings.

---

## Prerequisites

Phase 3 complete; tag `phase3-trailer-backend-complete` exists. 99 tests pass.

---

## Task 0: Inspect current KB + caller integration

**Files:** none (research only)

### Steps

- [ ] **Step 1: Read current KB code**

```bash
cat app/engines/knowledge.py
```

Note the current class shape, methods, how data is loaded/saved.

- [ ] **Step 2: Find callers**

```bash
grep -rn "knowledge\|KnowledgeBase\|kb_data\|knowledge.json\|my_knowledge" app/ | grep -v __pycache__
```

Identify:
- Where `KnowledgeBase` is instantiated
- Where `match(...)` is called (with what arguments)
- Where `kb_data` flows into `translator._build_prompt`
- Existing API endpoints

- [ ] **Step 3: Inspect current data file**

```bash
ls ~/AI_Sub_Pro_Data/data/knowledge.json 2>/dev/null || ls data/knowledge.json 2>/dev/null
ls my_knowledge.json 2>/dev/null
```

If any exists, `head -c 2000 <file>` to see the shape. Note the top-level keys and nested structure.

- [ ] **Step 4: Report findings**

Write a brief note (no commit) summarizing:
- Current class methods + signatures
- Current call sites with exact line numbers
- Current data shape (representative keys/values)
- Where `_build_prompt` in translator.py injects KB content (line numbers)

This note informs the rest of the plan.

---

## Task 1: New data model + dataclasses

**Files:**
- Create: `app/engines/kb_models.py`
- Test: `tests/test_kb_models.py`

### Steps

- [ ] **Step 1: Write failing tests**

```python
def test_term_entry_defaults():
    from app.engines.kb_models import TermEntry
    t = TermEntry(source="Elsbeth", target="艾尔斯贝丝")
    assert t.source == "Elsbeth"
    assert t.target == "艾尔斯贝丝"
    assert t.notes == ""


def test_term_entry_with_notes():
    from app.engines.kb_models import TermEntry
    t = TermEntry(source="Glamazons", target="魅力女战士", notes="pop culture reference")
    assert t.notes == "pop culture reference"


def test_style_notes_defaults():
    from app.engines.kb_models import StyleNotes
    s = StyleNotes()
    assert s.tone == ""
    assert s.perspective == ""
    assert s.rules == []


def test_style_notes_with_values():
    from app.engines.kb_models import StyleNotes
    s = StyleNotes(tone="conversational", perspective="first person feel", rules=["preserve wit", "use modern idioms"])
    assert s.tone == "conversational"
    assert len(s.rules) == 2


def test_project_kb_defaults():
    from app.engines.kb_models import ProjectKb, StyleNotes
    kb = ProjectKb(show_title="Elsbeth")
    assert kb.show_title == "Elsbeth"
    assert kb.tmdb_id is None
    assert kb.characters == []
    assert kb.places == []
    assert kb.brands == []
    assert kb.slang == []
    assert isinstance(kb.style_notes, StyleNotes)


def test_project_kb_serialize_roundtrip():
    """Convert to dict, back to ProjectKb — no data loss."""
    from app.engines.kb_models import ProjectKb, TermEntry, StyleNotes

    kb = ProjectKb(
        show_title="Elsbeth",
        tmdb_id=123,
        characters=[TermEntry(source="Elsbeth", target="艾尔斯贝丝")],
        places=[TermEntry(source="NJ", target="新泽西")],
        style_notes=StyleNotes(tone="sharp legal humor"),
    )
    data = kb.to_dict()
    restored = ProjectKb.from_dict(data)

    assert restored.show_title == "Elsbeth"
    assert restored.tmdb_id == 123
    assert len(restored.characters) == 1
    assert restored.characters[0].target == "艾尔斯贝丝"
    assert restored.style_notes.tone == "sharp legal humor"


def test_project_kb_from_dict_handles_missing_fields():
    """Robust load: missing category/style sections default to empty."""
    from app.engines.kb_models import ProjectKb
    kb = ProjectKb.from_dict({"show_title": "Foo"})
    assert kb.characters == []
    assert kb.style_notes.tone == ""
```

- [ ] **Step 2:** Run → FAIL (module missing).

- [ ] **Step 3: Write `app/engines/kb_models.py`**

```python
"""Typed data model for per-project knowledge base entries."""
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class TermEntry:
    """One term pair: source language → target language, optional note for translator."""
    source: str
    target: str
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TermEntry":
        return cls(
            source=d.get("source", ""),
            target=d.get("target", ""),
            notes=d.get("notes", ""),
        )


@dataclass
class StyleNotes:
    """Show-specific translation style guidance."""
    tone: str = ""
    perspective: str = ""
    rules: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StyleNotes":
        if not d:
            return cls()
        return cls(
            tone=d.get("tone", ""),
            perspective=d.get("perspective", ""),
            rules=list(d.get("rules", []) or []),
        )


@dataclass
class ProjectKb:
    """Per-project (or per-show) knowledge base entry set."""
    show_title: str = ""
    tmdb_id: Optional[int] = None
    characters: List[TermEntry] = field(default_factory=list)
    places: List[TermEntry] = field(default_factory=list)
    brands: List[TermEntry] = field(default_factory=list)
    slang: List[TermEntry] = field(default_factory=list)
    style_notes: StyleNotes = field(default_factory=StyleNotes)

    def to_dict(self) -> dict:
        return {
            "show_title": self.show_title,
            "tmdb_id": self.tmdb_id,
            "characters": [t.to_dict() for t in self.characters],
            "places": [t.to_dict() for t in self.places],
            "brands": [t.to_dict() for t in self.brands],
            "slang": [t.to_dict() for t in self.slang],
            "style_notes": self.style_notes.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectKb":
        if not d:
            return cls()
        return cls(
            show_title=d.get("show_title", ""),
            tmdb_id=d.get("tmdb_id"),
            characters=[TermEntry.from_dict(t) for t in d.get("characters", []) or []],
            places=[TermEntry.from_dict(t) for t in d.get("places", []) or []],
            brands=[TermEntry.from_dict(t) for t in d.get("brands", []) or []],
            slang=[TermEntry.from_dict(t) for t in d.get("slang", []) or []],
            style_notes=StyleNotes.from_dict(d.get("style_notes", {})),
        )

    def is_empty(self) -> bool:
        return not (self.characters or self.places or self.brands or self.slang or self.style_notes.tone)
```

- [ ] **Step 4:** Run tests → PASS. Full suite → 106 passed (99 + 7).

- [ ] **Step 5: Commit**

```bash
git add app/engines/kb_models.py tests/test_kb_models.py
git commit -m "feat(kb): typed data model — TermEntry/StyleNotes/ProjectKb"
```

---

## Task 2: Migration from v1 (flat) to v2 (typed categories)

**Files:**
- Create: `app/engines/kb_migration.py`
- Test: `tests/test_kb_migration.py`

### Steps

- [ ] **Step 1: Write failing tests**

```python
def test_migrate_v1_flat_to_v2_structured():
    """Old shape: {'Elsbeth': {'keywords': [...], 'style': '...', 'terms': {...}}} →
       New: {'Elsbeth': {'show_title': 'Elsbeth', 'characters': [{source, target, notes}], ...}}
    """
    from app.engines.kb_migration import migrate_v1_to_v2

    v1 = {
        "Elsbeth": {
            "keywords": ["Elsbeth", "Matlock", "legal"],
            "style": "conversational, sharp legal humor",
            "terms": {
                "Elsbeth Tascioni": "艾尔斯贝丝·塔西奥尼",
                "Matlock": "马特洛克",
            },
        },
        "通用": {
            "keywords": [],
            "style": "",
            "terms": {},
        },
    }

    v2 = migrate_v1_to_v2(v1)
    assert "Elsbeth" in v2
    proj = v2["Elsbeth"]
    assert proj["show_title"] == "Elsbeth"
    # All v1 'terms' go into characters by default (can be manually re-categorized later)
    sources = {t["source"] for t in proj["characters"]}
    assert "Elsbeth Tascioni" in sources
    assert "Matlock" in sources
    # Style preserved
    assert "legal humor" in proj["style_notes"]["tone"].lower() or "legal humor" in " ".join(proj["style_notes"].get("rules", [])).lower() or proj["style_notes"]["tone"] == "conversational, sharp legal humor"


def test_migrate_v2_data_passes_through_unchanged():
    """If data is already v2 (has 'characters' key), don't re-migrate."""
    from app.engines.kb_migration import migrate_v1_to_v2, is_v2_shape

    v2_input = {
        "Elsbeth": {
            "show_title": "Elsbeth",
            "characters": [{"source": "Elsbeth", "target": "艾尔斯贝丝", "notes": ""}],
            "places": [],
            "brands": [],
            "slang": [],
            "style_notes": {"tone": "", "perspective": "", "rules": []},
        },
    }
    assert is_v2_shape(v2_input) is True
    assert migrate_v1_to_v2(v2_input) == v2_input


def test_migrate_handles_swapped_src_dst_entries():
    """v1 data has known bad entries where src/dst look swapped (e.g. 'src':'不','dst':'No.'). Migration should NOT silently drop these — preserve as best-effort."""
    from app.engines.kb_migration import migrate_v1_to_v2

    v1 = {
        "Test": {
            "keywords": [],
            "style": "",
            "terms": {"不": "No.", "Hello": "你好"},
        }
    }
    v2 = migrate_v1_to_v2(v1)
    sources = {t["source"] for t in v2["Test"]["characters"]}
    assert "不" in sources  # preserve as-is
    assert "Hello" in sources


def test_is_v2_shape_detects_both():
    from app.engines.kb_migration import is_v2_shape
    assert is_v2_shape({"X": {"show_title": "X", "characters": []}}) is True
    assert is_v2_shape({"X": {"keywords": [], "terms": {}}}) is False
    assert is_v2_shape({}) is True  # empty is "already v2" (no migration needed)
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `app/engines/kb_migration.py`**

```python
"""Migrate knowledge.json from v1 (flat term→translation dict) to v2 (typed categories)."""
import logging
from typing import Dict

log = logging.getLogger(__name__)


def is_v2_shape(data: dict) -> bool:
    """Detect v2 shape: each project entry has 'characters' or 'style_notes' keys."""
    if not data:
        return True  # empty is trivially v2
    for key, val in data.items():
        if not isinstance(val, dict):
            return False
        if "characters" in val or "style_notes" in val:
            return True
        if "terms" in val or "keywords" in val:
            return False
    # Unknown shape: assume v2 to avoid destructive migration
    return True


def migrate_v1_to_v2(data: dict) -> dict:
    """Convert old knowledge.json shape to the new ProjectKb-compatible shape.

    v1 entry: {"keywords": [...], "style": "...", "terms": {src: dst, ...}}
    v2 entry: {"show_title": name, "tmdb_id": null, "characters": [{source, target, notes}], ..., "style_notes": {...}}

    All v1 terms are bucketed into `characters` by default — user can re-categorize later.
    """
    if is_v2_shape(data):
        return data

    v2: Dict[str, dict] = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            log.warning("kb migration: skipping non-dict entry %r", name)
            continue
        terms_dict = entry.get("terms", {}) or {}
        characters = [
            {"source": str(src), "target": str(dst), "notes": ""}
            for src, dst in terms_dict.items()
        ]
        style_text = entry.get("style", "") or ""
        v2[name] = {
            "show_title": name,
            "tmdb_id": None,
            "characters": characters,
            "places": [],
            "brands": [],
            "slang": [],
            "style_notes": {
                "tone": style_text,
                "perspective": "",
                "rules": [],
            },
            # Preserve keywords for potential future use (also helps legacy matchers)
            "_legacy_keywords": list(entry.get("keywords", []) or []),
        }
    return v2
```

- [ ] **Step 4:** Run tests → PASS. Full suite → 110 passed (106 + 4).

- [ ] **Step 5: Commit**

```bash
git add app/engines/kb_migration.py tests/test_kb_migration.py
git commit -m "feat(kb): migration helper v1 flat terms → v2 typed categories"
```

---

## Task 3: Refactor KnowledgeBase class — load/save/select

**Files:**
- Modify: `app/engines/knowledge.py`
- Test: `tests/test_knowledge_base_v2.py`

### Steps

- [ ] **Step 1: Write failing tests**

```python
import json


def test_knowledge_base_load_auto_migrates_v1(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module

    # Patch KB_FILE location
    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(kb_module, "KB_FILE", kb_file)

    # Seed with v1 data
    v1 = {"Elsbeth": {"keywords": [], "style": "sharp", "terms": {"Elsbeth": "艾"}}}
    kb_file.write_text(json.dumps(v1), encoding="utf-8")

    kb = kb_module.KnowledgeBase()
    kb.load()

    # Should have migrated to v2 in memory
    proj = kb.get_project("Elsbeth")
    assert proj is not None
    assert proj.show_title == "Elsbeth"
    sources = [t.source for t in proj.characters]
    assert "Elsbeth" in sources

    # Backup of v1 should exist
    backup = tmp_path / "knowledge.v1.backup.json"
    assert backup.exists()


def test_knowledge_base_save_writes_v2_format(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb, TermEntry

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(kb_module, "KB_FILE", kb_file)

    kb = kb_module.KnowledgeBase()
    proj = ProjectKb(show_title="Test", characters=[TermEntry(source="Hi", target="你好")])
    kb.set_project("Test", proj)
    kb.save()

    data = json.loads(kb_file.read_text())
    assert "Test" in data
    assert data["Test"]["show_title"] == "Test"
    assert data["Test"]["characters"][0]["source"] == "Hi"


def test_knowledge_base_select_by_tmdb_id(tmp_path, monkeypatch):
    """Match a project KB by tmdb_id when the project metadata has one."""
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(kb_module, "KB_FILE", kb_file)

    kb = kb_module.KnowledgeBase()
    kb.set_project("elsbeth_s1", ProjectKb(show_title="Elsbeth", tmdb_id=1399))

    # Project metadata has matching tmdb_id
    selected = kb.select_for_project({"tmdb_id": 1399, "name": "Random"})
    assert selected is not None
    assert selected.show_title == "Elsbeth"


def test_knowledge_base_select_by_show_title_fallback(tmp_path, monkeypatch):
    """If no tmdb_id match, fall back to show_title substring match."""
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(kb_module, "KB_FILE", kb_file)

    kb = kb_module.KnowledgeBase()
    kb.set_project("elsbeth", ProjectKb(show_title="Elsbeth", tmdb_id=None))

    # No tmdb match; show_title substring found in project name
    selected = kb.select_for_project({"tmdb_id": None, "name": "Elsbeth S01E01"})
    assert selected is not None
    assert selected.show_title == "Elsbeth"


def test_knowledge_base_select_returns_none_when_no_match(tmp_path, monkeypatch):
    from app.engines import knowledge as kb_module
    from app.engines.kb_models import ProjectKb

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(kb_module, "KB_FILE", kb_file)

    kb = kb_module.KnowledgeBase()
    kb.set_project("foo", ProjectKb(show_title="Foo"))

    selected = kb.select_for_project({"tmdb_id": 999, "name": "Something unrelated"})
    assert selected is None
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Rewrite `app/engines/knowledge.py`**

Read the original file first to understand the legacy interface. Keep a **`match(tags)` alias** for backward-compat (returns an empty-looking dict) so translator.py's existing call doesn't crash during the transition.

```python
"""Knowledge base for per-project translation context.

v2 format: typed categories + per-project/show scope.
v1 format auto-migrated on load, with .v1.backup.json preserved.
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional

from app.config import KB_FILE
from app.engines.kb_models import ProjectKb
from app.engines.kb_migration import is_v2_shape, migrate_v1_to_v2

log = logging.getLogger(__name__)


class KnowledgeBase:
    """Holds all ProjectKb entries and provides select + save operations."""

    def __init__(self):
        self._projects: Dict[str, ProjectKb] = {}

    def load(self) -> None:
        """Load knowledge.json. Auto-migrates v1 and backs up the old file."""
        path = Path(KB_FILE)
        if not path.exists():
            self._projects = {}
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("knowledge.json unreadable: %s; starting empty", e)
            self._projects = {}
            return

        if not is_v2_shape(raw):
            # Back up the old file before migration
            backup = path.parent / "knowledge.v1.backup.json"
            try:
                backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception as e:
                log.warning("failed to write KB v1 backup: %s", e)
            raw = migrate_v1_to_v2(raw)
            # Save the migrated version immediately
            self._projects = {k: ProjectKb.from_dict(v) for k, v in raw.items()}
            self.save()
            log.info("migrated knowledge.json from v1 to v2 (%d projects)", len(self._projects))
            return

        self._projects = {k: ProjectKb.from_dict(v) for k, v in raw.items()}

    def save(self) -> None:
        path = Path(KB_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: p.to_dict() for k, p in self._projects.items()}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_project(self, key: str) -> Optional[ProjectKb]:
        return self._projects.get(key)

    def set_project(self, key: str, kb: ProjectKb) -> None:
        self._projects[key] = kb

    def delete_project(self, key: str) -> bool:
        return self._projects.pop(key, None) is not None

    def list_projects(self) -> Dict[str, ProjectKb]:
        return dict(self._projects)

    def select_for_project(self, project: dict) -> Optional[ProjectKb]:
        """Find the best KB for a project dict based on tmdb_id → show_title substring.

        Priority:
        1. Exact tmdb_id match
        2. Case-insensitive substring match between any KB's show_title and project['name']
        3. None
        """
        tmdb_id = project.get("tmdb_id") if isinstance(project, dict) else None
        name = (project.get("name") or "") if isinstance(project, dict) else ""

        if tmdb_id is not None:
            for kb in self._projects.values():
                if kb.tmdb_id is not None and kb.tmdb_id == tmdb_id:
                    return kb

        lname = name.lower()
        if lname:
            for kb in self._projects.values():
                if kb.show_title and kb.show_title.lower() in lname:
                    return kb

        return None

    # --- Legacy compat (translator.py used to call .match(tags)) ---
    def match(self, tags) -> dict:
        """Legacy compat: return a dict shaped like the old '通用' fallback.

        Callers that still use .match() get an empty structure; translator.py should
        migrate to select_for_project() and build_prompt_snippet() instead.
        """
        return {"keywords": [], "style": "", "terms": {}}
```

- [ ] **Step 4:** Run tests → PASS. Full suite → 115 passed (110 + 5).

- [ ] **Step 5: Commit**

```bash
git add app/engines/knowledge.py tests/test_knowledge_base_v2.py
git commit -m "feat(kb): v2 KnowledgeBase with per-project select_for_project + auto-migrate"
```

---

## Task 4: Prompt snippet builder — inject KB as hard constraints

**Files:**
- Modify: `app/engines/knowledge.py` (add `build_prompt_snippet`)
- Test: `tests/test_kb_prompt_snippet.py`

### Steps

- [ ] **Step 1: Write failing tests**

```python
def test_build_prompt_snippet_empty_kb_returns_empty_string():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb
    assert build_prompt_snippet(None) == ""
    assert build_prompt_snippet(ProjectKb(show_title="Foo")) == ""  # empty categories


def test_build_prompt_snippet_includes_characters_as_strict_terms():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, TermEntry

    kb = ProjectKb(
        show_title="Elsbeth",
        characters=[
            TermEntry(source="Elsbeth Tascioni", target="艾尔斯贝丝·塔西奥尼"),
            TermEntry(source="Matlock", target="马特洛克"),
        ],
    )
    out = build_prompt_snippet(kb)
    # Must use strict phrasing
    assert ("EXACTLY" in out) or ("必须" in out) or ("strictly" in out.lower())
    # Must include both term pairs
    assert "Elsbeth Tascioni" in out and "艾尔斯贝丝·塔西奥尼" in out
    assert "Matlock" in out and "马特洛克" in out


def test_build_prompt_snippet_groups_by_category():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, TermEntry

    kb = ProjectKb(
        show_title="Test",
        characters=[TermEntry(source="Name", target="名字")],
        places=[TermEntry(source="Place", target="地点")],
        brands=[TermEntry(source="Brand", target="品牌")],
        slang=[TermEntry(source="Slang", target="俚语")],
    )
    out = build_prompt_snippet(kb)
    # Each category appears as a labeled section (case-insensitive OK)
    for label in ("CHARACTERS", "PLACES", "BRANDS", "SLANG"):
        assert label in out.upper()


def test_build_prompt_snippet_includes_style_notes():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, StyleNotes

    kb = ProjectKb(
        show_title="Test",
        style_notes=StyleNotes(
            tone="conversational, sharp",
            perspective="first-person feel",
            rules=["preserve wit", "use modern idioms"],
        ),
    )
    out = build_prompt_snippet(kb)
    assert "conversational" in out
    assert "preserve wit" in out


def test_build_prompt_snippet_includes_notes_as_context():
    """TermEntry.notes should be attached as parenthetical context."""
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, TermEntry

    kb = ProjectKb(
        show_title="Test",
        slang=[TermEntry(source="Glamazons", target="魅力女战士", notes="pop culture")],
    )
    out = build_prompt_snippet(kb)
    assert "Glamazons" in out
    assert "魅力女战士" in out
    # notes appear somewhere nearby
    assert "pop culture" in out
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Add `build_prompt_snippet` in `app/engines/knowledge.py`**

Append to the module (after the class):

```python
def build_prompt_snippet(kb) -> str:
    """Build a system-prompt-ready snippet from a ProjectKb (or None for empty).

    Output shape (example):

        Show context: Elsbeth

        Use EXACTLY these translations (do not paraphrase or substitute):

        [CHARACTERS]
          - Elsbeth Tascioni → 艾尔斯贝丝·塔西奥尼
          - Matlock → 马特洛克
        [PLACES]
          - New Jersey → 新泽西
        [SLANG]
          - Glamazons → 魅力女战士  (pop culture)

        Style: conversational, sharp legal humor
        Perspective: first-person feel
        Rules:
          - preserve character wit
          - use modern Mandarin idioms
    """
    from app.engines.kb_models import ProjectKb
    if kb is None or (isinstance(kb, ProjectKb) and kb.is_empty()):
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
```

- [ ] **Step 4:** Run tests → PASS. Full suite → 120 passed.

- [ ] **Step 5: Commit**

```bash
git add app/engines/knowledge.py tests/test_kb_prompt_snippet.py
git commit -m "feat(kb): prompt snippet builder — categorized terms as hard constraints"
```

---

## Task 5: Wire translator.py to use v2 KB

**Files:**
- Modify: `app/engines/translator.py` (`_build_prompt`)
- Test: `tests/test_translator_kb_integration.py`

### Steps

- [ ] **Step 1: Inspect current `_build_prompt`**

```bash
grep -n "_build_prompt\|kb_data\|knowledge" app/engines/translator.py | head -20
```

Read the function — understand how `kb_data` currently flows in. Note line numbers.

- [ ] **Step 2: Write failing tests**

```python
def test_build_prompt_includes_kb_snippet_when_kb_selected(monkeypatch):
    """When a project matches a KB, _build_prompt must include the prompt snippet."""
    from app.engines.translator import SubtitleTranslator
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb, TermEntry, StyleNotes

    # Stub a populated KB
    kb = KnowledgeBase()
    kb.set_project("test", ProjectKb(
        show_title="TestShow",
        characters=[TermEntry(source="Alice", target="爱丽丝")],
        style_notes=StyleNotes(tone="formal"),
    ))

    monkeypatch.setattr("app.engines.translator._shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai", "primary_model": "gpt-4o",
            "polish_provider": "", "batch_size": 10, "context_window": 3,
            "target_language": "简体中文",
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = SubtitleTranslator(cfg)

    # Project metadata carrying name that matches "TestShow"
    meta = {"name": "TestShow S01E02", "tmdb_id": None}
    prompt = t._build_prompt(
        target_lang="简体中文",
        meta_info=meta,
        kb_data=None,  # legacy arg ignored in v2 path
        context_before=[],
        context_after=[],
    )
    assert "Alice" in prompt
    assert "爱丽丝" in prompt
    assert "formal" in prompt


def test_build_prompt_no_kb_when_no_match(monkeypatch):
    """When no KB matches, prompt must not contain any KB section markers (CHARACTERS, PLACES, etc)."""
    from app.engines.translator import SubtitleTranslator
    from app.engines.knowledge import KnowledgeBase

    # Empty KB
    kb = KnowledgeBase()
    monkeypatch.setattr("app.engines.translator._shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai", "primary_model": "gpt-4o",
            "polish_provider": "", "batch_size": 10, "context_window": 3,
            "target_language": "简体中文",
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = SubtitleTranslator(cfg)
    meta = {"name": "Random", "tmdb_id": None}
    prompt = t._build_prompt(
        target_lang="简体中文", meta_info=meta, kb_data=None,
        context_before=[], context_after=[],
    )
    assert "CHARACTERS" not in prompt
    assert "Use EXACTLY" not in prompt
```

- [ ] **Step 3:** Run → FAIL.

- [ ] **Step 4: Modify `translator.py`**

Add a module-level shared KB instance (loaded on import) and use it in `_build_prompt`:

```python
# Near top of translator.py, after other imports:
from app.engines.knowledge import KnowledgeBase, build_prompt_snippet

_shared_kb: KnowledgeBase = KnowledgeBase()
try:
    _shared_kb.load()
except Exception as _e:
    log.warning("knowledge base load failed: %s", _e)
```

In `_build_prompt(...)` method, find where `kb_data` is currently injected (grep found the line around 278-281 in Phase 1 audit). Replace the legacy injection with:

```python
# v2 KB injection: select by project metadata + inject as hard constraints
kb_snippet = ""
try:
    project_kb = _shared_kb.select_for_project(meta_info or {})
    if project_kb is not None:
        kb_snippet = build_prompt_snippet(project_kb)
except Exception as e:
    log.warning("KB injection failed: %s", e)
    kb_snippet = ""

# ... existing prompt builder ...
# Inject kb_snippet into the system prompt where the legacy style/terms used to go.
# If kb_snippet is non-empty, append it in its own paragraph.
```

Concrete: in the part where the existing prompt text is assembled, add a block like:

```python
if kb_snippet:
    prompt_parts.append(kb_snippet)
```

Keep the legacy `kb_data` parameter in the signature for back-compat, but IGNORE it when the new `_shared_kb` path produces content.

- [ ] **Step 5:** Run tests → PASS. Full suite → 122 passed.

- [ ] **Step 6: Commit**

```bash
git add app/engines/translator.py tests/test_translator_kb_integration.py
git commit -m "feat(translator): wire v2 KB injection via select_for_project + build_prompt_snippet"
```

---

## Task 6: KB CRUD API endpoints

**Files:**
- Modify: `app/api/knowledge.py` (extend)
- Test: `tests/test_knowledge_api.py`

### Steps

- [ ] **Step 1: Inspect existing knowledge API**

```bash
grep -n "@router\|def " app/api/knowledge.py
```

Note existing routes and the prefix.

- [ ] **Step 2: Write failing tests**

```python
from fastapi.testclient import TestClient


def test_kb_list_projects_empty(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    r = client.get("/api/knowledge/projects")
    assert r.status_code == 200
    assert r.json() == {"projects": []}


def test_kb_create_and_get_project(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    payload = {
        "key": "elsbeth",
        "show_title": "Elsbeth",
        "tmdb_id": 1399,
        "characters": [{"source": "Elsbeth Tascioni", "target": "艾尔斯贝丝"}],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "sharp legal humor", "perspective": "", "rules": []},
    }
    r = client.put("/api/knowledge/projects/elsbeth", json=payload)
    assert r.status_code in (200, 201)

    r = client.get("/api/knowledge/projects/elsbeth")
    assert r.status_code == 200
    data = r.json()
    assert data["show_title"] == "Elsbeth"
    assert data["characters"][0]["source"] == "Elsbeth Tascioni"


def test_kb_delete_project(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    client.put("/api/knowledge/projects/temp", json={
        "key": "temp", "show_title": "Temp",
        "characters": [], "places": [], "brands": [], "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })
    r = client.delete("/api/knowledge/projects/temp")
    assert r.status_code == 200

    r = client.get("/api/knowledge/projects/temp")
    assert r.status_code == 404
```

Create a `patched_kb_file` fixture at top of the test file that points `KB_FILE` to a tmp path AND also refreshes the shared KB singleton in translator.py:

```python
import pytest


@pytest.fixture
def patched_kb_file(tmp_path, monkeypatch):
    # Patch both config and loaded singletons
    import app.config as cfg
    import app.engines.knowledge as kb_mod

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(cfg, "KB_FILE", kb_file)
    monkeypatch.setattr(kb_mod, "KB_FILE", kb_file)

    # Reset shared singleton if translator imported one
    try:
        import app.engines.translator as tmod
        fresh = kb_mod.KnowledgeBase()
        monkeypatch.setattr(tmod, "_shared_kb", fresh, raising=False)
    except ImportError:
        pass

    # Also replace the API's in-memory KB
    try:
        import app.api.knowledge as kbapi
        monkeypatch.setattr(kbapi, "_kb", kb_mod.KnowledgeBase(), raising=False)
    except Exception:
        pass

    return kb_file
```

- [ ] **Step 3:** Run → FAIL.

- [ ] **Step 4: Extend `app/api/knowledge.py`**

Look at existing router declaration (prefix, tags). Add new endpoints:

```python
from typing import List, Optional
from pydantic import BaseModel

from app.engines.knowledge import KnowledgeBase
from app.engines.kb_models import ProjectKb


class TermEntryIn(BaseModel):
    source: str
    target: str
    notes: str = ""


class StyleNotesIn(BaseModel):
    tone: str = ""
    perspective: str = ""
    rules: List[str] = []


class ProjectKbIn(BaseModel):
    key: str
    show_title: str = ""
    tmdb_id: Optional[int] = None
    characters: List[TermEntryIn] = []
    places: List[TermEntryIn] = []
    brands: List[TermEntryIn] = []
    slang: List[TermEntryIn] = []
    style_notes: StyleNotesIn = StyleNotesIn()


# Lazy-load a shared KB (use the same singleton as translator if possible)
_kb = KnowledgeBase()
try:
    _kb.load()
except Exception:
    pass


@router.get("/knowledge/projects")
def list_kb_projects():
    return {"projects": [
        {"key": k, "show_title": p.show_title, "tmdb_id": p.tmdb_id}
        for k, p in _kb.list_projects().items()
    ]}


@router.get("/knowledge/projects/{key}")
def get_kb_project(key: str):
    p = _kb.get_project(key)
    if p is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="project KB not found")
    return p.to_dict()


@router.put("/knowledge/projects/{key}")
def put_kb_project(key: str, body: ProjectKbIn):
    proj = ProjectKb(
        show_title=body.show_title,
        tmdb_id=body.tmdb_id,
        characters=[TermEntry(source=t.source, target=t.target, notes=t.notes) for t in body.characters],
        places=[TermEntry(source=t.source, target=t.target, notes=t.notes) for t in body.places],
        brands=[TermEntry(source=t.source, target=t.target, notes=t.notes) for t in body.brands],
        slang=[TermEntry(source=t.source, target=t.target, notes=t.notes) for t in body.slang],
        style_notes=StyleNotes(tone=body.style_notes.tone, perspective=body.style_notes.perspective, rules=list(body.style_notes.rules)),
    )
    _kb.set_project(key, proj)
    _kb.save()
    # Invalidate translator's shared KB cache so next translation sees the update
    try:
        import app.engines.translator as tmod
        if hasattr(tmod, "_shared_kb"):
            tmod._shared_kb.load()
    except Exception:
        pass
    return {"ok": True}


@router.delete("/knowledge/projects/{key}")
def delete_kb_project(key: str):
    removed = _kb.delete_project(key)
    if not removed:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="not found")
    _kb.save()
    try:
        import app.engines.translator as tmod
        if hasattr(tmod, "_shared_kb"):
            tmod._shared_kb.load()
    except Exception:
        pass
    return {"ok": True}
```

Make sure to `from app.engines.kb_models import TermEntry, StyleNotes` at the top.

- [ ] **Step 5:** Run tests → PASS. Full suite → 125 passed.

- [ ] **Step 6: Commit**

```bash
git add app/api/knowledge.py tests/test_knowledge_api.py
git commit -m "feat(kb): CRUD API — list/get/put/delete per-project knowledge"
```

---

## Task 7: Smoke + audit gate

### Steps

- [ ] **Step 1: Full suite**
`python3 -m pytest -v` → expect ~125 passed.

- [ ] **Step 2: Import smoke**
`python3 -c "from app.main import app; print('ok')"`

- [ ] **Step 3: Tag**
`git tag kb-redesign-complete`

- [ ] **Step 4: Audit gate** — 3 parallel agents:
  - **Agent A — Migration safety**: old knowledge.json files load and migrate; v1 backup preserved; no data loss
  - **Agent B — Prompt injection correctness**: snippet format matches spec; strict phrasing present; no legacy code path still active
  - **Agent C — API wire-up**: CRUD endpoints work; translator's shared KB invalidates on mutation; backward compat for existing legacy `.match()` callers

If any audit fails, fix before calling done.

---

## Out of this plan

- **learn()** — auto-extract terms from existing SRT via Claude CLI (separate future plan)
- **UI** — KB editor page with add/edit/delete forms → Plan 4
- **Global KB** — entries that apply across all projects (can add a `_global` key later)
- **Export/import as JSON file** — simple addition later, not required now
