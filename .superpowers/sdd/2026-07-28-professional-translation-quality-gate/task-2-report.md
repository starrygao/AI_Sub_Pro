# Task 2 Report: Context-aware Repair and Final Normalization

## Outcome

Implemented context-aware subtitle repair, truthful repair statistics, complete
deterministic normalization around model repair, expanded SDH recognition, and
conclusion wording that does not claim a successful recheck when findings remain
or a repair round did not improve.

The Task 1 run-bound, fail-closed quality certification fields and validation
remain intact.

## RED evidence

All production changes were preceded by focused failing tests.

### Context and SDH behavior

Command:

```bash
python3 -m pytest -q tests/test_translation_qa.py \
  -k 'repair_items_include_bounded_context or sound_description_source_recognizes_common_production_forms or sound_description_target_recognizes_common_production_forms'
```

Observed result:

```text
9 failed, 4 passed, 52 deselected
```

The context test failed with `KeyError: 'preceding_context'`. The new gurgling,
croaking, no-audible-dialogue, and Chinese no-audible-dialogue forms were not
recognized. Pounding was then tightened from an already-recognized
`POUNDING ON DOOR` fixture to pure `[POUNDING]` and independently observed RED:

```text
10 failed, 2 passed, 53 deselected
```

### Statistics, conclusion, and post-repair normalization

Command:

```bash
python3 -m pytest -q tests/test_translate_integration.py \
  -k 'quality_gate_never_claims_recheck_passed or apply_repair_results_counts or records_improved_and_still_failing_ids or removes_sdh_reintroduced'
```

Observed result:

```text
4 failed, 66 deselected
```

The failures showed:

- `复检通过` was emitted after a `not_improved` round with a remaining finding.
- `_apply_nonempty_repair_results` had no trace/statistics contract.
- round traces lacked `nonempty_responses` and ID-level outcome fields.
- mixed `[POUNDING ON DOOR]` was exported after model repair.

## GREEN evidence

### Focused new and compatibility tests

Commands:

```bash
python3 -m pytest -q tests/test_translation_qa.py \
  -k 'repair_prompt_contains_only_failing_blocks or repair_items_include_bounded_context or sound_description_source_recognizes_common_production_forms or sound_description_target_recognizes_common_production_forms'

python3 -m pytest -q tests/test_translate_integration.py \
  -k 'quality_gate_never_claims_recheck_passed or apply_repair_results_counts or records_improved_and_still_failing_ids or removes_sdh_reintroduced or batches_auto_repair_and_records_trace or can_auto_repair_quality_issues'
```

Observed result:

```text
14 passed, 51 deselected
6 passed, 64 deselected
```

### Complete affected test files

Command:

```bash
python3 -m pytest -q tests/test_translation_qa.py tests/test_translate_integration.py
```

Observed result:

```text
135 passed in 1.36s
```

### Full repository suite

Command:

```bash
python3 -m pytest -q
```

Observed result:

```text
1365 passed in 86.19s (0:01:26)
```

Additional verification:

```bash
git diff --check
python3 -m compileall -q app/api/translate.py app/engines/translation_qa.py
```

Both exited successfully without output.

## Files changed

- `app/engines/translation_qa.py`
  - adds one preceding and one following cue as bounded repair context;
  - labels contiguous semantic failures with shared `semantic_group_ids`;
  - tells the model to use context without outputting context IDs and to return
    grouped repairs as separate unchanged IDs;
  - recognizes pounding, whistles, gurgling, croaking, no-audible-dialogue
    variants, and confirmed Chinese no-audible-dialogue forms.
- `app/api/translate.py`
  - distinguishes non-empty responses from actual translation changes;
  - counts changed IDs uniquely even when response IDs repeat;
  - records resolved and still-failing IDs per round;
  - classifies a non-empty unchanged response as `not_improved`;
  - runs all deterministic translation normalizers before initial QA, after
    every changed model repair, and immediately before certification;
  - prevents pure or mixed SDH labels from surviving clean-dialogue repair;
  - prevents `复检通过` whenever findings remain or any round is
    `not_improved`.
- `tests/test_translation_qa.py`
  - covers paired-cue context/grouping and common source/target SDH forms.
- `tests/test_translate_integration.py`
  - covers repeated response IDs, unchanged responses, truthful round outcomes,
    not-improved wording, and SDH reintroduction after model repair.

## Repair-stat semantics

Each repair round records the following independent values:

- `repair_attempts` / compatibility alias `attempted_blocks`: number of repair
  item requests sent to the model, including a repeated ID if it was requested
  more than once.
- `nonempty_responses`: number of reconciled model responses with a non-blank
  string, whether or not the text changed.
- `changed_block_ids`: sorted unique subtitle IDs whose stored translation
  actually changed during the round.
- `changed_unique_ids`: cardinality of `changed_block_ids`.
- `improved_block_ids`: IDs that had findings before the round and have none
  after deterministic normalization and re-QA.
- `still_failing_block_ids`: IDs with findings after the round.

The final report also exposes these semantics in `summary.repair_stats`.
`quality_gate.auto_repaired_blocks` now uses changed unique IDs rather than raw
response count or repeated change records.

## Normalization semantics

The same deterministic normalizer set runs at three explicit phases:

1. `before_initial_qa`
2. `after_model_repair`
3. `before_certification`

Every pass includes sound-description cleanup, contextual-speaker annotation,
curated domain terms, inferred scientific terms, and inferred proper names.
If the final pass changes text, QA is rerun before the report is certified.
The phase and changed IDs are recorded under
`trace.deterministic_normalization_runs`.

## Concerns

No known blocking concerns. Context is intentionally bounded to one active cue
on each side to avoid prompt growth, and filtered cues are excluded from repair
context.
