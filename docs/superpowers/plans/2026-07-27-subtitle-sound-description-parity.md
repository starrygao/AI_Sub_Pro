# Subtitle Sound-Description Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate false “missing translation” export errors by making the backend sound-description classifier authoritative for both API responses and frontend export checks.

**Architecture:** `app.engines.translation_qa.is_sound_description_source()` remains the single classification implementation. Subtitle API responses annotate every editor block with a computed `sound_description: bool`; the frontend consumes that flag and removes its duplicate keyword classifier. PUT responses return refreshed annotations so source-text edits cannot leave stale classification in the editor.

**Tech Stack:** Python 3, FastAPI, JavaScript/Alpine.js, pytest, Node.js VM-based frontend tests

## Global Constraints

- Preserve the current product rule: pure sound-description rows remain untranslated and are omitted from translated output.
- Do not migrate or rewrite historical project files; compute metadata while loading and saving blocks.
- Add only backward-compatible response fields; existing request payloads and export formats remain unchanged.
- Treat only literal `sound_description === true` as exempt from missing-translation checks.
- Missing or malformed metadata must fail closed and must not hide a real blank dialogue translation.
- Do not maintain a second sound-description keyword list in JavaScript.
- Add no third-party dependencies.
- Tests must use repository fixtures or inline data, never the user runtime project directory.
- Preserve pre-existing `.DS_Store` and `.codebase-memory` worktree changes without staging or editing them.

---

## File Map

- Modify `app/api/projects.py`: add one response-payload helper and return canonical sound-description metadata from GET and PUT subtitle routes.
- Modify `app/static/js/app.js`: consume server metadata, refresh it after edits, and delete the duplicate JavaScript classifier.
- Modify `tests/test_subtitle_edit_api.py`: lock the API annotation contract and edit-time recomputation.
- Modify `tests/test_frontend_subtitle_js.py`: lock authoritative frontend behavior and metadata refresh.
- Modify `tests/test_translation_qa.py`: add real-world sound-cue inflection regressions to the canonical classifier.

---

### Task 1: Lock the canonical classifier against the failing real-world cues

**Files:**
- Modify: `tests/test_translation_qa.py:121-153`
- Test: `tests/test_translation_qa.py`

**Interfaces:**
- Consumes: `app.engines.translation_qa.is_sound_description_source(source: str) -> bool`
- Produces: regression coverage for the exact inflections that triggered the 50 false positives

- [ ] **Step 1: Write the classifier regression**

Add this test next to the existing sound-description positive and negative tests:

```python
@pytest.mark.parametrize("source", [
    "[gunshots]\n[people shouting]",
    "[tense music continues]\n[shouting]",
    "[walkers groaning]",
    "-[Negan grunting]\n-[walkers snarling]",
    "[The Croat breathing heavily]",
    "[Negan sighs]",
    "[lock rattling]",
    "[machines beeping]",
    "[sobs hysterically]",
    "[lively chatter]",
])
def test_sound_description_classifier_covers_export_regression_cues(source):
    from app.engines.translation_qa import is_sound_description_source

    assert is_sound_description_source(source) is True
```

- [ ] **Step 2: Run the focused test**

Run:

```bash
python3 -m pytest -q tests/test_translation_qa.py::test_sound_description_classifier_covers_export_regression_cues
```

Expected: PASS. The backend already classifies these rows correctly; this test protects the single source of truth before the API starts exposing it.

- [ ] **Step 3: Run the existing classifier-negative tests**

Run:

```bash
python3 -m pytest -q \
  tests/test_translation_qa.py::test_quality_checks_do_not_treat_speaker_labels_as_sound_descriptions \
  tests/test_translation_qa.py::test_quality_checks_do_not_treat_scientific_action_sentences_as_sound_descriptions
```

Expected: 2 passed. Speaker labels such as `[The Martian]` and ordinary dialogue containing action words must remain translatable.

- [ ] **Step 4: Commit the regression guard**

```bash
git add tests/test_translation_qa.py
git commit -m "test: cover real-world sound cue inflections"
```

---

### Task 2: Add canonical sound-description metadata to subtitle API responses

**Files:**
- Modify: `app/api/projects.py:20-45`
- Modify: `app/api/projects.py:1682-1743`
- Modify: `app/api/projects.py:1763-1827`
- Test: `tests/test_subtitle_edit_api.py`

**Interfaces:**
- Consumes: `is_sound_description_source(source: str) -> bool`
- Produces: `_subtitle_editor_payload(block: SubtitleBlock) -> dict`
- Produces: `GET /api/projects/{pid}/subtitles` blocks with `sound_description: bool`
- Produces: `PUT /api/projects/{pid}/subtitles` response with refreshed `blocks`

- [ ] **Step 1: Write a failing GET contract test**

Add this test after `test_get_subtitles_reports_actual_source_file`:

```python
def test_get_subtitles_returns_canonical_sound_description_metadata(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "filtered.srt").write_text(
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        "[gunshots]\n"
        "[people shouting]\n\n"
        "2\n"
        "00:00:01,000 --> 00:00:02,000\n"
        "[The Martian]\n\n",
        encoding="utf-8",
    )

    response = client.get(f"/api/projects/{pid}/subtitles")

    assert response.status_code == 200
    blocks = response.json()["blocks"]
    assert blocks[0]["sound_description"] is True
    assert blocks[1]["sound_description"] is False
```

- [ ] **Step 2: Write a failing PUT recomputation test**

Add this test beside the GET contract test:

```python
def test_save_subtitles_returns_recomputed_sound_description_metadata(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    response = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [{
            "index": 1,
            "start": "00:00:00,000",
            "end": "00:00:01,000",
            "text": "[grunting]",
            "translation": "",
            "sound_description": False,
        }],
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["count"] == 1
    assert body["blocks"][0]["sound_description"] is True
```

The request deliberately sends a false client value. The response must recompute from `text` and never trust client metadata.

- [ ] **Step 3: Run both API tests and verify they fail**

Run:

```bash
python3 -m pytest -q \
  tests/test_subtitle_edit_api.py::test_get_subtitles_returns_canonical_sound_description_metadata \
  tests/test_subtitle_edit_api.py::test_save_subtitles_returns_recomputed_sound_description_metadata
```

Expected: both fail because current responses do not contain `sound_description` or PUT `blocks`.

- [ ] **Step 4: Add the canonical payload helper**

Import the classifier in `app/api/projects.py`:

```python
from app.engines.translation_qa import is_sound_description_source
```

Add this helper near the subtitle parsing helpers:

```python
def _subtitle_editor_payload(block: SubtitleBlock) -> dict:
    payload = block.to_dict()
    payload["sound_description"] = is_sound_description_source(block.text)
    return payload
```

Do not accept `sound_description` while rebuilding `SubtitleBlock` from PUT data. The server derives it from the validated `text` field.

- [ ] **Step 5: Use the helper in GET and PUT**

Change the GET return value to:

```python
return {
    "blocks": [_subtitle_editor_payload(block) for block in blocks],
    "source": source_name,
}
```

Change the PUT return value to:

```python
return {
    "status": "ok",
    "count": len(blocks),
    "blocks": [_subtitle_editor_payload(block) for block in blocks],
}
```

- [ ] **Step 6: Run the API contract tests**

Run:

```bash
python3 -m pytest -q \
  tests/test_subtitle_edit_api.py::test_get_subtitles_returns_canonical_sound_description_metadata \
  tests/test_subtitle_edit_api.py::test_save_subtitles_returns_recomputed_sound_description_metadata
```

Expected: 2 passed.

- [ ] **Step 7: Run all subtitle editing API tests**

Run:

```bash
python3 -m pytest -q tests/test_subtitle_edit_api.py
```

Expected: all tests pass; source/translation persistence and filter state are unchanged.

- [ ] **Step 8: Commit the API contract**

```bash
git add app/api/projects.py tests/test_subtitle_edit_api.py
git commit -m "fix: expose canonical sound cue metadata"
```

---

### Task 3: Make frontend export checks consume only server metadata

**Files:**
- Modify: `app/static/js/app.js:3801-3959`
- Test: `tests/test_frontend_subtitle_js.py:1909-2097`

**Interfaces:**
- Consumes: each subtitle block's `sound_description: bool`
- Produces: `subtitleIsSoundDescription(item) -> bool`
- Preserves: `subtitleQualityIssues(format) -> Array`
- Preserves: `subtitleQualitySummary(format) -> {total, severe, warning, issues}`

- [ ] **Step 1: Write the failing authoritative-metadata test**

Add this test after `test_subtitle_quality_summary_flags_timing_translation_and_reading_speed`:

```python
def test_subtitle_quality_uses_backend_sound_description_metadata():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        const state = context.app();
        state.subtitles = [
          {
            index: 10,
            start: '00:00:00,000',
            end: '00:00:01,000',
            text: '[gunshots]\\n[people shouting]',
            translation: '',
            sound_description: true,
            filtered: false,
          },
          {
            index: 11,
            start: '00:00:01,000',
            end: '00:00:02,000',
            text: '[The Martian]',
            translation: '',
            sound_description: false,
            filtered: false,
          },
        ];

        const summary = state.subtitleQualitySummary('translated');
        const missing = summary.issues.filter((issue) => issue.code === 'missing_translation');
        if (summary.severe !== 1 || missing.length !== 1 || missing[0].index !== 11) {
          throw new Error(`unexpected canonical classification result ${JSON.stringify(summary)}`);
        }
        """
    )
```

This asserts both directions: backend `true` exempts a cue the old JavaScript list missed, while backend `false` prevents a bracketed speaker/title label from being hidden.

- [ ] **Step 2: Run the new frontend test and verify it fails**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py::test_subtitle_quality_uses_backend_sound_description_metadata
```

Expected: FAIL because current frontend ignores the API flag and misclassifies the first row.

- [ ] **Step 3: Replace the local classifier with a metadata reader**

Delete these methods from `app/static/js/app.js`:

```text
isSoundDescriptionText
isSubtitleSeparatorOnly
isSoundDescriptionLabel
isUnbracketedSoundDescriptionLabel
```

Add:

```javascript
subtitleIsSoundDescription(item) {
  return this.isPlainObject(item) && item.sound_description === true;
},
```

In `subtitleQualityIssues`, replace local text classification with:

```javascript
const sourceIsSoundDescription = this.subtitleIsSoundDescription(item);
```

Keep the existing early return for sound-description rows. In `subtitleQualityLinesForFormat`, change the translated branch to:

```javascript
} else if (normalizedFormat === 'translated') {
  parts.push(translation);
```

The quality loop already exits before this helper for canonical sound-description rows, so source text no longer needs a JavaScript heuristic fallback.

- [ ] **Step 4: Run the authoritative-metadata test**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py::test_subtitle_quality_uses_backend_sound_description_metadata
```

Expected: PASS.

- [ ] **Step 5: Update existing sound-cue frontend fixtures**

In `test_translated_export_quality_ignores_sound_cues_and_source_only_length`, add:

```javascript
sound_description: true,
```

to each pure sound-description row. Add:

```javascript
sound_description: false,
```

to the normal source row with `translation: '译文合格。'`.

Do not add a JavaScript vocabulary test. Classification vocabulary belongs to the backend regression in Task 1.

- [ ] **Step 6: Run the focused frontend quality tests**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py -k \
  'subtitle_quality_summary or translated_export_quality or export_quality_requires_confirmation'
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit the frontend source-of-truth change**

```bash
git add app/static/js/app.js tests/test_frontend_subtitle_js.py
git commit -m "fix: use backend sound cue classification in exports"
```

---

### Task 4: Refresh classification after every subtitle edit

**Files:**
- Modify: `app/static/js/app.js:4132-4135`
- Test: `tests/test_frontend_subtitle_js.py:130-235`

**Interfaces:**
- Consumes: PUT response `blocks[*].sound_description`
- Produces: `syncSubtitleServerMetadata(savedBlocks) -> void`
- Updates: `persistSubtitles() -> Promise<void>`

- [ ] **Step 1: Write a failing edit-refresh test**

Add this test beside the existing save/persist tests:

```python
def test_persist_subtitles_refreshes_sound_description_metadata():
    _run_node(
        """
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.currentProject = {id: 'p1'};
          state.subtitles = [{
            index: 1,
            start: '00:00:00,000',
            end: '00:00:01,000',
            text: '[grunting]',
            translation: '',
            sound_description: false,
            filtered: false,
          }];
          state.api = async (url, method) => {
            if (url !== '/api/projects/p1/subtitles' || method !== 'PUT') {
              throw new Error(`unexpected request ${method} ${url}`);
            }
            return {
              status: 'ok',
              count: 1,
              blocks: [{
                index: 1,
                start: '00:00:00,000',
                end: '00:00:01,000',
                text: '[grunting]',
                translation: '',
                sound_description: true,
                filtered: false,
              }],
            };
          };

          await state.persistSubtitles();

          if (state.subtitles[0].sound_description !== true) {
            throw new Error(`expected refreshed metadata ${JSON.stringify(state.subtitles[0])}`);
          }
          if (state.subtitleQualitySummary('translated').severe !== 0) {
            throw new Error('refreshed sound cue should not be reported as missing');
          }
        })().catch((error) => {
          console.error(error.message);
          process.exit(1);
        });
        """
    )
```

- [ ] **Step 2: Run the edit-refresh test and verify it fails**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py::test_persist_subtitles_refreshes_sound_description_metadata
```

Expected: FAIL because `persistSubtitles()` currently discards the PUT response.

- [ ] **Step 3: Implement metadata synchronization**

Add:

```javascript
syncSubtitleServerMetadata(savedBlocks) {
  const soundByIndex = new Map();
  if (Array.isArray(savedBlocks)) {
    savedBlocks.forEach((block) => {
      if (!this.isPlainObject(block) || !Number.isInteger(block.index)) return;
      soundByIndex.set(block.index, block.sound_description === true);
    });
  }
  this.subtitles.forEach((item) => {
    if (!this.isPlainObject(item)) return;
    item.sound_description = soundByIndex.get(item.index) === true;
  });
},
```

Update `persistSubtitles()`:

```javascript
async persistSubtitles() {
  this.renumberSubtitles();
  const data = await this.api(
    `/api/projects/${this.currentProject.id}/subtitles`,
    'PUT',
    { blocks: this.subtitles },
  );
  this.syncSubtitleServerMetadata(data?.blocks);
},
```

If a response is malformed, omits `blocks`, or omits an index, the matching row becomes `false`, so stale metadata cannot suppress a real missing translation.

- [ ] **Step 4: Run the edit-refresh test**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py::test_persist_subtitles_refreshes_sound_description_metadata
```

Expected: PASS.

- [ ] **Step 5: Run all editor mutation tests**

Run:

```bash
python3 -m pytest -q tests/test_frontend_subtitle_js.py -k \
  'save_edit or persist or add_subtitle or delete_subtitle or split_subtitle or merge_subtitle or replace'
```

Expected: all selected tests pass. Every mutation path already calls `persistSubtitles()`, so one synchronization point covers add, edit, split, merge, delete, and replace.

- [ ] **Step 6: Commit edit-time synchronization**

```bash
git add app/static/js/app.js tests/test_frontend_subtitle_js.py
git commit -m "fix: refresh subtitle classification after edits"
```

---

### Task 5: Verify the original failure and the broader subtitle workflow

**Files:**
- No product file changes
- Verification: API, frontend, translation QA, export, and full test suite

**Interfaces:**
- Consumes: completed Tasks 1-4
- Produces: evidence that the exact false-positive class is gone without weakening real missing-translation detection

- [ ] **Step 1: Run the complete focused regression set**

Run:

```bash
python3 -m pytest -q \
  tests/test_translation_qa.py \
  tests/test_subtitle_edit_api.py \
  tests/test_frontend_subtitle_js.py \
  tests/test_project_export.py
```

Expected: all tests pass.

- [ ] **Step 2: Run translation pipeline integration tests**

Run:

```bash
python3 -m pytest -q tests/test_translate_integration.py
```

Expected: all tests pass. Completion counts, sound-description omission, QA gating, and translated SRT generation remain unchanged.

- [ ] **Step 3: Run the full suite**

Run:

```bash
python3 -m pytest -q
```

Expected: all tests pass with no new failures.

- [ ] **Step 4: Reproduce the original UI signature with deterministic data**

Run:

```bash
python3 -m pytest -q \
  tests/test_translation_qa.py::test_sound_description_classifier_covers_export_regression_cues \
  tests/test_subtitle_edit_api.py::test_get_subtitles_returns_canonical_sound_description_metadata \
  tests/test_frontend_subtitle_js.py::test_subtitle_quality_uses_backend_sound_description_metadata
```

Expected: all three tests pass. `[gunshots]\n[people shouting]` is classified by the backend, carried through the API, and ignored by the translated-export missing check.

- [ ] **Step 5: Confirm real blank dialogue still blocks export**

Run:

```bash
python3 -m pytest -q \
  tests/test_frontend_subtitle_js.py::test_subtitle_quality_uses_backend_sound_description_metadata \
  tests/test_frontend_subtitle_js.py::test_export_quality_requires_confirmation_before_api_call_for_severe_issues
```

Expected: both tests pass. The `[The Martian]` row with backend `false` and ordinary blank dialogue still produce severe missing-translation issues.

- [ ] **Step 6: Review the final diff**

Run:

```bash
git diff --check
git diff --stat
git status --short
```

Expected: no whitespace errors; only the five product/test files and this plan document belong to this work. Pre-existing `.DS_Store` and `.codebase-memory` changes remain untouched.

- [ ] **Step 7: Commit final verification adjustments if test-only changes were needed**

```bash
git add \
  app/api/projects.py \
  app/static/js/app.js \
  tests/test_subtitle_edit_api.py \
  tests/test_frontend_subtitle_js.py \
  tests/test_translation_qa.py
git commit -m "test: verify subtitle sound cue parity"
```

Skip this commit when Step 6 shows no uncommitted planned changes.

---

## Acceptance Criteria

- The latest-task pattern `[gunshots]\n[people shouting]` never creates `missing_translation` when the backend marks it as a sound description.
- All pure sound-description rows returned by GET carry `sound_description: true`.
- A bracketed title or speaker label marked `sound_description: false` still requires a translation.
- PUT ignores client-supplied classification and returns a recomputed value.
- Source edits refresh classification before the user can export the saved result.
- JavaScript contains no sound-description keyword or morphology list.
- Historical projects need no file rewrite and are corrected on the next load.
- Translated SRT output continues to omit pure sound-description rows.
- The full test suite passes.

## Deliberate Non-Goals

- Do not change whether SDH/audio-description cues should be translated; that is a separate product-policy decision.
- Do not merge the local export-structure summary with the existing backend QA report. The quality report already has its own UI and API; this patch fixes the false severe count without changing QA semantics.
- Do not rewrite `translated.srt`, `bilingual.srt`, or `translation_qa_report.json` for existing projects.
