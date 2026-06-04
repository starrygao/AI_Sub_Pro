# Milestone 3 Editor Release UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the next stacked upgrade slice: professional subtitle editing, release automation scaffolding, and production-tool UI polish.

**Architecture:** Keep the existing local-first FastAPI plus Alpine frontend boundaries. Editor operations stay client-side and persist through the existing subtitle API; release automation is added as repository scripts/workflows that dry-run safely in PRs; UI polish is additive around existing project/settings views.

**Tech Stack:** FastAPI, Pydantic, vanilla Alpine-style JavaScript, pytest, Node syntax checks, GitHub Actions YAML, shell/Python release helpers.

---

## File Map

- Modify `app/static/js/app.js`: editor state, quality checks, merge/bulk replace/timeline/project filter helpers.
- Modify `app/static/index.html`: editor toolbar, timeline strip, quality panel, project filters, grouped settings anchors.
- Modify `app/static/css/app.css`: compact editor/timeline/filter layout and mobile rules.
- Modify `tests/test_frontend_subtitle_js.py`: TDD coverage for merge, bulk replace, quality checks, export confirmation, shortcuts.
- Modify `tests/test_frontend_settings_js.py`: TDD coverage for project filters/settings groups when existing helper placement fits better here.
- Modify `tests/test_packaging_scripts.py`: release workflow, checksum, size-report, and optional ASR packaging checks.
- Create `.github/workflows/release.yml`: PR dry-run and tag/manual release workflow.
- Create `tools/release/prepare_release.py`: checksum and size report helper for existing artifacts.
- Create `docs/RELEASE_CHECKLIST.md` and `docs/RELEASE_CHECKLIST.zh-CN.md`: manual tag-to-release checklist.
- Modify `docs/RELEASE_NOTES.md`, `docs/RELEASE_NOTES.zh-CN.md`, `docs/USAGE.md`, and `docs/USAGE.zh-CN.md`: unreleased notes for editor, release automation, and UI polish.

## Task 1: Editor Quality Model And Merge Operation

**Files:**
- Modify `tests/test_frontend_subtitle_js.py`
- Modify `app/static/js/app.js`

- [ ] **Step 1: Write failing frontend tests**

Add tests proving:

```javascript
state.subtitles = [
  {index: 1, start: '00:00:00,000', end: '00:00:01,000', text: 'Hello', translation: '你好', filtered: false},
  {index: 2, start: '00:00:01,000', end: '00:00:03,000', text: 'world', translation: '世界', filtered: false},
];
await state.mergeSubtitleWithNext(0);
// one row remains, end is 00:00:03,000, source/translation text are joined, persist called once.
```

Also add a rollback-on-persist-failure case and a quality summary case that flags overlap, missing translation, zero duration, long lines, and high reading speed.

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py -k "mergeSubtitleWithNext or subtitle_quality"
```

Expected: tests fail because `mergeSubtitleWithNext()` and quality helpers do not exist yet.

- [ ] **Step 3: Implement minimal editor helpers**

Add focused helpers in `app/static/js/app.js` near existing subtitle methods:

- `subtitleDurationMs(item)`
- `subtitleQualityIssues()`
- `subtitleQualitySummary()`
- `hasSevereSubtitleIssues()`
- `joinSubtitleText(left, right)`
- `mergeSubtitleWithNext(idx)`

`mergeSubtitleWithNext()` must use `subtitleActionPending`, snapshot/rollback, `persistSubtitles()`, and `renumberSubtitles()` just like split/add/delete.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py -k "mergeSubtitleWithNext or subtitle_quality"
node --check app/static/js/app.js
git add app/static/js/app.js tests/test_frontend_subtitle_js.py
git commit -m "feat: add subtitle merge and quality checks"
```

## Task 2: Bulk Find/Replace And Export Confirmation

**Files:**
- Modify `tests/test_frontend_subtitle_js.py`
- Modify `app/static/js/app.js`

- [ ] **Step 1: Write failing tests**

Add tests proving:

```javascript
state.subtitleFindText = 'Stark';
state.subtitleReplaceText = '史塔克';
state.subtitleReplaceScope = 'translation';
const preview = state.subtitleReplacePreview();
// preview.count === 2 and no subtitle text is mutated.
await state.applySubtitleReplace();
// matching translation fields are replaced, persist called once, rollback works on failure.
```

Add a severe export warning test:

```javascript
state.subtitles = [{index: 1, start: '00:00:00,000', end: '00:00:00,000', text: 'Hello', translation: '', filtered: false}];
await state.exportSrt('translated');
// first call opens confirmation instead of API; decline skips API; accept calls API once.
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py -k "replace or export_quality"
```

Expected: tests fail because replace state/helpers and severe export confirmation do not exist.

- [ ] **Step 3: Implement minimal replace/export behavior**

Add state fields:

- `subtitleFindText`
- `subtitleReplaceText`
- `subtitleReplaceScope`
- `subtitleReplaceCaseSensitive`
- `subtitleQualityOverride`

Add helpers:

- `subtitleReplacePreview()`
- `replaceInSubtitleField(value, find, replacement, caseSensitive)`
- `applySubtitleReplace()`
- `subtitleExportWarningMessage(format)`

Update `exportSrt(format)` so severe quality issues require `askConfirm()` before the API call. Confirmation must be per export attempt and must not bypass `canExportSrt()`.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py -k "replace or export_quality"
node --check app/static/js/app.js
git add app/static/js/app.js tests/test_frontend_subtitle_js.py
git commit -m "feat: add subtitle bulk replace and export warnings"
```

## Task 3: Editor Toolbar, Shortcuts, Timeline Strip

**Files:**
- Modify `tests/test_frontend_accessibility.py`
- Modify `tests/test_frontend_subtitle_js.py`
- Modify `app/static/index.html`
- Modify `app/static/js/app.js`
- Modify `app/static/css/app.css`

- [ ] **Step 1: Write failing markup/helper tests**

Add tests proving:

- The editor includes controls bound to `subtitleFindText`, `subtitleReplaceText`, `applySubtitleReplace()`, `mergeSubtitleWithNext(idx)`, and `subtitleQualitySummary()`.
- Shortcut handler calls save/split/merge/add/delete when editing focus and current index make the operation valid.
- Timeline helper returns block percentages and remains stable without media duration.

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest -q tests/test_frontend_accessibility.py tests/test_frontend_subtitle_js.py -k "subtitle_editor_toolbar or shortcut or timeline"
```

Expected: tests fail because markup and helpers are absent.

- [ ] **Step 3: Implement UI**

Add above the subtitle table:

- Compact find/replace toolbar with scope selector and preview count.
- Quality summary strip with warning counts and first severe issue.
- Timeline strip where each subtitle row is a positioned segment; use deterministic pseudo-wave bars when no waveform file is available.
- Row action for merge with next.

Add `handleSubtitleShortcut(event, idx)` to support:

- `Cmd/Ctrl+Enter`: save edit.
- `Cmd/Ctrl+Shift+S`: split.
- `Cmd/Ctrl+Shift+M`: merge with next.
- `Cmd/Ctrl+Shift+A`: add after.
- `Cmd/Ctrl+Backspace`: delete.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
python3 -m pytest -q tests/test_frontend_accessibility.py tests/test_frontend_subtitle_js.py
node --check app/static/js/app.js
git add app/static/index.html app/static/js/app.js app/static/css/app.css tests/test_frontend_accessibility.py tests/test_frontend_subtitle_js.py
git commit -m "feat: add subtitle editor toolbar and timeline"
```

## Task 4: Release Automation Dry Run

**Files:**
- Modify `tests/test_packaging_scripts.py`
- Create `.github/workflows/release.yml`
- Create `tools/release/prepare_release.py`
- Modify `package.json`

- [ ] **Step 1: Write failing packaging tests**

Add tests proving:

- `.github/workflows/release.yml` exists and has `workflow_dispatch`, tag trigger `v*`, a PR-safe dry-run path, checksum generation, and `gh release upload` or `actions/upload-release-asset` equivalent.
- `tools/release/prepare_release.py` computes SHA-256 files and writes a JSON size report.
- Root `package.json` exposes a `release:prepare` script.

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest -q tests/test_packaging_scripts.py -k "release_workflow or release_prepare"
```

Expected: tests fail because workflow/helper/script are absent.

- [ ] **Step 3: Implement release helper and workflow**

`tools/release/prepare_release.py` must:

- Accept `--dist-dir`, `--output`, and `--checksum-dir`.
- Refuse missing dist dirs unless `--allow-empty` is passed.
- Emit deterministic JSON with artifact path, bytes, sha256, and generated checksum file.
- Print a concise summary.

The workflow must:

- Run tests and CSS build.
- Run packaging script checks.
- On PR/manual dry run, run release preparation with `--allow-empty`.
- On tag/manual publish, build macOS DMG, prepare checksums/size report, and upload release assets using `softprops/action-gh-release`.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
python3 -m pytest -q tests/test_packaging_scripts.py
python3 tools/release/prepare_release.py --dist-dir dist --output dist/release-size-report.json --checksum-dir dist --allow-empty
git add .github/workflows/release.yml tools/release/prepare_release.py package.json tests/test_packaging_scripts.py
git commit -m "feat: add release automation dry run"
```

## Task 5: Package Split Signals And Release Docs

**Files:**
- Modify `tests/test_packaging_scripts.py`
- Modify `build_mac.sh`
- Modify `build_win.bat`
- Modify `make_dmg.sh`
- Create `docs/RELEASE_CHECKLIST.md`
- Create `docs/RELEASE_CHECKLIST.zh-CN.md`
- Modify `docs/RELEASE_NOTES.md`
- Modify `docs/RELEASE_NOTES.zh-CN.md`
- Modify `docs/USAGE.md`
- Modify `docs/USAGE.zh-CN.md`

- [ ] **Step 1: Write failing tests**

Add tests proving:

- macOS build has `AISUBPRO_BUNDLE_LOCAL_ASR` defaulting to `0`, so heavyweight optional ASR dependencies are skipped unless explicitly requested.
- DMG script writes or preserves checksum generation hooks.
- English and Simplified Chinese release checklist files mention tag trigger, dry run, checksum verification, and optional ASR package strategy.

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest -q tests/test_packaging_scripts.py -k "optional_asr or release_checklist or checksum"
```

Expected: tests fail because package split controls and docs are incomplete.

- [ ] **Step 3: Implement packaging controls and docs**

Update scripts so default builds are base-app oriented:

- macOS: only bundle local `models/asr` and collect optional local ASR packages when `AISUBPRO_BUNDLE_LOCAL_ASR=1`.
- Windows: mirror the same opt-in variable.
- DMG: call `tools/release/prepare_release.py` after creating the DMG when Python is available.

Update bilingual docs/release notes with the new release flow and app/package distinction.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
python3 -m pytest -q tests/test_packaging_scripts.py
git diff --check
git add build_mac.sh build_win.bat make_dmg.sh docs/RELEASE_CHECKLIST.md docs/RELEASE_CHECKLIST.zh-CN.md docs/RELEASE_NOTES.md docs/RELEASE_NOTES.zh-CN.md docs/USAGE.md docs/USAGE.zh-CN.md tests/test_packaging_scripts.py
git commit -m "docs: document release pipeline and optional ASR packaging"
```

## Task 6: Project List And Settings Polish

**Files:**
- Modify `tests/test_frontend_settings_js.py`
- Modify `tests/test_frontend_accessibility.py`
- Modify `app/static/js/app.js`
- Modify `app/static/index.html`
- Modify `app/static/css/app.css`

- [ ] **Step 1: Write failing tests**

Add tests proving:

- `filteredProjects()` filters by search text, status, archived toggle, and sort mode.
- `recentTaskProjects()` returns busy/error/recent projects for a compact operations view.
- Settings markup exposes grouped anchors for provider, ASR, translation/export, TMDB, and storage/release guidance.
- Error display helper returns specific next-action text for provider, ASR, export, and network errors without exposing secrets.

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest -q tests/test_frontend_settings_js.py tests/test_frontend_accessibility.py -k "project_filter or recent_tasks or settings_groups or next_action"
```

Expected: tests fail because helpers/markup are absent.

- [ ] **Step 3: Implement UI polish**

Add state:

- `projectSearch`
- `projectStatusFilter`
- `projectSortMode`

Add helpers:

- `filteredProjects()`
- `recentTaskProjects(limit = 5)`
- `projectErrorNextAction(projectOrMessage)`

Update project list view to use filtered projects, show compact filters, and display recent task strip. Add settings anchors or grouped labels that make provider/ASR/export/TMDB/storage sections scannable.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
python3 -m pytest -q tests/test_frontend_settings_js.py tests/test_frontend_accessibility.py
node --check app/static/js/app.js
git add app/static/index.html app/static/js/app.js app/static/css/app.css tests/test_frontend_settings_js.py tests/test_frontend_accessibility.py
git commit -m "feat: polish project list and settings workflow"
```

## Task 7: Final Review And Verification

**Files:**
- Entire branch.

- [ ] **Step 1: Run focused gate**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py tests/test_frontend_settings_js.py tests/test_frontend_accessibility.py tests/test_packaging_scripts.py tests/test_subtitle_edit_api.py
node --check app/static/js/app.js
python3 tools/release/prepare_release.py --dist-dir dist --output dist/release-size-report.json --checksum-dir dist --allow-empty
git diff --check
```

- [ ] **Step 2: Run full suite**

Run:

```bash
python3 -m pytest -q
```

- [ ] **Step 3: Final review**

Dispatch a final reviewer over the stacked diff against `origin/codex/milestone2-workflow-asr`. Address findings with focused commits.

- [ ] **Step 4: Push and PR**

Create a stacked PR:

```bash
git push -u origin codex/milestone3-editor-release-ui
gh pr create --repo starrygao/AI_Sub_Pro --base codex/milestone2-workflow-asr --head codex/milestone3-editor-release-ui --title "feat: upgrade subtitle editor and release workflow"
```

The PR body must include focused tests, full-suite result, release-helper dry run result, and note that no packaged app/DMG was produced unless a real local package was built.
