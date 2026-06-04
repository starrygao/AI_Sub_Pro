# Release Notes

Language: [English](RELEASE_NOTES.md) | [简体中文](RELEASE_NOTES.zh-CN.md)

## Unreleased - Quality Evaluation And KB Review

This unreleased milestone documents the deterministic evaluation loop and the
new Knowledge Base review tools. No packaged app or DMG is attached for this
unreleased milestone.

Highlights:

- Added release pipeline documentation covering the `v*` tag trigger, dry-run
  release preparation, checksum verification, and size-report review.
- Split base app packages from optional local ASR packages. macOS and Windows
  builds now keep local ASR models/backends out of default packages unless
  `AISUBPRO_BUNDLE_LOCAL_ASR=1` is set.
- macOS DMG builds now run the release preparation helper after DMG creation
  when Python is available, producing checksum files and
  `release-size-report.json`.
- Added `python3 -m app.evaluation.cli` for deterministic golden-corpus
  translation quality reports without network calls or paid providers.
- Added a project Knowledge Base suggestion review workflow based on TMDB
  metadata and current subtitles, with edit, accept, and reject actions.
- Added KB usage trace recording for translation runs, with a project API and
  frontend panel showing which KB entries were used when trace data exists.
- Added intent-level ASR modes for speed, accuracy, and offline use, with
  backend/model recommendations based on detected local backends and model
  cache status.
- Added structured workflow state with bounded per-stage logs, failing-stage
  display, log download, retry, and resume from the last verified artifact.

Quality/Verification:

- Deterministic evaluation CLI passed and wrote reports for 7 cases to
  `build/evaluation/milestone1.json` and `build/evaluation/milestone1.md`.
- Focused milestone tests passed: `109 passed in 1.66s`.
- Full test suite passed: `838 passed in 45.70s`.

## v1.1.1 - Knowledge Base Injection Fix

This patch release fixes the project-specific Knowledge Base v2 injection path
used by real translation runs.

Highlights:

- The translation pipeline now forwards loaded project metadata into
  `SubtitleTranslator`, so Knowledge Base matching can use TMDB IDs, project
  names, titles, cast, and plot context during actual workflows.
- Project-specific terminology and style notes now apply to manual translation,
  full workflow translation, and trailer translation instead of only working in
  isolated prompt-builder tests.
- Added integration coverage that verifies project metadata reaches the
  translator and protects against regressions in this wiring.

Quality:

- Full test suite passed: `757 passed`.
- Frontend CSS build, Python compile checks, and release merge checks passed.

Packages:

- The macOS DMG is attached as split release assets:
  `AI_Sub_Pro_v1.1.1.dmg.part-aa` through `AI_Sub_Pro_v1.1.1.dmg.part-ar`.
- Rebuild the DMG with
  `cat AI_Sub_Pro_v1.1.1.dmg.part-* > AI_Sub_Pro_v1.1.1.dmg`, then verify it
  with `AI_Sub_Pro_v1.1.1.dmg.sha256`. Part-level checksums are provided in
  `AI_Sub_Pro_v1.1.1.dmg.parts.sha256`.
- Windows packaging currently requires a Windows machine and `build_win.bat`;
  no prebuilt Windows installer is attached to this release.

## v1.1.0 - Display Language Preference

This release adds the first public multilingual UI controls and refreshes the
packaged macOS build.

Highlights:

- Added a **Display language** setting with **Follow system**, **Simplified
  Chinese**, and **English** options.
- The interface now applies the selected language to navigation, settings,
  status labels, common workflow text, and translated system messages.
- Existing settings that contain an unsupported display language are repaired
  back to `auto`, and the settings API rejects unsupported values.
- README and usage documentation now mention the display-language option in
  English and Simplified Chinese.

Quality:

- Full test suite passed: `764 passed`.
- Release files were scanned to avoid publishing local runtime data, build
  caches, or personal account identifiers.

Packages:

- `AI_Sub_Pro_v1.1.0.dmg` is attached for macOS users, with a matching
  `.sha256` checksum file.
- Windows packaging currently requires a Windows machine and `build_win.bat`;
  no prebuilt Windows installer is attached to this release.

## v1.0.0 - Initial Open Source Release

AI Sub Pro is now published as an MIT-licensed local-first subtitle workflow
tool.

Highlights:

- Local FastAPI backend with browser and Electron/pywebview frontends.
- Local project store for uploaded videos, subtitles, exports, and settings.
- ASR support through `mlx-whisper`, `faster-whisper`, or `openai-whisper`.
- Translation through OpenAI-compatible providers, Claude CLI, or Codex CLI.
- Subtitle editor with translated, bilingual, and original SRT export.
- Knowledge-base context for names, places, brands, slang, and style rules.
- TMDB and YouTube trailer project workflow.
- `ffmpeg` burn-in output.
- Focused test suite covering backend APIs, project-store safety, scheduling,
  provider behavior, subtitle parsing, and frontend JavaScript.

Open-source preparation:

- Runtime data, build artifacts, model caches, and local project media are
  excluded from the public repository.
- `.env.example` and `config.example.json` document safe configuration.
- Security, contribution, and third-party notice files are included.

Packages:

- `AI_Sub_Pro_v1.0.0.dmg` is attached for macOS users, with a matching
  `.sha256` checksum file.
- Windows packaging currently requires a Windows machine and `build_win.bat`;
  no prebuilt Windows installer is attached to this release.
