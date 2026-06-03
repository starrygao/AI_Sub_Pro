# Milestone 1 Quality And KB Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic translation quality evaluation loop and productize KB v2 with suggested entries plus KB usage explanations.

**Architecture:** Add a focused `app/evaluation/` package for corpus loading, metrics, reports, and CLI entry points so translation quality checks do not bloat translator code. Add a focused KB suggestion/trace layer under `app/engines/` and expose it through existing FastAPI routers and the existing KB frontend view. Persist suggestions and trace artifacts as project-local JSON files so runtime data stays local.

**Tech Stack:** Python dataclasses, JSON fixtures, FastAPI, pytest, vanilla JavaScript state tests with Node `vm`, existing project store atomic JSON helpers.

---

## File Structure

- Create `app/evaluation/__init__.py`: package marker and public exports.
- Create `app/evaluation/corpus.py`: schema validation and loading for golden corpus JSON files.
- Create `app/evaluation/metrics.py`: deterministic metrics for terminology, format, missing translation, and row alignment.
- Create `app/evaluation/reports.py`: JSON and Markdown report serialization, including manual scoring artifacts.
- Create `app/evaluation/cli.py`: command line runner invoked with `python3 -m app.evaluation.cli`.
- Create `tests/fixtures/golden_corpus/milestone1.json`: small CI-safe corpus with film, series, trailer, pun, proper noun, long sentence, and colloquial examples.
- Create `tests/test_eval_corpus.py`, `tests/test_eval_metrics.py`, and `tests/test_eval_cli.py`: evaluation coverage.
- Create `app/engines/kb_suggestions.py`: TMDB/subtitle KB suggestion extraction and collision detection.
- Create `app/engines/kb_trace.py`: matched KB entry tracing and project-local persistence.
- Modify `app/api/knowledge.py`: suggestion list/accept/reject endpoints.
- Modify `app/engines/translator.py`: record KB prompt matches in a trace object without changing provider contracts.
- Modify `app/api/translate.py`: persist KB trace after translation tasks.
- Modify `app/static/js/app.js` and `app/static/index.html`: suggestion review and KB usage explanation panels.
- Extend `tests/test_knowledge_api.py`, `tests/test_translator_kb_integration.py`, and `tests/test_frontend_knowledge_js.py`.
- Update `docs/USAGE.md` and `docs/USAGE.zh-CN.md` with eval CLI and KB suggestion workflow.

## Task 1: Golden Corpus Loader

**Files:**
- Create: `app/evaluation/__init__.py`
- Create: `app/evaluation/corpus.py`
- Create: `tests/fixtures/golden_corpus/milestone1.json`
- Test: `tests/test_eval_corpus.py`

- [ ] **Step 1: Write the failing corpus tests**

Create `tests/test_eval_corpus.py`:

```python
import json

import pytest


def test_load_golden_corpus_validates_required_fields(tmp_path):
    from app.evaluation.corpus import CorpusValidationError, load_corpus_file

    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"cases": [{"id": "missing-blocks"}]}), encoding="utf-8")

    with pytest.raises(CorpusValidationError, match="source_blocks"):
        load_corpus_file(path)


def test_load_golden_corpus_normalizes_cases():
    from pathlib import Path

    from app.evaluation.corpus import load_corpus_file

    corpus = load_corpus_file(Path("tests/fixtures/golden_corpus/milestone1.json"))

    assert len(corpus.cases) >= 7
    assert {case.id for case in corpus.cases}
    assert {"film", "series", "trailer", "pun", "proper_noun", "long_sentence", "colloquial"} <= {
        tag for case in corpus.cases for tag in case.tags
    }
    first = corpus.cases[0]
    assert first.source_blocks[0]["id"] == "1"
    assert first.source_blocks[0]["text"]
    assert first.expected_terms
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_eval_corpus.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.evaluation'`.

- [ ] **Step 3: Create the corpus fixture**

Create `tests/fixtures/golden_corpus/milestone1.json`:

```json
{
  "version": 1,
  "cases": [
    {
      "id": "film-proper-noun",
      "tags": ["film", "proper_noun"],
      "source_language": "en",
      "target_language": "zh-CN",
      "project": {"name": "Moonlit Case", "tmdb_id": 101, "cast": ["Elsbeth Tascioni"]},
      "source_blocks": [
        {"id": "1", "text": "Elsbeth, the Moonlit Club is not a joke."}
      ],
      "candidate_blocks": [
        {"id": "1", "translation": "艾尔斯贝丝，月光俱乐部不是玩笑。"}
      ],
      "expected_terms": [
        {"source": "Elsbeth", "target": "艾尔斯贝丝"},
        {"source": "Moonlit Club", "target": "月光俱乐部"}
      ],
      "reference_blocks": [
        {"id": "1", "translation": "艾尔斯贝丝，月光俱乐部不是玩笑。"}
      ]
    },
    {
      "id": "series-colloquial",
      "tags": ["series", "colloquial"],
      "source_language": "en",
      "target_language": "zh-CN",
      "project": {"name": "Harbor Room S01E02", "tmdb_id": 202, "cast": ["Maya Chen"]},
      "source_blocks": [
        {"id": "1", "text": "Maya, that plan is way off."}
      ],
      "candidate_blocks": [
        {"id": "1", "translation": "玛雅，这个计划太离谱了。"}
      ],
      "expected_terms": [
        {"source": "Maya", "target": "玛雅"}
      ],
      "reference_blocks": [
        {"id": "1", "translation": "玛雅，这个计划太离谱了。"}
      ]
    },
    {
      "id": "trailer-tagline",
      "tags": ["trailer"],
      "source_language": "en",
      "target_language": "zh-CN",
      "project": {"name": "Last Signal Trailer", "tmdb_id": 303, "overview": "A rescue team hears one final call."},
      "source_blocks": [
        {"id": "1", "text": "This summer, one signal changes everything."}
      ],
      "candidate_blocks": [
        {"id": "1", "translation": "这个夏天，一个信号改变一切。"}
      ],
      "expected_terms": [
        {"source": "signal", "target": "信号"}
      ],
      "reference_blocks": [
        {"id": "1", "translation": "这个夏天，一个信号改变一切。"}
      ]
    },
    {
      "id": "pun-line",
      "tags": ["pun"],
      "source_language": "en",
      "target_language": "zh-CN",
      "project": {"name": "Bread Winner", "tmdb_id": 404},
      "source_blocks": [
        {"id": "1", "text": "I knead answers, not excuses."}
      ],
      "candidate_blocks": [
        {"id": "1", "translation": "我要的是答案，不是借口。"}
      ],
      "expected_terms": [
        {"source": "knead", "target": "揉"}
      ],
      "reference_blocks": [
        {"id": "1", "translation": "我要的是答案，不是借口。"}
      ]
    },
    {
      "id": "long-sentence",
      "tags": ["long_sentence"],
      "source_language": "en",
      "target_language": "zh-CN",
      "project": {"name": "Long Night", "tmdb_id": 505},
      "source_blocks": [
        {"id": "1", "text": "When the doors finally opened, everyone who had waited in silence realized the warning had been real."}
      ],
      "candidate_blocks": [
        {"id": "1", "translation": "当门终于打开时，所有沉默等待的人都意识到那个警告是真的。"}
      ],
      "expected_terms": [
        {"source": "warning", "target": "警告"}
      ],
      "reference_blocks": [
        {"id": "1", "translation": "当门终于打开时，所有沉默等待的人都意识到那个警告是真的。"}
      ]
    },
    {
      "id": "missing-translation-fixture",
      "tags": ["film"],
      "source_language": "en",
      "target_language": "zh-CN",
      "project": {"name": "Silent Frame", "tmdb_id": 606},
      "source_blocks": [
        {"id": "1", "text": "Do not leave the frame."},
        {"id": "2", "text": "Stay with me."}
      ],
      "candidate_blocks": [
        {"id": "1", "translation": "不要离开画面。"},
        {"id": "2", "translation": ""}
      ],
      "expected_terms": [
        {"source": "frame", "target": "画面"}
      ],
      "reference_blocks": [
        {"id": "1", "translation": "不要离开画面。"},
        {"id": "2", "translation": "跟着我。"}
      ]
    },
    {
      "id": "format-preservation-fixture",
      "tags": ["series"],
      "source_language": "en",
      "target_language": "zh-CN",
      "project": {"name": "Code Room", "tmdb_id": 707},
      "source_blocks": [
        {"id": "1", "text": "<i>Run protocol 7.</i>"}
      ],
      "candidate_blocks": [
        {"id": "1", "translation": "<i>执行 7 号协议。</i>"}
      ],
      "expected_terms": [
        {"source": "protocol 7", "target": "7 号协议"}
      ],
      "reference_blocks": [
        {"id": "1", "translation": "<i>执行 7 号协议。</i>"}
      ]
    }
  ]
}
```

- [ ] **Step 4: Implement corpus loader**

Create `app/evaluation/__init__.py`:

```python
"""Translation quality evaluation helpers."""
```

Create `app/evaluation/corpus.py`:

```python
"""Golden corpus loading and validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class CorpusValidationError(ValueError):
    """Raised when a golden corpus file cannot be used for evaluation."""


@dataclass(frozen=True)
class CorpusCase:
    id: str
    tags: list[str]
    source_language: str
    target_language: str
    project: dict[str, Any]
    source_blocks: list[dict[str, str]]
    candidate_blocks: list[dict[str, str]]
    expected_terms: list[dict[str, str]]
    reference_blocks: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class GoldenCorpus:
    version: int
    cases: list[CorpusCase]


def _string(value: Any, field: str, case_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorpusValidationError(f"{case_id}: {field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str, case_id: str) -> list[str]:
    if not isinstance(value, list):
        raise CorpusValidationError(f"{case_id}: {field} must be a list")
    cleaned = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CorpusValidationError(f"{case_id}: {field} contains a non-string item")
        cleaned.append(item.strip())
    return cleaned


def _blocks(value: Any, field: str, case_id: str, text_key: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise CorpusValidationError(f"{case_id}: {field} must be a non-empty list")
    blocks = []
    for item in value:
        if not isinstance(item, dict):
            raise CorpusValidationError(f"{case_id}: {field} entries must be objects")
        blocks.append({
            "id": _string(item.get("id"), f"{field}.id", case_id),
            text_key: item.get(text_key, "") if isinstance(item.get(text_key, ""), str) else "",
        })
    return blocks


def _terms(value: Any, case_id: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise CorpusValidationError(f"{case_id}: expected_terms must be a list")
    terms = []
    for item in value:
        if not isinstance(item, dict):
            raise CorpusValidationError(f"{case_id}: expected_terms entries must be objects")
        source = _string(item.get("source"), "expected_terms.source", case_id)
        target = _string(item.get("target"), "expected_terms.target", case_id)
        terms.append({"source": source, "target": target})
    return terms


def _case(raw: Any) -> CorpusCase:
    if not isinstance(raw, dict):
        raise CorpusValidationError("case entries must be objects")
    case_id = _string(raw.get("id"), "id", "<case>")
    project = raw.get("project", {})
    if not isinstance(project, dict):
        raise CorpusValidationError(f"{case_id}: project must be an object")
    return CorpusCase(
        id=case_id,
        tags=_string_list(raw.get("tags", []), "tags", case_id),
        source_language=_string(raw.get("source_language"), "source_language", case_id),
        target_language=_string(raw.get("target_language"), "target_language", case_id),
        project=dict(project),
        source_blocks=_blocks(raw.get("source_blocks"), "source_blocks", case_id, "text"),
        candidate_blocks=_blocks(raw.get("candidate_blocks"), "candidate_blocks", case_id, "translation"),
        expected_terms=_terms(raw.get("expected_terms", []), case_id),
        reference_blocks=_blocks(raw.get("reference_blocks", []), "reference_blocks", case_id, "translation")
        if raw.get("reference_blocks") else [],
    )


def load_corpus_file(path: str | Path) -> GoldenCorpus:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CorpusValidationError("corpus root must be an object")
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CorpusValidationError("version must be a positive integer")
    cases_raw = raw.get("cases")
    if not isinstance(cases_raw, list) or not cases_raw:
        raise CorpusValidationError("cases must be a non-empty list")
    return GoldenCorpus(version=version, cases=[_case(item) for item in cases_raw])
```

- [ ] **Step 5: Run corpus tests**

Run: `python3 -m pytest -q tests/test_eval_corpus.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/evaluation/__init__.py app/evaluation/corpus.py tests/fixtures/golden_corpus/milestone1.json tests/test_eval_corpus.py
git commit -m "test: add golden corpus loader"
```

## Task 2: Evaluation Metrics

**Files:**
- Create: `app/evaluation/metrics.py`
- Test: `tests/test_eval_metrics.py`

- [ ] **Step 1: Write failing metric tests**

Create `tests/test_eval_metrics.py`:

```python
from app.evaluation.corpus import CorpusCase


def make_case(candidate_blocks):
    return CorpusCase(
        id="metric-case",
        tags=["film"],
        source_language="en",
        target_language="zh-CN",
        project={"name": "Metric Case"},
        source_blocks=[
            {"id": "1", "text": "<i>Elsbeth enters.</i>"},
            {"id": "2", "text": "Moonlit Club waits."},
        ],
        candidate_blocks=candidate_blocks,
        expected_terms=[
            {"source": "Elsbeth", "target": "艾尔斯贝丝"},
            {"source": "Moonlit Club", "target": "月光俱乐部"},
        ],
        reference_blocks=[],
    )


def test_evaluate_case_scores_perfect_output():
    from app.evaluation.metrics import evaluate_case

    result = evaluate_case(make_case([
        {"id": "1", "translation": "<i>艾尔斯贝丝进来了。</i>"},
        {"id": "2", "translation": "月光俱乐部在等。"},
    ]))

    assert result["terminology"]["hit_rate"] == 1.0
    assert result["missing_translation"]["rate"] == 0.0
    assert result["row_alignment"]["rate"] == 1.0
    assert result["format"]["breakage_rate"] == 0.0


def test_evaluate_case_catches_bad_output():
    from app.evaluation.metrics import evaluate_case

    result = evaluate_case(make_case([
        {"id": "1", "translation": "Elsbeth enters."},
        {"id": "3", "translation": ""},
    ]))

    assert result["terminology"]["hit_rate"] == 0.0
    assert result["missing_translation"]["missing_ids"] == ["3"]
    assert result["row_alignment"]["missing_ids"] == ["2"]
    assert result["row_alignment"]["extra_ids"] == ["3"]
    assert result["format"]["broken_ids"] == ["1"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_eval_metrics.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.evaluation.metrics'`.

- [ ] **Step 3: Implement metrics**

Create `app/evaluation/metrics.py`:

```python
"""Deterministic translation quality metrics."""
from __future__ import annotations

import re
from typing import Any

from app.evaluation.corpus import CorpusCase


_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _by_id(blocks: list[dict[str, str]], text_key: str) -> dict[str, str]:
    result = {}
    for block in blocks:
        block_id = str(block.get("id", "")).strip()
        if block_id:
            value = block.get(text_key, "")
            result[block_id] = value if isinstance(value, str) else ""
    return result


def _tags(text: str) -> list[str]:
    return _TAG_RE.findall(text if isinstance(text, str) else "")


def _round(value: float) -> float:
    return round(value, 4)


def terminology_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    combined = "\n".join(candidate_by_id.values())
    hits = []
    misses = []
    for term in case.expected_terms:
        target = term["target"]
        if target and target in combined:
            hits.append(term)
        else:
            misses.append(term)
    total = len(case.expected_terms)
    return {
        "hit_count": len(hits),
        "total": total,
        "hit_rate": _round(len(hits) / total) if total else 1.0,
        "misses": misses,
    }


def missing_translation_score(candidate_by_id: dict[str, str]) -> dict[str, Any]:
    missing_ids = [block_id for block_id, text in candidate_by_id.items() if not text.strip()]
    total = len(candidate_by_id)
    return {
        "missing_ids": missing_ids,
        "missing_count": len(missing_ids),
        "total": total,
        "rate": _round(len(missing_ids) / total) if total else 0.0,
    }


def row_alignment_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    source_ids = {str(block["id"]) for block in case.source_blocks}
    candidate_ids = set(candidate_by_id)
    missing = sorted(source_ids - candidate_ids)
    extra = sorted(candidate_ids - source_ids)
    aligned = len(source_ids) - len(missing)
    return {
        "source_count": len(source_ids),
        "candidate_count": len(candidate_ids),
        "missing_ids": missing,
        "extra_ids": extra,
        "rate": _round(aligned / len(source_ids)) if source_ids else 1.0,
    }


def format_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    source_by_id = _by_id(case.source_blocks, "text")
    broken = []
    for block_id, source_text in source_by_id.items():
        expected_tags = _tags(source_text)
        if expected_tags and _tags(candidate_by_id.get(block_id, "")) != expected_tags:
            broken.append(block_id)
    total_tagged = sum(1 for text in source_by_id.values() if _tags(text))
    return {
        "broken_ids": broken,
        "tagged_count": total_tagged,
        "breakage_rate": _round(len(broken) / total_tagged) if total_tagged else 0.0,
    }


def evaluate_case(case: CorpusCase) -> dict[str, Any]:
    candidate_by_id = _by_id(case.candidate_blocks, "translation")
    return {
        "case_id": case.id,
        "tags": list(case.tags),
        "terminology": terminology_score(case, candidate_by_id),
        "missing_translation": missing_translation_score(candidate_by_id),
        "row_alignment": row_alignment_score(case, candidate_by_id),
        "format": format_score(case, candidate_by_id),
    }
```

- [ ] **Step 4: Run metric tests**

Run: `python3 -m pytest -q tests/test_eval_metrics.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/evaluation/metrics.py tests/test_eval_metrics.py
git commit -m "feat: add translation quality metrics"
```

## Task 3: Evaluation Reports And CLI

**Files:**
- Create: `app/evaluation/reports.py`
- Create: `app/evaluation/cli.py`
- Test: `tests/test_eval_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_eval_cli.py`:

```python
import json
import subprocess
from pathlib import Path


def test_eval_cli_writes_json_and_markdown(tmp_path):
    json_out = tmp_path / "report.json"
    md_out = tmp_path / "report.md"

    result = subprocess.run(
        [
            "python3",
            "-m",
            "app.evaluation.cli",
            "--corpus",
            "tests/fixtures/golden_corpus/milestone1.json",
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(md_out),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["summary"]["case_count"] >= 7
    assert "terminology_hit_rate" in data["summary"]
    assert "manual_scores" in data
    markdown = md_out.read_text(encoding="utf-8")
    assert "# Translation Quality Evaluation" in markdown
    assert "Manual scoring" in markdown
```

- [ ] **Step 2: Run test to verify failure**

Run: `python3 -m pytest -q tests/test_eval_cli.py`

Expected: FAIL with `No module named app.evaluation.cli`.

- [ ] **Step 3: Implement reports**

Create `app/evaluation/reports.py`:

```python
"""Evaluation report serialization."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def build_report(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "summary": {
            "case_count": len(case_results),
            "terminology_hit_rate": _avg([r["terminology"]["hit_rate"] for r in case_results]),
            "missing_translation_rate": _avg([r["missing_translation"]["rate"] for r in case_results]),
            "row_alignment_rate": _avg([r["row_alignment"]["rate"] for r in case_results]),
            "format_breakage_rate": _avg([r["format"]["breakage_rate"] for r in case_results]),
        },
        "cases": case_results,
        "manual_scores": [
            {"case_id": r["case_id"], "score": None, "notes": ""}
            for r in case_results
        ],
    }


def write_json_report(report: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown_report(report: dict[str, Any], path: str | Path) -> None:
    summary = report["summary"]
    lines = [
        "# Translation Quality Evaluation",
        "",
        "## Summary",
        "",
        f"- Cases: {summary['case_count']}",
        f"- Terminology hit rate: {summary['terminology_hit_rate']}",
        f"- Missing translation rate: {summary['missing_translation_rate']}",
        f"- Row alignment rate: {summary['row_alignment_rate']}",
        f"- Format breakage rate: {summary['format_breakage_rate']}",
        "",
        "## Case Details",
        "",
    ]
    for item in report["cases"]:
        lines.extend([
            f"### {item['case_id']}",
            "",
            f"- Tags: {', '.join(item['tags'])}",
            f"- Terminology hit rate: {item['terminology']['hit_rate']}",
            f"- Missing translation ids: {', '.join(item['missing_translation']['missing_ids']) or 'none'}",
            f"- Row alignment missing ids: {', '.join(item['row_alignment']['missing_ids']) or 'none'}",
            f"- Format broken ids: {', '.join(item['format']['broken_ids']) or 'none'}",
            "",
        ])
    lines.extend([
        "## Manual scoring",
        "",
        "| Case | Score | Notes |",
        "| --- | --- | --- |",
    ])
    for item in report["manual_scores"]:
        lines.append(f"| {item['case_id']} |  |  |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Implement CLI**

Create `app/evaluation/cli.py`:

```python
"""Command line entry point for translation quality evaluation."""
from __future__ import annotations

import argparse

from app.evaluation.corpus import load_corpus_file
from app.evaluation.metrics import evaluate_case
from app.evaluation.reports import build_report, write_json_report, write_markdown_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AI Sub Pro translation quality evaluation.")
    parser.add_argument("--corpus", required=True, help="Path to golden corpus JSON.")
    parser.add_argument("--json-out", required=True, help="Path for JSON report.")
    parser.add_argument("--markdown-out", required=True, help="Path for Markdown report.")
    args = parser.parse_args(argv)

    corpus = load_corpus_file(args.corpus)
    report = build_report([evaluate_case(case) for case in corpus.cases])
    write_json_report(report, args.json_out)
    write_markdown_report(report, args.markdown_out)
    print(
        "Evaluation complete: "
        f"{report['summary']['case_count']} cases, "
        f"terminology_hit_rate={report['summary']['terminology_hit_rate']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run CLI tests**

Run: `python3 -m pytest -q tests/test_eval_cli.py tests/test_eval_metrics.py tests/test_eval_corpus.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/evaluation/reports.py app/evaluation/cli.py tests/test_eval_cli.py
git commit -m "feat: add translation evaluation CLI"
```

## Task 4: KB Suggestion Engine

**Files:**
- Create: `app/engines/kb_suggestions.py`
- Test: `tests/test_kb_suggestions.py`

- [ ] **Step 1: Write failing suggestion tests**

Create `tests/test_kb_suggestions.py`:

```python
def test_suggest_kb_entries_from_tmdb_and_subtitles():
    from app.engines.kb_suggestions import suggest_kb_entries
    from app.engines.kb_models import ProjectKb, TermEntry

    project = {
        "name": "Moonlit Case",
        "tmdb_id": 101,
        "title": "Moonlit Case",
        "original_title": "Moonlit Case",
        "cast": ["Elsbeth Tascioni", {"name": "Maya Chen", "character": "Detective Chen"}],
        "overview": "Elsbeth follows a case at the Moonlit Club.",
    }
    subtitles = [
        {"index": 1, "text": "Elsbeth meets Maya Chen at the Moonlit Club."},
        {"index": 2, "text": "Detective Chen waits."},
    ]
    existing = ProjectKb(characters=[TermEntry(source="Elsbeth Tascioni", target="艾尔斯贝丝")])

    suggestions = suggest_kb_entries(project, subtitles, existing)

    by_source = {item.source: item for item in suggestions}
    assert by_source["Maya Chen"].category == "characters"
    assert by_source["Moonlit Club"].category in {"places", "brands", "slang"}
    assert by_source["Elsbeth Tascioni"].collision == "existing"
    assert by_source["Maya Chen"].evidence


def test_suggest_kb_entries_ignores_short_noise():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"name": "A", "cast": ["A"]},
        [{"index": 1, "text": "OK. TV. A."}],
        None,
    )

    assert suggestions == []
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_kb_suggestions.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.engines.kb_suggestions'`.

- [ ] **Step 3: Implement suggestion engine**

Create `app/engines/kb_suggestions.py`:

```python
"""Suggest project KB entries from metadata and subtitle text."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

from app.engines.kb_models import ProjectKb


_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b")
_NOISE = {"OK", "TV", "AI", "US", "UK"}


@dataclass(frozen=True)
class KbSuggestion:
    source: str
    target: str
    category: str
    notes: str
    evidence: list[str]
    confidence: float
    collision: str = "new"

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _cast_names(raw) -> Iterable[tuple[str, str]]:
    if not isinstance(raw, list):
        return []
    names = []
    for item in raw:
        if isinstance(item, str):
            name = _clean(item)
            if name:
                names.append((name, "cast"))
        elif isinstance(item, dict):
            name = _clean(item.get("name"))
            character = _clean(item.get("character"))
            if name:
                names.append((name, "cast"))
            if character and character != name:
                names.append((character, "character"))
    return names


def _existing_sources(kb: ProjectKb | None) -> set[str]:
    if kb is None:
        return set()
    sources = set()
    for entries in (kb.characters, kb.places, kb.brands, kb.slang):
        for entry in entries:
            if entry.source:
                sources.add(entry.source.lower())
    return sources


def _subtitle_phrases(subtitles) -> list[tuple[str, str]]:
    phrases = []
    if not isinstance(subtitles, list):
        return phrases
    for block in subtitles:
        if not isinstance(block, dict):
            continue
        text = _clean(block.get("text"))
        if not text:
            continue
        for match in _PHRASE_RE.findall(text):
            phrase = match.strip()
            if len(phrase) < 4 or phrase in _NOISE:
                continue
            phrases.append((phrase, f"subtitle:{block.get('index', '')}"))
    return phrases


def _category_for_phrase(phrase: str, source: str) -> str:
    if source in {"cast", "character"}:
        return "characters"
    if any(word in phrase.lower() for word in ("club", "room", "street", "harbor", "city")):
        return "places"
    return "slang"


def suggest_kb_entries(project: dict, subtitles: list[dict] | None, existing_kb: ProjectKb | None) -> list[KbSuggestion]:
    project = project if isinstance(project, dict) else {}
    existing = _existing_sources(existing_kb)
    seen = set()
    candidates: list[tuple[str, str]] = []
    candidates.extend(_cast_names(project.get("cast")))
    for field in ("title", "original_title", "name"):
        value = _clean(project.get(field))
        if value and len(value) >= 4:
            candidates.append((value, field))
    overview = _clean(project.get("overview"))
    for phrase in _PHRASE_RE.findall(overview):
        if len(phrase) >= 4 and phrase not in _NOISE:
            candidates.append((phrase, "overview"))
    candidates.extend(_subtitle_phrases(subtitles or []))

    suggestions = []
    for phrase, source in candidates:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        collision = "existing" if key in existing else "new"
        if len(phrase) < 4 or phrase in _NOISE:
            continue
        suggestions.append(KbSuggestion(
            source=phrase,
            target="",
            category=_category_for_phrase(phrase, source),
            notes=f"Suggested from {source}",
            evidence=[source],
            confidence=0.9 if source in {"cast", "character"} else 0.65,
            collision=collision,
        ))
    return suggestions
```

- [ ] **Step 4: Run suggestion tests**

Run: `python3 -m pytest -q tests/test_kb_suggestions.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/engines/kb_suggestions.py tests/test_kb_suggestions.py
git commit -m "feat: suggest knowledge base entries"
```

## Task 5: KB Suggestion API

**Files:**
- Modify: `app/api/knowledge.py`
- Test: `tests/test_knowledge_api.py`

- [ ] **Step 1: Write failing API tests**

Append to `tests/test_knowledge_api.py`:

```python
def test_kb_suggestions_endpoint_returns_project_suggestions(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_suggest"
    pdir = tmp_project_dir(pid)
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Moonlit Case",
        "tmdb_id": 101,
        "cast": ["Maya Chen"],
        "overview": "Maya Chen visits the Moonlit Club.",
    })
    (pdir / "raw.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nMaya Chen enters the Moonlit Club.\n\n",
        encoding="utf-8",
    )

    response = client.get(f"/api/knowledge/projects/{pid}/suggestions")

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == pid
    assert any(item["source"] == "Maya Chen" for item in data["suggestions"])


def test_kb_accept_suggestions_persists_entries(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_accept"
    pdir = tmp_project_dir(pid)
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "moonlit",
        "show_title": "Moonlit Case",
        "tmdb_id": 101,
        "entries": [
            {"source": "Maya Chen", "target": "玛雅·陈", "category": "characters", "notes": "lead"}
        ],
    })

    assert response.status_code == 200
    saved = client.get("/api/knowledge/projects/moonlit").json()
    assert saved["characters"][0]["source"] == "Maya Chen"
    assert saved["characters"][0]["target"] == "玛雅·陈"


def test_kb_reject_suggestions_persists_project_decision(tmp_project_dir, patched_kb_file):
    import json

    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_reject"
    pdir = tmp_project_dir(pid)
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/reject", json={
        "sources": ["Noisy Phrase", "Unused Name"]
    })

    assert response.status_code == 200
    data = json.loads((pdir / "kb_suggestion_decisions.json").read_text(encoding="utf-8"))
    assert data["rejected_sources"] == ["Noisy Phrase", "Unused Name"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_knowledge_api.py::test_kb_suggestions_endpoint_returns_project_suggestions tests/test_knowledge_api.py::test_kb_accept_suggestions_persists_entries tests/test_knowledge_api.py::test_kb_reject_suggestions_persists_project_decision`

Expected: FAIL with 404 for the new endpoints.

- [ ] **Step 3: Add request models and helpers**

Modify `app/api/knowledge.py`:

```python
class SuggestionAcceptEntryIn(BaseModel):
    source: str
    target: str = ""
    category: str
    notes: str = ""


class SuggestionAcceptIn(BaseModel):
    key: str
    show_title: str = ""
    tmdb_id: Optional[StrictInt] = None
    entries: List[SuggestionAcceptEntryIn] = Field(default_factory=list)


class SuggestionRejectIn(BaseModel):
    sources: List[str] = Field(default_factory=list)


def _append_term(target: list[TermEntry], entry: SuggestionAcceptEntryIn) -> None:
    source = _clean_text(entry.source)
    translated = _clean_text(entry.target)
    if not source or not translated:
        return
    if any(item.source.lower() == source.lower() for item in target):
        return
    target.append(TermEntry(source=source, target=translated, notes=_clean_text(entry.notes)))
```

- [ ] **Step 4: Add suggestion endpoints**

Modify `app/api/knowledge.py` with imports:

```python
from app.utils.srt import parse_srt_file
from app.utils.project_store import atomic_write_json, project_dir
from app.engines.kb_suggestions import suggest_kb_entries
```

Add routes:

```python
@router.get("/projects/{pid}/suggestions")
def suggest_for_project(pid: str):
    pdir = project_dir(pid)
    project_path = pdir / "project.json"
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="project not found")
    import json
    project = json.loads(project_path.read_text(encoding="utf-8"))
    subtitles = []
    for name in ("filtered.srt", "raw.srt", "native.srt"):
        path = pdir / name
        if path.exists():
            subtitles = [block.to_dict() for block in parse_srt_file(str(path))]
            break
    selected = _get_kb().select_for_project(project)
    return {
        "project_id": pid,
        "suggestions": [item.to_dict() for item in suggest_kb_entries(project, subtitles, selected)],
    }


@router.post("/projects/{pid}/suggestions/accept")
def accept_project_suggestions(pid: str, body: SuggestionAcceptIn):
    pdir = project_dir(pid)
    if not (pdir / "project.json").exists():
        raise HTTPException(status_code=404, detail="project not found")
    key = _clean_text(body.key)
    if not key:
        raise HTTPException(status_code=400, detail="key must not be empty")
    if body.tmdb_id is not None and body.tmdb_id < 1:
        raise HTTPException(status_code=400, detail="tmdb_id must be positive")
    kb = _get_kb().get_project(key) or ProjectKb(show_title=_clean_text(body.show_title), tmdb_id=body.tmdb_id)
    if body.show_title:
        kb.show_title = _clean_text(body.show_title)
    if body.tmdb_id is not None:
        kb.tmdb_id = body.tmdb_id
    for entry in body.entries:
        category = _clean_text(entry.category)
        if category == "characters":
            _append_term(kb.characters, entry)
        elif category == "places":
            _append_term(kb.places, entry)
        elif category == "brands":
            _append_term(kb.brands, entry)
        elif category == "slang":
            _append_term(kb.slang, entry)
    _get_kb().put_project(key, kb)
    _invalidate_translator_kb()
    return {"ok": True, "key": key, "accepted": len(body.entries)}


@router.post("/projects/{pid}/suggestions/reject")
def reject_project_suggestions(pid: str, body: SuggestionRejectIn):
    pdir = project_dir(pid)
    if not (pdir / "project.json").exists():
        raise HTTPException(status_code=404, detail="project not found")
    sources = []
    for source in body.sources:
        cleaned = _clean_text(source)
        if cleaned and cleaned not in sources:
            sources.append(cleaned)
    atomic_write_json(pdir / "kb_suggestion_decisions.json", {
        "rejected_sources": sources,
    })
    return {"ok": True, "rejected": len(sources)}
```

- [ ] **Step 5: Run API tests**

Run: `python3 -m pytest -q tests/test_knowledge_api.py tests/test_kb_suggestions.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/knowledge.py tests/test_knowledge_api.py
git commit -m "feat: expose knowledge base suggestions"
```

## Task 6: KB Usage Trace

**Files:**
- Create: `app/engines/kb_trace.py`
- Modify: `app/engines/translator.py`
- Modify: `app/api/translate.py`
- Test: `tests/test_translator_kb_integration.py`

- [ ] **Step 1: Write failing trace tests**

Append to `tests/test_translator_kb_integration.py`:

```python
def test_translator_records_kb_usage_trace(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb, TermEntry

    kb = KnowledgeBase()
    kb.set_project("trace", ProjectKb(
        show_title="Trace Show",
        tmdb_id=808,
        characters=[TermEntry(source="Maya Chen", target="玛雅·陈")],
    ))
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = tmod.SubtitleTranslator(cfg)
    prompt = t._build_prompt(
        target_lang="简体中文",
        meta_info={"name": "Trace Show", "tmdb_id": 808},
        kb_data=None,
        context_before=[],
        context_after=[],
    )

    assert "Maya Chen" in prompt
    trace = t.get_kb_usage_trace()
    assert trace["project"]["tmdb_id"] == 808
    assert trace["matches"][0]["source"] == "Maya Chen"
    assert trace["matches"][0]["target"] == "玛雅·陈"
```

- [ ] **Step 2: Run test to verify failure**

Run: `python3 -m pytest -q tests/test_translator_kb_integration.py::test_translator_records_kb_usage_trace`

Expected: FAIL because `get_kb_usage_trace` does not exist.

- [ ] **Step 3: Implement trace helper**

Create `app/engines/kb_trace.py`:

```python
"""Knowledge-base usage trace helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.engines.kb_models import ProjectKb
from app.utils.project_store import atomic_write_json


def trace_for_project_kb(kb: ProjectKb | None) -> dict[str, Any]:
    if kb is None:
        return {"project": {}, "matches": []}
    matches = []
    for category, entries in (
        ("characters", kb.characters),
        ("places", kb.places),
        ("brands", kb.brands),
        ("slang", kb.slang),
    ):
        for entry in entries:
            matches.append({
                "category": category,
                "source": entry.source,
                "target": entry.target,
                "notes": entry.notes,
                "scope": "project",
            })
    for rule in kb.style_notes.rules:
        matches.append({
            "category": "style_notes",
            "source": rule,
            "target": "",
            "notes": "style rule",
            "scope": "style",
        })
    return {
        "project": {"show_title": kb.show_title, "tmdb_id": kb.tmdb_id},
        "matches": matches,
    }


def write_kb_usage_trace(project_dir: Path, trace: dict[str, Any]) -> None:
    atomic_write_json(project_dir / "kb_usage_trace.json", trace)
```

- [ ] **Step 4: Modify translator to store trace**

Modify `app/engines/translator.py`:

```python
from app.engines.kb_trace import trace_for_project_kb
```

Add in `SubtitleTranslator.__init__`:

```python
        self._kb_usage_trace = {"project": {}, "matches": []}
```

Add method:

```python
    def get_kb_usage_trace(self) -> dict:
        return {
            "project": dict(self._kb_usage_trace.get("project", {})),
            "matches": [dict(item) for item in self._kb_usage_trace.get("matches", [])],
        }
```

Inside `_build_prompt`, after selecting the effective project KB, call:

```python
        self._kb_usage_trace = trace_for_project_kb(project_kb)
```

Use the existing local variable name that currently holds the selected `ProjectKb`. If the current method does not name it `project_kb`, introduce that name where `select_for_project` is called and pass it to both `build_prompt_snippet` and `trace_for_project_kb`.

- [ ] **Step 5: Persist trace after translation**

Modify `app/api/translate.py` in each translation task after `translator.translate(...)` returns and before the task is marked complete:

```python
from app.engines.kb_trace import write_kb_usage_trace
```

Then persist:

```python
        try:
            write_kb_usage_trace(_project_dir(pid), translator.get_kb_usage_trace())
        except Exception as e:
            log.warning("failed to persist KB usage trace for %s: %s", pid, e)
```

If multiple translation paths instantiate `SubtitleTranslator`, apply the same persistence block to each path that writes `translated.srt`.

- [ ] **Step 6: Run trace tests**

Run: `python3 -m pytest -q tests/test_translator_kb_integration.py tests/test_translate_integration.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/engines/kb_trace.py app/engines/translator.py app/api/translate.py tests/test_translator_kb_integration.py
git commit -m "feat: record knowledge base usage traces"
```

## Task 7: Frontend Suggestion Review And Trace Panel

**Files:**
- Modify: `app/static/js/app.js`
- Modify: `app/static/index.html`
- Test: `tests/test_frontend_knowledge_js.py`

- [ ] **Step 1: Write failing frontend tests**

Append to `tests/test_frontend_knowledge_js.py`:

```python
def test_knowledge_frontend_loads_and_accepts_suggestions():
    result = run_js(
        """
        const fs = require('fs');
        const vm = require('vm');

        const code = fs.readFileSync('app/static/js/app.js', 'utf8');
        const context = { console, setTimeout, clearTimeout };
        vm.createContext(context);
        vm.runInContext(code, context);

        (async () => {
          const state = context.app();
          state.currentProject = {id: 'p1', name: 'Moonlit Case', tmdb_id: 101};
          state.kbSelectedKey = 'moonlit';
          state.kbCurrent = {
            key: 'moonlit',
            show_title: 'Moonlit Case',
            tmdb_id: 101,
            characters: [],
            places: [],
            brands: [],
            slang: [],
            style_notes: {tone: '', perspective: '', rules: []},
          };
          const calls = [];
          state.api = async (url, method, body) => {
            calls.push({url, method: method || 'GET', body});
            if (url === '/api/knowledge/projects/p1/suggestions') {
              return {project_id: 'p1', suggestions: [
                {source: 'Maya Chen', target: '', category: 'characters', notes: 'cast', evidence: ['cast'], confidence: 0.9, collision: 'new'}
              ]};
            }
            if (url === '/api/knowledge/projects/p1/suggestions/accept') {
              return {ok: true, key: 'moonlit', accepted: 1};
            }
            throw new Error(`unexpected URL ${url}`);
          };
          state.toast = () => {};
          state.loadKbProjects = async () => {};
          state.selectKb = async () => {};

          await state.loadKbSuggestions();
          if (state.kbSuggestions.length !== 1) throw new Error('expected one suggestion');
          state.kbSuggestions[0].target = '玛雅·陈';
          state.kbSuggestions[0].selected = true;
          await state.acceptKbSuggestions();
          const acceptCall = calls.find((call) => call.url.endsWith('/suggestions/accept'));
          if (!acceptCall || acceptCall.body.entries[0].source !== 'Maya Chen') {
            throw new Error(`expected accept payload, got ${JSON.stringify(calls)}`);
          }
        })().catch((err) => {
          console.error(err.message);
          process.exit(1);
        });
        """
    )

    assert result.returncode == 0, result.stderr


def test_knowledge_html_contains_suggestion_and_trace_panels():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")

    assert "loadKbSuggestions" in html
    assert "kbSuggestions" in html
    assert "kbUsageTrace" in html
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python3 -m pytest -q tests/test_frontend_knowledge_js.py::test_knowledge_frontend_loads_and_accepts_suggestions tests/test_frontend_knowledge_js.py::test_knowledge_html_contains_suggestion_and_trace_panels`

Expected: FAIL because state fields and HTML panels do not exist.

- [ ] **Step 3: Add frontend state and methods**

Modify `app/static/js/app.js` initial state:

```javascript
    kbSuggestions: [],
    kbSuggestionsLoading: false,
    kbSuggestionsError: '',
    kbUsageTrace: null,
    kbTraceLoading: false,
    kbTraceError: '',
```

Add methods near KB management:

```javascript
    async loadKbSuggestions() {
      if (!this.currentProject?.id) return;
      this.kbSuggestionsLoading = true;
      this.kbSuggestionsError = '';
      try {
        const data = await this.api(`/api/knowledge/projects/${encodeURIComponent(this.currentProject.id)}/suggestions`);
        this.kbSuggestions = Array.isArray(data.suggestions)
          ? data.suggestions.map((item) => ({
              ...item,
              target: typeof item.target === 'string' ? item.target : '',
              selected: item.collision !== 'existing',
            }))
          : [];
      } catch (e) {
        this.kbSuggestionsError = e.message || '加载建议词条失败';
        this.toast('加载建议词条失败: ' + e.message, 'error');
      } finally {
        this.kbSuggestionsLoading = false;
      }
    },

    async acceptKbSuggestions() {
      if (!this.currentProject?.id || !this.kbSelectedKey || !this.kbCurrent) return;
      const entries = this.kbSuggestions
        .filter((item) => item.selected && item.source && item.target)
        .map((item) => ({
          source: item.source,
          target: item.target,
          category: item.category,
          notes: item.notes || '',
        }));
      if (!entries.length) {
        this.toast('请先选择建议并填写译名', 'error');
        return;
      }
      await this.api(`/api/knowledge/projects/${encodeURIComponent(this.currentProject.id)}/suggestions/accept`, 'POST', {
        key: this.kbSelectedKey,
        show_title: this.kbCurrent.show_title || this.currentProject.name || this.kbSelectedKey,
        tmdb_id: this.kbCurrent.tmdb_id || this.currentProject.tmdb_id || null,
        entries,
      });
      this.toast('建议词条已加入知识库', 'success');
      await this.selectKb(this.kbSelectedKey, {allowDuringPending: true});
      await this.loadKbSuggestions();
    },
```

- [ ] **Step 4: Add HTML panels**

Modify `app/static/index.html` in the knowledge view, below the existing KB editor actions:

```html
<section class="glass rounded-2xl p-4 mt-4" x-show="currentProject">
  <div class="flex items-center justify-between gap-3 mb-3">
    <h3 class="text-[13px] font-semibold">建议词条</h3>
    <button class="btn-secondary px-3 py-1.5 rounded-lg text-[12px]" @click="loadKbSuggestions()" x-text="kbSuggestionsLoading ? '扫描中...' : '扫描当前项目'"></button>
  </div>
  <p x-show="kbSuggestionsError" class="text-[12px] text-danger" x-text="kbSuggestionsError"></p>
  <div x-show="kbSuggestions.length" class="space-y-2">
    <template x-for="item in kbSuggestions" :key="item.source + item.category">
      <div class="grid grid-cols-[auto_1fr_1fr_auto] gap-2 items-center text-[12px]">
        <input type="checkbox" x-model="item.selected" :disabled="item.collision === 'existing'">
        <span x-text="item.source"></span>
        <input class="px-2 py-1 rounded-lg" x-model="item.target" placeholder="译名">
        <span class="text-surface-400" x-text="kbCategoryLabel(item.category)"></span>
      </div>
    </template>
    <button class="btn-primary px-3 py-1.5 rounded-lg text-[12px]" @click="acceptKbSuggestions()">加入知识库</button>
  </div>
</section>

<section class="glass rounded-2xl p-4 mt-4">
  <h3 class="text-[13px] font-semibold mb-2">本次翻译使用的 KB</h3>
  <div x-show="kbUsageTrace?.matches?.length">
    <template x-for="item in kbUsageTrace.matches" :key="item.category + item.source">
      <p class="text-[12px] text-surface-500">
        <span x-text="kbCategoryLabel(item.category)"></span>
        <span x-text="': ' + item.source"></span>
        <span x-show="item.target" x-text="' → ' + item.target"></span>
      </p>
    </template>
  </div>
  <p x-show="!kbUsageTrace?.matches?.length" class="text-[12px] text-surface-400">暂无 KB 命中记录</p>
</section>
```

- [ ] **Step 5: Run frontend tests**

Run: `python3 -m pytest -q tests/test_frontend_knowledge_js.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/static/js/app.js app/static/index.html tests/test_frontend_knowledge_js.py
git commit -m "feat: add KB suggestion review UI"
```

## Task 8: KB Trace API And Frontend Loading

**Files:**
- Modify: `app/api/knowledge.py`
- Modify: `app/static/js/app.js`
- Test: `tests/test_knowledge_api.py`
- Test: `tests/test_frontend_knowledge_js.py`

- [ ] **Step 1: Write failing API test**

Append to `tests/test_knowledge_api.py`:

```python
def test_kb_usage_trace_endpoint_reads_project_trace(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "trace_project"
    pdir = tmp_project_dir(pid)
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Trace Project"})
    atomic_write_json(pdir / "kb_usage_trace.json", {
        "project": {"show_title": "Trace Project", "tmdb_id": 808},
        "matches": [{"category": "characters", "source": "Maya", "target": "玛雅"}],
    })

    response = client.get(f"/api/knowledge/projects/{pid}/usage-trace")

    assert response.status_code == 200
    assert response.json()["matches"][0]["source"] == "Maya"
```

- [ ] **Step 2: Add usage trace endpoint**

Modify `app/api/knowledge.py`:

```python
@router.get("/projects/{pid}/usage-trace")
def get_project_usage_trace(pid: str):
    pdir = project_dir(pid)
    if not (pdir / "project.json").exists():
        raise HTTPException(status_code=404, detail="project not found")
    trace_path = pdir / "kb_usage_trace.json"
    if not trace_path.exists():
        return {"project": {}, "matches": []}
    import json
    data = json.loads(trace_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"project": {}, "matches": []}
    matches = data.get("matches", [])
    return {
        "project": data.get("project", {}) if isinstance(data.get("project"), dict) else {},
        "matches": matches if isinstance(matches, list) else [],
    }
```

- [ ] **Step 3: Add frontend trace loader**

Modify `app/static/js/app.js`:

```javascript
    async loadKbUsageTrace() {
      if (!this.currentProject?.id) return;
      this.kbTraceLoading = true;
      this.kbTraceError = '';
      try {
        const data = await this.api(`/api/knowledge/projects/${encodeURIComponent(this.currentProject.id)}/usage-trace`);
        this.kbUsageTrace = this.isPlainObject(data) ? data : {project: {}, matches: []};
      } catch (e) {
        this.kbTraceError = e.message || '加载 KB 命中记录失败';
      } finally {
        this.kbTraceLoading = false;
      }
    },
```

Call `await this.loadKbUsageTrace();` in `openProject` after subtitles load, so the panel updates when a project is opened.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest -q tests/test_knowledge_api.py tests/test_frontend_knowledge_js.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/knowledge.py app/static/js/app.js tests/test_knowledge_api.py tests/test_frontend_knowledge_js.py
git commit -m "feat: expose KB usage trace"
```

## Task 9: Documentation And Verification

**Files:**
- Modify: `docs/USAGE.md`
- Modify: `docs/USAGE.zh-CN.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Document eval CLI in English**

Add to `docs/USAGE.md` after the testing section:

```markdown
## Translation Quality Evaluation

Run the deterministic golden-corpus evaluation after changing translator,
provider, or knowledge-base behavior:

```bash
python3 -m app.evaluation.cli \
  --corpus tests/fixtures/golden_corpus/milestone1.json \
  --json-out /tmp/ai-sub-pro-eval.json \
  --markdown-out /tmp/ai-sub-pro-eval.md
```

The default corpus uses checked-in candidate outputs and does not call network
or paid providers. The report includes terminology hit rate, format breakage
rate, missing translation rate, row alignment rate, and a manual scoring table.
```

- [ ] **Step 2: Document KB suggestions in English**

Add to `docs/USAGE.md` knowledge-base workflow section:

```markdown
Project pages can scan TMDB metadata and current subtitles for suggested
knowledge-base entries. Review each suggestion, enter the preferred
translation, then accept selected entries into the project KB. After
translation, the KB panel shows which entries were used by the latest run when
trace data is available.
```

- [ ] **Step 3: Add Simplified Chinese docs**

Add equivalent sections to `docs/USAGE.zh-CN.md`:

```markdown
## 翻译质量评测

修改 translator、provider 或知识库逻辑后，可以运行内置 golden corpus 评测：

```bash
python3 -m app.evaluation.cli \
  --corpus tests/fixtures/golden_corpus/milestone1.json \
  --json-out /tmp/ai-sub-pro-eval.json \
  --markdown-out /tmp/ai-sub-pro-eval.md
```

默认评测使用仓库内的候选输出，不调用网络或付费 provider。报告包含术语命中率、
格式破坏率、漏翻率、行数对齐率，以及人工评分表。
```

Add this KB workflow note:

```markdown
项目页可以根据 TMDB 元数据和当前字幕扫描建议词条。用户逐条确认、填写译名后，
再把选中的词条加入项目知识库。翻译完成后，如果存在命中记录，知识库面板会显示
本次翻译使用过的 KB 词条。
```

- [ ] **Step 4: Update README feature bullets**

Add one bullet to both `README.md` and `README.zh-CN.md`:

```markdown
- Run deterministic translation quality evaluation with a golden corpus.
```

Chinese:

```markdown
- 使用 golden corpus 运行确定性的翻译质量评测。
```

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
python3 -m pytest -q tests/test_eval_corpus.py tests/test_eval_metrics.py tests/test_eval_cli.py tests/test_kb_suggestions.py tests/test_knowledge_api.py tests/test_translator_kb_integration.py tests/test_translate_integration.py tests/test_frontend_knowledge_js.py
npm run build:css
python3 -m compileall -q app
python3 -m pytest -q
git diff --check
```

Expected:

- Focused tests PASS.
- CSS build PASS.
- Python compile PASS.
- Full pytest PASS.
- `git diff --check` prints no output.

- [ ] **Step 6: Commit docs**

```bash
git add docs/USAGE.md docs/USAGE.zh-CN.md README.md README.zh-CN.md
git commit -m "docs: document translation evaluation and KB suggestions"
```

## Final Milestone 1 Gate

- [ ] **Step 1: Run evaluation CLI**

Run:

```bash
python3 -m app.evaluation.cli \
  --corpus tests/fixtures/golden_corpus/milestone1.json \
  --json-out /tmp/ai-sub-pro-m1-eval.json \
  --markdown-out /tmp/ai-sub-pro-m1-eval.md
```

Expected: command exits 0 and writes both files.

- [ ] **Step 2: Inspect report summary**

Run:

```bash
python3 - <<'PY'
import json
data = json.load(open('/tmp/ai-sub-pro-m1-eval.json', encoding='utf-8'))
print(data['summary'])
assert data['summary']['case_count'] >= 7
assert 'terminology_hit_rate' in data['summary']
assert 'manual_scores' in data
PY
```

Expected: prints summary and exits 0.

- [ ] **Step 3: Run full milestone verification**

Run:

```bash
npm run build:css
python3 -m compileall -q app
python3 -m pytest -q
git diff --check
git status --short --branch
```

Expected: all checks pass and `git status` shows only the current branch/tracking line.

- [ ] **Step 4: Request code review**

Use `requesting-code-review` on the milestone branch. Review focus:

- Eval metrics are deterministic and CI-safe.
- Suggestion extraction avoids silent writes.
- KB trace failures cannot break translation.
- Frontend suggestion acceptance cannot write entries without user-provided targets.
- No API keys or runtime data are written to docs, fixtures, or reports.

- [ ] **Step 5: Address review**

Use `receiving-code-review` for any findings. Each accepted finding gets its own test or verification command.

- [ ] **Step 6: Finish branch**

Use `verification-before-completion`, then `finishing-a-development-branch`.

Merge only after:

- All tests and build checks pass.
- PR summary lists the new eval CLI, KB suggestion workflow, and KB usage trace.
- Docs mention the new behavior in English and Simplified Chinese.
