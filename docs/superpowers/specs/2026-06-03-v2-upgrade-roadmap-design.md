# AI Sub Pro v2 Upgrade Roadmap Design

Date: 2026-06-03
Branch: `codex/v2-upgrade-roadmap`

## Goal

Upgrade AI Sub Pro across seven product and engineering areas while keeping
the work reviewable and verifiable:

1. Translation quality evaluation loop.
2. Knowledge Base v2 productization.
3. Professional subtitle editor upgrades.
4. Release and packaging pipeline rebuild.
5. Unified ASR backend experience.
6. Stronger long-running workflow state.
7. Release-grade UI polish.

The full scope is too large for one implementation branch. The work will be
delivered as four milestones, each with its own implementation plan, tests,
review, verification, and merge preparation.

## Current System Context

The app is a local-first FastAPI desktop/web application with a vanilla
JavaScript frontend. The relevant current boundaries are:

- Translation orchestration lives mainly in `app/api/translate.py` and
  `app/engines/translator.py`.
- Knowledge Base models and matching live in `app/engines/kb_models.py`,
  `app/engines/knowledge.py`, and `app/api/knowledge.py`.
- Project persistence and editable subtitle timelines live in
  `app/api/projects.py` and `app/utils/project_store.py`.
- Long-running task state, semaphores, cancellation, and progress live in
  `app/engines/scheduler.py` and API task wrappers.
- The main frontend state lives in `app/static/js/app.js`, with markup in
  `app/static/index.html`.
- macOS release packaging is handled by `build_mac.sh` and `make_dmg.sh`.

Important pressure points:

- `app/static/js/app.js`, `app/api/translate.py`, and `app/api/projects.py`
  are large enough that major features should extract focused modules as part
  of the touched area.
- v1.1.1 fixed the critical KB metadata injection path. The next KB work
  should expose the benefit to users, not just strengthen internals.
- Current test coverage is broad, but it mostly verifies behavior and
  regressions. It does not provide a durable translation quality signal.
- GitHub release asset upload was painful for the v1.1.1 DMG, so release
  engineering needs first-class automation and package-size control.

## Milestone 1: Quality And KB Core

This milestone covers the translation quality evaluation loop and Knowledge
Base v2 productization.

### User Outcomes

- Developers can run a deterministic evaluation command after changing
  translator, KB, or provider code.
- The report shows whether translation quality moved in the right direction
  through concrete metrics instead of intuition.
- Users can review suggested KB entries extracted from TMDB metadata and
  subtitle content before accepting them into the project knowledge base.
- Users can inspect which KB entries affected a translation run.

### Components

#### Golden Corpus

Add a small, versioned corpus under a repository path such as
`tests/fixtures/golden_corpus/` or `eval/golden_corpus/`.

Each case should contain:

- Source subtitle blocks.
- Expected glossary terms and aliases.
- Optional reference translations for format and terminology checks.
- Case metadata: genre, source language, target language, project metadata,
  and tags such as `film`, `series`, `trailer`, `pun`, `proper_noun`,
  `long_sentence`, and `colloquial`.

The corpus must be small enough to run in CI without external provider calls.
Provider-dependent evaluation can be supported separately as an opt-in local
command.

#### Evaluation Runner

Add a CLI entry point that can run against deterministic fixtures and produce:

- Terminology hit rate.
- Format breakage rate.
- Missing translation rate.
- Subtitle row alignment rate.
- A manual scoring artifact for human review.

The default CI mode must not call paid or network providers. It should use
fixture outputs, fake providers, or stored candidate outputs. A local
provider-backed mode may be added behind an explicit flag.

#### KB Suggestions

Add a suggestion engine that reads:

- TMDB title, original title, cast, crew, characters, overview, and year.
- Existing subtitle text.
- Existing project KB entries.

It returns suggested entries with:

- Type: person, place, organization, title, phrase, style note, or glossary.
- Source evidence.
- Confidence.
- Collision status against existing entries.
- Preview of how the term would appear in prompts.

Suggestions are not written automatically. The user confirms, edits, rejects,
or bulk-accepts them.

#### KB Usage Explanation

During translation prompt construction and result application, preserve a
lightweight trace of which KB entries matched each run or block. The trace
should be stored as local project metadata, not in global settings.

The first implementation should expose run-level and block-level summaries:

- Matched entry key and display text.
- Match source: TMDB metadata, subtitle text, or existing KB.
- Scope: project, title, cast, style, or glossary.
- Translation block IDs affected when available.

### Data Flow

1. Project metadata and subtitles are loaded.
2. The suggestion engine produces candidate KB entries.
3. The frontend displays candidates for review.
4. Accepted candidates are persisted to the project KB.
5. Translation loads project metadata and KB entries.
6. Prompt construction records matched KB entries.
7. Translation output is saved with an explanation artifact.
8. Evaluation runner can compare output and traces against golden corpus
   expectations.

### Error Handling

- Malformed corpus files fail fast with clear validation errors.
- Missing reference outputs mark only dependent metrics as unavailable; they
  do not hide format or alignment checks.
- KB suggestions with ambiguous collisions must be surfaced as review-needed,
  not silently merged.
- Explanation trace failures must not fail translation, but they must be logged
  and covered by tests.

### Tests And Evidence

Completion evidence for this milestone:

- Unit tests for corpus schema validation and metric calculations.
- Tests proving row alignment, missing translation, format breakage, and
  terminology metrics catch known bad outputs.
- Tests proving TMDB/subtitle extraction creates suggestions and avoids
  duplicates.
- API tests for listing, accepting, rejecting, and persisting suggestions.
- Tests proving translation records KB usage explanation for matched entries.
- CLI output fixtures for JSON and Markdown reports.

## Milestone 2: Workflow Reliability And ASR Experience

This milestone covers unified ASR backend experience and stronger long-running
workflow state.

### User Outcomes

- Users choose intent-level ASR modes instead of backend package names.
- The app recommends a backend and model based on platform, installed
  packages, local caches, and user preference.
- Failed long-running tasks have actionable logs and can be retried or resumed
  from the last safe stage.
- Cancellation and cleanup are predictable.

### Components

#### ASR Capability Detector

Add a backend capability layer that reports:

- Platform and architecture.
- Installed ASR packages.
- Available local model caches.
- Whether VAD, beam search, Apple Silicon acceleration, and offline mode are
  supported.
- Estimated model size or download requirement when known.

Expose user-facing modes:

- Speed first.
- Accuracy first.
- Offline first.

The recommendation engine maps these modes to concrete backend/model choices.

#### Workflow State Model

Replace ad hoc progress metadata with a structured state model for long tasks:

- Stage name.
- Status: pending, running, succeeded, failed, cancelled, skipped.
- Started and finished timestamps.
- Input artifact path.
- Output artifact path.
- Retry count.
- Error summary and log path.
- Resume eligibility.

The first implementation should cover the main pipeline stages already present:
ASR, subtitle extraction, filtering, translation, trailer download, burn-in,
and export.

#### Logs And Recovery

Persist stage logs under the project directory with a bounded retention policy.
Expose a download endpoint for logs. Add retry/resume endpoints that validate
stage state before launching work.

### Data Flow

1. System check records ASR capabilities.
2. Settings UI displays recommended mode and concrete backend.
3. A workflow starts and creates a structured state file.
4. Each stage updates state atomically.
5. On failure, state records the failing stage and logs.
6. User can download logs, retry the stage, or resume from the last safe
   artifact.

### Error Handling

- Resume is allowed only from verified artifacts.
- Retry must respect existing task locks and semaphores.
- Logs must be bounded and must not include API keys.
- ASR recommendation must degrade gracefully when optional packages are absent.

### Tests And Evidence

Completion evidence for this milestone:

- Unit tests for ASR capability detection across simulated platforms.
- Tests for intent-to-backend recommendation.
- API/frontend tests for displaying backend recommendation and download size
  notes.
- Scheduler tests for state transitions, retry, resume, cancellation, and log
  download.
- Tests proving retry cannot run concurrently with an active task.

## Milestone 3: Professional Subtitle Editor

This milestone covers subtitle editor upgrades.

### User Outcomes

- Editing common subtitle problems is fast and keyboard-friendly.
- Users can bulk-fix terminology and punctuation without exporting to another
  tool.
- Export catches obvious quality issues before writing final SRT or burn-in
  output.
- Timeline and waveform help users reason about timing when available.

### Components

#### Editing Operations

Strengthen editor operations around:

- Split.
- Merge.
- Add before and after.
- Delete.
- Bulk find and replace.
- Undo and redo for local editor operations.
- Keyboard shortcuts for common actions.

Existing API contracts should be kept where possible. New operations should
preserve subtitle IDs, ordering, and timing invariants.

#### Quality Checks

Add export-before checks for:

- Empty subtitle text.
- Missing translation.
- Overlapping time ranges.
- Negative or zero duration.
- Excessive characters per line.
- Excessive reading speed.
- Unbalanced bilingual output.

Checks should be warnings by default, with explicit confirmation required to
export when severe issues remain.

#### Timeline And Waveform

Add a timeline panel after the core editing and validation work is stable.
The first version should show subtitle blocks against time and optionally a
waveform if waveform extraction is available locally. It must remain usable
without waveform data.

### Data Flow

1. Project subtitles load into editor state.
2. User applies local edits.
3. Edits are validated locally before persistence.
4. API persists the timeline atomically.
5. Export runs quality checks and returns warnings.
6. User fixes issues or confirms export.

### Error Handling

- Failed persistence rolls back optimistic UI edits.
- Merge and split must reject invalid timing.
- Bulk replace must show count and support dry-run preview.
- Waveform extraction failure must not block subtitle editing.

### Tests And Evidence

Completion evidence for this milestone:

- Backend tests for edit invariants and export quality checks.
- Frontend tests for split, merge, bulk replace, shortcuts, and rollback.
- Tests for severe warning confirmation before export.
- UI verification for desktop and mobile layouts.
- Manual smoke test with a real project timeline.

## Milestone 4: Release Engineering And UI Polish

This milestone covers release pipeline rebuild, package-size control, and
release-grade UI polish.

### User Outcomes

- Releases are repeatable and do not depend on manual asset upload steps.
- macOS packages are smaller and clearer about optional ASR dependencies.
- The UI feels like a focused production tool.

### Components

#### CI Release Pipeline

Add GitHub Actions workflows for:

- Python tests.
- Frontend CSS build.
- Packaging script checks.
- Release notes verification.
- macOS build on macOS runner where feasible.
- Checksum generation.
- GitHub Release asset upload.

Release automation should support dry runs for pull requests and real release
publishing for tags.

#### Package Split

Move toward a smaller base app and optional offline ASR assets:

- Base app contains UI, API, provider clients, ffmpeg helpers, and online/model
  download support.
- Optional ASR package contains heavyweight local ASR dependencies and offline
  models.
- Documentation explains the trade-off between small download and offline
  readiness.

The first version may keep current scripts but add explicit checks and size
reporting. Later versions can split artifacts once the runtime loading path is
verified.

#### UI Polish

Improve tool ergonomics without turning the app into a marketing page:

- Project list filtering and sorting.
- Recent tasks panel.
- More specific error messages with next actions.
- Settings grouped by provider, ASR, export, storage, and app language.
- Clearer empty states.
- Compact, scan-friendly layout for repeated daily use.

### Data Flow

1. A tag or manual workflow triggers release automation.
2. CI runs validation and builds package artifacts.
3. Checksums and release notes are generated or verified.
4. Assets are uploaded to the GitHub release.
5. UI surfaces release-grade task and configuration information to users.

### Error Handling

- CI release steps must fail before publishing incomplete assets.
- Asset upload should retry and report clear diagnostics.
- Package-size checks should warn on major regressions.
- UI errors should avoid exposing secrets and should point users to concrete
  recovery actions.

### Tests And Evidence

Completion evidence for this milestone:

- GitHub Actions workflow files exist and pass dry-run validation.
- Packaging checks generate size reports and checksums.
- Release notes checks cover English and Simplified Chinese files.
- UI tests cover project filtering, recent tasks, settings grouping, and error
  rendering.
- Manual release checklist documents tag-to-release flow.

## Cross-Milestone Architecture Rules

- Keep runtime data local and out of git.
- Do not call paid/network providers in default tests.
- Preserve project-store path safety and atomic writes.
- Prefer additive APIs with backward-compatible project metadata migrations.
- Split large frontend/backend modules only when touching the relevant
  responsibility.
- Every milestone must include tests that prove the user-facing behavior, not
  only internal helpers.
- Every milestone must finish with a verification summary and branch merge
  preparation.

## Workflow

Each milestone follows the requested process:

1. `brainstorming`: refine milestone scope and user-facing behavior.
2. `writing-plans`: create a task-by-task implementation plan.
3. `test-driven-development`: write failing tests for the core behavior before
   implementation.
4. `executing-plans`: implement the plan in small commits.
5. `systematic-debugging`: use when tests fail or runtime behavior diverges.
6. `requesting-code-review`: review the completed milestone branch.
7. `receiving-code-review`: address review findings.
8. `verification-before-completion`: run the milestone verification gate.
9. `finishing-a-development-branch`: prepare merge, push, and PR/release notes.

## Requirement Mapping

| Objective item | Milestone | Primary completion evidence |
| --- | --- | --- |
| Translation quality evaluation loop | 1 | Golden corpus, eval CLI, metrics, CI-safe reports |
| KB v2 productization | 1 | Suggestion API/UI, accepted entries, KB usage explanation |
| Subtitle editor upgrade | 3 | Edit operations, quality checks, shortcuts, timeline/waveform |
| Release pipeline rebuild | 4 | GitHub Actions release pipeline, checksums, package-size checks |
| Unified ASR experience | 2 | Capability detector, recommendation UI, backend mode tests |
| Stronger workflow state | 2 | Structured stage state, retry/resume, logs, cleanup tests |
| Release-grade UI polish | 4 | Project filtering, recent tasks, settings grouping, better errors |

## Validation Strategy

The final completion audit for the full objective must verify:

- All four milestones have completed implementation plans and merged code.
- The seven objective items have direct file, test, runtime, or release
  evidence.
- Full test suite passes.
- Frontend build passes.
- Relevant CLI commands and packaging checks pass.
- GitHub release pipeline dry run or real run has been verified.
- User-facing documentation is updated in English and Simplified Chinese where
  the behavior changes.

## Non-Goals

- Replacing the existing local-first architecture.
- Moving user data to a hosted backend.
- Requiring paid provider calls in default tests.
- Shipping a complex video editor beyond subtitle-focused timeline operations.
- Guaranteeing notarized macOS distribution before package signing credentials
  are configured.

