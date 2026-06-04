"""Command line entry point for translation quality evaluation."""
from __future__ import annotations

import argparse
from pathlib import Path

from app.evaluation.corpus import load_corpus_file
from app.evaluation.metrics import evaluate_case
from app.evaluation.reports import (
    build_report,
    write_json_report,
    write_markdown_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a golden translation corpus and write reports."
    )
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--markdown-out", required=True, type=Path)
    args = parser.parse_args(argv)

    corpus = load_corpus_file(args.corpus)
    case_results = [evaluate_case(case) for case in corpus.cases]
    report = build_report(case_results)
    write_json_report(report, args.json_out)
    write_markdown_report(report, args.markdown_out)

    print(
        "Wrote translation quality reports "
        f"for {len(case_results)} cases: {args.json_out} and {args.markdown_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
