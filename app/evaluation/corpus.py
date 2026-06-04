"""Golden corpus loading and validation for translation quality evaluation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class CorpusValidationError(ValueError):
    pass


@dataclass
class CorpusCase:
    id: str
    tags: list[str]
    source_language: str
    target_language: str
    source_blocks: list[dict]
    candidate_blocks: list[dict] = field(default_factory=list)
    expected_terms: list[dict] = field(default_factory=list)
    reference_blocks: list[dict] = field(default_factory=list)
    project: dict = field(default_factory=dict)


@dataclass
class GoldenCorpus:
    version: int
    cases: list[CorpusCase]


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (_clean_text(item) for item in value) if text]


def _block_list(value, field: str, case_id: str, *, required: bool = True) -> list[dict]:
    if not isinstance(value, list) or (required and not value):
        raise CorpusValidationError(f"{case_id}: {field} must be a non-empty list")
    blocks = []
    for i, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise CorpusValidationError(f"{case_id}: {field}[{i}] must be an object")
        block_id = _clean_text(item.get("id"))
        text = _clean_text(item.get("text") if field == "source_blocks" else item.get("translation"))
        if not block_id:
            raise CorpusValidationError(f"{case_id}: {field}[{i}].id is required")
        if required and not text:
            raise CorpusValidationError(f"{case_id}: {field}[{i}] text is required")
        normalized = {"id": block_id}
        if field == "source_blocks":
            normalized["text"] = text
        else:
            normalized["translation"] = text
        blocks.append(normalized)
    return blocks


def _terms(value, case_id: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CorpusValidationError(f"{case_id}: expected_terms must be a list")
    terms = []
    for i, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise CorpusValidationError(f"{case_id}: expected_terms[{i}] must be an object")
        source = _clean_text(item.get("source"))
        target = _clean_text(item.get("target"))
        if source and target:
            terms.append({"source": source, "target": target})
    return terms


def _case_from_dict(item: dict) -> CorpusCase:
    if not isinstance(item, dict):
        raise CorpusValidationError("case must be an object")
    case_id = _clean_text(item.get("id"))
    if not case_id:
        raise CorpusValidationError("case id is required")
    if "source_blocks" not in item:
        raise CorpusValidationError(f"{case_id}: source_blocks is required")
    source_language = _clean_text(item.get("source_language")) or "en"
    target_language = _clean_text(item.get("target_language")) or "zh-CN"
    return CorpusCase(
        id=case_id,
        tags=_string_list(item.get("tags")),
        source_language=source_language,
        target_language=target_language,
        source_blocks=_block_list(item.get("source_blocks"), "source_blocks", case_id),
        candidate_blocks=_block_list(
            item.get("candidate_blocks", []),
            "candidate_blocks",
            case_id,
            required=False,
        ),
        expected_terms=_terms(item.get("expected_terms", []), case_id),
        reference_blocks=_block_list(
            item.get("reference_blocks", []),
            "reference_blocks",
            case_id,
            required=False,
        ),
        project=item.get("project") if isinstance(item.get("project"), dict) else {},
    )


def load_corpus_file(path: Path) -> GoldenCorpus:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusValidationError(f"invalid corpus JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CorpusValidationError("corpus root must be an object")
    version = raw.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CorpusValidationError("version must be a positive integer")
    cases_raw = raw.get("cases")
    if not isinstance(cases_raw, list) or not cases_raw:
        raise CorpusValidationError("cases must be a non-empty list")
    return GoldenCorpus(version=version, cases=[_case_from_dict(item) for item in cases_raw])
