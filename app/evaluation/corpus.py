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


def _block_id(value: Any, field: str, case_id: str) -> str:
    normalized = "" if value is None else str(value).strip()
    if not normalized:
        raise CorpusValidationError(f"{case_id}: {field} must be a non-empty string")
    return normalized


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _blocks(
    value: Any,
    field: str,
    case_id: str,
    text_key: str,
    *,
    allow_empty: bool = False,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise CorpusValidationError(f"{case_id}: {field} must be a list")
    if not value:
        if allow_empty:
            return []
        raise CorpusValidationError(f"{case_id}: {field} must be a non-empty list")
    blocks = []
    for item in value:
        if not isinstance(item, dict):
            raise CorpusValidationError(f"{case_id}: {field} entries must be objects")
        if text_key not in item:
            raise CorpusValidationError(f"{case_id}: {field}.{text_key} is required")
        blocks.append(
            {
                "id": _block_id(item.get("id"), f"{field}.id", case_id),
                text_key: _text(item[text_key]),
            }
        )
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
    source_blocks = _blocks(raw.get("source_blocks"), "source_blocks", case_id, "text")
    candidate_blocks = _blocks(
        raw.get("candidate_blocks"),
        "candidate_blocks",
        case_id,
        "translation",
    )
    project = raw.get("project")
    if not isinstance(project, dict):
        raise CorpusValidationError(f"{case_id}: project must be an object")
    reference_blocks = (
        _blocks(
            raw["reference_blocks"],
            "reference_blocks",
            case_id,
            "translation",
            allow_empty=True,
        )
        if "reference_blocks" in raw
        else []
    )
    return CorpusCase(
        id=case_id,
        tags=_string_list(raw.get("tags"), "tags", case_id),
        source_language=_string(raw.get("source_language"), "source_language", case_id),
        target_language=_string(raw.get("target_language"), "target_language", case_id),
        project=dict(project),
        source_blocks=source_blocks,
        candidate_blocks=candidate_blocks,
        expected_terms=_terms(raw.get("expected_terms"), case_id),
        reference_blocks=reference_blocks,
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
    cases = [_case(item) for item in cases_raw]
    return GoldenCorpus(version=version, cases=cases)
