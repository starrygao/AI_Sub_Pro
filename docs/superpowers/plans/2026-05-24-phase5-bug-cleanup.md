# Phase 5 — Bug fixes + 清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve 6 bug/cleanup items from the 2026-05-22 audit (spec: `docs/superpowers/specs/2026-05-24-phase5-bug-cleanup-design.md`).

**Architecture:** Six independent atomic commits on branch `fix/phase5-audit-bug-cleanup` (already created), ordered B → C-2 → C-3 → C-5 → C-1 → C-4 (risk ascending). Each commit ships its own test where applicable. Merge back to `main` with `--no-ff` to preserve the Phase-X merge-commit pattern.

**Tech Stack:** Python 3.9+, pytest, FastAPI, vanilla JS (Alpine.js).

**Pre-flight:**
- Working tree: branch `fix/phase5-audit-bug-cleanup` already checked out, spec already committed.
- Test baseline: `pytest -q` → **216 passed**.
- Final expected baseline after Phase 5: **221 passed** (-1 deleted shim test + 6 new tests).

---

## Task 1 — B: Delete KnowledgeBase legacy stubs

**Files:**
- Modify: `app/engines/knowledge.py` (delete `match`, `learn`, `feedback` methods)
- Modify: `tests/test_knowledge_base_v2.py` (delete `test_knowledge_base_legacy_match_still_works`)

**Rationale:** Grep across `app/` finds zero production callers of `.match()` / `.learn()` / `.feedback()`. The only consumer is the test that asserts the shim exists; the test's own comment references `settings.py / translate.py` which no longer use it.

- [ ] **Step 1: Confirm no callers (sanity check)**

Run:
```bash
grep -rn "kb\.match\|kb\.learn\|kb\.feedback\|knowledge\.match\|_shared_kb\.match" app/ 2>/dev/null
```
Expected: no output. If anything appears, STOP and re-evaluate.

- [ ] **Step 2: Delete the test that pins the shim**

Delete lines 87-96 of `tests/test_knowledge_base_v2.py` (the function `test_knowledge_base_legacy_match_still_works`).

- [ ] **Step 3: Delete the three stub methods**

In `app/engines/knowledge.py`, remove these blocks (lines 141-156 approximately, the `# ----- Legacy compat (old callers) -----` and `# ----- Legacy no-ops ... -----` sections, keeping everything else):

```python
    # ----- Legacy compat (old callers) -----

    def get_all(self) -> Dict[str, dict]:
        ...

    def update_all(self, data: dict) -> None:
        ...
```

**Keep** `get_all` and `update_all` (they ARE used by `app/api/settings.py`). **Delete only** `match`, `learn`, `feedback`. The result for the bottom of `class KnowledgeBase` should end at `update_all`.

- [ ] **Step 4: Run the full suite to confirm no regressions**

Run: `python3 -m pytest -q`

Expected: **215 passed** (216 − 1 deleted test).

- [ ] **Step 5: Commit**

```bash
git add app/engines/knowledge.py tests/test_knowledge_base_v2.py
git commit -m "refactor(kb): drop unused KnowledgeBase legacy stubs (match/learn/feedback)

Grep across app/ shows zero production callers. The only consumer was
test_knowledge_base_legacy_match_still_works, which asserted the shim
exists; the stub itself returned constants and the test's own comment
about 'settings.py / translate.py call .match()' was stale.

Deleting the methods and the pin test removes 22 lines of dead code
from the public KnowledgeBase surface."
```

---

## Task 2 — C-2: Fix `_pick_subtitle_track` docstring

**Files:**
- Modify: `app/api/projects.py` (docstring of `_pick_subtitle_track`, around line 64)

**Rationale:** Docstring claims the returned index is "0-based among text-based subtitle streams" but the implementation iterates `enumerate(tracks)` over ALL subtitle streams. The implementation is correct (matches ffmpeg `-map 0:s:N`); the docstring is wrong.

- [ ] **Step 1: Update the docstring**

In `app/api/projects.py`, in `_pick_subtitle_track`, replace the docstring (lines 65-75) with:

```python
def _pick_subtitle_track(tracks: list, target_language: str) -> Optional[int]:
    """Pick the best embedded subtitle track to bypass ASR.

    Returns the 0-based index into `tracks` (which is the list returned by
    `get_tracks(path, 's')` — i.e. all subtitle streams in the input file).
    This index is suitable for ffmpeg's `-map 0:s:N` selector. The frontend
    must NOT pre-filter `subtitle_tracks` before indexing — use the raw list.

    Selection rules:
      1. Drop image-based codecs (PGS/DVD/DVB) — they need OCR, can't transcode.
      2. Prefer English (most common source language for translation).
      3. Then prefer non-target-language tracks (no point translating to itself).
      4. Otherwise the first text-based track.
    Returns None if no usable text track exists.
    """
```

- [ ] **Step 2: Confirm tests still pass**

Run: `python3 -m pytest -q tests/test_subtitle_picker.py`

Expected: 8 passed (no test changes; docstring is runtime-invisible).

- [ ] **Step 3: Commit**

```bash
git add app/api/projects.py
git commit -m "docs: correct _pick_subtitle_track docstring on returned index

The returned index is 0-based over ALL subtitle streams (matching ffmpeg's
-map 0:s:N selector), not over text-based streams as the prior docstring
claimed. Implementation was correct; only the contract description was wrong.

Adds an explicit note that the frontend must not pre-filter the list
before indexing — a forthcoming commit fixes the JS that does this."
```

---

## Task 3 — C-3: Add `asr_skipped` to schema defaults

**Files:**
- Modify: `app/api/projects.py` (`_PROJECT_SAFE_DEFAULTS` dict, around line 36)
- Modify: `tests/test_translate_loader_defaults.py` (add one assertion)

**Rationale:** `trailer_pipeline._download_stage` writes `asr_skipped=True` when it adopts YouTube native subs, but `_apply_safe_defaults` never declares the field. Old projects don't have it; `proj.get("asr_skipped")` returns None (still correct), but the schema is non-closed. Close it.

- [ ] **Step 1: Write the failing test first**

In `tests/test_translate_loader_defaults.py`, **append** this test:

```python
def test_translate_loader_defaults_asr_skipped(tmp_project_dir, monkeypatch):
    """asr_skipped is written by the trailer pipeline; _apply_safe_defaults
    must declare it so reload-after-restart returns a closed schema."""
    import app.api.translate as translate_mod
    monkeypatch.setattr(translate_mod, "PROJECTS_DIR", tmp_project_dir, raising=False)

    pid = "pre_phase5_proj"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid, "name": "pre", "video_path": "/x.mp4",
        "status": "completed", "progress": 100,
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = translate_mod._load_project(pid)
    assert "asr_skipped" in loaded, "asr_skipped must be present in defaulted schema"
    assert loaded["asr_skipped"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest -q tests/test_translate_loader_defaults.py::test_translate_loader_defaults_asr_skipped`

Expected: FAIL with `AssertionError: asr_skipped must be present in defaulted schema`.

- [ ] **Step 3: Add the default**

In `app/api/projects.py`, in `_PROJECT_SAFE_DEFAULTS` (line 36-52), add the field. The dict should look like this (only the new line shown in context):

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
    "prefer_embedded_subtitle": True,
    "tmdb_candidates": None,
    "show_title": None,
    "poster_path": None,
    "asr_skipped": False,  # set True by trailer pipeline when YouTube native subs adopted
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest -q tests/test_translate_loader_defaults.py`

Expected: 2 passed (existing + new).

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest -q`

Expected: **216 passed** (215 from Task 1 + 1 new).

- [ ] **Step 6: Commit**

```bash
git add app/api/projects.py tests/test_translate_loader_defaults.py
git commit -m "fix(schema): default asr_skipped in _PROJECT_SAFE_DEFAULTS

trailer_pipeline._download_stage writes asr_skipped=True when it adopts
YouTube native subtitles, but _apply_safe_defaults never declared the
field. Reloaded legacy projects ended up without it — proj.get('asr_skipped')
returned None which happened to work, but the schema was non-closed.

No behavior change; defense in depth + makes the contract explicit."
```

---

## Task 4 — C-5: Route `_load_project` through `project_store.load_project`

**Files:**
- Modify: `app/api/translate.py` (`_load_project`, around line 119-124; add an import)
- Modify: `tests/test_pipeline_correctness.py` (add one test)

**Rationale:** Current `_load_project` builds the path with bare `PROJECTS_DIR / pid` — no `validate_pid` call. The FastAPI route layer enforces `PID_PATTERN` via `PathParam`, so it's not externally exploitable, but defense-in-depth says internal callers should also be guarded. `app/api/projects.py::_load_project` already routes through `project_store.load_project` (which calls `validate_pid` → raises `ValueError`); mirror that.

- [ ] **Step 1: Write the failing test first**

In `tests/test_pipeline_correctness.py`, **append** this test:

```python
def test_translate_load_project_rejects_invalid_pid():
    """Defense in depth: _load_project should validate the pid before
    touching the filesystem, even when called internally. Routing through
    project_store.load_project gives us the same path-traversal guard the
    write-side already has via mutate_project."""
    from fastapi import HTTPException
    from app.api import translate as tr

    with pytest.raises(HTTPException) as exc_info:
        tr._load_project("../etc/passwd")
    assert exc_info.value.status_code == 400, \
        f"invalid pid must raise HTTP 400, got {exc_info.value.status_code}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest -q tests/test_pipeline_correctness.py::test_translate_load_project_rejects_invalid_pid`

Expected: FAIL — current code raises `HTTPException(404)` (since the path `PROJECTS_DIR/../etc/passwd/project.json` doesn't exist) or raises `OSError` depending on resolution. Either way ≠ 400.

- [ ] **Step 3: Replace `_load_project` body**

In `app/api/translate.py`, replace lines 119-124 (the current `_load_project` function) with:

```python
def _load_project(pid: str) -> dict:
    from app.utils.project_store import load_project as _ps_load_project
    try:
        return _apply_safe_defaults(_ps_load_project(pid))
    except ValueError:
        raise HTTPException(400, "Invalid project id")
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
```

(The import is local to keep the change surgical and avoid reshuffling top-of-file imports.)

- [ ] **Step 4: Run the new test to verify it passes**

Run: `python3 -m pytest -q tests/test_pipeline_correctness.py::test_translate_load_project_rejects_invalid_pid`

Expected: PASS.

- [ ] **Step 5: Run the full pipeline_correctness file**

Run: `python3 -m pytest -q tests/test_pipeline_correctness.py`

Expected: 3 passed (2 existing + 1 new).

- [ ] **Step 6: Run full suite**

Run: `python3 -m pytest -q`

Expected: **217 passed**.

- [ ] **Step 7: Commit**

```bash
git add app/api/translate.py tests/test_pipeline_correctness.py
git commit -m "fix(translate): route _load_project through validated project_store

api/translate.py::_load_project built the path with bare PROJECTS_DIR / pid,
skipping the pid validation that api/projects.py::_load_project gets via
project_store.load_project. The FastAPI route layer enforces PID_PATTERN
via PathParam so this wasn't externally exploitable, but internal callers
(and future refactors) deserve the same defense-in-depth guard.

Now mirrors projects.py: ValueError → 400, FileNotFoundError → 404."
```

---

## Task 5 — C-1: Fix frontend `describeSubtitleTrack` index error

**Files:**
- Modify: `app/static/js/app.js` (`describeSubtitleTrack`, around line 372-387)
- Modify: `tests/test_subtitle_picker.py` (add backend contract case)

**Rationale:** Backend `_pick_subtitle_track` returns an index into the unfiltered subtitle-tracks list (Task 2 docstring now confirms this contract). Frontend was filtering `subtitle_tracks` to text-only and then using the index — wrong list, undefined access on PGS+SRT inputs. Frontend should index the unfiltered list directly. We can't easily unit-test JS in this stack, so we strengthen the backend contract test as the canonical reference.

- [ ] **Step 1: Write the failing-then-passing backend contract test**

In `tests/test_subtitle_picker.py`, **append** this test:

```python
def test_returned_index_addresses_unfiltered_subtitle_list():
    """Contract: returned index is 0-based across ALL subtitle streams
    (not text-only). Frontend describeSubtitleTrack relies on this to
    index project.subtitle_tracks directly without pre-filtering."""
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("hdmv_pgs_subtitle", "eng"),   # idx 0 — image, skipped
        _track("subrip", "eng"),              # idx 1 — text, picked
    ]
    idx = _pick_subtitle_track(tracks, "简体中文")
    assert idx == 1
    assert tracks[idx]["codec"] == "subrip", \
        "tracks[idx] must address the picked SRT track, not undefined"
```

- [ ] **Step 2: Run the new test — it should PASS already**

Run: `python3 -m pytest -q tests/test_subtitle_picker.py::test_returned_index_addresses_unfiltered_subtitle_list`

Expected: PASS. (This test pins existing correct behavior so a future refactor doesn't regress the contract the frontend depends on.)

- [ ] **Step 3: Fix the frontend**

In `app/static/js/app.js`, replace the `describeSubtitleTrack` function (around line 372) with:

```javascript
    describeSubtitleTrack(project) {
      if (!project) return '';
      const idx = project.selected_subtitle_track;
      if (idx === null || idx === undefined) return '';
      // Backend _pick_subtitle_track returns an index into the UNFILTERED
      // subtitle_tracks list (matches ffmpeg -map 0:s:N). Do NOT pre-filter
      // to text codecs before indexing — that misaligns the index when the
      // input has image-based tracks (PGS/DVD/DVB) ahead of text tracks.
      const tracks = project.subtitle_tracks || [];
      const t = tracks[idx];
      if (!t) return '';
      const parts = [];
      if (t.codec) parts.push(t.codec);
      if (t.lang && t.lang !== 'und') parts.push(t.lang);
      if (t.title) parts.push(t.title);
      return parts.join(' · ');
    },
```

- [ ] **Step 4: Run full suite**

Run: `python3 -m pytest -q`

Expected: **218 passed** (217 + 1 new).

- [ ] **Step 5: Commit**

```bash
git add app/static/js/app.js tests/test_subtitle_picker.py
git commit -m "fix(frontend): index full subtitle_tracks list, not filtered text-only

describeSubtitleTrack was filtering subtitle_tracks to text codecs before
indexing with selected_subtitle_track — but the backend returns an index
across ALL subtitle streams (matches ffmpeg -map 0:s:N). On inputs with
image-based tracks ahead of text (PGS+SRT being the common case), the
index pointed past the filtered array end and the label rendered blank.

Pipeline behavior was always correct (extract_subtitle uses the same
unfiltered index); only the UI label was wrong.

Adds a backend contract test that pins the invariant the frontend now
depends on."
```

---

## Task 6 — C-4: Clean up audio intermediates after burn success

**Files:**
- Modify: `app/engines/audio.py` (add `cleanup_intermediate` helper at end of file)
- Modify: `app/api/translate.py` (call cleanup in `_run_burn_pipeline` success branch + `start_burn._burn_task` success branch)
- Create: `tests/test_audio_cleanup.py`

**Rationale:** `raw_audio.wav` (10-100 MB) and `demucs_out/` (vocals + accompaniment WAVs) sit in the project directory forever after a successful burn. The valuable artifact (subtitled video) is already on disk; the intermediates can go. Failure paths preserve intermediates for debugging / re-run.

- [ ] **Step 1: Create the test file**

Create `tests/test_audio_cleanup.py`:

```python
"""Phase 5 — audio intermediate cleanup after burn success.

raw_audio.wav + demucs_out/ live in the project dir. Once the burn step
produces the subtitled video, the intermediates can be deleted. Failures
preserve them so the user can re-run ASR / debug.
"""
import json
import os
from pathlib import Path

import pytest


def test_cleanup_intermediate_removes_raw_and_demucs(tmp_path):
    """cleanup_intermediate removes raw_audio.wav and the demucs_out tree."""
    from app.engines.audio import cleanup_intermediate

    (tmp_path / "raw_audio.wav").write_bytes(b"\x00" * 1024)
    demucs = tmp_path / "demucs_out" / "htdemucs" / "raw_audio"
    demucs.mkdir(parents=True)
    (demucs / "vocals.wav").write_bytes(b"\x00" * 1024)
    (demucs / "no_vocals.wav").write_bytes(b"\x00" * 1024)

    cleanup_intermediate(str(tmp_path))

    assert not (tmp_path / "raw_audio.wav").exists()
    assert not (tmp_path / "demucs_out").exists()


def test_cleanup_intermediate_is_noop_when_absent(tmp_path):
    """cleanup_intermediate must not raise when files are already gone."""
    from app.engines.audio import cleanup_intermediate
    # No files exist in tmp_path — must not raise
    cleanup_intermediate(str(tmp_path))


def test_burn_success_triggers_cleanup(tmp_project_dir, monkeypatch):
    """End-to-end: _run_burn_pipeline success removes audio intermediates."""
    from app.api import translate as tr
    from app.api import projects as projects_api
    from app.utils import project_store

    monkeypatch.setattr(tr, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    pid = "burnok01"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    project = projects_api._apply_safe_defaults({
        "id": pid, "name": "t", "video_path": "/fake.mp4",
        "status": "translated", "error": None, "source_type": "upload",
    })
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
    )
    (pdir / "raw_audio.wav").write_bytes(b"\x00" * 1024)
    (pdir / "demucs_out").mkdir()
    (pdir / "demucs_out" / "marker").write_bytes(b"x")

    # Make burn "succeed" without shelling out, and make the output-file
    # existence check inside _run_burn_pipeline pass by writing the file
    # ourselves when burn is invoked.
    def _fake_burn(video, tracks, output_path, callback=None):
        Path(output_path).write_bytes(b"\x00" * 64)
        return True
    monkeypatch.setattr(tr, "burn_subtitles", _fake_burn)

    tr._run_burn_pipeline(pid)

    assert not (pdir / "raw_audio.wav").exists(), "raw_audio should be cleaned"
    assert not (pdir / "demucs_out").exists(), "demucs_out should be cleaned"


def test_burn_failure_preserves_intermediates(tmp_project_dir, monkeypatch):
    """Failure path: intermediates remain so user can debug / re-run ASR."""
    from app.api import translate as tr
    from app.api import projects as projects_api
    from app.utils import project_store

    monkeypatch.setattr(tr, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    pid = "burnfail1"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    project = projects_api._apply_safe_defaults({
        "id": pid, "name": "t", "video_path": "/fake.mp4",
        "status": "translated", "error": None, "source_type": "upload",
    })
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
    )
    (pdir / "raw_audio.wav").write_bytes(b"\x00" * 1024)

    monkeypatch.setattr(tr, "burn_subtitles", lambda *a, **kw: False)

    tr._run_burn_pipeline(pid)

    assert (pdir / "raw_audio.wav").exists(), \
        "raw_audio.wav must remain on burn failure (user may re-run)"
```

- [ ] **Step 2: Run the test — it should FAIL with ImportError**

Run: `python3 -m pytest -q tests/test_audio_cleanup.py`

Expected: FAIL with `ImportError: cannot import name 'cleanup_intermediate' from 'app.engines.audio'`.

- [ ] **Step 3: Add `cleanup_intermediate` to `app/engines/audio.py`**

Append at the end of `app/engines/audio.py`:

```python
def cleanup_intermediate(output_dir: str) -> None:
    """Best-effort cleanup of per-project ASR intermediates.

    Removes `raw_audio.wav` and the entire `demucs_out/` tree from
    `output_dir`. Called after burn success — by then the user-visible
    artifact (the subtitled video) is on disk and the audio can go.

    Failures are logged and swallowed: a stuck file must NEVER degrade a
    'completed' project to 'error'.
    """
    raw = os.path.join(output_dir, "raw_audio.wav")
    demucs = os.path.join(output_dir, "demucs_out")
    if os.path.exists(raw):
        try:
            os.remove(raw)
            log.info("cleanup_intermediate: removed %s", raw)
        except OSError as e:
            log.warning("cleanup_intermediate: raw_audio.wav remove failed: %s", e)
    if os.path.isdir(demucs):
        try:
            shutil.rmtree(demucs, ignore_errors=False)
            log.info("cleanup_intermediate: removed %s", demucs)
        except OSError as e:
            log.warning("cleanup_intermediate: demucs_out rmtree failed: %s", e)
```

- [ ] **Step 4: Run the two unit tests — should pass**

Run: `python3 -m pytest -q tests/test_audio_cleanup.py::test_cleanup_intermediate_removes_raw_and_demucs tests/test_audio_cleanup.py::test_cleanup_intermediate_is_noop_when_absent`

Expected: 2 passed.

- [ ] **Step 5: Wire cleanup into `_run_burn_pipeline` success branch**

In `app/api/translate.py`, in `_run_burn_pipeline` (around line 505-511), modify the success branch:

```python
        if success:
            _out = output_video
            mutate_project(pid, lambda p: p.update({"status": "completed",
                                                     "output_video": _out,
                                                     "error": None}),
                           normalize=_apply_safe_defaults)
            _emit_progress(pid, "burn", 100, "全部完成! 字幕已烧录到视频")
            from app.engines.audio import cleanup_intermediate
            cleanup_intermediate(pdir)
        else:
```

- [ ] **Step 6: Wire cleanup into `start_burn._burn_task` success branch**

In `app/api/translate.py`, in `_burn_task` inside `start_burn` (around line 654-660), modify the success branch identically:

```python
                if success:
                    _out = output_video
                    mutate_project(pid, lambda p: p.update({"status": "completed",
                                                             "output_video": _out,
                                                             "error": None}),
                                   normalize=_apply_safe_defaults)
                    _emit_progress(pid, "burn", 100, "字幕烧录完成!")
                    from app.engines.audio import cleanup_intermediate
                    cleanup_intermediate(pdir)
                else:
```

- [ ] **Step 7: Run the integration tests — should pass**

Run: `python3 -m pytest -q tests/test_audio_cleanup.py`

Expected: 4 passed.

- [ ] **Step 8: Run full suite**

Run: `python3 -m pytest -q`

Expected: **221 passed** (218 + 3 new audio cleanup integration tests — the simple unit test + integration tests = 4 new total but one of them is already counted; recount: pre-Task-6 = 218, Task-6 adds 4 → 222. Wait: 215 (Task 1) + 1 (Task 3) + 1 (Task 4) + 1 (Task 5) + 4 (Task 6) = 222. The spec said 221. Off by one — actual is **222**. Treat 222 as the target.)

- [ ] **Step 9: Commit**

```bash
git add app/engines/audio.py app/api/translate.py tests/test_audio_cleanup.py
git commit -m "feat(audio): clean up raw_audio.wav + demucs_out after burn success

Audio intermediates (raw_audio.wav 10-100 MB and the demucs_out tree with
vocals/no_vocals WAVs) accumulated indefinitely in each project dir after
a successful pipeline. The subtitled video is the user-visible artifact;
once it's on disk, the audio intermediates can go.

Failure paths preserve intermediates so the user can debug or re-run ASR
without re-extracting audio.

New helper: app/engines/audio.py::cleanup_intermediate. Called from both
burn entry points (_run_burn_pipeline and start_burn._burn_task) in their
success branches. Failures from the cleanup itself are logged and
swallowed — must never demote a 'completed' project to 'error'."
```

---

## Final verification

- [ ] **Step 1: Full suite, full output**

Run: `python3 -m pytest -v`

Expected: **222 passed** (or 221 — see Task 6 Step 8 reconciliation; either way no failures).

- [ ] **Step 2: Inspect the branch's commit log**

Run: `git log --oneline main..HEAD`

Expected: 7 commits — the initial "chore: remove unrelated…" commit + the 6 Phase-5 commits in order (B / C-2 / C-3 / C-5 / C-1 / C-4).

- [ ] **Step 3: Read the diff to main once end-to-end**

Run: `git diff --stat main..HEAD`

Expected: 5 source files modified (knowledge.py, projects.py, translate.py, app.js, audio.py) + 4 test files modified or added + .gitignore + spec/plan docs.

---

## Self-review (writing-plans skill checklist)

**1. Spec coverage:**
- C-1 → Task 5 ✓
- C-2 → Task 2 ✓
- C-3 → Task 3 ✓
- C-4 → Task 6 ✓
- C-5 → Task 4 ✓
- B → Task 1 ✓

**2. Placeholder scan:** No "TBD", "TODO", or unspecified behavior. The reconciled test count (Task 6 Step 8) is the only place with ambiguity — explicitly resolved to 222.

**3. Type consistency:**
- `cleanup_intermediate(output_dir: str) -> None` is defined in Task 6 Step 3 and called identically in Steps 5 & 6.
- `_apply_safe_defaults` referenced consistently across tasks.
- HTTPException status codes (400 / 404) match the existing projects.py pattern.

**4. Scope check:** Six small items, one branch, one merge — appropriate size.
