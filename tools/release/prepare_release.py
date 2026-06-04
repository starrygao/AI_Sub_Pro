#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_artifacts(dist_dir: Path, output_path: Path) -> list[Path]:
    if not dist_dir.exists():
        return []

    output_resolved = output_path.resolve()
    artifacts = []
    for path in sorted(dist_dir.iterdir()):
        if not path.is_file():
            continue
        if path.resolve() == output_resolved:
            continue
        if path.suffix == ".sha256":
            continue
        artifacts.append(path)
    return artifacts


def prepare_release(dist_dir: Path, output_path: Path, checksum_dir: Path, allow_empty: bool) -> dict:
    dist_dir.mkdir(parents=True, exist_ok=True)
    checksum_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    artifacts = release_artifacts(dist_dir, output_path)
    if not artifacts and not allow_empty:
        raise SystemExit(f"No release artifacts found in {dist_dir}. Pass --allow-empty for a dry run.")

    report_artifacts = []
    total_bytes = 0
    for artifact in artifacts:
        size_bytes = artifact.stat().st_size
        digest = sha256_file(artifact)
        checksum_path = checksum_dir / f"{artifact.name}.sha256"
        checksum_path.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
        total_bytes += size_bytes
        report_artifacts.append(
            {
                "name": artifact.name,
                "path": str(artifact),
                "size_bytes": size_bytes,
                "sha256": digest,
                "checksum_path": str(checksum_path),
            }
        )

    report = {
        "artifact_count": len(report_artifacts),
        "total_bytes": total_bytes,
        "artifacts": report_artifacts,
    }
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare release checksums and a size report.")
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checksum-dir", type=Path, required=True)
    parser.add_argument("--allow-empty", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prepare_release(args.dist_dir, args.output, args.checksum_dir, args.allow_empty)


if __name__ == "__main__":
    main()
