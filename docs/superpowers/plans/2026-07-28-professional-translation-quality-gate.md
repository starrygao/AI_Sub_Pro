# Professional Translation Quality Gate Implementation Plan

## Objective

Make “professional” translation mode enforce a real fail-closed delivery policy,
repair context-dependent subtitle defects safely, preserve professional subtitle
formatting, surface one authoritative QA result in the UI, and replay the latest
project before releasing the new desktop version.

## Global Constraints

- Follow strict TDD: add each regression test first, run it, and confirm the
  expected failure before changing production code.
- Preserve existing fast-mode behavior unless a shared safety invariant requires
  fail-closed handling.
- In professional or strict mode, a semantic mismatch must block final artifact
  delivery; semantic uncertainty must require human review.
- Semantic QA unavailable, failed, partial, or stale must never be reported as
  complete coverage or unattended delivery.
- A QA report may certify only the exact translation run and subtitle content it
  was generated for.
- Never claim successful repair for unchanged, duplicate, still-failing, or
  not-improved results.
- Every model mutation must be followed by deterministic final normalization
  before QA certification and export.
- Structural two-speaker line breaks must survive translated and bilingual SRT
  output.
- The export dialog and quality panel must use the same persisted backend QA
  findings, augmented by local unsaved structural checks without double counting.
- Do not hard-code series-specific terms into generic runtime code.
- Preserve unrelated user changes in the main checkout.

## Task 1: Strict professional gate and fresh QA identity

### Requirements

1. Bind professional/strict mode to backend policy rather than UI labels.
2. Make semantic mismatch blocking in professional/strict mode.
3. Make semantic uncertainty set `requires_human_review=true` and prevent
   unattended final delivery in professional/strict mode.
4. Treat unavailable provider, import failure, batch failure, malformed response,
   and partial semantic coverage as fail-closed in professional/strict mode.
5. Track requested, checked, failed, and skipped semantic block IDs accurately.
6. Add a per-run identity and deterministic source/translation content hash to
   the quality report.
7. Invalidate prior certification at translation start and reject missing,
   malformed, stale, or hash-mismatched reports.
8. Do not swallow QA persistence failures that could otherwise allow delivery.
9. Replace the existing test that intentionally approves a known semantic
   mismatch and add regressions for provider failure and stale-report reuse.

### Verification

- Focused integration and QA tests demonstrate RED then GREEN for mismatch,
  uncertainty, provider failure, partial coverage, and stale reports.
- Existing non-professional compatibility tests remain green.

## Task 2: Context-aware repair, truthful statistics, and final normalization

### Requirements

1. Include bounded preceding and following cue context in repair items.
2. Group adjacent semantic findings so cue-boundary meaning can be repaired
   coherently without changing IDs or timing.
3. Track repair attempts, non-empty responses, changed unique IDs, improved IDs,
   and still-failing IDs separately.
4. Never use “复检通过” when any finding remains or a round is `not_improved`.
5. Rerun all deterministic normalizers after every model repair and immediately
   before certification/export.
6. Expand source and target SDH recognition for the confirmed common forms,
   including pounding, whistles, gurgling, croaking, and no-audible-dialogue
   variants.
7. Ensure auto-repair cannot reintroduce pure or mixed SDH labels in clean-dialogue
   mode.

### Verification

- Regression tests cover paired-cue context, repeated IDs, unchanged responses,
  not-improved rounds, common SDH forms, and post-repair SDH reintroduction.

## Task 3: Professional subtitle formatting and terminology consistency

### Requirements

1. Preserve structural two-speaker line breaks in translated and bilingual SRT.
2. Continue compacting ordinary non-structural short line wraps where safe.
3. Preserve source punctuation such as interrupted-speech trailing `--` in the
   bilingual source track.
4. Add prompt and deterministic validation contracts for speaker-line
   preservation across translation, polish, and repair.
5. Strengthen project-KB terminology enforcement and final consistency checks for
   repeated proper names, places, and context-selected domain terms without
   hard-coding the current series.
6. Expose source block ID to translated output ID mapping in the persisted report
   or subtitle API.

### Verification

- Regression tests cover two-speaker cues, speaker labels, ordinary wraps,
  interrupted source punctuation, term drift, and ID mapping.

## Task 4: One authoritative UI quality view

### Requirements

1. Merge persisted backend QA issues with local unsaved structural issues for
   export decisions and counts.
2. Deduplicate equivalent findings and retain severity.
3. Show semantic mismatch, semantic uncertainty, QA failure, and human-review
   labels in Chinese.
4. Provide access to every residual issue rather than silently truncating after
   four.
5. Show “passed with warnings” or “requires human review” accurately; never
   display ready-to-export language for a blocked professional report.
6. Reconcile terminal progress so project, workflow, websocket, and persisted
   progress consumers agree that translation-only completion is complete.

### Verification

- Frontend behavior tests cover backend-only warnings, local-only edits,
  deduplication, warning-only confirmation, human-review blocking, full issue
  visibility, and terminal progress.

## Task 5: End-to-end replay and release

### Requirements

1. Run focused suites after each task and the complete test suite after final
   review.
2. Replay latest project `0737e65f` in an isolated project copy using professional
   mode and a project glossary derived from the audited episode context.
3. Verify semantic coverage, report freshness, UI/report parity, terminology
   consistency, SDH policy, speaker formatting, timing, and artifact completeness.
4. Perform an independent final code review and resolve all Critical/Important
   findings.
5. Merge the reviewed branch into `main`, create a commit, build/install the new
   desktop version, verify the running version, and remove the superseded
   installed version without deleting project data.
