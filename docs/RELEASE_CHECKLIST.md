# Release Checklist

Language: [English](RELEASE_CHECKLIST.md) | [简体中文](RELEASE_CHECKLIST.zh-CN.md)

Use this checklist before publishing a GitHub Release.

## Trigger

- Create release tags as `v*`, for example `v1.2.0`; the release workflow uses
  the tag trigger to run the publish path.
- Use `workflow_dispatch` for a manual dry run before tagging when validating
  release plumbing.
- Pull requests should stay on the dry-run path with `--allow-empty` so the
  workflow can verify release preparation without requiring built artifacts.

## Build Strategy

- Default packages are base-app builds. They include the app, frontend assets,
  and ffmpeg binaries, but do not bundle local Whisper models or optional local
  ASR packages.
- Set `AISUBPRO_BUNDLE_LOCAL_ASR=1` only when intentionally producing a larger
  offline-oriented package that includes `models/asr` and installed optional
  ASR backends such as `faster-whisper`, `mlx-whisper`, or `openai-whisper`.
- Record whether a release asset is a base package or an optional ASR package
  in the release notes.

## Verification

- Run the focused packaging tests before publishing:
  `python3 -m pytest -q tests/test_packaging_scripts.py`.
- Run a release dry run:
  `python3 tools/release/prepare_release.py --dist-dir dist --output dist/release-size-report.json --checksum-dir dist --allow-empty`.
- After building a DMG or other asset, verify generated checksum files with
  `shasum -a 256 -c <artifact>.sha256` or an equivalent SHA-256 checker.
- Inspect `dist/release-size-report.json` for expected artifact names and
  package sizes before uploading assets.

## Publish

- Push the `v*` tag only after tests, dry run, checksum verification, and size
  review pass.
- Upload the DMG, checksum files, and size report generated from the same
  `dist` directory.
- If split assets are required, publish part-level checksums and document the
  join command in the release notes.
