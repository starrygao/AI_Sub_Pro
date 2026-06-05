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


_ASS_OVERRIDE_RE = re.compile(r"\{[^}]*\}")
_ENGLISH_RE = re.compile(r"[A-Za-z]{3,}")


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
    """Compare local source, old output, new output, and optional reference files."""
    source = _validate_path(source_path, "source")
    old = _validate_path(old_path, "old")
    new = _validate_path(new_path, "new")
    reference = _validate_path(reference_path, "reference", required=False)

    source_by_id = _load_subtitle_file(source)
    old_by_id = _load_subtitle_file(old)
    new_by_id = _load_subtitle_file(new)
    reference_by_id = _load_subtitle_file(reference) if reference is not None else {}
    terms = _expected_terms(expected_terms)

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
            "old_count": len(old_by_id),
            "new_count": len(new_by_id),
            "reference_count": len(reference_by_id),
            "has_reference": bool(reference_by_id),
            "expected_term_count": len(terms),
        },
        "alignment": _alignment(source_by_id, old_by_id, new_by_id, reference_by_id),
        "old": old_metrics,
        "new": new_metrics,
        "delta": _delta(old_metrics, new_metrics),
    }


def report_to_markdown(report: dict[str, Any]) -> str:
    """Render a subtitle comparison report as Markdown."""
    summary = report.get("summary", {})
    delta = report.get("delta", {})
    lines = [
        "# Translation Accuracy Report",
        "",
        "## Summary",
        "",
        f"- Source blocks: {summary.get('source_count', 0)}",
        f"- Old blocks: {summary.get('old_count', 0)}",
        f"- New blocks: {summary.get('new_count', 0)}",
        f"- Reference provided: {summary.get('has_reference', False)}",
        f"- Expected terms: {summary.get('expected_term_count', 0)}",
        "",
        "## Delta",
        "",
        f"- Missing translations: {delta.get('missing_translation_count', 0):+}",
        f"- English residue: {delta.get('english_residue_count', 0):+}",
        f"- Length violations: {delta.get('length_violation_count', 0):+}",
        f"- Terminology hit rate: {_format_signed_rate(delta.get('terminology_hit_rate', 0.0))}",
        "- Reference exact-match rate: "
        f"{_format_signed_rate(delta.get('reference_exact_match_rate', 0.0))}",
        "",
        "## Candidate Metrics",
        "",
    ]
    lines.extend(_candidate_markdown("Old", report.get("old", {})))
    lines.extend(_candidate_markdown("New", report.get("new", {})))
    lines.extend(["", "## Inputs", ""])
    for key, value in report.get("inputs", {}).items():
        lines.append(f"- {key}: {value or 'None'}")
    lines.append("")
    return "\n".join(lines)


def save_report(
    report: dict[str, Any],
    *,
    json_path: str | Path,
    markdown_path: str | Path,
) -> None:
    """Write a report to UTF-8 JSON and Markdown files."""
    json_out = Path(json_path)
    markdown_out = Path(markdown_path)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_out.write_text(report_to_markdown(report), encoding="utf-8")


def _validate_path(
    value: str | Path | None,
    label: str,
    *,
    required: bool = True,
) -> Path | None:
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


def _load_subtitle_file(path: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".ass":
        return _parse_ass(path)
    if suffix == ".srt":
        return _blocks_by_id(parse_srt_file(str(path)))

    content = path.read_text(encoding="utf-8-sig", errors="ignore")
    return _blocks_by_id(parse_srt(content))


def _blocks_by_id(blocks: Iterable[SubtitleBlock]) -> dict[str, str]:
    result: dict[str, str] = {}
    for block in blocks:
        block_id = str(getattr(block, "index", "")).strip()
        text = getattr(block, "text", "")
        if block_id:
            result[block_id] = text.strip() if isinstance(text, str) else ""
    return result


def _parse_ass(path: Path) -> dict[str, str]:
    blocks: dict[str, str] = {}
    in_events = False
    text_index = 9
    row_index = 1

    for raw_line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower == "[events]":
            in_events = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_events = False
            continue
        if not in_events:
            continue
        if lower.startswith("format:"):
            fields = [part.strip().lower() for part in line.split(":", 1)[1].split(",")]
            if "text" in fields:
                text_index = fields.index("text")
            continue
        if not lower.startswith("dialogue:"):
            continue

        payload = line.split(":", 1)[1].lstrip()
        parts = payload.split(",", text_index)
        if len(parts) <= text_index:
            continue
        text = _clean_ass_text(parts[text_index])
        if text:
            blocks[str(row_index)] = text
            row_index += 1
    return blocks


def _clean_ass_text(value: str) -> str:
    text = _ASS_OVERRIDE_RE.sub("", value)
    text = text.replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ")
    return re.sub(r"\s+", " ", text).strip()


def _candidate_metrics(
    *,
    source_by_id: dict[str, str],
    candidate_by_id: dict[str, str],
    reference_by_id: dict[str, str],
    expected_terms: list[dict[str, str]],
    max_chars: int,
) -> dict[str, Any]:
    source_ids = list(source_by_id)
    case = _MetricCase(source_by_id, candidate_by_id, expected_terms)
    return {
        "missing_translation": missing_translation_score(candidate_by_id, source_ids),
        "english_residue": _english_residue(candidate_by_id),
        "length": _length_violations(candidate_by_id, max_chars),
        "terminology": terminology_score(case, candidate_by_id),
        "reference_similarity": (
            _reference_similarity(candidate_by_id, reference_by_id)
            if reference_by_id
            else _empty_reference_similarity()
        ),
    }


def _alignment(
    source_by_id: dict[str, str],
    old_by_id: dict[str, str],
    new_by_id: dict[str, str],
    reference_by_id: dict[str, str],
) -> dict[str, Any]:
    source_ids = set(source_by_id)
    old_ids = set(old_by_id)
    new_ids = set(new_by_id)
    reference_ids = set(reference_by_id)
    return {
        "source_count": len(source_ids),
        "old_count": len(old_ids),
        "new_count": len(new_ids),
        "reference_count": len(reference_ids),
        "old_missing_ids": _sorted_ids(source_ids - old_ids),
        "new_missing_ids": _sorted_ids(source_ids - new_ids),
        "reference_missing_ids": _sorted_ids(source_ids - reference_ids),
        "old_extra_ids": _sorted_ids(old_ids - source_ids),
        "new_extra_ids": _sorted_ids(new_ids - source_ids),
        "reference_extra_ids": _sorted_ids(reference_ids - source_ids),
    }


def _delta(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    return {
        "missing_translation_count": (
            new["missing_translation"]["missing_count"]
            - old["missing_translation"]["missing_count"]
        ),
        "english_residue_count": (
            new["english_residue"]["count"] - old["english_residue"]["count"]
        ),
        "length_violation_count": new["length"]["count"] - old["length"]["count"],
        "terminology_hit_rate": _round_rate(
            new["terminology"]["hit_rate"] - old["terminology"]["hit_rate"]
        ),
        "reference_exact_match_rate": _round_rate(
            new["reference_similarity"]["exact_match_rate"]
            - old["reference_similarity"]["exact_match_rate"]
        ),
    }


def _english_residue(candidate_by_id: dict[str, str]) -> dict[str, Any]:
    ids = [
        block_id
        for block_id, text in candidate_by_id.items()
        if isinstance(text, str) and _ENGLISH_RE.search(text)
    ]
    return {
        "ids": ids,
        "count": len(ids),
        "rate": _rate(len(ids), len(candidate_by_id)),
    }


def _length_violations(candidate_by_id: dict[str, str], max_chars: int) -> dict[str, Any]:
    if max_chars <= 0:
        return {"ids": [], "count": 0, "rate": 0.0, "max_chars": max_chars}
    ids = []
    for block_id, text in candidate_by_id.items():
        compact = re.sub(r"\s+", "", text if isinstance(text, str) else "")
        if len(compact) > max_chars:
            ids.append(block_id)
    return {
        "ids": ids,
        "count": len(ids),
        "rate": _rate(len(ids), len(candidate_by_id)),
        "max_chars": max_chars,
    }


def _reference_similarity(
    candidate_by_id: dict[str, str],
    reference_by_id: dict[str, str],
) -> dict[str, Any]:
    shared = _sorted_ids(set(candidate_by_id) & set(reference_by_id))
    exact = [
        block_id
        for block_id in shared
        if candidate_by_id.get(block_id, "").strip()
        == reference_by_id.get(block_id, "").strip()
    ]
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


def _empty_reference_similarity() -> dict[str, Any]:
    return {
        "shared_count": 0,
        "exact_match_count": 0,
        "exact_match_rate": 0.0,
        "changed": [],
    }


def _expected_terms(
    expected_terms: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    cleaned = []
    for item in expected_terms or []:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        target = item.get("target")
        if (
            isinstance(source, str)
            and source.strip()
            and isinstance(target, str)
            and target.strip()
        ):
            cleaned.append({"source": source.strip(), "target": target.strip()})
    return cleaned


def _rate(count: int, total: int) -> float:
    return _round_rate(count / total) if total else 0.0


def _round_rate(value: float) -> float:
    return round(value, 4)


def _sorted_ids(ids: Iterable[str]) -> list[str]:
    return sorted(ids, key=_id_sort_key)


def _id_sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if str(value).isdigit() else (1, str(value))


def _format_signed_rate(value: Any) -> str:
    return f"{float(value):+.4f}"


def _candidate_markdown(label: str, metrics: dict[str, Any]) -> list[str]:
    missing = metrics.get("missing_translation", {})
    residue = metrics.get("english_residue", {})
    length = metrics.get("length", {})
    terminology = metrics.get("terminology", {})
    reference = metrics.get("reference_similarity", {})
    return [
        f"### {label}",
        "",
        f"- Missing translations: {missing.get('missing_count', 0)}",
        f"- English residue: {residue.get('count', 0)}",
        f"- Length violations: {length.get('count', 0)}",
        f"- Terminology hit rate: {_format_signed_rate(terminology.get('hit_rate', 0.0))[1:]}",
        "- Reference exact-match rate: "
        f"{_format_signed_rate(reference.get('exact_match_rate', 0.0))[1:]}",
        "",
    ]


class _MetricCase:
    def __init__(
        self,
        source_by_id: dict[str, str],
        candidate_by_id: dict[str, str],
        expected_terms: list[dict[str, str]],
    ) -> None:
        self.id = "local-subtitle-compare"
        self.tags = ["local"]
        self.source_blocks = [
            {"id": block_id, "text": text} for block_id, text in source_by_id.items()
        ]
        self.candidate_blocks = [
            {"id": block_id, "translation": text}
            for block_id, text in candidate_by_id.items()
        ]
        self.expected_terms = expected_terms


__all__ = [
    "SubtitleCompareError",
    "compare_subtitle_files",
    "report_to_markdown",
    "save_report",
]
