# Release Notes

Language: [English](RELEASE_NOTES.md) | [简体中文](RELEASE_NOTES.zh-CN.md)

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
