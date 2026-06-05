# Translation Accuracy Next Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add measurable local translation accuracy evaluation, stronger retrieval for memory and phrase examples, safe local corpus import, proper-name consistency checks, and conservative QA repair controls.

**Architecture:** Keep the existing translation provider and project pipeline stable. Add focused evaluation/import/retrieval modules, then wire them into existing `TranslationMemoryStore`, `PhraseLibrary`, `translation_qa`, and settings without committing user subtitle content or bundled external corpora.

**Tech Stack:** Python 3.14, SQLite/FTS5 with deterministic fallback, FastAPI config, pytest, existing SRT/evaluation/phrase-library modules, Markdown/JSON report output.

---

## File Structure

- Create `app/evaluation/subtitle_compare.py`: loads local SRT or ASS subtitle files, compares source/old/new/reference blocks, computes alignment, missing, residue, length, reference-similarity, and consistency signals.
- Create `tools/quality/compare_translation_outputs.py`: CLI wrapper around `app.evaluation.subtitle_compare` that writes JSON and Markdown reports.
- Create `tests/test_eval_subtitle_compare.py`: synthetic local-file tests for the comparison engine.
- Create `tests/test_quality_compare_cli.py`: CLI tests for report writing and missing-path failures.
- Create `app/engines/retrieval_scoring.py`: shared normalization, token/ngram scoring, FTS5 capability detection, and bounded score helpers.
- Modify `app/engines/phrase_library.py`: add FTS5-backed retrieval when available, fallback scoring, backend trace, and migration-safe indexing.
- Modify `app/engines/translation_memory.py`: add FTS5-backed retrieval when available, recency/usage scoring, and retrieval usage increments.
- Modify `app/engines/translator.py`: read max retrieval examples from config and include backend metadata in trace without changing provider contracts.
- Create `app/engines/corpus_import.py`: parse JSONL/TSV/CSV local bilingual corpora, validate metadata, apply row limits, import into `PhraseLibrary`, and produce an import report.
- Create `tools/phrase_packs/import_corpus.py`: CLI wrapper around `app.engines.corpus_import`.
- Create `tests/test_corpus_import.py`: parser, validation, duplicate, row-limit, and report tests.
- Modify `app/engines/translation_qa.py`: add proper-name consistency issue detection and repair-round report details.
- Modify `app/evaluation/metrics.py`: add proper-name consistency and reference-similarity helpers for corpus/report reuse.
- Modify `app/api/translate.py`: honor `translation.qa_auto_repair_rounds` with a conservative stop policy.
- Modify `app/config.py`: add retrieval backend/example-count and repair-round defaults.
- Modify `app/static/js/app.js`, `app/static/index.html`, and frontend settings tests only if existing settings UI does not automatically expose the new config fields.
- Modify `docs/USAGE.md` and `docs/USAGE.zh-CN.md`: document local A/B evaluation, corpus import, retrieval settings, and privacy boundaries.

## Scope Check

The design has three related subsystems: local evaluation, retrieval, and corpus import. They are coupled through phrase/memory scoring and quality reports, so this plan keeps them in one staged implementation. Each task still produces a testable slice and a focused commit.

## Task 1: Local Subtitle Comparison Engine

**Files:**
- Create: `app/evaluation/subtitle_compare.py`
- Create: `tests/test_eval_subtitle_compare.py`

- [ ] **Step 1: Write failing comparison tests**

Add `tests/test_eval_subtitle_compare.py`:

```python
import json


def _srt(*rows):
    parts = []
    for index, text in rows:
        start = f"00:00:{index:02d},000"
        end = f"00:00:{index + 1:02d},000"
        parts.append(f"{index}\n{start} --> {end}\n{text}\n")
    return "\n".join(parts) + "\n"


def test_compare_subtitle_files_reports_core_metrics(tmp_path):
    from app.evaluation.subtitle_compare import compare_subtitle_files

    source = tmp_path / "source.srt"
    old = tmp_path / "old.srt"
    new = tmp_path / "new.srt"
    reference = tmp_path / "reference.srt"
    source.write_text(_srt((1, "Hudson Oaks is quiet."), (2, "Are you okay?")), encoding="utf-8")
    old.write_text(_srt((1, "哈德森橡树很安静。"), (2, "Are you okay?")), encoding="utf-8")
    new.write_text(_srt((1, "哈德逊奥克斯很安静。"), (2, "你还好吗？")), encoding="utf-8")
    reference.write_text(_srt((1, "哈德逊奥克斯很安静。"), (2, "你还好吗？")), encoding="utf-8")

    report = compare_subtitle_files(
        source_path=source,
        old_path=old,
        new_path=new,
        reference_path=reference,
        target_language="简体中文",
        expected_terms=[{"source": "Hudson Oaks", "target": "哈德逊奥克斯"}],
        max_chars=18,
    )

    assert report["summary"]["source_count"] == 2
    assert report["old"]["english_residue"]["count"] == 1
    assert report["new"]["english_residue"]["count"] == 0
    assert report["old"]["terminology"]["hit_rate"] == 0.0
    assert report["new"]["terminology"]["hit_rate"] == 1.0
    assert report["new"]["reference_similarity"]["exact_match_rate"] == 1.0
    assert report["delta"]["english_residue_count"] == -1
    json.dumps(report, ensure_ascii=False)


def test_compare_subtitle_files_rejects_missing_paths(tmp_path):
    from app.evaluation.subtitle_compare import SubtitleCompareError, compare_subtitle_files

    source = tmp_path / "source.srt"
    source.write_text(_srt((1, "Hello.")), encoding="utf-8")

    try:
        compare_subtitle_files(
            source_path=source,
            old_path=tmp_path / "missing-old.srt",
            new_path=tmp_path / "missing-new.srt",
        )
    except SubtitleCompareError as exc:
        assert "missing-old.srt" in str(exc)
    else:
        raise AssertionError("expected missing path error")


def test_compare_subtitle_files_accepts_ass_reference(tmp_path):
    from app.evaluation.subtitle_compare import compare_subtitle_files

    source = tmp_path / "source.srt"
    old = tmp_path / "old.srt"
    new = tmp_path / "new.srt"
    reference = tmp_path / "reference.ass"
    source.write_text(_srt((1, "Are you okay?")), encoding="utf-8")
    old.write_text(_srt((1, "Are you okay?")), encoding="utf-8")
    new.write_text(_srt((1, "你还好吗？")), encoding="utf-8")
    reference.write_text(
        "\n".join([
            "[Script Info]",
            "Title: unit",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,你还好吗？",
        ]) + "\n",
        encoding="utf-8",
    )

    report = compare_subtitle_files(
        source_path=source,
        old_path=old,
        new_path=new,
        reference_path=reference,
    )

    assert report["new"]["reference_similarity"]["exact_match_rate"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest -q tests/test_eval_subtitle_compare.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.evaluation.subtitle_compare'`.

- [ ] **Step 3: Implement comparison engine**

Create `app/evaluation/subtitle_compare.py`:

```python
"""Local subtitle A/B comparison for translation accuracy reports."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from app.evaluation.metrics import missing_translation_score, terminology_score
from app.utils.srt import SubtitleBlock, parse_srt, parse_srt_file


class SubtitleCompareError(ValueError):
    """Raised when local subtitle comparison inputs are invalid."""


_ENGLISH_RE = re.compile(r"[A-Za-z]{3,}")
_PROPER_NOUN_RE = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")


def _path(value: str | Path | None, label: str, *, required: bool = True) -> Path | None:
    if value is None:
        if required:
            raise SubtitleCompareError(f"{label} path is required")
        return None
    path = Path(value).expanduser()
    if not path.exists():
        raise SubtitleCompareError(f"{label} path does not exist: {path}")
    if not path.is_file():
        raise SubtitleCompareError(f"{label} path is not a file: {path}")
    return path


def _blocks_by_id(blocks: Iterable[SubtitleBlock], *, text_attr: str = "text") -> dict[str, str]:
    result: dict[str, str] = {}
    for block in blocks:
        block_id = str(getattr(block, "index", "")).strip()
        text = getattr(block, text_attr, "")
        if block_id:
            result[block_id] = text.strip() if isinstance(text, str) else ""
    return result


def _strip_ass_markup(value: str) -> str:
    text = re.sub(r"\{[^}]*\}", "", value)
    text = text.replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_ass(path: Path) -> dict[str, str]:
    blocks: dict[str, str] = {}
    in_events = False
    text_index = 9
    row_index = 1
    for raw_line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower() == "[events]":
            in_events = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_events = False
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            fields = [part.strip().lower() for part in line.split(":", 1)[1].split(",")]
            if "text" in fields:
                text_index = fields.index("text")
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        payload = line.split(":", 1)[1].lstrip()
        parts = payload.split(",", text_index)
        if len(parts) <= text_index:
            continue
        text = _strip_ass_markup(parts[text_index])
        if text:
            blocks[str(row_index)] = text
            row_index += 1
    return blocks


def _load(path: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".ass":
        return _parse_ass(path)
    if suffix == ".srt":
        return _blocks_by_id(parse_srt_file(str(path)))
    return _blocks_by_id(parse_srt(path.read_text(encoding="utf-8-sig", errors="ignore")))


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _english_residue(candidate_by_id: dict[str, str]) -> dict[str, Any]:
    ids = [block_id for block_id, text in candidate_by_id.items() if _ENGLISH_RE.search(text)]
    return {"ids": ids, "count": len(ids), "rate": _rate(len(ids), len(candidate_by_id))}


def _length_violations(candidate_by_id: dict[str, str], max_chars: int) -> dict[str, Any]:
    if max_chars <= 0:
        return {"ids": [], "count": 0, "rate": 0.0, "max_chars": max_chars}
    ids = []
    for block_id, text in candidate_by_id.items():
        compact = re.sub(r"\s+", "", text)
        if len(compact) > max_chars:
            ids.append(block_id)
    return {"ids": ids, "count": len(ids), "rate": _rate(len(ids), len(candidate_by_id)), "max_chars": max_chars}


def _reference_similarity(candidate_by_id: dict[str, str], reference_by_id: dict[str, str]) -> dict[str, Any]:
    shared = sorted(set(candidate_by_id) & set(reference_by_id), key=lambda item: int(item) if item.isdigit() else item)
    exact = [block_id for block_id in shared if candidate_by_id.get(block_id, "").strip() == reference_by_id.get(block_id, "").strip()]
    changed = [
        {
            "id": block_id,
            "candidate": candidate_by_id.get(block_id, ""),
            "reference": reference_by_id.get(block_id, ""),
        }
        for block_id in shared
        if block_id not in exact
    ]
    return {
        "shared_count": len(shared),
        "exact_match_count": len(exact),
        "exact_match_rate": _rate(len(exact), len(shared)),
        "changed": changed[:50],
    }


def _terms(expected_terms: list[dict[str, str]] | None) -> list[dict[str, str]]:
    cleaned = []
    for item in expected_terms or []:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        target = item.get("target")
        if isinstance(source, str) and source.strip() and isinstance(target, str) and target.strip():
            cleaned.append({"source": source.strip(), "target": target.strip()})
    return cleaned


class _Case:
    def __init__(self, source_blocks, candidate_blocks, expected_terms):
        self.id = "local-subtitle-compare"
        self.tags = ["local"]
        self.source_blocks = source_blocks
        self.candidate_blocks = candidate_blocks
        self.expected_terms = expected_terms


def _case(source_by_id: dict[str, str], candidate_by_id: dict[str, str], expected_terms: list[dict[str, str]]) -> _Case:
    return _Case(
        [{"id": block_id, "text": text} for block_id, text in source_by_id.items()],
        [{"id": block_id, "translation": text} for block_id, text in candidate_by_id.items()],
        expected_terms,
    )


def _candidate_metrics(
    *,
    source_by_id: dict[str, str],
    candidate_by_id: dict[str, str],
    reference_by_id: dict[str, str],
    expected_terms: list[dict[str, str]],
    max_chars: int,
) -> dict[str, Any]:
    case = _case(source_by_id, candidate_by_id, expected_terms)
    source_ids = list(source_by_id)
    return {
        "missing_translation": missing_translation_score(candidate_by_id, source_ids),
        "english_residue": _english_residue(candidate_by_id),
        "length": _length_violations(candidate_by_id, max_chars),
        "terminology": terminology_score(case, candidate_by_id),
        "reference_similarity": _reference_similarity(candidate_by_id, reference_by_id) if reference_by_id else {
            "shared_count": 0,
            "exact_match_count": 0,
            "exact_match_rate": 0.0,
            "changed": [],
        },
    }


def _alignment(source_by_id: dict[str, str], old_by_id: dict[str, str], new_by_id: dict[str, str]) -> dict[str, Any]:
    source_ids = set(source_by_id)
    old_ids = set(old_by_id)
    new_ids = set(new_by_id)
    return {
        "source_count": len(source_ids),
        "old_count": len(old_ids),
        "new_count": len(new_ids),
        "old_missing_ids": sorted(source_ids - old_ids),
        "new_missing_ids": sorted(source_ids - new_ids),
        "old_extra_ids": sorted(old_ids - source_ids),
        "new_extra_ids": sorted(new_ids - source_ids),
    }


def _delta(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    return {
        "missing_translation_count": new["missing_translation"]["missing_count"] - old["missing_translation"]["missing_count"],
        "english_residue_count": new["english_residue"]["count"] - old["english_residue"]["count"],
        "length_violation_count": new["length"]["count"] - old["length"]["count"],
        "terminology_hit_rate": round(new["terminology"]["hit_rate"] - old["terminology"]["hit_rate"], 4),
        "reference_exact_match_rate": round(
            new["reference_similarity"]["exact_match_rate"] - old["reference_similarity"]["exact_match_rate"],
            4,
        ),
    }


def compare_subtitle_files(
    *,
    source_path: str | Path,
    old_path: str | Path,
    new_path: str | Path,
    reference_path: str | Path | None = None,
    target_language: str = "简体中文",
    expected_terms: list[dict[str, str]] | None = None,
    max_chars: int = 32,
) -> dict[str, Any]:
    source = _path(source_path, "source")
    old = _path(old_path, "old")
    new = _path(new_path, "new")
    reference = _path(reference_path, "reference", required=False)
    source_by_id = _load(source)
    old_by_id = _load(old)
    new_by_id = _load(new)
    reference_by_id = _load(reference) if reference is not None else {}
    terms = _terms(expected_terms)
    old_metrics = _candidate_metrics(
        source_by_id=source_by_id,
        candidate_by_id=old_by_id,
        reference_by_id=reference_by_id,
        expected_terms=terms,
        max_chars=max_chars,
    )
    new_metrics = _candidate_metrics(
        source_by_id=source_by_id,
        candidate_by_id=new_by_id,
        reference_by_id=reference_by_id,
        expected_terms=terms,
        max_chars=max_chars,
    )
    return {
        "schema_version": 1,
        "target_language": target_language,
        "inputs": {
            "source": str(source),
            "old": str(old),
            "new": str(new),
            "reference": str(reference) if reference is not None else "",
        },
        "summary": {
            "source_count": len(source_by_id),
            "has_reference": bool(reference_by_id),
            "expected_term_count": len(terms),
        },
        "alignment": _alignment(source_by_id, old_by_id, new_by_id),
        "old": old_metrics,
        "new": new_metrics,
        "delta": _delta(old_metrics, new_metrics),
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    delta = report.get("delta", {})
    lines = [
        "# Translation Accuracy Report",
        "",
        f"- Source blocks: {report.get('summary', {}).get('source_count', 0)}",
        f"- Reference provided: {report.get('summary', {}).get('has_reference', False)}",
        "",
        "## Delta",
        f"- Missing translations: {delta.get('missing_translation_count', 0):+}",
        f"- English residue: {delta.get('english_residue_count', 0):+}",
        f"- Length violations: {delta.get('length_violation_count', 0):+}",
        f"- Terminology hit rate: {delta.get('terminology_hit_rate', 0):+}",
        f"- Reference exact-match rate: {delta.get('reference_exact_match_rate', 0):+}",
        "",
        "## Inputs",
    ]
    for key, value in report.get("inputs", {}).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def save_report(report: dict[str, Any], *, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(report_to_markdown(report), encoding="utf-8")
```

- [ ] **Step 4: Run comparison tests**

Run:

```bash
python3 -m pytest -q tests/test_eval_subtitle_compare.py
```

Expected: PASS.

- [ ] **Step 5: Commit comparison engine**

```bash
git add app/evaluation/subtitle_compare.py tests/test_eval_subtitle_compare.py
git commit -m "feat: add local subtitle accuracy comparison"
```

## Task 2: Quality Comparison CLI

**Files:**
- Create: `tools/quality/compare_translation_outputs.py`
- Create: `tests/test_quality_compare_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add `tests/test_quality_compare_cli.py`:

```python
import json
import subprocess
import sys


def _srt(text):
    return f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n"


def test_quality_compare_cli_writes_json_and_markdown(tmp_path):
    source = tmp_path / "source.srt"
    old = tmp_path / "old.srt"
    new = tmp_path / "new.srt"
    reference = tmp_path / "reference.srt"
    out = tmp_path / "report"
    source.write_text(_srt("Hudson Oaks is quiet."), encoding="utf-8")
    old.write_text(_srt("哈德森橡树很安静。"), encoding="utf-8")
    new.write_text(_srt("哈德逊奥克斯很安静。"), encoding="utf-8")
    reference.write_text(_srt("哈德逊奥克斯很安静。"), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/quality/compare_translation_outputs.py",
            "--source", str(source),
            "--old", str(old),
            "--new", str(new),
            "--reference", str(reference),
            "--term", "Hudson Oaks=哈德逊奥克斯",
            "--out-dir", str(out),
        ],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads((out / "translation_accuracy_report.json").read_text(encoding="utf-8"))
    assert data["new"]["terminology"]["hit_rate"] == 1.0
    assert "# Translation Accuracy Report" in (out / "translation_accuracy_report.md").read_text(encoding="utf-8")


def test_quality_compare_cli_rejects_bad_term(tmp_path):
    source = tmp_path / "source.srt"
    old = tmp_path / "old.srt"
    new = tmp_path / "new.srt"
    source.write_text(_srt("Hello."), encoding="utf-8")
    old.write_text(_srt("你好。"), encoding="utf-8")
    new.write_text(_srt("你好。"), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/quality/compare_translation_outputs.py",
            "--source", str(source),
            "--old", str(old),
            "--new", str(new),
            "--term", "missing-separator",
            "--out-dir", str(tmp_path / "out"),
        ],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--term must use SOURCE=TARGET" in result.stderr
```

- [ ] **Step 2: Run CLI tests to verify failure**

Run:

```bash
python3 -m pytest -q tests/test_quality_compare_cli.py
```

Expected: FAIL because `tools/quality/compare_translation_outputs.py` does not exist.

- [ ] **Step 3: Implement CLI**

Create `tools/quality/compare_translation_outputs.py`:

```python
#!/usr/bin/env python3
"""Compare local subtitle translation outputs and write accuracy reports."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.subtitle_compare import (  # noqa: E402
    SubtitleCompareError,
    compare_subtitle_files,
    save_report,
)


def _term(value: str) -> dict[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--term must use SOURCE=TARGET")
    source, target = value.split("=", 1)
    source = source.strip()
    target = target.strip()
    if not source or not target:
        raise argparse.ArgumentTypeError("--term must use SOURCE=TARGET")
    return {"source": source, "target": target}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--old", required=True, type=Path)
    parser.add_argument("--new", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--target-language", default="简体中文")
    parser.add_argument("--term", action="append", type=_term, default=[])
    parser.add_argument("--max-chars", type=int, default=32)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        report = compare_subtitle_files(
            source_path=args.source,
            old_path=args.old,
            new_path=args.new,
            reference_path=args.reference,
            target_language=args.target_language,
            expected_terms=args.term,
            max_chars=args.max_chars,
        )
        save_report(
            report,
            json_path=args.out_dir / "translation_accuracy_report.json",
            markdown_path=args.out_dir / "translation_accuracy_report.md",
        )
    except SubtitleCompareError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Wrote {args.out_dir / 'translation_accuracy_report.json'}")
    print(f"Wrote {args.out_dir / 'translation_accuracy_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
python3 -m pytest -q tests/test_quality_compare_cli.py tests/test_eval_subtitle_compare.py
```

Expected: PASS.

- [ ] **Step 5: Commit CLI**

```bash
git add tools/quality/compare_translation_outputs.py tests/test_quality_compare_cli.py
git commit -m "feat: add translation accuracy comparison cli"
```

## Task 3: Shared Retrieval Scoring

**Files:**
- Create: `app/engines/retrieval_scoring.py`
- Create: `tests/test_retrieval_scoring.py`

- [ ] **Step 1: Write failing scoring tests**

Add `tests/test_retrieval_scoring.py`:

```python
def test_ngram_similarity_matches_subtitle_like_variants():
    from app.engines.retrieval_scoring import ngram_similarity

    assert ngram_similarity("I need to go to Hudson Oaks.", "Hudson Oaks is quiet.") > 0.2
    assert ngram_similarity("你还好吗", "你还好吧") > 0.2
    assert ngram_similarity("", "anything") == 0.0


def test_bounded_score_includes_quality_tags_and_priority():
    from app.engines.retrieval_scoring import bounded_retrieval_score

    base = bounded_retrieval_score(
        lexical_score=0.4,
        quality=0.7,
        tag_matches=0,
        priority=0.0,
    )
    boosted = bounded_retrieval_score(
        lexical_score=0.4,
        quality=0.7,
        tag_matches=2,
        priority=0.1,
    )

    assert 0.0 <= base <= 1.0
    assert 0.0 <= boosted <= 1.0
    assert boosted > base


def test_sqlite_fts5_capability_returns_bool(tmp_path):
    from app.engines.retrieval_scoring import sqlite_supports_fts5

    assert isinstance(sqlite_supports_fts5(tmp_path / "fts.sqlite3"), bool)
```

- [ ] **Step 2: Run scoring tests to verify failure**

Run:

```bash
python3 -m pytest -q tests/test_retrieval_scoring.py
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement scoring module**

Create `app/engines/retrieval_scoring.py`:

```python
"""Shared deterministic retrieval scoring helpers."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_TOKEN_RE = re.compile(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+")
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def normalize_text(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def token_set(value: str) -> set[str]:
    tokens: set[str] = set()
    for part in _TOKEN_RE.findall(normalize_text(value)):
        tokens.add(part)
        if _CJK_RE.search(part):
            for size in (2, 3):
                if len(part) >= size:
                    tokens.update(part[index:index + size] for index in range(len(part) - size + 1))
    return {token for token in tokens if token}


def ngram_similarity(query: str, candidate: str) -> float:
    q = token_set(query)
    c = token_set(candidate)
    if not q or not c:
        return 0.0
    score = len(q & c) / max(len(q), len(c))
    q_text = normalize_text(query)
    c_text = normalize_text(candidate)
    if q_text and c_text and (q_text in c_text or c_text in q_text):
        score += 0.35
    return min(1.0, score)


def clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def bounded_retrieval_score(
    *,
    lexical_score: float,
    quality: float = 0.5,
    tag_matches: int = 0,
    priority: float = 0.0,
    recency_boost: float = 0.0,
    usage_boost: float = 0.0,
) -> float:
    score = (
        clamp(float(lexical_score)) * 0.68
        + clamp(float(quality)) * 0.16
        + min(0.10, max(0, int(tag_matches)) * 0.04)
        + clamp(float(priority)) * 0.10
        + min(0.04, max(0.0, float(recency_boost)))
        + min(0.04, max(0.0, float(usage_boost)))
    )
    return round(clamp(score), 6)


def sqlite_supports_fts5(path: str | Path) -> bool:
    try:
        db = Path(path)
        db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db)) as conn:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.__fts5_probe USING fts5(value)")
            conn.execute("DROP TABLE temp.__fts5_probe")
        return True
    except sqlite3.Error:
        return False
```

- [ ] **Step 4: Run scoring tests**

Run:

```bash
python3 -m pytest -q tests/test_retrieval_scoring.py
```

Expected: PASS.

- [ ] **Step 5: Commit scoring helpers**

```bash
git add app/engines/retrieval_scoring.py tests/test_retrieval_scoring.py
git commit -m "feat: add shared retrieval scoring helpers"
```

## Task 4: Phrase Library Retrieval Upgrade

**Files:**
- Modify: `app/engines/phrase_library.py`
- Modify: `tests/test_phrase_library.py`

- [ ] **Step 1: Add failing phrase retrieval tests**

Append to `tests/test_phrase_library.py`:

```python
def test_phrase_library_reports_retrieval_backend(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    library.add_phrase(
        source_text="Hudson Oaks is quiet.",
        target_text="哈德逊奥克斯很安静。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )

    results = library.retrieve(
        "I need to go to Hudson Oaks.",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="ngram",
    )

    assert results
    assert library.last_retrieval_backend == "ngram"


def test_phrase_library_auto_backend_preserves_existing_rows(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    db = tmp_path / "phrases.sqlite3"
    first = PhraseLibrary(db)
    first.add_phrase(
        source_text="We need to run the scan.",
        target_text="我们需要做扫描。",
        source_language="en",
        target_language="zh-CN",
        source_name="medical",
        license="local",
        quality=0.88,
        tags=["medical"],
    )

    second = PhraseLibrary(db)
    results = second.retrieve(
        "Can we run a scan?",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        preferred_tags={"medical"},
        backend="auto",
    )

    assert results[0].target_text == "我们需要做扫描。"
    assert second.last_retrieval_backend in {"fts5", "ngram"}
```

- [ ] **Step 2: Run phrase tests to verify failure**

Run:

```bash
python3 -m pytest -q tests/test_phrase_library.py::test_phrase_library_reports_retrieval_backend tests/test_phrase_library.py::test_phrase_library_auto_backend_preserves_existing_rows
```

Expected: FAIL because `retrieve()` does not accept `backend` and `last_retrieval_backend` is missing.

- [ ] **Step 3: Modify phrase library retrieval**

In `app/engines/phrase_library.py`:

- Import shared helpers:

```python
from app.engines.retrieval_scoring import (
    bounded_retrieval_score,
    ngram_similarity,
    normalize_text,
    sqlite_supports_fts5,
)
```

- Add `self.last_retrieval_backend = "ngram"` in `PhraseLibrary.__init__`.

- In `_ensure_schema()`, after existing indexes, create FTS table when available:

```python
            if sqlite_supports_fts5(self.path):
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS phrase_examples_fts
                    USING fts5(source_text, target_text, content='phrase_examples', content_rowid='id')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO phrase_examples_fts(rowid, source_text, target_text)
                    SELECT id, source_text, target_text
                    FROM phrase_examples
                    WHERE id NOT IN (SELECT rowid FROM phrase_examples_fts)
                    """
                )
```

- After `INSERT INTO phrase_examples`, add:

```python
            if sqlite_supports_fts5(self.path):
                conn.execute(
                    "INSERT INTO phrase_examples_fts(rowid, source_text, target_text) VALUES (?, ?, ?)",
                    (int(cur.lastrowid), source, target),
                )
```

- Change `retrieve()` signature to:

```python
    def retrieve(
        self,
        source_text: str,
        *,
        source_language: str,
        target_language: str,
        limit: int = 5,
        preferred_tags: Optional[Iterable[str]] = None,
        backend: str = "auto",
    ) -> list[PhraseExample]:
```

- Inside `retrieve()`, select backend:

```python
        requested_backend = backend if backend in {"auto", "fts5", "ngram"} else "auto"
        use_fts = requested_backend in {"auto", "fts5"} and sqlite_supports_fts5(self.path)
        self.last_retrieval_backend = "fts5" if use_fts else "ngram"
```

- For FTS lexical candidates, use:

```python
        if use_fts:
            fts_query = " OR ".join(sorted(_tokens(query))) or normalize_text(query)
            rows = conn.execute(
                """
                SELECT pe.*, bm25(phrase_examples_fts) AS rank
                FROM phrase_examples_fts
                JOIN phrase_examples pe ON pe.id = phrase_examples_fts.rowid
                WHERE phrase_examples_fts MATCH ?
                  AND pe.source_language = ?
                  AND pe.target_language = ?
                ORDER BY rank
                LIMIT 500
                """,
                (fts_query, _lang(source_language, "auto"), _lang(target_language, "zh-CN")),
            ).fetchall()
```

- Score rows through `bounded_retrieval_score()` using lexical FTS score or `ngram_similarity()` fallback, quality, and tag matches. Keep returning `PhraseExample` sorted by score descending.

- [ ] **Step 4: Run phrase retrieval tests**

Run:

```bash
python3 -m pytest -q tests/test_retrieval_scoring.py tests/test_phrase_library.py
```

Expected: PASS.

- [ ] **Step 5: Commit phrase retrieval upgrade**

```bash
git add app/engines/phrase_library.py tests/test_phrase_library.py
git commit -m "feat: upgrade phrase library retrieval"
```

## Task 5: Translation Memory Retrieval Upgrade

**Files:**
- Modify: `app/engines/translation_memory.py`
- Modify: `tests/test_translation_memory.py`

- [ ] **Step 1: Add failing memory retrieval tests**

Append to `tests/test_translation_memory.py`:

```python
def test_translation_memory_reports_backend_and_updates_usage(tmp_path):
    from app.engines.translation_memory import TranslationMemoryStore

    store = TranslationMemoryStore(tmp_path / "memory.sqlite3")
    store.record_edit(
        source_text="Hudson Oaks is quiet.",
        machine_translation="哈德森橡树很安静。",
        final_translation="哈德逊奥克斯很安静。",
        source_language="en",
        target_language="zh-CN",
    )

    first = store.retrieve(
        "I need Hudson Oaks.",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="ngram",
    )
    second = store.retrieve(
        "I need Hudson Oaks.",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="ngram",
    )

    assert first[0].usage_count == 0
    assert second[0].usage_count >= 1
    assert store.last_retrieval_backend == "ngram"
```

- [ ] **Step 2: Run memory test to verify failure**

Run:

```bash
python3 -m pytest -q tests/test_translation_memory.py::test_translation_memory_reports_backend_and_updates_usage
```

Expected: FAIL because `retrieve()` does not accept `backend` and does not update usage.

- [ ] **Step 3: Modify translation memory**

In `app/engines/translation_memory.py`:

- Import:

```python
from app.engines.retrieval_scoring import (
    bounded_retrieval_score,
    ngram_similarity,
    normalize_text,
    sqlite_supports_fts5,
)
```

- Add `self.last_retrieval_backend = "ngram"` in `TranslationMemoryStore.__init__`.

- Add FTS migration in `_ensure_schema()`:

```python
            if sqlite_supports_fts5(self.path):
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS translation_memory_fts
                    USING fts5(source_text, final_translation, content='translation_memory', content_rowid='id')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO translation_memory_fts(rowid, source_text, final_translation)
                    SELECT id, source_text, final_translation
                    FROM translation_memory
                    WHERE id NOT IN (SELECT rowid FROM translation_memory_fts)
                    """
                )
```

- After inserting a memory row, insert into FTS when available:

```python
            entry_id = int(cur.lastrowid)
            if sqlite_supports_fts5(self.path):
                conn.execute(
                    "INSERT INTO translation_memory_fts(rowid, source_text, final_translation) VALUES (?, ?, ?)",
                    (entry_id, source, final),
                )
            return entry_id
```

- Change `retrieve()` signature:

```python
    def retrieve(
        self,
        source_text: str,
        *,
        source_language: str,
        target_language: str,
        limit: int = 5,
        backend: str = "auto",
    ) -> list[MemoryEntry]:
```

- Use FTS rows when available, otherwise existing recent-row query. Score each row:

```python
            lexical = ngram_similarity(query, row["source_text"] or "")
            usage_boost = min(0.04, float(row["usage_count"] or 0) / 100)
            score = bounded_retrieval_score(
                lexical_score=lexical,
                quality=1.0,
                priority=0.2,
                usage_boost=usage_boost,
            )
```

- After selecting final results, increment usage for returned IDs:

```python
        if scored:
            with self._connect() as conn:
                conn.executemany(
                    "UPDATE translation_memory SET usage_count = usage_count + 1 WHERE id = ?",
                    [(item.id,) for item in scored[:max_results]],
                )
```

- [ ] **Step 4: Run memory tests**

Run:

```bash
python3 -m pytest -q tests/test_retrieval_scoring.py tests/test_translation_memory.py
```

Expected: PASS.

- [ ] **Step 5: Commit memory retrieval upgrade**

```bash
git add app/engines/translation_memory.py tests/test_translation_memory.py
git commit -m "feat: upgrade translation memory retrieval"
```

## Task 6: Translation Prompt Retrieval Settings

**Files:**
- Modify: `app/config.py`
- Modify: `app/engines/translator.py`
- Modify: `tests/test_translator_quality_context.py`

- [ ] **Step 1: Add failing translator settings test**

Append to `tests/test_translator_quality_context.py`:

```python
def test_build_prompt_respects_retrieval_example_limits(monkeypatch, tmp_path):
    from app.engines import translator as translator_module
    from app.engines.translator import SubtitleTranslator

    config = _base_config(tmp_path)
    config["translation"]["max_memory_examples"] = 1
    config["translation"]["max_phrase_examples"] = 1

    class DummyMemoryStore:
        def retrieve(self, *args, **kwargs):
            assert kwargs["limit"] == 1
            return []

    class DummyPhraseLibrary:
        def retrieve(self, *args, **kwargs):
            assert kwargs["limit"] == 1
            assert kwargs["backend"] == "auto"
            return []

    monkeypatch.setattr(translator_module, "TranslationMemoryStore", DummyMemoryStore)
    monkeypatch.setattr(translator_module, "PhraseLibrary", DummyPhraseLibrary)

    st = SubtitleTranslator(config)
    st._build_prompt(
        [{"id": 1, "original": "Hello."}],
        target_lang="简体中文",
        meta_info={"original_language": "en"},
        kb_data={},
        context_before=[],
        context_after=[],
    )
```

- [ ] **Step 2: Run translator settings test to verify failure**

Run:

```bash
python3 -m pytest -q tests/test_translator_quality_context.py::test_build_prompt_respects_retrieval_example_limits
```

Expected: FAIL because translator always uses hard-coded retrieval limits and does not pass backend.

- [ ] **Step 3: Add config defaults**

In `app/config.py`, extend `DEFAULT_CONFIG["translation"]`:

```python
        "memory_retrieval_backend": "auto",
        "phrase_retrieval_backend": "auto",
        "max_memory_examples": 6,
        "max_phrase_examples": 6,
        "qa_auto_repair_rounds": 1,
```

- [ ] **Step 4: Read settings in translator**

In `SubtitleTranslator.__init__`, after `self.use_phrase_library`:

```python
        self.memory_retrieval_backend = _coerce_text_setting(
            trans_cfg.get("memory_retrieval_backend"),
            "auto",
        )
        if self.memory_retrieval_backend not in {"auto", "fts5", "ngram"}:
            self.memory_retrieval_backend = "auto"
        self.phrase_retrieval_backend = _coerce_text_setting(
            trans_cfg.get("phrase_retrieval_backend"),
            "auto",
        )
        if self.phrase_retrieval_backend not in {"auto", "fts5", "ngram"}:
            self.phrase_retrieval_backend = "auto"
        self.max_memory_examples = _coerce_int_setting(
            trans_cfg.get("max_memory_examples", 6),
            6,
            min_value=0,
            max_value=20,
        )
        self.max_phrase_examples = _coerce_int_setting(
            trans_cfg.get("max_phrase_examples", 6),
            6,
            min_value=0,
            max_value=20,
        )
```

- [ ] **Step 5: Apply limits in `_build_retrieval_snippets()`**

Replace hard-coded `limit=2` and `len(memory_lines) >= 6` with bounded settings:

```python
                    per_item_limit = 2 if self.max_memory_examples > 1 else 1
                    for hit in store.retrieve(
                        original,
                        source_language=source_lang,
                        target_language=target_code,
                        limit=per_item_limit,
                        backend=self.memory_retrieval_backend,
                    ):
                        ...
                        if len(memory_lines) >= self.max_memory_examples:
                            break
                    if len(memory_lines) >= self.max_memory_examples:
                        break
```

Use the same pattern for phrase retrieval:

```python
                    per_item_limit = 2 if self.max_phrase_examples > 1 else 1
                    for hit in library.retrieve(
                        original,
                        source_language=source_lang,
                        target_language=target_code,
                        limit=per_item_limit,
                        preferred_tags=preferred_tags,
                        backend=self.phrase_retrieval_backend,
                    ):
                        ...
                        if len(phrase_lines) >= self.max_phrase_examples:
                            break
                    if len(phrase_lines) >= self.max_phrase_examples:
                        break
```

- [ ] **Step 6: Run translator context tests**

Run:

```bash
python3 -m pytest -q tests/test_translator_quality_context.py tests/test_config.py
```

Expected: PASS.

- [ ] **Step 7: Commit retrieval settings**

```bash
git add app/config.py app/engines/translator.py tests/test_translator_quality_context.py
git commit -m "feat: configure translation retrieval limits"
```

## Task 7: Local Corpus Import Pipeline

**Files:**
- Create: `app/engines/corpus_import.py`
- Create: `tools/phrase_packs/import_corpus.py`
- Create: `tests/test_corpus_import.py`

- [ ] **Step 1: Write failing corpus import tests**

Add `tests/test_corpus_import.py`:

```python
import csv
import json
import subprocess
import sys


def test_import_jsonl_corpus_validates_metadata_and_limits_rows(tmp_path):
    from app.engines.corpus_import import import_corpus_file
    from app.engines.phrase_library import PhraseLibrary

    source = tmp_path / "corpus.jsonl"
    source.write_text(
        "\n".join([
            json.dumps({"source": "Hello there.", "target": "你好。"}),
            json.dumps({"source": "Read the room.", "target": "看点气氛。"}),
            json.dumps({"source": "", "target": "空。"}),
        ]) + "\n",
        encoding="utf-8",
    )
    library = PhraseLibrary(tmp_path / "phrases.sqlite3")

    report = import_corpus_file(
        source,
        library=library,
        source_name="unit-jsonl",
        license_name="CC-BY",
        source_language="en",
        target_language="zh-CN",
        input_format="jsonl",
        max_rows=1,
        tags=["subtitle"],
    )

    assert report.accepted == 1
    assert report.rejected >= 0
    assert report.limited is True
    results = library.retrieve("Hello there.", source_language="en", target_language="zh-CN")
    assert results[0].source_name == "unit-jsonl"
    assert results[0].license == "CC-BY"


def test_import_tsv_corpus_drops_duplicates(tmp_path):
    from app.engines.corpus_import import import_corpus_file
    from app.engines.phrase_library import PhraseLibrary

    source = tmp_path / "corpus.tsv"
    source.write_text("source\ttarget\nDrop it.\t别说了。\nDrop it.\t别说了。\n", encoding="utf-8")
    library = PhraseLibrary(tmp_path / "phrases.sqlite3")

    report = import_corpus_file(
        source,
        library=library,
        source_name="unit-tsv",
        license_name="local",
        source_language="en",
        target_language="zh-CN",
        input_format="tsv",
    )

    assert report.accepted == 1
    assert report.duplicates == 1


def test_import_corpus_cli_dry_run(tmp_path):
    source = tmp_path / "corpus.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "target"])
        writer.writeheader()
        writer.writerow({"source": "Hello.", "target": "你好。"})

    result = subprocess.run(
        [
            sys.executable,
            "tools/phrase_packs/import_corpus.py",
            str(source),
            "--format", "csv",
            "--source-name", "unit",
            "--license", "local",
            "--source-language", "en",
            "--target-language", "zh-CN",
            "--dry-run",
        ],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"accepted": 1' in result.stdout
```

- [ ] **Step 2: Run corpus tests to verify failure**

Run:

```bash
python3 -m pytest -q tests/test_corpus_import.py
```

Expected: FAIL because `app.engines.corpus_import` and CLI are missing.

- [ ] **Step 3: Implement corpus import module**

Create `app/engines/corpus_import.py`:

```python
"""Safe local bilingual corpus import into the phrase library."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from app.engines.phrase_library import PhraseLibrary


class CorpusImportError(ValueError):
    """Raised for invalid corpus import inputs."""


@dataclass
class CorpusImportReport:
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    limited: bool = False
    sampled_rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _require(value: str, label: str) -> str:
    cleaned = _clean(value)
    if not cleaned:
        raise CorpusImportError(f"{label} is required")
    return cleaned


def _jsonl(path: Path) -> Iterable[dict]:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            yield {"__error__": f"line {line_number}: {exc.msg}"}
            continue
        yield raw if isinstance(raw, dict) else {"__error__": f"line {line_number}: row must be an object"}


def _delimited(path: Path, delimiter: str) -> Iterable[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            yield dict(row)


def _rows(path: Path, input_format: str) -> Iterable[dict]:
    if input_format == "jsonl":
        return _jsonl(path)
    if input_format == "tsv":
        return _delimited(path, "\t")
    if input_format == "csv":
        return _delimited(path, ",")
    raise CorpusImportError("format must be jsonl, tsv, or csv")


def import_corpus_file(
    path: str | Path,
    *,
    library: PhraseLibrary | None = None,
    source_name: str,
    license_name: str,
    source_language: str,
    target_language: str,
    input_format: str,
    source_column: str = "source",
    target_column: str = "target",
    max_rows: int = 5000,
    tags: list[str] | None = None,
    dry_run: bool = False,
) -> CorpusImportReport:
    corpus_path = Path(path).expanduser()
    if not corpus_path.exists() or not corpus_path.is_file():
        raise CorpusImportError(f"corpus file does not exist: {corpus_path}")
    source_name = _require(source_name, "source name")
    license_name = _require(license_name, "license")
    source_language = _require(source_language, "source language")
    target_language = _require(target_language, "target language")
    max_rows = max(1, min(int(max_rows), 1_000_000))
    phrase_library = library or PhraseLibrary()
    report = CorpusImportReport()
    seen: set[tuple[str, str]] = set()
    tag_list = tags or []

    for raw in _rows(corpus_path, input_format):
        if report.accepted >= max_rows:
            report.limited = True
            break
        if not isinstance(raw, dict) or raw.get("__error__"):
            report.rejected += 1
            report.errors.append(str(raw.get("__error__", "row must be an object")))
            continue
        source = _clean(raw.get(source_column))
        target = _clean(raw.get(target_column))
        if not source or not target:
            report.rejected += 1
            continue
        key = (source, target)
        if key in seen:
            report.duplicates += 1
            continue
        seen.add(key)
        if len(source) > 220 or len(target) > 160:
            report.rejected += 1
            continue
        if not dry_run:
            added = phrase_library.add_phrase(
                source_text=source,
                target_text=target,
                source_language=source_language,
                target_language=target_language,
                source_name=source_name,
                license=license_name,
                quality=float(raw.get("quality") or 0.7),
                tags=tag_list or raw.get("tags") or "",
            )
            if added is None:
                report.duplicates += 1
                continue
        report.accepted += 1
        if len(report.sampled_rows) < 5:
            report.sampled_rows.append({"source": source, "target": target})

    return report
```

- [ ] **Step 4: Implement corpus import CLI**

Create `tools/phrase_packs/import_corpus.py`:

```python
#!/usr/bin/env python3
"""Import a local bilingual corpus into AI Sub Pro's phrase library."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engines.corpus_import import CorpusImportError, import_corpus_file  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--format", choices=["jsonl", "tsv", "csv"], required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--license", required=True, dest="license_name")
    parser.add_argument("--source-language", required=True)
    parser.add_argument("--target-language", required=True)
    parser.add_argument("--source-column", default="source")
    parser.add_argument("--target-column", default="target")
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = import_corpus_file(
            args.path,
            source_name=args.source_name,
            license_name=args.license_name,
            source_language=args.source_language,
            target_language=args.target_language,
            input_format=args.format,
            source_column=args.source_column,
            target_column=args.target_column,
            max_rows=args.max_rows,
            tags=args.tag,
            dry_run=args.dry_run,
        )
    except CorpusImportError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run corpus import tests**

Run:

```bash
python3 -m pytest -q tests/test_corpus_import.py tests/test_phrase_library.py
```

Expected: PASS.

- [ ] **Step 6: Commit corpus import**

```bash
git add app/engines/corpus_import.py tools/phrase_packs/import_corpus.py tests/test_corpus_import.py
git commit -m "feat: add local bilingual corpus import"
```

## Task 8: Proper-Name Consistency Metrics

**Files:**
- Modify: `app/evaluation/metrics.py`
- Modify: `app/engines/translation_qa.py`
- Modify: `tests/test_eval_metrics.py`
- Modify: `tests/test_translation_qa.py`

- [ ] **Step 1: Add failing consistency tests**

Append to `tests/test_eval_metrics.py`:

```python
def test_proper_name_consistency_detects_multiple_targets():
    from app.evaluation.metrics import proper_name_consistency_score

    source_by_id = {
        "1": "Hudson Oaks is quiet.",
        "2": "I came from Hudson Oaks.",
    }
    candidate_by_id = {
        "1": "哈德逊奥克斯很安静。",
        "2": "我从哈德森橡树来。",
    }

    result = proper_name_consistency_score(source_by_id, candidate_by_id)

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"
```

Append to `tests/test_translation_qa.py`:

```python
def test_quality_checks_flag_inferred_proper_name_inconsistency():
    from datetime import timedelta
    from app.engines.translation_qa import run_quality_checks
    from app.utils.srt import SubtitleBlock

    blocks = [
        SubtitleBlock(1, timedelta(seconds=0), timedelta(seconds=1), "Hudson Oaks is quiet.", "哈德逊奥克斯很安静。"),
        SubtitleBlock(2, timedelta(seconds=1), timedelta(seconds=2), "I came from Hudson Oaks.", "我从哈德森橡树来。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文")

    assert "proper_name_inconsistent" in report.summary["by_type"]
```

- [ ] **Step 2: Run consistency tests to verify failure**

Run:

```bash
python3 -m pytest -q tests/test_eval_metrics.py::test_proper_name_consistency_detects_multiple_targets tests/test_translation_qa.py::test_quality_checks_flag_inferred_proper_name_inconsistency
```

Expected: FAIL because the functions/issues do not exist.

- [ ] **Step 3: Add evaluation metric**

In `app/evaluation/metrics.py`, add:

```python
_PROPER_NOUN_RE = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


def _proper_names(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    ignored = {"New York"} if False else set()
    names = []
    for match in _PROPER_NOUN_RE.findall(text):
        cleaned = match.strip()
        if cleaned and cleaned not in ignored:
            names.append(cleaned)
    return names


def _target_signature(text: str) -> str:
    if not isinstance(text, str):
        return ""
    compact = re.sub(r"\s+", "", text)
    cjk = "".join(re.findall(r"[\u3400-\u9fff]+", compact))
    return cjk or compact[:24]


def proper_name_consistency_score(
    source_by_id: dict[str, str],
    candidate_by_id: dict[str, str],
) -> dict[str, Any]:
    observations: dict[str, list[dict[str, str]]] = {}
    for block_id, source in source_by_id.items():
        for name in _proper_names(source):
            observations.setdefault(name, []).append({
                "id": block_id,
                "translation": candidate_by_id.get(block_id, ""),
                "signature": _target_signature(candidate_by_id.get(block_id, "")),
            })
    issues = []
    for source, rows in observations.items():
        signatures = {row["signature"] for row in rows if row["signature"]}
        if len(rows) > 1 and len(signatures) > 1:
            issues.append({"source": source, "observations": rows})
    return {"issue_count": len(issues), "issues": issues}
```

- [ ] **Step 4: Wire QA issue**

In `app/engines/translation_qa.py`, import:

```python
from app.evaluation.metrics import proper_name_consistency_score
```

At the end of `run_quality_checks()`, before computing status:

```python
    source_by_id = {}
    translation_by_id = {}
    for block in blocks or []:
        block_id = getattr(block, "index", None)
        if isinstance(block_id, int):
            source_by_id[str(block_id)] = _clean_text(getattr(block, "text", ""))
            translation_by_id[str(block_id)] = _clean_text(getattr(block, "translation", ""))
    consistency = proper_name_consistency_score(source_by_id, translation_by_id)
    for item in consistency.get("issues", []):
        first = item.get("observations", [{}])[0]
        block_id = first.get("id")
        issues.append(QualityIssue(
            type="proper_name_inconsistent",
            severity="warning",
            block_id=int(block_id) if isinstance(block_id, str) and block_id.isdigit() else None,
            message=f"inferred proper name {item.get('source')} has inconsistent target forms",
            source_text=item.get("source", ""),
        ))
```

- [ ] **Step 5: Run QA and metric tests**

Run:

```bash
python3 -m pytest -q tests/test_eval_metrics.py tests/test_translation_qa.py
```

Expected: PASS.

- [ ] **Step 6: Commit consistency checks**

```bash
git add app/evaluation/metrics.py app/engines/translation_qa.py tests/test_eval_metrics.py tests/test_translation_qa.py
git commit -m "feat: detect proper name consistency issues"
```

## Task 9: Conservative Auto-Repair Rounds

**Files:**
- Modify: `app/api/translate.py`
- Modify: `tests/test_translate_integration.py`

- [ ] **Step 1: Add failing repair-round test**

Append to `tests/test_translate_integration.py`:

```python
def test_translate_pipeline_limits_auto_repair_rounds(tmp_path, monkeypatch):
    from app.api import translate as translate_api

    assert translate_api._repair_round_limit({"translation": {"qa_auto_repair_rounds": 0}}) == 1
    assert translate_api._repair_round_limit({"translation": {"qa_auto_repair_rounds": 2}}) == 2
    assert translate_api._repair_round_limit({"translation": {"qa_auto_repair_rounds": 99}}) == 2
```

- [ ] **Step 2: Run repair-round test to verify failure**

Run:

```bash
python3 -m pytest -q tests/test_translate_integration.py::test_translate_pipeline_limits_auto_repair_rounds
```

Expected: FAIL because `_repair_round_limit` does not exist.

- [ ] **Step 3: Add repair-round helper**

In `app/api/translate.py`, before `_auto_repair_quality_issues()`:

```python
def _repair_round_limit(cfg: dict) -> int:
    trans_cfg = cfg.get("translation", {}) if isinstance(cfg, dict) else {}
    raw = trans_cfg.get("qa_auto_repair_rounds", 1) if isinstance(trans_cfg, dict) else 1
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        value = 1
    return max(1, min(value, 2))
```

- [ ] **Step 4: Use helper in report persistence**

In `_persist_translation_quality_report()`, replace the single repair call with:

```python
        repaired = []
        previous_hard_errors = sum(1 for issue in report.issues if issue.severity == "error")
        for _round in range(_repair_round_limit(cfg)):
            round_repaired = _auto_repair_quality_issues(
                cfg,
                translator,
                blocks,
                report,
                target_language,
                project_kb,
            )
            if not round_repaired:
                break
            repaired.extend(round_repaired)
            report = run_quality_checks(
                blocks,
                project_kb=project_kb,
                target_language=target_language,
                trace=trace,
            )
            current_hard_errors = sum(1 for issue in report.issues if issue.severity == "error")
            if current_hard_errors >= previous_hard_errors:
                break
            previous_hard_errors = current_hard_errors
            if current_hard_errors == 0:
                break
        if repaired:
            report.repaired_blocks = repaired
```

Keep the existing `qa_auto_repair` guard inside `_auto_repair_quality_issues()`.

- [ ] **Step 5: Run translate tests**

Run:

```bash
python3 -m pytest -q tests/test_translate_integration.py tests/test_translation_qa.py
```

Expected: PASS.

- [ ] **Step 6: Commit repair rounds**

```bash
git add app/api/translate.py tests/test_translate_integration.py
git commit -m "feat: limit translation qa repair rounds"
```

## Task 10: Documentation And Local Sample Command

**Files:**
- Modify: `docs/USAGE.md`
- Modify: `docs/USAGE.zh-CN.md`

- [ ] **Step 1: Add English docs section**

In `docs/USAGE.md`, add a section named `Translation Accuracy Evaluation`:

```markdown
## Translation Accuracy Evaluation

AI Sub Pro can compare local subtitle outputs without committing the subtitle
files to the repository:

```bash
python3 tools/quality/compare_translation_outputs.py \
  --source /path/to/source.en.srt \
  --old /path/to/old-output.zh.srt \
  --new /path/to/new-output.zh.srt \
  --reference /path/to/reference.zh.srt \
  --term "Hudson Oaks=哈德逊奥克斯" \
  --out-dir /tmp/ai-sub-pro-quality
```

The command writes `translation_accuracy_report.json` and
`translation_accuracy_report.md`. Keep local episode subtitles and reports out
of git unless you own the content and intend to publish it.

Local bilingual corpora can be imported into the phrase library:

```bash
python3 tools/phrase_packs/import_corpus.py /path/to/corpus.tsv \
  --format tsv \
  --source-name "local-opensubtitles-export" \
  --license "source license name" \
  --source-language en \
  --target-language zh-CN \
  --tag subtitle \
  --max-rows 5000
```

Retrieval uses SQLite FTS5 when available and falls back to deterministic n-gram
scoring. The app does not download or bundle large public corpora by default.
```
```

- [ ] **Step 2: Add Chinese docs section**

In `docs/USAGE.zh-CN.md`, add matching Chinese text:

```markdown
## 翻译准确度评测

AI Sub Pro 可以对比本地字幕输出，但不会把字幕文件提交到仓库：

```bash
python3 tools/quality/compare_translation_outputs.py \
  --source /path/to/source.en.srt \
  --old /path/to/old-output.zh.srt \
  --new /path/to/new-output.zh.srt \
  --reference /path/to/reference.zh.srt \
  --term "Hudson Oaks=哈德逊奥克斯" \
  --out-dir /tmp/ai-sub-pro-quality
```

命令会生成 `translation_accuracy_report.json` 和
`translation_accuracy_report.md`。除非你拥有内容并明确要发布，否则不要把本地剧集
字幕或评测报告提交到 git。

可以把本地双语语料导入口语库：

```bash
python3 tools/phrase_packs/import_corpus.py /path/to/corpus.tsv \
  --format tsv \
  --source-name "local-opensubtitles-export" \
  --license "source license name" \
  --source-language en \
  --target-language zh-CN \
  --tag subtitle \
  --max-rows 5000
```

检索会优先使用 SQLite FTS5；不可用时自动回退到确定性的 n-gram 评分。应用默认不下载、
不打包大型公开语料。
```
```

- [ ] **Step 3: Run docs grep**

Run:

```bash
rg -n "Translation Accuracy Evaluation|翻译准确度评测|import_corpus|compare_translation_outputs" docs/USAGE.md docs/USAGE.zh-CN.md
```

Expected: both English and Chinese docs contain the new commands.

- [ ] **Step 4: Commit docs**

```bash
git add docs/USAGE.md docs/USAGE.zh-CN.md
git commit -m "docs: document translation accuracy evaluation"
```

## Task 11: Final Verification And Local Brilliant Minds Report

**Files:**
- No planned source edits unless verification finds defects.
- Local-only output under `/tmp` or another ignored path.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python3 -m pytest -q \
  tests/test_eval_subtitle_compare.py \
  tests/test_quality_compare_cli.py \
  tests/test_retrieval_scoring.py \
  tests/test_phrase_library.py \
  tests/test_translation_memory.py \
  tests/test_corpus_import.py \
  tests/test_eval_metrics.py \
  tests/test_translation_qa.py \
  tests/test_translator_quality_context.py \
  tests/test_translate_integration.py
```

Expected: PASS.

- [ ] **Step 2: Run full tests**

Run:

```bash
python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run local sample evaluation without committing subtitles**

Use the user's local files as inputs. If the old/new source path names differ,
replace paths in the command with the actual local outputs. The comparison
engine supports `.srt` and `.ass` files:

```bash
python3 tools/quality/compare_translation_outputs.py \
  --source "/Users/gaopengxiang/Downloads/电视剧/Brilliant.Minds.S02E15.1080p.WEB.h264-GRACE[EZTVx.to].mkv.bilingual.srt" \
  --old "/Users/gaopengxiang/Downloads/电视剧/Brilliant.Minds.S02E15.1080p.WEB.h264-GRACE[EZTVx.to].mkv.bilingual.srt" \
  --new "/Users/gaopengxiang/Downloads/电视剧/Brilliant.Minds.S02E15.1080p.WEB.h264-GRACE[EZTVx.to].mkv.bilingual.srt" \
  --reference "/Users/gaopengxiang/Downloads/电视剧/Brilliant.Minds.S02E15.1080p.WEB.h264-GRACE.en.chs.ass" \
  --term "Hudson Oaks=哈德逊奥克斯" \
  --out-dir /tmp/ai-sub-pro-brilliant-minds-quality
```

Expected: The command writes `/tmp/ai-sub-pro-brilliant-minds-quality/translation_accuracy_report.json`
and `/tmp/ai-sub-pro-brilliant-minds-quality/translation_accuracy_report.md`.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short --branch
```

Expected: only intentionally untracked local artifacts such as `local-launcher/`
remain.

- [ ] **Step 5: Commit verification fixes only if needed**

If verification required a source fix:

```bash
git add <fixed-files>
git commit -m "fix: stabilize translation accuracy stage"
```

If no fixes were needed, do not create an empty commit.

## Completion Gate

This stage is ready for release only when:

- Local A/B evaluation writes JSON and Markdown reports.
- Corpus import handles JSONL and at least one delimited format.
- Retrieval uses FTS5 when available and deterministic n-gram fallback otherwise.
- Proper-name consistency appears in evaluation or QA reports.
- Conservative repair rounds are bounded to 1-2 rounds.
- English and Chinese usage docs are updated.
- Focused tests and full test suite pass.
- Local user subtitle files are not committed.
