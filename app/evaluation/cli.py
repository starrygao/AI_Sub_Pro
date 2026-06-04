"""CLI entry point for deterministic translation quality evaluation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.evaluation.corpus import CorpusValidationError, load_corpus_file
from app.evaluation.metrics import evaluate_corpus
from app.evaluation.reports import report_to_json, report_to_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate a golden subtitle translation corpus.")
    parser.add_argument("--corpus", required=True, help="Path to golden corpus JSON")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--max-chars", type=int, default=32)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        corpus = load_corpus_file(Path(args.corpus))
        report = evaluate_corpus(corpus, max_chars=args.max_chars)
    except CorpusValidationError as exc:
        print(f"Corpus error: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(report_to_json(report), end="")
    else:
        print(report_to_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
