# Phase 1 — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the config/schema extensions, three critical bugfixes (B1/B2/B3), and a centralized scheduler (semaphores + locked progress store with persistence + cooperative cancel) — everything downstream plans depend on.

**Architecture:** All changes are additive or localized. Config uses the existing `_deep_merge` so missing keys auto-populate from defaults. Legacy project JSONs get safe defaults at load time via `setdefault()`. A new `app/engines/scheduler.py` centralizes concurrency, progress state, and cancellation — existing `api/translate.py` is refactored to route through it.

**Tech Stack:** Python 3.11+, FastAPI, pytest, threading. No new runtime dependencies in this plan.

**Spec reference:** `docs/superpowers/specs/2026-04-19-trailer-translation-and-foundations-design.md` — this plan implements §4, §7, and B1/B2/B3 from §10.

**Out of scope for this plan** (covered by later plans):
- B4/B5 (ASR VAD + mlx beam_size) → Plan 2 (touches ASR engine during translator work)
- B6/B7 (other `except: pass`) → Phase 4
- Provider abstraction / Claude CLI → Plan 2
- Bilingual burn → Plan 3
- Trailer module → Plan 3
- UI → Plan 4

---

## Prerequisites (do before Task 0)

1. **Git**: AI_Sub_Pro is not a git repo. Run once:
   ```bash
   cd /Users/gaopengxiang/Desktop/AI_Sub_Pro
   git init
   git add .
   git commit -m "chore: baseline before Phase 1 foundations"
   ```
2. **pytest**: `pip install pytest` (if not already on PATH).
3. **Python version**: ≥3.10 (spec uses `|` type syntax).

---

## Task 0: Set up test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `pytest.ini`

### Steps

- [ ] **Step 1: Create empty package marker**

```bash
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Step 2: Create pytest.ini**

Write `pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -v
filterwarnings =
    ignore::DeprecationWarning
```

- [ ] **Step 3: Create conftest.py with shared fixtures**

Write `tests/conftest.py`:
```python
import pytest
from pathlib import Path


@pytest.fixture
def tmp_project_dir(tmp_path, monkeypatch):
    """Isolated data/projects dir. Patches app.config paths + scheduler PROJECTS_DIR."""
    import app.config as cfg
    data_dir = tmp_path / "data"
    projects_dir = data_dir / "projects"
    projects_dir.mkdir(parents=True)
    monkeypatch.setattr(cfg, "DATA_DIR", data_dir)
    monkeypatch.setattr(cfg, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(cfg, "CONFIG_FILE", data_dir / "config.json")
    # Scheduler module captures PROJECTS_DIR at import; patch there too
    try:
        import app.engines.scheduler as sch
        monkeypatch.setattr(sch, "PROJECTS_DIR", projects_dir, raising=False)
    except ImportError:
        pass  # scheduler doesn't exist yet until Task 7
    return projects_dir
```

- [ ] **Step 4: Verify pytest collects 0 tests without error**

Run: `pytest --collect-only`
Expected: `collected 0 items`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add tests/ pytest.ini
git commit -m "chore: set up pytest infrastructure"
```

---

## Task 1: Extend DEFAULT_CONFIG with new sections

**Files:**
- Modify: `app/config.py` (DEFAULT_CONFIG dict)
- Test: `tests/test_config.py`

### Steps

- [ ] **Step 1: Write failing test**

Write `tests/test_config.py`:
```python
from app.config import DEFAULT_CONFIG


def test_default_config_has_tmdb_section():
    assert "tmdb" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["tmdb"] == {"api_key": "", "language": "zh-CN"}


def test_default_config_has_providers_claude_cli():
    assert "providers" in DEFAULT_CONFIG
    cc = DEFAULT_CONFIG["providers"]["claude_cli"]
    assert cc["enabled"] is True
    assert cc["model"] == "claude-opus-4-7"
    assert cc["timeout_sec"] == 180


def test_default_config_has_concurrency_section():
    c = DEFAULT_CONFIG["concurrency"]
    assert c["asr"] == 2
    assert c["translate"] == 4
    assert c["download"] == 3
    assert c["burn"] == 1


def test_default_config_translation_has_full_doc_mode():
    assert DEFAULT_CONFIG["translation"]["full_doc_mode"] is False
```

- [ ] **Step 2: Run, verify FAIL**

Run: `pytest tests/test_config.py -v`
Expected: 4 failures (KeyError on missing sections).

- [ ] **Step 3: Extend DEFAULT_CONFIG**

In `app/config.py`, add new sections alongside existing ones. The full updated dict:
```python
DEFAULT_CONFIG = {
    "api_keys": {
        "openai": "",
        "deepseek": "",
        "gemini": "",
    },
    "tmdb": {
        "api_key": "",
        "language": "zh-CN",
    },
    "asr": {
        "model_size": "large-v3",
        "language": "auto",
        "vad_filter": True,
        "offset_ms": 0,
        "beam_size": 5,
        "use_demucs": True,
    },
    "translation": {
        "primary_provider": "openai",
        "primary_model": "gpt-4o",
        "polish_provider": "",
        "polish_model": "",
        "batch_size": 10,
        "context_window": 3,
        "target_language": "简体中文",
        "filter_repetitive": True,
        "repetitive_threshold": 3,
        "filter_interjections": True,
        "full_doc_mode": False,
    },
    "providers": {
        "claude_cli": {
            "enabled": True,
            "model": "claude-opus-4-7",
            "timeout_sec": 180,
        },
    },
    "concurrency": {
        "asr": 2,
        "translate": 4,
        "download": 3,
        "burn": 1,
    },
    "general": {
        "max_workers": 4,
        "theme": "dark",
    },
}
```

- [ ] **Step 4: Run, verify PASS**

Run: `pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat(config): extend DEFAULT_CONFIG with tmdb/providers/concurrency/full_doc_mode"
```

---

## Task 2: Verify backward-compatible config merge (regression guard)

**Files:**
- Test only: `tests/test_config.py` (append)

### Steps

- [ ] **Step 1: Append regression test**

Append to `tests/test_config.py`:
```python
import json


def test_config_loads_and_merges_partial_saved_config(tmp_path, monkeypatch):
    """Old config.json without new sections still loads; new keys populate from DEFAULT_CONFIG."""
    import app.config as cfg
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", cfg_file)

    old = {
        "api_keys": {"openai": "sk-legacy"},
        "translation": {"primary_provider": "openai", "primary_model": "gpt-4o"},
    }
    cfg_file.write_text(json.dumps(old))

    cfg.Config._data = {}  # reset class-level state
    cfg.Config.load()
    loaded = cfg.Config.to_dict()

    # Existing values preserved
    assert loaded["api_keys"]["openai"] == "sk-legacy"
    assert loaded["translation"]["primary_provider"] == "openai"
    # New sections auto-populated
    assert loaded["tmdb"]["language"] == "zh-CN"
    assert loaded["concurrency"]["asr"] == 2
    assert loaded["providers"]["claude_cli"]["enabled"] is True
    assert loaded["translation"]["full_doc_mode"] is False
```

- [ ] **Step 2: Run, verify PASS immediately**

Run: `pytest tests/test_config.py::test_config_loads_and_merges_partial_saved_config -v`
Expected: PASS (existing `_deep_merge` handles this).

If FAIL: read `_deep_merge` in `app/config.py` — it may not recurse into nested dicts for the new sections. Fix `_deep_merge` if needed before declaring done.

- [ ] **Step 3: Commit**

```bash
git add tests/test_config.py
git commit -m "test(config): guard backward-compat merge for new sections"
```

---

## Task 3: Project schema safe defaults on load

**Files:**
- Modify: `app/api/projects.py`
- Test: `tests/test_projects_loader.py`

### Steps

- [ ] **Step 1: Locate the project loader**

Run: `grep -n "def.*project\|load.*project\|PROJECTS_DIR" app/api/projects.py | head -20`

Identify the function that reads a project's `project.json` from disk and returns the dict (likely `_load_project`, `get_project`, or similar). Note its exact name and line range.

- [ ] **Step 2: Write failing test**

Write `tests/test_projects_loader.py` (use the loader function name you found; below uses `_load_project` as placeholder — rename if your codebase differs):
```python
import json


def test_legacy_project_gets_safe_defaults(tmp_project_dir):
    from app.api.projects import _load_project  # rename to match actual function

    pid = "legacy01"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid,
        "name": "old",
        "video_path": "/old.mp4",
        "created_at": "2024-01-01",
        "status": "completed",
        "progress": 100,
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = _load_project(pid)

    # Existing fields preserved
    assert loaded["status"] == "completed"
    assert loaded["name"] == "old"
    # New fields defaulted
    assert loaded["source_type"] == "upload"
    assert loaded["auto_run"] is False
    assert loaded["tmdb_id"] is None
    assert loaded["tmdb_type"] is None
    assert loaded["season_number"] is None
    assert loaded["tmdb_video_key"] is None
    assert loaded["youtube_url"] is None
    assert loaded["original_language"] is None
    assert loaded["parent_project_id"] is None
    assert loaded["pipeline_stage"] is None
    assert loaded["archived"] is False
```

- [ ] **Step 3: Run, verify FAIL**

Run: `pytest tests/test_projects_loader.py -v`
Expected: FAIL with KeyError on `source_type`.

- [ ] **Step 4: Add safe defaults**

In `app/api/projects.py`, near the top (module level):
```python
_PROJECT_SAFE_DEFAULTS = {
    "source_type": "upload",
    "auto_run": False,
    "tmdb_id": None,
    "tmdb_type": None,
    "season_number": None,
    "tmdb_video_key": None,
    "youtube_url": None,
    "original_language": None,
    "parent_project_id": None,
    "pipeline_stage": None,
    "archived": False,
}


def _apply_safe_defaults(project: dict) -> dict:
    for k, v in _PROJECT_SAFE_DEFAULTS.items():
        project.setdefault(k, v)
    return project
```

Inside the loader function, right before returning the project dict:
```python
return _apply_safe_defaults(project)
```

If multiple functions read projects, apply `_apply_safe_defaults` to each path.

- [ ] **Step 5: Run, verify PASS**

Run: `pytest tests/test_projects_loader.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/projects.py tests/test_projects_loader.py
git commit -m "feat(projects): backward-compat safe defaults for new schema fields on load"
```

---

## Task 4: Bugfix B1 — language detection no longer hardcodes 'ja'

**Files:**
- Modify: `app/api/translate.py` (around line 122)
- Modify/Create: `app/utils/text.py` (add `detect_language_hint` if missing)
- Test: `tests/test_translate_language.py`

### Steps

- [ ] **Step 1: Locate the bug**

Run: `grep -n 'else "ja"' app/api/translate.py`
Confirm the line reads: `detected_lang = language if language != "auto" else "ja"` (or equivalent).

Also check if `detect_language_hint` exists:
Run: `grep -n "detect_language_hint" app/utils/text.py`

- [ ] **Step 2: Write failing tests**

Write `tests/test_translate_language.py`:
```python
class _Block:
    def __init__(self, text, filtered=False):
        self.text = text
        self.filtered = filtered


def test_explicit_language_is_used():
    from app.api.translate import _resolve_filter_language
    assert _resolve_filter_language(lang="zh", original_language=None, blocks=[]) == "zh"


def test_auto_with_original_language_wins():
    from app.api.translate import _resolve_filter_language
    assert _resolve_filter_language(lang="auto", original_language="en", blocks=[]) == "en"


def test_auto_without_original_detects_chinese_from_blocks():
    from app.api.translate import _resolve_filter_language
    blocks = [_Block("你好世界"), _Block("今天天气真好"), _Block("再见")]
    assert _resolve_filter_language(lang="auto", original_language=None, blocks=blocks) == "zh"


def test_auto_without_original_detects_english_from_blocks():
    from app.api.translate import _resolve_filter_language
    blocks = [_Block("hello world"), _Block("good morning everyone")]
    assert _resolve_filter_language(lang="auto", original_language=None, blocks=blocks) == "en"


def test_auto_no_signal_falls_back_to_ja():
    from app.api.translate import _resolve_filter_language
    # Empty blocks — per spec §10 B1, fall back to ja for filter compatibility
    assert _resolve_filter_language(lang="auto", original_language=None, blocks=[]) == "ja"
```

- [ ] **Step 3: Run, verify FAIL**

Run: `pytest tests/test_translate_language.py -v`
Expected: ImportError or 5 failures.

- [ ] **Step 4: Add detect_language_hint if missing**

If grep in Step 1 showed no existing `detect_language_hint` in `app/utils/text.py`, append this to that file:
```python
import re


def detect_language_hint(texts):
    """Return 'zh'|'ja'|'ko'|'en' based on dominant character class, or None if inconclusive."""
    if not texts:
        return None
    joined = " ".join(texts)[:2000]
    zh = len(re.findall(r"[\u4e00-\u9fff]", joined))
    ja = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", joined))
    ko = len(re.findall(r"[\uac00-\ud7af]", joined))
    en = len(re.findall(r"[A-Za-z]", joined))
    counts = [("zh", zh), ("ja", ja), ("ko", ko), ("en", en)]
    lang, n = max(counts, key=lambda x: x[1])
    return lang if n > 5 else None
```

- [ ] **Step 5: Add _resolve_filter_language helper**

In `app/api/translate.py`, near the top (after imports):
```python
def _resolve_filter_language(lang, original_language, blocks):
    """Resolve language used by downstream filter logic.

    Priority:
      1. Explicit non-auto language
      2. original_language from project (e.g., from TMDB)
      3. Auto-detect from block texts
      4. Fallback 'ja' (legacy behavior kept for filter compatibility)
    """
    if lang and lang != "auto":
        return lang
    if original_language:
        return original_language
    texts = [b.text for b in blocks if not getattr(b, "filtered", False) and getattr(b, "text", "")]
    if texts:
        from app.utils.text import detect_language_hint
        hint = detect_language_hint(texts)
        if hint:
            return hint
    return "ja"
```

- [ ] **Step 6: Replace the buggy line**

At the old bug location (where `detected_lang = language if language != "auto" else "ja"` was), replace with:
```python
detected_lang = _resolve_filter_language(
    lang=language,
    original_language=project.get("original_language") if isinstance(project, dict) else None,
    blocks=blocks,
)
```

Make sure `project` is in scope at that line; if not, pass the project's `original_language` explicitly from the caller. Search for callers with `grep -n "detected_lang\|language" app/api/translate.py` and adjust.

- [ ] **Step 7: Run, verify PASS**

Run: `pytest tests/test_translate_language.py -v`
Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
git add app/api/translate.py app/utils/text.py tests/test_translate_language.py
git commit -m "fix(translate): B1 resolve filter language from original_language or detection"
```

---

## Task 5: Bugfix B2 — context window honors config

**Files:**
- Modify: `app/engines/translator.py` (line ~199)
- Test: `tests/test_translator_context.py`

### Steps

- [ ] **Step 1: Locate the bug**

Run: `grep -n "batch_end + 2\|ctx_end" app/engines/translator.py`
Confirm the line `ctx_end = min(total, batch_end + 2)`.

- [ ] **Step 2: Write failing test**

Write `tests/test_translator_context.py`:
```python
def test_context_window_respects_config(monkeypatch):
    """With context_window=5, lookahead must be 5 not hardcoded 2."""
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 2,
            "context_window": 5,
            "target_language": "简体中文",
            "polish_provider": "",
            "polish_model": "",
        },
        "api_keys": {"openai": "sk-test"},
    }
    captured = []

    def fake_translate_batch(items, system_prompt, retries=3):
        captured.append({"items": list(items), "prompt": system_prompt})
        return [{"id": it["id"], "translation": f"t-{it['id']}", "error": ""} for it in items]

    t = SubtitleTranslator(config)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)

    blocks = [SubtitleBlock(index=i, start=float(i), end=float(i + 1), text=f"line {i}") for i in range(10)]
    t.translate(blocks, target_lang="简体中文")

    # Second batch covers blocks idx 2..3; with context_window=5, lookahead must extend to idx 8
    second = captured[1]
    assert "line 7" in second["prompt"] or "line 8" in second["prompt"], (
        f"Expected lookahead to include line 7/8 (context_window=5), prompt was: {second['prompt'][:500]}"
    )
```

Note: the exact `SubtitleTranslator.translate` signature and prompt-building path may vary. If the test fails for reasons other than the bug, adapt the assertion (e.g., inspect `items` rather than prompt) based on the actual structure. The principle: **assert lookahead count matches `context_window`**, not hardcoded 2.

- [ ] **Step 3: Run, verify FAIL**

Run: `pytest tests/test_translator_context.py -v`
Expected: FAIL — only "line 4" / "line 5" present in prompt (hardcoded +2).

- [ ] **Step 4: Fix the bug**

In `app/engines/translator.py` at the line identified in Step 1:
```python
# Before:
ctx_end = min(total, batch_end + 2)
# After:
ctx_end = min(total, batch_end + self.context_window)
```

Verify `self.context_window` is set in `SubtitleTranslator.__init__` — grep for it. If not set, add:
```python
self.context_window = config["translation"].get("context_window", 3)
```

- [ ] **Step 5: Run, verify PASS**

Run: `pytest tests/test_translator_context.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/engines/translator.py tests/test_translator_context.py
git commit -m "fix(translator): B2 context window lookahead honors config"
```

---

## Task 6: Bugfix B3 — translate_batch returns error-carrying items

**Files:**
- Modify: `app/engines/translator.py` (`TranslationProvider.translate_batch` + callers)
- Modify: `app/utils/srt.py` (add `translation_error` attribute to SubtitleBlock if missing)
- Test: `tests/test_translator_failure.py`

### Steps

- [ ] **Step 1: Write failing test**

Write `tests/test_translator_failure.py`:
```python
from unittest.mock import patch


def test_translate_batch_exhausted_retries_returns_error_items():
    from app.engines.translator import TranslationProvider
    p = TranslationProvider(provider="openai", api_key="sk-x", model="gpt-4o")
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]

    with patch.object(p.client.chat.completions, "create", side_effect=RuntimeError("network down")):
        result = p.translate_batch(items, "sys", retries=2)

    assert len(result) == 2
    ids = {r["id"] for r in result}
    assert ids == {1, 2}
    for r in result:
        assert r["translation"] == ""
        assert "error" in r and r["error"]
        assert "network" in r["error"].lower() or "runtimeerror" in r["error"].lower()


def test_translate_batch_success_unchanged():
    """Regression: successful path still returns [{id, translation}] shape."""
    from app.engines.translator import TranslationProvider
    p = TranslationProvider(provider="openai", api_key="sk-x", model="gpt-4o")
    items = [{"id": 1, "original": "hello"}]

    class FakeResp:
        class C:
            class M:
                content = '[{"id": 1, "translation": "你好"}]'
            message = M()
        choices = [C()]

    with patch.object(p.client.chat.completions, "create", return_value=FakeResp()):
        result = p.translate_batch(items, "sys", retries=1)

    assert len(result) == 1
    assert result[0]["id"] == 1
    assert result[0]["translation"] == "你好"
```

- [ ] **Step 2: Run, verify FAIL**

Run: `pytest tests/test_translator_failure.py -v`
Expected: first test FAIL (returns `[]`), second likely PASS.

- [ ] **Step 3: Modify translate_batch error return**

In `app/engines/translator.py`, inside `TranslationProvider.translate_batch`:

1. Track the last exception:
```python
def translate_batch(self, items, system_prompt, retries=3):
    user_content = json.dumps(items, ensure_ascii=False)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    last_exc = None

    for attempt in range(retries):
        try:
            # ... existing API call + JSON parse logic ...
            # On success, return parsed
            return parsed  # or whatever the success return is
        except Exception as e:
            last_exc = e
            log.warning("Attempt %d failed: %s", attempt + 1, str(e)[:100])
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))

    # All retries exhausted: return error-carrying items
    err = f"{type(last_exc).__name__}: {str(last_exc)[:120]}" if last_exc else "unknown failure"
    return [{"id": it["id"], "translation": "", "error": err} for it in items]
```

2. Also handle the JSON-parse-fails-but-no-exception path (where current code might `continue`). After the loop, make sure the error fallback runs.

- [ ] **Step 4: Add translation_error attribute to SubtitleBlock**

Check `app/utils/srt.py` for `SubtitleBlock` class. If it's a dataclass or regular class, add a default attribute:
```python
@dataclass
class SubtitleBlock:
    index: int
    start: float
    end: float
    text: str
    # ... existing fields ...
    translation: str = ""
    translation_error: str = ""  # NEW: carries translator error for UI
    filtered: bool = False
```

If it's a non-dataclass class, add `self.translation_error = ""` in `__init__`.

- [ ] **Step 5: Update caller(s) that apply results to blocks**

Search: `grep -n "translation\s*=" app/engines/translator.py`

Find where results from `translate_batch` are applied to `SubtitleBlock`. Replace the naive assignment with:
```python
for r in results:
    bid = str(r.get("id"))
    trans = r.get("translation", "") or ""
    err = r.get("error", "") or ""
    for b in blocks:
        if str(b.index) == bid:
            if err and not trans:
                b.translation = ""
                b.translation_error = err
            else:
                b.translation = trans
                b.translation_error = ""
            break
```

- [ ] **Step 6: Run tests, verify PASS**

Run: `pytest tests/test_translator_failure.py tests/test_translator_context.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/engines/translator.py app/utils/srt.py tests/test_translator_failure.py
git commit -m "fix(translator): B3 surface batch errors via error field instead of dropping items"
```

---

## Task 7: Create scheduler module with semaphores

**Files:**
- Create: `app/engines/scheduler.py`
- Test: `tests/test_scheduler_semaphores.py`

### Steps

- [ ] **Step 1: Write failing test**

Write `tests/test_scheduler_semaphores.py`:
```python
import threading
import time


def test_sem_asr_respects_max_concurrent():
    from app.engines.scheduler import SEM_ASR, slot

    running = []
    peak = [0]
    lock = threading.Lock()

    def worker(i):
        with slot(SEM_ASR, f"pid{i}", "asr"):
            with lock:
                running.append(i)
                peak[0] = max(peak[0], len(running))
            time.sleep(0.05)
            with lock:
                running.remove(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak[0] <= 2, f"ASR concurrency exceeded cap: peak={peak[0]}"


def test_sem_burn_is_strictly_sequential():
    from app.engines.scheduler import SEM_BURN, slot

    running = []
    peak = [0]
    lock = threading.Lock()

    def worker(i):
        with slot(SEM_BURN, f"pid{i}", "burn"):
            with lock:
                running.append(i)
                peak[0] = max(peak[0], len(running))
            time.sleep(0.03)
            with lock:
                running.remove(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak[0] == 1, f"Burn must be sequential: peak={peak[0]}"
```

- [ ] **Step 2: Run, verify FAIL**

Run: `pytest tests/test_scheduler_semaphores.py -v`
Expected: ImportError.

- [ ] **Step 3: Create scheduler module**

Write `app/engines/scheduler.py`:
```python
"""Centralized concurrency control, progress store, and cancellation for AI_Sub_Pro.

Usage:
    from app.engines.scheduler import slot, SEM_ASR, update_progress

    with slot(SEM_ASR, pid, "asr"):
        run_asr(...)
    update_progress(pid, stage="asr", local_pct=50, msg="halfway")
"""
import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.config import Config, PROJECTS_DIR

log = logging.getLogger(__name__)

# --- Concurrency semaphores ---
_cfg = Config.get("concurrency") or {}
SEM_ASR = threading.BoundedSemaphore(_cfg.get("asr", 2))
SEM_TRANSLATE = threading.BoundedSemaphore(_cfg.get("translate", 4))
SEM_DOWNLOAD = threading.BoundedSemaphore(_cfg.get("download", 3))
SEM_BURN = threading.BoundedSemaphore(_cfg.get("burn", 1))


@contextmanager
def slot(sem: threading.BoundedSemaphore, pid: str, stage: str):
    """Acquire a concurrency slot with logging. Blocks until slot available."""
    log.info("semaphore[%s] acquiring pid=%s", stage, pid)
    sem.acquire()
    log.info("semaphore[%s] acquired pid=%s", stage, pid)
    try:
        yield
    finally:
        sem.release()
        log.info("semaphore[%s] released pid=%s", stage, pid)
```

- [ ] **Step 4: Run, verify PASS**

Run: `pytest tests/test_scheduler_semaphores.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/engines/scheduler.py tests/test_scheduler_semaphores.py
git commit -m "feat(scheduler): add BoundedSemaphores for asr/translate/download/burn stages"
```

---

## Task 8: Progress store with lock + persistence + stage mapping

**Files:**
- Modify: `app/engines/scheduler.py` (extend)
- Test: `tests/test_scheduler_progress.py`

### Steps

- [ ] **Step 1: Write failing tests**

Write `tests/test_scheduler_progress.py`:
```python
import json
import threading


def test_update_progress_writes_to_store(tmp_project_dir):
    from app.engines.scheduler import update_progress, get_progress

    update_progress("pid1", stage="asr", local_pct=50, msg="half")
    p = get_progress("pid1")
    assert p["stage"] == "asr"
    assert 15 <= p["progress"] <= 40, f"asr stage maps to 15..40, got {p['progress']}"
    assert p["message"] == "half"


def test_update_progress_persists_to_disk(tmp_project_dir):
    from app.engines.scheduler import update_progress

    update_progress("pid2", stage="translate", local_pct=0, msg="starting")
    fp = tmp_project_dir / "pid2" / "progress.json"
    assert fp.exists()
    payload = json.loads(fp.read_text())
    assert payload["stage"] == "translate"
    assert payload["progress"] == 40


def test_update_progress_stage_ranges(tmp_project_dir):
    from app.engines.scheduler import update_progress, get_progress

    for stage, local, lo, hi in [
        ("download", 0, 0, 0),
        ("download", 100, 15, 15),
        ("asr", 0, 15, 15),
        ("asr", 100, 40, 40),
        ("translate", 50, 57, 58),  # 40 + 0.5*(75-40) = 57.5 → 57
        ("burn", 100, 100, 100),
    ]:
        update_progress(f"p-{stage}-{local}", stage=stage, local_pct=local, msg="")
        p = get_progress(f"p-{stage}-{local}")
        assert lo <= p["progress"] <= hi, f"{stage}/{local}: got {p['progress']}"


def test_update_progress_threadsafe(tmp_project_dir):
    from app.engines.scheduler import update_progress, progress_store

    def worker(i):
        for _ in range(50):
            update_progress(f"pid{i}", stage="asr", local_pct=50, msg=f"from {i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i in range(8):
        assert f"pid{i}" in progress_store


def test_load_progress_store_from_disk(tmp_project_dir):
    from app.engines.scheduler import progress_store, load_progress_store_from_disk

    pdir = tmp_project_dir / "seed1"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 45, "stage": "translate", "message": "restored",
        "updated_at": "2026-04-19T00:00:00",
    }))
    progress_store.clear()

    count = load_progress_store_from_disk()
    assert count >= 1
    assert progress_store["seed1"]["stage"] == "translate"
    assert progress_store["seed1"]["progress"] == 45
```

- [ ] **Step 2: Run, verify FAIL**

Run: `pytest tests/test_scheduler_progress.py -v`
Expected: all FAIL (functions not yet defined).

- [ ] **Step 3: Extend scheduler.py with progress machinery**

Append to `app/engines/scheduler.py`:
```python
# --- Progress store ---
_progress_lock = threading.Lock()
progress_store: dict = {}

_STAGE_RANGES = {
    "download":  (0, 15),
    "asr":       (15, 40),
    "translate": (40, 75),
    "burn":      (75, 100),
}


def _map_global(stage: str, local_pct: int) -> int:
    lo, hi = _STAGE_RANGES.get(stage, (0, 100))
    local = max(0, min(100, int(local_pct)))
    return lo + int((hi - lo) * (local / 100))


def update_progress(pid: str, stage: str, local_pct: int, msg: str) -> None:
    """Thread-safe progress update. Persists per-project progress.json."""
    payload = {
        "progress": _map_global(stage, local_pct),
        "stage": stage,
        "message": msg,
        "updated_at": datetime.utcnow().isoformat(),
    }
    with _progress_lock:
        progress_store[pid] = payload
        try:
            pdir = Path(PROJECTS_DIR) / pid
            pdir.mkdir(parents=True, exist_ok=True)
            with open(pdir / "progress.json", "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception as e:
            log.warning("persist progress failed pid=%s: %s", pid, e)


def get_progress(pid: str) -> dict | None:
    with _progress_lock:
        return dict(progress_store[pid]) if pid in progress_store else None


def load_progress_store_from_disk() -> int:
    """Restore in-memory progress_store from disk. Returns count restored."""
    count = 0
    root = Path(PROJECTS_DIR)
    if not root.exists():
        return 0
    for pdir in root.iterdir():
        if not pdir.is_dir():
            continue
        fp = pdir / "progress.json"
        if not fp.exists():
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            with _progress_lock:
                progress_store[pdir.name] = data
            count += 1
        except Exception as e:
            log.warning("load progress failed pid=%s: %s", pdir.name, e)
    return count
```

- [ ] **Step 4: Run, verify PASS**

Run: `pytest tests/test_scheduler_progress.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/engines/scheduler.py tests/test_scheduler_progress.py
git commit -m "feat(scheduler): locked progress store with persistence + stage mapping"
```

---

## Task 9: Cooperative cancellation events

**Files:**
- Modify: `app/engines/scheduler.py` (extend)
- Test: `tests/test_scheduler_cancel.py`

### Steps

- [ ] **Step 1: Write failing tests**

Write `tests/test_scheduler_cancel.py`:
```python
def test_request_cancel_sets_flag():
    from app.engines.scheduler import request_cancel, is_cancelled, reset_cancel

    reset_cancel("pidc1")
    assert is_cancelled("pidc1") is False
    request_cancel("pidc1")
    assert is_cancelled("pidc1") is True


def test_is_cancelled_unknown_pid_is_false():
    from app.engines.scheduler import is_cancelled
    assert is_cancelled("never-existed-xxx") is False


def test_reset_cancel_clears_flag():
    from app.engines.scheduler import request_cancel, is_cancelled, reset_cancel

    request_cancel("pidc2")
    assert is_cancelled("pidc2") is True
    reset_cancel("pidc2")
    assert is_cancelled("pidc2") is False
```

- [ ] **Step 2: Run, verify FAIL**

Run: `pytest tests/test_scheduler_cancel.py -v`
Expected: ImportError.

- [ ] **Step 3: Add cancel machinery**

Append to `app/engines/scheduler.py`:
```python
# --- Cooperative cancellation ---
_cancel_events: dict = {}
_cancel_lock = threading.Lock()


def request_cancel(pid: str) -> None:
    with _cancel_lock:
        ev = _cancel_events.setdefault(pid, threading.Event())
        ev.set()


def is_cancelled(pid: str) -> bool:
    with _cancel_lock:
        ev = _cancel_events.get(pid)
    return bool(ev and ev.is_set())


def reset_cancel(pid: str) -> None:
    with _cancel_lock:
        ev = _cancel_events.get(pid)
        if ev is not None:
            ev.clear()
```

- [ ] **Step 4: Run, verify PASS**

Run: `pytest tests/test_scheduler_cancel.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/engines/scheduler.py tests/test_scheduler_cancel.py
git commit -m "feat(scheduler): cooperative cancellation via per-pid events"
```

---

## Task 10: Wire existing translate pipeline to scheduler

**Files:**
- Modify: `app/api/translate.py`
- Test: `tests/test_translate_integration.py`

### Steps

- [ ] **Step 1: Inventory existing progress_store writes**

Run: `grep -n "progress_store\[" app/api/translate.py`
List every location and note whether it's ASR, translate, or burn context (infer from surrounding code).

- [ ] **Step 2: Write failing integration test**

Write `tests/test_translate_integration.py`:
```python
from unittest.mock import patch


def test_emit_progress_routes_through_scheduler():
    """_emit_progress must delegate to scheduler.update_progress (single source of truth)."""
    with patch("app.engines.scheduler.update_progress") as mock_update:
        from app.api import translate as api_translate
        api_translate._emit_progress("pidx", stage="asr", local_pct=10, msg="m")
    mock_update.assert_called_once_with("pidx", stage="asr", local_pct=10, msg="m")
```

- [ ] **Step 3: Run, verify FAIL**

Run: `pytest tests/test_translate_integration.py -v`
Expected: FAIL — `_emit_progress` not defined.

- [ ] **Step 4: Add shim at top of api/translate.py**

In `app/api/translate.py`, after imports:
```python
from app.engines.scheduler import (
    update_progress as _scheduler_update_progress,
    progress_store,  # re-export for existing readers (e.g., WS handler)
    SEM_ASR,
    SEM_TRANSLATE,
    SEM_BURN,
    slot,
    is_cancelled,
    reset_cancel,
)


def _emit_progress(pid: str, stage: str, local_pct: int, msg: str) -> None:
    """Route progress through scheduler (locked + persisted + stage-mapped)."""
    _scheduler_update_progress(pid, stage=stage, local_pct=local_pct, msg=msg)
```

- [ ] **Step 5: Replace raw progress_store writes**

For each `progress_store[pid] = {...}` found in Step 1, replace with `_emit_progress(pid, stage=..., local_pct=..., msg=...)`. Determine `stage` from context:
- ASR extraction / transcription → `stage="asr"`
- Translator calls → `stage="translate"`
- ffmpeg burn → `stage="burn"`

Where the original code wrote a raw percentage (0–100 within the whole pipeline), break it into per-stage local percentages. The `_emit_progress` call will map back to the global scale.

If the code computes global % directly (e.g., `progress=50` during ASR meaning "mid-pipeline"), replace with local percentage:
```python
# Before: progress_store[pid] = {"progress": 50, "message": "ASR"}
# After (ASR is stage; 50% global corresponds to ~100% local within ASR stage range):
_emit_progress(pid, stage="asr", local_pct=100, msg="ASR done")
```

When the stage is unclear, trace the call site upward: find which background thread entry point (e.g., `_run_asr_pipeline`, `_run_translate_pipeline`) calls this code path, and use that function's stage. Do NOT leave `TODO` markers — resolve them now.

- [ ] **Step 6: Wrap stage runners in semaphore slots**

Find the function(s) that run ASR and translate stages (likely background tasks launched via `threading.Thread`). Wrap:
```python
from app.engines.scheduler import slot, SEM_ASR, SEM_TRANSLATE

def _run_asr_stage(pid, ...):
    with slot(SEM_ASR, pid, "asr"):
        # existing ASR body
        ...

def _run_translate_stage(pid, ...):
    with slot(SEM_TRANSLATE, pid, "translate"):
        # existing translate body
        ...
```

If burn is in this file, same for `SEM_BURN`.

- [ ] **Step 7: Add cancel checkpoints**

Inside ASR loops and translate batch loops, at boundaries:
```python
from app.engines.scheduler import is_cancelled

for segment in segments:
    if is_cancelled(pid):
        raise RuntimeError(f"cancelled by user pid={pid}")
    # ... process segment ...
```

Also at project start (before heavy work): `reset_cancel(pid)`.

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_translate_integration.py tests/test_scheduler_semaphores.py tests/test_scheduler_progress.py -v`
Expected: all PASS.

- [ ] **Step 9: Manual smoke — ensure existing upload flow still works**

Run: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
In a browser, upload a short video (≤30s) and let it run through. Verify logs show:
- `semaphore[asr] acquiring pid=...`
- `semaphore[asr] acquired pid=...`
- `semaphore[translate] acquired pid=...`
- Progress updates in UI (any stage).

Expected: pipeline completes without errors. UI shows progress moving through stages.

If the UI progress bar looks wrong (e.g., jumps from 15 to 75 skipping translate range), the stage mapping in Step 5 has misassigned percentages — fix and re-test.

- [ ] **Step 10: Commit**

```bash
git add app/api/translate.py tests/test_translate_integration.py
git commit -m "refactor(translate): route progress via scheduler + wrap stages in semaphore slots"
```

---

## Task 11: Restore progress store on startup

**Files:**
- Modify: `app/main.py` (startup event)
- Test: `tests/test_startup_progress_restore.py`

### Steps

- [ ] **Step 1: Write failing test**

Write `tests/test_startup_progress_restore.py`:
```python
import json


def test_startup_restores_progress_from_disk(tmp_project_dir):
    pdir = tmp_project_dir / "restored"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 55, "stage": "translate", "message": "pre-crash",
        "updated_at": "2026-04-19T00:00:00",
    }))

    from fastapi.testclient import TestClient
    from app.main import app
    from app.engines.scheduler import progress_store

    progress_store.clear()

    with TestClient(app):  # triggers startup event
        pass

    assert "restored" in progress_store
    assert progress_store["restored"]["progress"] == 55
    assert progress_store["restored"]["stage"] == "translate"
```

- [ ] **Step 2: Run, verify FAIL**

Run: `pytest tests/test_startup_progress_restore.py -v`
Expected: FAIL — startup doesn't restore.

- [ ] **Step 3: Add startup restoration**

In `app/main.py`, inside `@app.on_event("startup")` / `startup()` function, add:
```python
from app.engines.scheduler import load_progress_store_from_disk
restored = load_progress_store_from_disk()
log.info("restored progress for %d projects from disk", restored)
```

- [ ] **Step 4: Run, verify PASS**

Run: `pytest tests/test_startup_progress_restore.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_startup_progress_restore.py
git commit -m "feat(main): restore in-memory progress store from disk on startup"
```

---

## Task 12: Full-suite smoke + tag phase complete

**Files:** none

### Steps

- [ ] **Step 1: Run all tests**

Run: `pytest -v`
Expected: all tests pass, no errors, no warnings other than filtered deprecations.

- [ ] **Step 2: Boot app and open an existing legacy project**

Run: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`

In the browser, navigate to Projects, open any existing project that was created before this phase.

Expected: the project opens, all fields render (new fields like `source_type`, `auto_run` use defaults without crashing the UI or API).

- [ ] **Step 3: Exercise a short video end-to-end**

Upload a short (≤30s) video. Let it run.

Expected: ASR → translate → burn all complete. Logs show semaphore acquire/release for each stage. `data/projects/<pid>/progress.json` exists and reflects final state.

- [ ] **Step 4: Tag completion**

```bash
git tag phase1-foundations-complete
```

- [ ] **Step 5: Summary commit note**

No commit needed; tag suffices.

---

## Audit Gate (team-mode workflow)

Before starting Plan 2 (Translator Refactor), dispatch 3 independent audit agents (read-only) to review what this plan produced:

- **Agent A — Bugfix verification**: Open `app/api/translate.py`, `app/engines/translator.py` at the B1/B2/B3 fix sites. Confirm the fix is actually in place (not just tested). Verify test coverage exercises the real code path, not a stub.
- **Agent B — Concurrency correctness**: Review `app/engines/scheduler.py` for race conditions, deadlock risk (nested `slot()` calls), missed lock acquisitions. Check that `update_progress` never holds `_progress_lock` while doing blocking I/O (it does file I/O inside the lock — assess risk).
- **Agent C — Backward compatibility**: Load 3 real pre-existing projects from `~/AI_Sub_Pro_Data/data/projects/`, confirm they open in the UI and can be re-processed. Confirm no stored config.json migration breakage.

Each audit agent outputs ≤300 words: current state / problems / severity. If any agent finds a blocking issue, fix in this plan before proceeding to Plan 2.

---

## Out of this plan (picked up later)

- Provider abstraction & ClaudeCliProvider & full-doc mode → **Plan 2**
- ASR VAD + mlx beam_size bugfixes (B4/B5) → **Plan 2** (while refactoring translator)
- Bilingual burn + SubtitleTrack → **Plan 3**
- TMDB + yt-dlp + trailer pipeline + API → **Plan 3**
- UI redesign + trailer wizard + Settings conditional → **Plan 4**
- Full E2E scenarios 1–7 → **Plan 4**
