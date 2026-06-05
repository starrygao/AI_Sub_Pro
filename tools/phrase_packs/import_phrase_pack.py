#!/usr/bin/env python3
"""Validate and import a local phrase pack into the AI Sub Pro phrase library."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.engines.phrase_library import PhraseLibrary  # noqa: E402


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def validate_payload(raw: object, *, allow_missing_license: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(raw, dict):
        return ["phrase pack must be a JSON object"]
    if not _clean_text(raw.get("source")):
        errors.append("top-level source is required")
    if not allow_missing_license and not _clean_text(raw.get("license")):
        errors.append("top-level license is required")
    if not _clean_text(raw.get("source_language")):
        errors.append("top-level source_language is required")
    if not _clean_text(raw.get("target_language")):
        errors.append("top-level target_language is required")
    phrases = raw.get("phrases")
    if not isinstance(phrases, list) or not phrases:
        errors.append("phrases must be a non-empty list")
        return errors
    for index, row in enumerate(phrases, start=1):
        if not isinstance(row, dict):
            errors.append(f"phrases[{index}] must be an object")
            continue
        if not _clean_text(row.get("source_text")):
            errors.append(f"phrases[{index}].source_text is required")
        if not _clean_text(row.get("target_text")):
            errors.append(f"phrases[{index}].target_text is required")
    return errors


def load_pack(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path, help="JSON phrase pack to validate/import")
    parser.add_argument("--database", type=Path, help="SQLite phrase library path; defaults to app data dir")
    parser.add_argument("--dry-run", action="store_true", help="validate only; do not import")
    parser.add_argument(
        "--allow-missing-license",
        action="store_true",
        help="allow packs without license metadata; not recommended for public corpora",
    )
    args = parser.parse_args()

    try:
        raw = load_pack(args.pack)
    except Exception as exc:
        print(f"Failed to read {args.pack}: {exc}", file=sys.stderr)
        return 2

    errors = validate_payload(raw, allow_missing_license=args.allow_missing_license)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"OK: {args.pack}")
        return 0

    library = PhraseLibrary(args.database) if args.database is not None else PhraseLibrary()
    imported = library.import_pack(args.pack)
    print(f"Imported {imported} phrase example(s) from {args.pack}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
