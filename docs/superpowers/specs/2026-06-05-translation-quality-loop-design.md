# Translation Quality Closed Loop Design

Date: 2026-06-05
Branch: `codex/v2-upgrade-roadmap`

## Goal

Build an automatic subtitle translation quality loop for AI Sub Pro so common
errors such as literal place-name translations, inconsistent character names,
missed context, untranslated text, and stiff subtitle phrasing are detected and
fixed without requiring the user to manually inspect every line.

The finished system must cover four phases:

1. Automatic project knowledge-base discovery.
2. Local translation memory and optional colloquial phrase retrieval.
3. Post-translation QA with targeted repair.
4. Evaluation, reporting, documentation, and product UI.

## Current Context

The current app already has a useful foundation:

- `app/engines/translator.py` builds translation prompts, selects providers,
  injects project KB snippets, and applies provider results.
- `app/engines/knowledge.py` and `app/engines/kb_models.py` store project
  knowledge base entries for names, places, brands, slang, and style notes.
- `app/api/knowledge.py` exposes KB CRUD endpoints.
- `docs/superpowers/specs/2026-06-03-v2-upgrade-roadmap-design.md` already
  calls out translation evaluation and KB productization as v2 priorities.
- Existing tests cover translator prompt injection and provider result
  reconciliation, but they do not yet prove translation quality improvement.

The missing layer is not a larger static glossary. The app needs a closed loop:
learn useful project facts, retrieve only relevant examples, translate with
explicit constraints, inspect the result, repair only the lines that fail QA,
and preserve user corrections for future runs.

## Design Principles

- **Local first:** All user video text, translation memory, QA reports, and
  learned corrections stay on the user's machine.
- **Traceable automation:** Automatic suggestions are explainable and reviewable.
  Hard constraints must show their evidence source.
- **Strict priority order:** User corrections beat project KB; project KB beats
  metadata suggestions; metadata beats public phrase examples; the model's free
  choice comes last.
- **Small prompt footprint:** Retrieve a small number of highly relevant memory
  or phrase examples instead of injecting a large phrase book.
- **Repair narrowly:** QA repair operates on failing blocks and known issues,
  not by re-translating the whole document.
- **Deterministic baseline:** CI must verify rules, schema, alignment, and report
  generation without paid or network provider calls.

## Phase 1: Automatic Project KB Discovery

### User Outcome

Before translation starts, the app proposes likely names, places, organizations,
titles, key phrases, and style notes for the current project. The user can accept
or reject suggestions, and accepted entries become hard translation constraints.

### Inputs

- Project metadata: name, TMDB ID, title, original title, cast, crew, overview,
  season, episode, and release year when present.
- Subtitle source blocks.
- Existing project KB.
- Optional previous project entries for the same TMDB title.

### Suggestion Types

- `character`: credited character or speaker-like proper noun.
- `person`: actor, creator, doctor, detective, or named person when the target
  label should remain stable.
- `place`: location, hospital, town, neighborhood, clinic, school, or named
  facility.
- `organization`: police department, hospital department, company, agency.
- `title`: show, episode, book, file, or in-universe work title.
- `phrase`: recurring idiom, slang, or show-specific expression.
- `style`: tone, register, or subtitle-specific rule.

### Heuristics

- Detect capitalized English spans from subtitles and metadata.
- Prefer multi-word capitalized spans over single words.
- Treat words following prepositions such as `at`, `in`, `to`, `from`, and
  `near` as possible places when capitalized.
- Treat recurring forms with stable capitalization as stronger candidates.
- Reject common false positives such as sentence-initial `I`, `We`, `The`, day
  names, month names, and generic medical terms unless metadata confirms them.
- Detect collisions against existing KB by source term and target term.

### Storage

Suggestions are project-local artifacts, not global settings:

```text
<project_dir>/kb_suggestions.json
```

Each suggestion stores:

- `id`
- `type`
- `source`
- `target`
- `notes`
- `confidence`
- `evidence`
- `status`: `pending`, `accepted`, `rejected`
- `created_at`

## Phase 2: Translation Memory And Colloquial Phrase Retrieval

### User Outcome

When the user edits a translated subtitle line, the app learns the correction.
Future translations automatically retrieve similar examples from local memory.
Optional public phrase libraries can be installed locally for broader colloquial
examples, but they remain lower priority than user memory.

### Translation Memory

Translation memory entries are created from user-confirmed edits and explicit
imports. Each entry stores:

- `source_text`
- `machine_translation`
- `final_translation`
- `source_language`
- `target_language`
- `project_name`
- `tmdb_id`
- `genre`
- `speaker`
- `context_before`
- `context_after`
- `created_at`
- `usage_count`

Initial implementation uses SQLite with FTS5 when available. If FTS5 is not
available, it falls back to simple LIKE scoring so tests remain portable.

### Public Phrase Library

Public phrase libraries are optional and installable. They must not be required
for core translation. Candidate sources:

- OPUS OpenSubtitles for subtitle-domain bilingual examples.
- Tatoeba for short sentence translations.
- Opusparcus for same-language paraphrase inspiration.
- FLORES-style corpora for evaluation, not as primary subtitle phrase examples.

Every imported source row must keep source metadata and license metadata. The
app should retrieve only a compact set of examples for the current batch:

- Same language pair.
- Similar source text.
- Short enough to fit subtitle style.
- High enough quality score or trusted source.
- Maximum 10 examples per provider call.

## Phase 3: Post-Translation QA And Targeted Repair

### User Outcome

After translation, the app automatically reports and repairs common subtitle
translation defects. Users get a concise quality report instead of discovering
problems only after watching the video.

### QA Checks

The first implementation must support deterministic checks:

- Missing translation.
- English residue in Chinese target output.
- Source IDs missing or duplicated.
- Source/target row count mismatch.
- Accepted KB source appears but required target term is missing.
- A source term is translated multiple different ways.
- Subtitle translation is too long for comfortable reading.
- Sound-description blocks are translated when they should be blank or preserved
  according to rule.

The second implementation can add model-assisted checks:

- Context-sensitive tense/time errors.
- Literal place-name translations.
- Overly formal phrasing.
- Medical/legal term consistency.
- Character voice mismatch.

### Repair Loop

Repair uses the existing provider contract and sends only failing blocks plus
the QA issue list. It must:

- Preserve subtitle IDs.
- Preserve accepted KB terms.
- Preserve timing and block order.
- Run at most two repair rounds by default.
- Stop early when deterministic critical issues are gone.
- Store all changed lines in the QA report.

Repair must never silently overwrite the original source text. The final
translated blocks and report together prove what changed.

## Phase 4: Evaluation, Reporting, UI, And Documentation

### Evaluation

Add a deterministic evaluation package under `app/evaluation/` with:

- Golden corpus loader.
- Metrics for terminology hit rate, missing translation rate, alignment rate,
  format breakage rate, English residue, and length limit violations.
- JSON and Markdown report output.
- CLI runner:

```bash
python3 -m app.evaluation.cli --corpus tests/fixtures/golden_corpus/milestone1.json --format markdown
```

Default CI mode must not call a paid or network provider. Provider-backed
evaluation may be opt-in.

### Report Artifacts

Each translation task should be able to store:

```text
<project_dir>/translation_qa_report.json
<project_dir>/translation_qa_report.md
```

The report includes:

- Overall status.
- Counts by issue type.
- Repaired blocks.
- Unresolved blocks.
- KB hits and misses.
- Memory examples used.
- Phrase-library examples used.

### UI

The frontend should expose:

- Reviewable KB suggestions.
- Toggle for learning from user edits.
- QA report summary.
- Button to run QA again.
- Clear list of unresolved issues requiring manual review.

### Documentation

Update English and Chinese usage docs with:

- How automatic KB suggestions work.
- How translation memory is learned and stored locally.
- How optional phrase libraries work and why licenses matter.
- How to run evaluation locally.
- What the QA report means.

## Data Priority

Prompt construction must use this precedence:

1. Accepted user correction memory for similar lines.
2. Accepted project KB.
3. Current project metadata suggestions.
4. Public phrase library examples.
5. General style rules.
6. Provider model knowledge.

When entries conflict, the higher-priority source wins and the conflict is
recorded in the trace/report.

## Error Handling

- Malformed suggestion, memory, phrase, or report files should fail with a
  clear warning and continue with the remaining valid data.
- Missing optional phrase libraries should not block translation.
- QA repair provider failure should leave the original translation intact and
  mark repair as failed in the report.
- Ambiguous KB suggestions stay pending; they are not auto-accepted.
- Local storage write failures are surfaced in task logs and do not corrupt
  existing project files.

## Testing Requirements

Completion requires tests proving:

- Suggestion extraction catches person/place/organization examples and filters
  common false positives.
- Suggestion collisions are detected and not auto-merged.
- Translation memory records user edits and retrieves similar examples.
- Phrase library retrieval respects language pair and result limits.
- Translator prompts include memory and phrase snippets with the correct
  priority order.
- QA detects missing translations, English residue, KB misses, duplicate IDs,
  row mismatch, and overly long lines.
- Repair prompts include only failing blocks and preserve IDs.
- Evaluation CLI emits stable JSON and Markdown reports.
- Frontend tests cover displaying suggestions and QA report summaries.

## Completion Evidence

The feature is complete only when:

- Unit and API tests for all new backend modules pass.
- Frontend JavaScript tests pass.
- Full `pytest` passes.
- Documentation is updated in English and Chinese.
- The local desktop app can run and expose the new workflow without startup
  errors.
- A sample subtitle run produces a QA report artifact.
