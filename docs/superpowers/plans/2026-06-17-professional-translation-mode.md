# Professional Translation Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn AI Sub Pro's translation flow from "strong automatic draft" into an explicit two-mode workflow: fast automatic draft mode and professional delivery mode with reviewable KB, deterministic QA, and visible quality gates.

**Architecture:** Keep the existing translation pipeline and project UI. Add a small mode flag in translation settings, derive professional-mode behavior from that flag, and extend existing cards instead of adding a parallel workflow. Professional mode must be opt-in so the previously fixed automatic flow remains non-blocking by default.

**Tech Stack:** Python FastAPI, Alpine.js frontend, existing KB suggestion and QA modules, pytest, Node VM frontend tests.

---

### Task 1: Translation Mode Configuration

**Files:**
- Modify: `app/config.py`
- Modify: `app/api/settings.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_settings_claude_cli.py`

- [ ] **Step 1: Write tests for a translation mode setting**

Add assertions that default config has `translation.quality_mode == "fast"` and that settings reject invalid modes.

```python
assert translation["quality_mode"] == "fast"
```

```python
({"translation": {"quality_mode": "slow"}}, "quality_mode")
```

- [ ] **Step 2: Add the setting**

Add this default:

```python
"quality_mode": "fast",
```

Validate it with allowed values:

```python
_validate_choice_field(
    "translation",
    translation,
    "quality_mode",
    allowed={"fast", "professional"},
)
```

- [ ] **Step 3: Run config/settings tests**

Run:

```bash
python3 -m pytest tests/test_config.py tests/test_settings_claude_cli.py
```

Expected: all tests pass.

### Task 2: Professional Mode Strategy And KB Gate

**Files:**
- Modify: `app/engines/translation_strategy.py`
- Modify: `app/api/translate.py`
- Modify: `tests/test_project_metadata.py`
- Modify: `tests/test_translate_start_validation.py`

- [ ] **Step 1: Test mode appears in strategy**

Extend `test_build_translation_strategy_explains_profiles_retrieval_and_qa` to assert:

```python
assert strategy["quality_mode"]["id"] == "professional"
assert strategy["quality_mode"]["requires_kb_review"] is True
```

- [ ] **Step 2: Test professional mode blocks on pending KB suggestions**

Add a start-translate validation test with:

```python
monkeypatch.setattr(
    translate_api.Config,
    "to_dict",
    lambda: {"translation": {"quality_mode": "professional"}},
)
```

Expected: `POST /start-translate` returns `409` with `code == "kb_review_required"`.

- [ ] **Step 3: Implement derived behavior**

In `translation_strategy`, return a `quality_mode` object that explains the mode and gate behavior. In `translate.py`, treat `quality_mode == "professional"` as requiring KB suggestion review while preserving `fast` default behavior.

- [ ] **Step 4: Run focused backend tests**

Run:

```bash
python3 -m pytest tests/test_project_metadata.py tests/test_translate_start_validation.py
```

Expected: all tests pass.

### Task 3: Project UI Professional Mode Visibility

**Files:**
- Modify: `app/static/js/app.js`
- Modify: `app/static/index.html`
- Modify: `tests/test_frontend_knowledge_js.py`
- Modify: `tests/test_frontend_accessibility.py`

- [ ] **Step 1: Add frontend tests for mode pills**

Ensure `normalizeTranslationStrategy()` accepts a `quality_mode` object and `translationStrategyCapabilityPills()` includes `专业模式` when active.

- [ ] **Step 2: Show the mode without redesigning the card**

Keep the existing strategy card. Add mode text and a pill derived from `quality_mode.label`.

- [ ] **Step 3: Run frontend knowledge/accessibility tests**

Run:

```bash
python3 -m pytest tests/test_frontend_knowledge_js.py tests/test_frontend_accessibility.py
```

Expected: all tests pass.

### Task 4: Inline KB Suggestion Editing In Project Card

**Files:**
- Modify: `app/static/js/app.js`
- Modify: `app/static/index.html`
- Modify: `tests/test_frontend_knowledge_js.py`

- [ ] **Step 1: Test accepted single suggestion sends edited target**

In the project quality helper test, load a suggestion with empty `target`, set `state.kbSuggestions[0].target = "奥利弗·沃尔夫"`, call `setKbSuggestionStatus(item, "accepted")`, and assert the POST body includes the target.

- [ ] **Step 2: Implement local patch before accept**

When a project-card suggestion is accepted, send the current `target` and `notes` with the status request:

```js
{status, target: cleanedTarget, notes: cleanedNotes}
```

Backend should update the persisted suggestion before applying accepted status.

- [ ] **Step 3: Add compact target input**

In the project-card suggestion row, show a small input for `item.target` when status is not accepted. Keep the card compact and preserve existing buttons.

- [ ] **Step 4: Run frontend and KB API tests**

Run:

```bash
python3 -m pytest tests/test_frontend_knowledge_js.py tests/test_knowledge_api.py
```

Expected: all tests pass.

### Task 5: QA Issues As A Review Queue

**Files:**
- Modify: `app/static/js/app.js`
- Modify: `app/static/index.html`
- Modify: `tests/test_frontend_knowledge_js.py`
- Modify: `tests/test_frontend_subtitle_js.py`

- [ ] **Step 1: Test normalized QA issues are reviewable**

Add tests for:

```js
state.qaReportTopIssues()
state.qaIssueLabel(issue)
state.focusSubtitleById(12)
```

Expected: top issues are capped, labels are readable, and focus sets the editor/search state without mutating subtitle rows.

- [ ] **Step 2: Add a compact issue list**

In the quality report card, show the first 3-5 issues with severity, label, and block id. Make block ids clickable when present.

- [ ] **Step 3: Add row focus helper**

Implement a helper that scrolls to the subtitle row if the DOM exists and sets `editingIdx`/`editText` to that row's translation for immediate correction.

- [ ] **Step 4: Run frontend tests**

Run:

```bash
python3 -m pytest tests/test_frontend_knowledge_js.py tests/test_frontend_subtitle_js.py
```

Expected: all tests pass.

### Task 6: Local Video Regression Harness

**Files:**
- Do not commit user video or subtitle content.
- Use local project: `data/projects/fe43271a`

- [ ] **Step 1: Verify local project artifacts exist**

Run:

```bash
test -f data/projects/fe43271a/raw.srt
test -f data/projects/fe43271a/translated.srt
test -f data/projects/fe43271a/project.json
```

Expected: all commands return 0.

- [ ] **Step 2: Run deterministic QA against the existing translated SRT**

Use existing project APIs or a small local script to parse the project and inspect `translation_qa_report.json` generation without committing media output.

- [ ] **Step 3: Record verification only**

Summarize issue count, hard errors, and whether professional mode would block. Do not commit generated reports from user media unless explicitly requested.

### Task 7: Broad Regression And Packaging Gate

**Files:**
- No code changes expected.

- [ ] **Step 1: Run focused tests from changed areas**

Run:

```bash
python3 -m pytest tests/test_config.py tests/test_settings_claude_cli.py tests/test_project_metadata.py tests/test_translate_start_validation.py tests/test_knowledge_api.py tests/test_frontend_knowledge_js.py tests/test_frontend_subtitle_js.py tests/test_frontend_accessibility.py
```

Expected: all tests pass.

- [ ] **Step 2: Run full test suite when time allows**

Run:

```bash
python3 -m pytest
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

Commit after tests pass:

```bash
git add app tests docs/superpowers/plans/2026-06-17-professional-translation-mode.md
git commit -m "Add professional translation mode workflow"
```

## Completion Criteria

- Fast mode remains the default and does not block on KB suggestions.
- Professional mode explicitly blocks on unreviewed KB suggestions.
- Translation strategy explains the active mode and gates.
- Project UI lets users fill KB suggestion targets before accepting.
- QA report card exposes actionable issue rows and can jump to subtitles.
- Focused tests pass; full suite passes before packaging or reinstall.
- Local user video is used only as private verification evidence, not committed content.
