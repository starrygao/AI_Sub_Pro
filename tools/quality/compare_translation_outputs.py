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
