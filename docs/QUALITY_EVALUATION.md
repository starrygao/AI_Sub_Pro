# Subtitle quality evaluation

Stored-candidate mode tests deterministic rules; it never measures a model. The
original 12 cases remain, and `context_regressions.json` adds 12 authored minimal
cases for pronouns, conditions, negation, slang, repeated names and sound cues.
They are explicitly marked authored, not falsely attributed to production runs.
Existing documentary/name failures remain in `translation_quality_loop.json`.

Generate fresh output through the production translator with an explicit model:

```sh
python -m app.evaluation.cli --execute --provider codex_cli --model gpt-5.5 \
  --corpus tests/fixtures/golden_corpus/context_regressions.json \
  --json-out evaluation/run.json --markdown-out evaluation/run.md
```

This makes actual provider calls. API credentials come from the application
configuration/system credential store. Omit `--execute` for offline rule checks.
Use `AI_SUB_PRO_DATA_DIR` to select the intended configuration directory.
No real model call is made by the test suite. Memory and phrase retrieval are
disabled for reproducibility. Provider/model/effort must be selected explicitly;
polishing is disabled in the CLI baseline, while the runner supports it.

Reports retain source, generated output and reference for every row, plus manual
scoring slots. Score accuracy, pronoun/condition fidelity, terminology and natural
subtitle wording before claiming a quality improvement. References are not fed
to the translator. `--baseline previous.json` reports rate deltas for identical
ordered cases; automatic rate improvements do not prove semantic improvement.

Timing uses a monotonic clock. Calls are provider batch submissions, including
translator-level retries; SDK-internal transport retries are not counted. Rework
is the fraction of source blocks resubmitted to the primary provider, with polish
calls tracked separately. Project-level QA repair is outside this runner's scope.
Failed executions are recorded with safe exception types and produce nonzero CLI
exit status. Human review is required even when deterministic metrics pass.

To add a real failure, reduce it to the smallest context-preserving clip, remove
private metadata, record its origin and model/run identity in `project`, and add
source, bad candidate and a reviewed reference. Keep reference IDs aligned with
source IDs. Commit only material the project is allowed to redistribute.
