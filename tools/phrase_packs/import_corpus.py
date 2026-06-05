#!/usr/bin/env python3
"""Import a local bilingual corpus into the phrase library."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.engines.corpus_import import MAX_IMPORT_ROWS, CorpusImportError, import_corpus  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="local corpus file to import")
    parser.add_argument(
        "--format",
        required=True,
        dest="input_format",
        help="input format: jsonl, tsv, or csv",
    )
    parser.add_argument("--source-name", required=True, help="human-readable corpus source name")
    parser.add_argument(
        "--license",
        required=True,
        dest="license_name",
        help="license or usage terms for the corpus",
    )
    parser.add_argument("--source-language", required=True, help="source language code")
    parser.add_argument("--target-language", required=True, help="target language code")
    parser.add_argument("--source-column", default="source", help="source text column name")
    parser.add_argument("--target-column", default="target", help="target text column name")
    parser.add_argument(
        "--max-rows",
        default=5000,
        help=(
            f"maximum accepted rows to import (1-{MAX_IMPORT_ROWS}); "
            "the importer may stop early on its local scan cap and report limited=true"
        ),
    )
    parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        default=None,
        help="tag to attach to imported rows; repeatable",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate without writing to the phrase DB")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = import_corpus(
            args.path,
            input_format=args.input_format,
            source_name=args.source_name,
            license_name=args.license_name,
            source_language=args.source_language,
            target_language=args.target_language,
            source_column=args.source_column,
            target_column=args.target_column,
            max_rows=args.max_rows,
            tags=args.tags,
            dry_run=args.dry_run,
        )
    except CorpusImportError as exc:
        print(f"Corpus import failed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
