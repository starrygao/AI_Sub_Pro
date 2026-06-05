"""Local bilingual corpus import helpers for PhraseLibrary."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from app.engines.phrase_library import PhraseLibrary

SUPPORTED_INPUT_FORMATS = {"jsonl", "tsv", "csv"}
DEFAULT_MAX_ROWS = 5000
MAX_TEXT_LENGTH = 240
MAX_SAMPLED_ROWS = 5


class CorpusImportError(ValueError):
    """Raised when corpus import arguments or inputs are invalid."""


@dataclass
class CorpusImportReport:
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    limited: bool = False
    sampled_rows: list[dict[str, object]] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)

    def add_sample(self, *, row_number: int, source_text: str, target_text: str) -> None:
        if len(self.sampled_rows) >= MAX_SAMPLED_ROWS:
            return
        self.sampled_rows.append({
            "row_number": row_number,
            "source_text": source_text,
            "target_text": target_text,
        })

    def add_error(self, *, row_number: int, error: str) -> None:
        self.errors.append({"row_number": row_number, "error": error})

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "limited": self.limited,
            "sampled_rows": list(self.sampled_rows),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class _ValidatedMetadata:
    source_name: str
    license_name: str
    source_language: str
    target_language: str
    source_column: str
    target_column: str
    max_rows: int
    tags: tuple[str, ...]
    input_format: str


def import_corpus(
    path: str | Path,
    *,
    input_format: str,
    source_name: str,
    license_name: str,
    source_language: str,
    target_language: str,
    source_column: str = "source",
    target_column: str = "target",
    max_rows: int = DEFAULT_MAX_ROWS,
    tags: Iterable[str] | None = None,
    dry_run: bool = False,
    library: PhraseLibrary | None = None,
) -> CorpusImportReport:
    metadata = _validate_metadata(
        input_format=input_format,
        source_name=source_name,
        license_name=license_name,
        source_language=source_language,
        target_language=target_language,
        source_column=source_column,
        target_column=target_column,
        max_rows=max_rows,
        tags=tags,
    )
    corpus_path = _validate_path(path)
    active_library = library
    if active_library is None and not dry_run:
        active_library = PhraseLibrary()

    report = CorpusImportReport()
    seen: set[tuple[str, str, str, str, str]] = set()

    for row_number, row, parser_error in _iter_rows(corpus_path, metadata):
        if report.accepted >= metadata.max_rows:
            report.limited = True
            break
        if parser_error is not None:
            report.rejected += 1
            report.add_error(row_number=row_number, error=parser_error)
            continue
        source_text = _normalize_text(row.get(metadata.source_column))
        target_text = _normalize_text(row.get(metadata.target_column))
        row_error = _validate_row(source_text=source_text, target_text=target_text)
        if row_error is not None:
            report.rejected += 1
            report.add_error(row_number=row_number, error=row_error)
            continue
        dedupe_key = (
            source_text,
            target_text,
            metadata.source_language,
            metadata.target_language,
            metadata.source_name,
        )
        if dedupe_key in seen:
            report.duplicates += 1
            continue
        seen.add(dedupe_key)

        if dry_run:
            report.accepted += 1
            report.add_sample(
                row_number=row_number,
                source_text=source_text,
                target_text=target_text,
            )
            continue

        entry_id = active_library.add_phrase(
            source_text=source_text,
            target_text=target_text,
            source_language=metadata.source_language,
            target_language=metadata.target_language,
            source_name=metadata.source_name,
            license=metadata.license_name,
            tags=list(metadata.tags),
        )
        if entry_id is None:
            report.duplicates += 1
            continue
        report.accepted += 1
        report.add_sample(
            row_number=row_number,
            source_text=source_text,
            target_text=target_text,
        )

    return report


def _validate_metadata(
    *,
    input_format: str,
    source_name,
    license_name,
    source_language,
    target_language,
    source_column,
    target_column,
    max_rows,
    tags: Iterable[str] | None,
) -> _ValidatedMetadata:
    normalized_format = _normalize_input_format(input_format)
    normalized_source_name = _require_metadata("source_name", source_name)
    normalized_license_name = _require_metadata("license_name", license_name)
    normalized_source_language = _require_metadata("source_language", source_language)
    normalized_target_language = _require_metadata("target_language", target_language)
    normalized_source_column = _require_metadata("source_column", source_column)
    normalized_target_column = _require_metadata("target_column", target_column)
    if isinstance(tags, str):
        raw_tags: Iterable[str] = [tags]
    else:
        raw_tags = tags or ()
    normalized_tags = tuple(
        value
        for value in (_normalize_text(tag) for tag in raw_tags)
        if value
    )
    return _ValidatedMetadata(
        source_name=normalized_source_name,
        license_name=normalized_license_name,
        source_language=normalized_source_language,
        target_language=normalized_target_language,
        source_column=normalized_source_column,
        target_column=normalized_target_column,
        max_rows=_coerce_max_rows(max_rows),
        tags=normalized_tags,
        input_format=normalized_format,
    )


def _normalize_input_format(value) -> str:
    normalized = _normalize_text(value).lower()
    if normalized not in SUPPORTED_INPUT_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_INPUT_FORMATS))
        raise CorpusImportError(f"unsupported input_format {value!r}; expected one of: {supported}")
    return normalized


def _coerce_max_rows(value) -> int:
    if isinstance(value, bool):
        raise CorpusImportError("max_rows must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CorpusImportError("max_rows must be a positive integer") from exc
    if parsed <= 0:
        raise CorpusImportError("max_rows must be a positive integer")
    return parsed


def _require_metadata(name: str, value) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        raise CorpusImportError(f"{name} is required")
    return normalized


def _validate_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        raise CorpusImportError(f"corpus file does not exist: {candidate}")
    if not candidate.is_file():
        raise CorpusImportError(f"corpus path is not a file: {candidate}")
    return candidate


def _normalize_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _validate_row(*, source_text: str, target_text: str) -> str | None:
    if not source_text:
        return "source text is empty"
    if not target_text:
        return "target text is empty"
    if len(source_text) > MAX_TEXT_LENGTH:
        return f"source text exceeds {MAX_TEXT_LENGTH} characters"
    if len(target_text) > MAX_TEXT_LENGTH:
        return f"target text exceeds {MAX_TEXT_LENGTH} characters"
    return None


def _iter_rows(
    path: Path,
    metadata: _ValidatedMetadata,
) -> Iterator[tuple[int, dict[str, object], str | None]]:
    if metadata.input_format == "jsonl":
        yield from _iter_jsonl_rows(path)
        return
    yield from _iter_delimited_rows(path, metadata)


def _iter_jsonl_rows(path: Path) -> Iterator[tuple[int, dict[str, object], str | None]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        for row_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                yield row_number, {}, f"invalid JSON: {exc.msg}"
                continue
            if not isinstance(row, dict):
                yield row_number, {}, "row must be a JSON object"
                continue
            yield row_number, row, None


def _iter_delimited_rows(
    path: Path,
    metadata: _ValidatedMetadata,
) -> Iterator[tuple[int, dict[str, object], str | None]]:
    delimiter = "\t" if metadata.input_format == "tsv" else ","
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            raise CorpusImportError("corpus file is missing a header row")
        missing = [
            column
            for column in (metadata.source_column, metadata.target_column)
            if column not in reader.fieldnames
        ]
        if missing:
            raise CorpusImportError(
                "missing required column(s): " + ", ".join(missing)
            )
        for row_number, row in enumerate(reader, start=2):
            yield row_number, row, None
