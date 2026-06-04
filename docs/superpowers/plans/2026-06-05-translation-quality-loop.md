# Translation Quality Closed Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build automatic subtitle translation quality improvement through KB suggestions, local translation memory, phrase retrieval, deterministic QA, targeted repair hooks, reports, evaluation, UI, and bilingual documentation.

**Architecture:** Keep the current translation pipeline stable and add focused modules under `app/engines/` and `app/evaluation/`. Persist suggestions, memory, phrase examples, and QA reports locally; integrate them into `translator.py`, `translate.py`, `projects.py`, and the existing KB/editor frontend with small adapter calls.

**Tech Stack:** Python dataclasses, SQLite/JSON local storage, FastAPI, pytest, vanilla JavaScript state tests, existing project store helpers.

---

## File Structure

- Create `app/engines/kb_suggestions.py`: extract project KB candidates from metadata and subtitles, persist suggestion files, accept/reject entries.
- Create `app/engines/translation_memory.py`: local SQLite-backed memory of user subtitle edits, with portable LIKE fallback retrieval.
- Create `app/engines/phrase_library.py`: optional local phrase examples and retrieval API, initially JSON/SQLite import-ready.
- Create `app/engines/translation_qa.py`: deterministic issue detection, report model, Markdown/JSON serialization, repair prompt helpers.
- Create `app/engines/kb_trace.py`: trace prompt KB/memory/phrase usage for reports.
- Create `app/evaluation/__init__.py`, `corpus.py`, `metrics.py`, `reports.py`, `cli.py`: deterministic evaluation runner.
- Create `tests/fixtures/golden_corpus/translation_quality_loop.json`: small CI-safe corpus.
- Modify `app/engines/translator.py`: retrieve memory/phrase examples and expose the prompt trace.
- Modify `app/api/translate.py`: generate suggestions before translation, run QA after translation, persist reports.
- Modify `app/api/projects.py`: learn from user subtitle edits.
- Modify `app/api/knowledge.py`: expose suggestion and QA report endpoints.
- Modify `app/static/js/app.js` and `app/static/index.html`: load suggestions and QA report summaries.
- Update `docs/USAGE.md` and `docs/USAGE.zh-CN.md`.

## Task 1: Deterministic KB Suggestions

- [x] Add tests in `tests/test_kb_suggestions.py` for extracting `Hudson Oaks`, `Dr. Pierce`, and recurring character/place candidates while filtering sentence-start false positives.
- [x] Implement `KbSuggestion`, extraction, collision detection, load/save, accept/reject in `app/engines/kb_suggestions.py`.
- [x] Add API tests proving `/api/knowledge/projects/{pid}/suggestions` lists and mutates project-local suggestions.
- [x] Wire suggestion endpoints in `app/api/knowledge.py`.
- [x] Run `python3 -m pytest -q tests/test_kb_suggestions.py tests/test_knowledge_api.py`.

## Task 2: Translation Memory

- [x] Add tests in `tests/test_translation_memory.py` for recording an edit, rejecting empty/no-op edits, retrieving similar same-language examples, and respecting result limits.
- [x] Implement `TranslationMemoryStore` in `app/engines/translation_memory.py` using SQLite and deterministic scoring.
- [x] Modify `app/api/projects.py::save_subtitles` to compare old and new subtitle translations and record user edits when learning is enabled.
- [x] Add API tests proving a saved edit becomes retrievable memory.
- [x] Run `python3 -m pytest -q tests/test_translation_memory.py tests/test_subtitle_edit_api.py`.

## Task 3: Optional Phrase Library

- [x] Add tests in `tests/test_phrase_library.py` for importing phrase rows, preserving source/license metadata, language-pair filtering, and max result limits.
- [x] Implement `PhraseLibrary` in `app/engines/phrase_library.py` with JSON import and deterministic retrieval.
- [x] Keep public corpus import optional; no network access in tests or default app startup.
- [x] Run `python3 -m pytest -q tests/test_phrase_library.py`.

## Task 4: Prompt Context And Trace

- [x] Add tests in `tests/test_translator_quality_context.py` proving prompt order is memory, KB, phrase examples, style rules.
- [x] Add `TranslationContextTrace` in `app/engines/kb_trace.py`.
- [x] Modify `SubtitleTranslator` to retrieve memory and phrase examples per batch and include compact snippets.
- [x] Preserve provider contracts: `translate_batch(items, system_prompt)` stays unchanged.
- [x] Run `python3 -m pytest -q tests/test_translator_quality_context.py tests/test_translator_kb_integration.py`.

## Task 5: Deterministic QA And Reports

- [x] Add tests in `tests/test_translation_qa.py` for missing translation, English residue, duplicate/missing IDs, KB misses, inconsistent term translations, long lines, and sound-description behavior.
- [x] Implement issue model, report model, JSON/Markdown serialization, and `run_quality_checks()` in `app/engines/translation_qa.py`.
- [x] Add API test proving a translated project exposes `translation_qa_report.json`.
- [x] Run `python3 -m pytest -q tests/test_translation_qa.py tests/test_translate_integration.py`.

## Task 6: Targeted Repair Hook

- [x] Add tests proving repair prompt includes only failing blocks, issue descriptions, accepted KB terms, and original IDs.
- [x] Add `build_repair_items()` and `build_repair_prompt()` to `translation_qa.py`.
- [x] Integrate an optional repair pass in `app/api/translate.py` behind config `translation.qa_auto_repair`.
- [x] Default repair off until deterministic QA is verified; expose config but do not require provider calls in tests.
- [x] Run `python3 -m pytest -q tests/test_translation_qa.py tests/test_translate_integration.py`.

## Task 7: Evaluation Package

- [x] Add tests in `tests/test_eval_corpus.py`, `tests/test_eval_metrics.py`, and `tests/test_eval_cli.py`.
- [x] Implement `app/evaluation/corpus.py`, `metrics.py`, `reports.py`, and `cli.py`.
- [x] Add golden corpus fixture with proper noun, place, colloquial, long line, missing translation, and English residue cases.
- [x] Run `python3 -m pytest -q tests/test_eval_corpus.py tests/test_eval_metrics.py tests/test_eval_cli.py`.

## Task 8: Frontend Productization

- [x] Add frontend state tests for loading suggestions, accepting/rejecting suggestions, loading QA report summaries, and blocking duplicate QA actions.
- [x] Add KB suggestion and QA report panels to `app/static/index.html`.
- [x] Add methods/state in `app/static/js/app.js`.
- [x] Run `python3 -m pytest -q tests/test_frontend_knowledge_js.py tests/test_frontend_subtitle_js.py`.

## Task 9: Documentation And Verification

- [x] Update `docs/USAGE.md` and `docs/USAGE.zh-CN.md`.
- [x] Run focused pytest groups for new functionality.
- [x] Run full `python3 -m pytest -q`.
- [x] Run Python compile checks for new modules.
- [x] Start the local app and verify `/api/system-check` and project APIs still respond.
- [x] Produce a sample QA report from fixture/project data.

## Completion Gate

The work is complete only when all tasks above are implemented, all focused and
full tests pass, docs are updated in both languages, the local app starts, and a
sample QA report artifact exists.
