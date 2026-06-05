# Translation Accuracy Next Stage Design

Date: 2026-06-05
Base release: `v1.2.2`

## Goal

Improve AI Sub Pro translation accuracy in a way that is measurable on real
subtitle projects, not only by adding more synthetic phrase examples.

This stage focuses on three linked outcomes:

1. Evaluate translation quality against local reference subtitles.
2. Improve retrieval for translation memory and phrase examples.
3. Add a safe local import pipeline for larger real-world bilingual corpora.

The work must stay local-first. User media, subtitle files, generated reports,
translation memory, and imported corpus rows remain on the user's machine unless
the user explicitly publishes them.

## Current State

`v1.2.2` already includes a useful quality foundation:

- 12 bundled synthetic phrase packs with 612 examples.
- Language coverage for `en`, `ja`, `ko`, `es`, `fr`, and `de` into `zh-CN`.
- English medical, crime/procedural, and workplace domain phrase packs.
- Metadata-derived phrase tags that lightly boost matching domain examples.
- Local translation memory learned from user subtitle edits.
- Deterministic translation QA reports and an optional auto-repair pass.
- Evaluation modules for deterministic metrics and report generation.

The remaining gap is evidence and scale. Current retrieval uses deterministic
token overlap. The bundled packs are intentionally small and synthetic. The app
does not yet provide a first-class command that compares old output, new output,
and a local human reference subtitle for a real episode.

## Non-Goals

- Do not commit copyrighted subtitle content or downloaded public corpus rows to
  the repository.
- Do not require network downloads during normal app startup, tests, or packaged
  builds.
- Do not make model-based QA mandatory for every translation job.
- Do not replace the existing provider contract or project pipeline.
- Do not bundle large external corpora in the application package.

## Approach

Use a staged local pipeline:

1. Build local A/B evaluation around user-supplied subtitle files.
2. Upgrade retrieval so existing memory and phrase data are used better.
3. Add corpus import plumbing that can ingest larger local datasets safely.

This is better than only adding more hand-written phrase packs because it
creates a repeatable feedback loop: run a real sample, measure defects, improve
retrieval/import behavior, and rerun the same sample.

## Components

### 1. Local A/B Evaluation CLI

Add a command-line workflow under `tools/quality/` or `app/evaluation/` that can
compare:

- Source subtitle file.
- Old machine translation output.
- New machine translation output.
- Optional local human reference subtitle.

The CLI writes reports under a local output directory, for example:

```text
<output_dir>/translation_accuracy_report.json
<output_dir>/translation_accuracy_report.md
```

Metrics should include:

- Missing translation rate.
- English residue rate for Chinese target output.
- Subtitle length violations.
- Terminology hit rate when a KB/glossary is supplied.
- Proper-name consistency across the document.
- Alignment integrity: row count, IDs, timing, and empty sound-description rules.
- Reference similarity signals when a reference subtitle is supplied.

Reference similarity should start deterministic and lightweight. It does not
need to claim human-level quality scoring. It should highlight changed lines and
likely regressions for review.

### 2. Real Sample Harness

Support local project sample configuration without committing sample content.

The user's `Brilliant Minds` files can be used as a private fixture by passing
absolute local paths to the evaluation CLI. The report may be generated locally
and ignored by git. The repository may include a template config with placeholder
paths, but not the subtitle contents themselves.

The sample harness should support these modes:

- Compare existing output against a reference file.
- Compare newly generated output against the same reference file.
- Compare old output and new output directly when no reference is available.

### 3. Retrieval Upgrade

Improve `TranslationMemoryStore.retrieve()` and `PhraseLibrary.retrieve()`
without changing their public call sites.

Preferred implementation:

- Add SQLite FTS5 virtual tables when available.
- Use normalized source text, token text, language pair, pack id, tags, quality,
  and source/license metadata.
- Keep deterministic n-gram fallback when FTS5 is unavailable.
- Score candidates with a bounded formula:
  - lexical/FTS match
  - phrase quality
  - tag match
  - user memory priority
  - recency and usage count for memory
- Keep prompt footprint compact: maximum 6 memory lines and 6 phrase examples
  per provider call, unless settings explicitly raise the limit.

Migration must preserve existing SQLite data. Existing users with imported
phrase packs or memory entries should not lose rows.

### 4. Corpus Import Pipeline

Extend local phrase-pack import into a safer corpus ingestion pipeline.

Inputs:

- Local JSONL, TSV, or CSV bilingual rows.
- Required metadata: source name, license, source language, target language.
- Optional metadata: domain tags, quality score, row id, speaker, project name.

Processing:

- Validate metadata before import.
- Normalize whitespace and language codes.
- Reject empty source/target rows.
- Drop exact duplicates.
- Prefer short subtitle-like examples.
- Limit maximum imported rows per command unless an explicit flag raises it.
- Produce an import report with accepted, rejected, duplicate, and sampled rows.

The first version should not download public corpora directly. It can document
how to import local exports from sources such as subtitle-domain corpora or
sentence-pair corpora, but the user supplies the files and metadata.

### 5. Proper Name And Terminology Consistency

Extend deterministic QA and evaluation around consistency:

- Detect source proper nouns that recur multiple times.
- Detect whether the same source term maps to multiple different target forms.
- Respect accepted project KB as hard constraints.
- Prefer user memory over project KB, project KB over metadata suggestions,
  metadata suggestions over public phrase examples, and phrase examples over
  free model choice.

The QA report should distinguish:

- Hard errors: accepted KB term missing, row mismatch, missing translation.
- Warnings: inconsistent inferred proper noun, long line, English residue.
- Informational notes: phrase examples used, memory examples used, tag boosts.

### 6. Optional Repair Strategy

Keep `translation.qa_auto_repair` off by default until the deterministic
evaluation reports prove the repair loop improves results on local samples.

Add a more conservative repair policy:

- Run deterministic QA after translation.
- Repair only failing blocks.
- Preserve IDs, timing, source text, and accepted KB terms.
- Run at most two rounds.
- Write before/after repair lines into the QA report.
- Stop if the second round does not reduce hard errors.

## Data Flow

```text
local subtitles/reference
  -> evaluation CLI
  -> baseline report
  -> retrieval/corpus import improvements
  -> rerun translation
  -> QA + optional repair
  -> updated report
```

At translation time:

```text
project metadata + KB + local memory + phrase library
  -> retrieval scoring
  -> compact prompt snippets
  -> provider translation
  -> deterministic QA
  -> optional targeted repair
  -> reports and learned edits
```

## Configuration

Add settings conservatively:

- `translation.memory_retrieval_backend`: `auto`, `fts5`, or `ngram`.
- `translation.phrase_retrieval_backend`: `auto`, `fts5`, or `ngram`.
- `translation.max_memory_examples`: default `6`.
- `translation.max_phrase_examples`: default `6`.
- `translation.qa_auto_repair_rounds`: default `1`, max `2`.

Existing `use_translation_memory`, `use_phrase_library`, and `qa_auto_repair`
remain compatible.

## Error Handling

- If FTS5 is unavailable, fall back to deterministic n-gram scoring and include
  the fallback in trace metadata.
- If corpus import rows are malformed, reject those rows and continue unless the
  input file itself cannot be parsed.
- If a local sample path is missing, fail the evaluation command with a clear
  path-specific error.
- If model repair fails, keep the original translation and write the failure to
  the QA report.
- If a migration fails, do not delete existing SQLite data.

## Testing

Add focused tests for:

- Evaluation CLI report generation with small synthetic fixture files.
- Local sample config path validation without committing user subtitles.
- FTS5 retrieval when available.
- N-gram fallback retrieval.
- Migration from existing memory and phrase library schemas.
- Corpus import validation, duplicate handling, metadata preservation, and row
  limits.
- Proper-name consistency metrics.
- Conservative repair round stopping.

Full verification remains:

```bash
python3 -m pytest -q
```

## Documentation

Update both:

- `docs/USAGE.md`
- `docs/USAGE.zh-CN.md`

Document:

- How to run local A/B evaluation.
- How to import local bilingual corpus files.
- Why user-supplied subtitle/reference files are not committed.
- How retrieval backends and repair settings affect quality and cost.

## Acceptance Criteria

This stage is complete when:

- A local A/B evaluation command can produce JSON and Markdown reports.
- The user's local `Brilliant Minds` sample can be evaluated without committing
  the source files.
- Memory and phrase retrieval use FTS5 when available and deterministic fallback
  otherwise.
- Corpus import supports at least JSONL and TSV or CSV with strict metadata.
- QA reports include proper-name consistency signals.
- Existing v1.2.2 behavior remains compatible.
- Focused tests and the full test suite pass.
