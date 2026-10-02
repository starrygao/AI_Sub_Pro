## Unreleased

- Default new configurations to OMP CLI. Desktop and server settings independently select OMP, Codex, or Claude for translation and polishing while preserving existing choices.
- Run OMP in an isolated, tool-free, session-free JSON mode with dynamic model discovery, reasoning levels, and model-specific credential checks. Protocol and authentication failures never become empty subtitles.
- Pin and verify the OMP 18.4.4 Linux binary in Docker and persist its login separately. Server model and CLI changes continue to apply after the current task finishes.
- Make model synchronization refresh OMP's upstream catalog instead of only bypassing the application cache. Preserve selected models and discover GPT-6.1 Sol through the updated CLI.
- Match OMP readiness checks to the effective primary model when the polishing model is empty, and keep Cursor inference models available while isolating coding-tool configuration.
- Tighten name-span evidence so sentence-initial ordinary words, titles, and adjacent Chinese text do not become spurious name variants. Full-name deduplication must not hide genuine short-name inconsistencies.
- Use bounded, read-only neighboring context in translation and targeted semantic review, retaining source sound cues. Targeted review shares project terminology and entity context without duplicating dialogue already present in full-document requests.
- Recognize full-width sound-cue brackets and correct exhaling forms while preserving two-speaker line breaks and markers during cleanup.
- Classify English residue as a content issue. Exempt source-backed brands, pronunciation exercises, and approved retained terms without exempting surrounding untranslated dialogue. Preserve source-supported consecutive repetition while checking the full displayed reading load.

## v1.3.42

`AI_Sub_Pro_v1.3.42.dmg`

- Resolve macOS file drops directly from the current native drag, validating file names and sizes without relying on DOM callback delivery.
- Show failed TMDB lookups before task launch, with retry, cancel, and explicit skip actions.

## v1.3.41

Package: `AI_Sub_Pro_v1.3.41.dmg`

- Introduce a self-rendered HTML/CSS diffusion-glass interface shared by desktop and browser.
- Reflow project actions, language selectors, settings, and recent tasks according to workspace width.
- Reduce the desktop minimum size to 560 × 480 and retain mobile layouts, keyboard operation, and reduced-motion support.

## v1.3.40

Package: `AI_Sub_Pro_v1.3.40.dmg`

- Treat native file/folder cancellation as terminal and prevent duplicate dialogs.
- Distinguish series identity years from special-episode years; retry empty year-filtered TV searches while retaining candidate confirmation.
- Redact TMDB query credentials in HTTP request logs.

## v1.3.39

Package: `AI_Sub_Pro_v1.3.39.dmg`

- Fix missed sound cues and quality false positives from formatting tags and URLs.
- Improve document-wide name consistency checks and group entity findings while preserving every subtitle location.
- Share entity context with translation and semantic repair, protecting possibility wording and curated terms.
- Prevent stale checkpoints from overwriting subtitle edits and keep filtered source IDs aligned after renumbering.

## v1.3.38

Package: `AI_Sub_Pro_v1.3.38.dmg`

- Preserve wrapped dialogue containing sound-like words in quality-check inputs.
- Reduce false name inconsistencies for unchanged ranks and explicitly delimited work titles across dialogue contexts while retaining genuine differences.

## v1.3.37

Package: `AI_Sub_Pro_v1.3.37.dmg`

- Prevent inferred-name normalization from replacing ordinary possessive context or duplicating titles.
- Reduce false positives for short Chinese names, titles, and conditional phrases; check single-word speaker labels for name drift.
- Supply read-only neighboring subtitles to semantic QA and evaluate natural Chinese word order across continuous cues.
- Check the rendered export layout and retire stale execution failures only after a fresh check of the same content.

## v1.3.36

Installer: `AI_Sub_Pro_v1.3.36.dmg`

- Translation, retries, QA and export share a source classification contract. Known sound cues are skipped before translation; unknown bracketed content requires a nonempty translation, while dialogue and lyrics are retained.
- Save source-, timeline- and configuration-bound drafts between batches. Retry only missing content, then run fresh QA before download or burn.
- Migrate verifiable legacy partial subtitles before invalidating old reports. Reject incompatible source, configuration or draft identities.
- Resolve the project directory before creating burn transaction files, preventing commit failures when the data root is a symlink.

## v1.3.35

Installer: `AI_Sub_Pro_v1.3.35.dmg`

- Deliver complete translated and bilingual subtitles after automatic repair, retaining unresolved semantic and quality findings as optional review notes.
- Downloads and automatic burning no longer require human review for these advisory findings.
- Keep missing-dialogue, timing, artifact integrity and run identity checks, including rollback of unverified repair candidates.

## v1.3.34

Installer: `AI_Sub_Pro_v1.3.34.dmg`

- Recognize bracketed action cues such as gunfire, hand rapping, and seagulls mewing so omitted sound descriptions no longer cause repeated missing-translation retries and task failure.
- Keep sound omission consistent across completion counts, quality checks, and export while preserving dialogue checks and other review requirements.

## v1.3.33

Installer: `AI_Sub_Pro_v1.3.33.dmg`

- Allow up to two minutes for desktop startup permission prompts, while stopping immediately if the server thread exits.
- Fix local server startup from Finder when the windowed bundle has no console streams; reuse file logging instead of the console formatter.
- Refresh active tasks on the home page to avoid stale processing indicators.
- Show a persistent notice when the local service disconnects, explain why details and completion status are unavailable, and refresh task state after reconnection.

## v1.3.32

Installer: `AI_Sub_Pro_v1.3.32.dmg`

- Keep full-pipeline projects visibly processing while waiting for a translation slot after subtitle extraction.
- Persist and publish the waiting stage for both translation-only and translation-and-burn workflows.

## v1.3.31

Installer: `AI_Sub_Pro_v1.3.31.dmg`

- Allow projects with unfinished strict translation runs to open their source subtitles before translated output exists.
- Preserve certification checks for existing translations and export, with regression coverage for recognized and cancelled projects.

## v1.3.30

Installer: `AI_Sub_Pro_v1.3.30.dmg`

- Resolve ambiguous TMDB matches before launching project tasks, with associate, skip and cancel options.
- Keep failed association saves retryable without starting a worker; disable association changes during processing.
- Cover local, batch, translation and resume entry points while retaining the backend context lock.

# Release Notes

Language: [English](RELEASE_NOTES.md) | [简体中文](RELEASE_NOTES.zh-CN.md)

## v1.3.29 - Quality evaluation, release verification and credential storage

- Evaluate fresh translator output with timings, submission/rework metrics and manual-review packets.
- Pin the macOS arm64 release environment and verify the real bundle using isolated legacy data and synthetic Keychain credentials.
- Move translation workers into a shared task service and extract frontend model settings.
- Store API credentials in the OS vault; settings responses expose configured state only.
- macOS package: `AI_Sub_Pro_v1.3.29.dmg`.

## v1.3.28 - Unified model capabilities

- Share one model catalog across the UI and translation providers, including context budgets and supported request parameters.
- Preserve selected models when refreshing lists and show catalog availability status.
- Expose supported OpenAI reasoning efforts while keeping API and CLI capabilities separate.
- macOS package: `AI_Sub_Pro_v1.3.28.dmg`.

## v1.3.27 - Model catalog refresh

- Refresh OpenAI, Codex CLI, Gemini and DeepSeek model options.
- Preserve nano text models and use compatible parameters for newer OpenAI models.
- macOS package: `AI_Sub_Pro_v1.3.27.dmg`.

## v1.3.26 - Professional Translation Quality Gate

Highlights:

- Professional strict mode now fails closed across translation, certification,
  subtitle editing, and translated/bilingual export; stale, incomplete, or
  failed quality evidence cannot certify changed delivery artifacts.
- Context-aware repair keeps semantic groups atomic, rechecks partial batches,
  reports only net model changes, and reruns deterministic normalization after
  every mutation so repair statistics and residual findings stay truthful.
- Structural speaker lines and interruption punctuation survive subtitle
  formatting, approved project/context terminology is enforced without
  hard-coded series vocabulary, and per-project delivery transactions prevent
  readers or editors from observing mixed artifact generations.
- The editor now presents one authoritative merged quality view with visible
  residual issues and fail-closed export controls; terminal progress is
  reconciled across project, workflow, websocket, and persisted readers.

Quality/Verification:

- Release metadata and packaging consistency are covered by automated checks.
- Local package target: `AI_Sub_Pro_v1.3.26.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.26.dmg` is the macOS package name for this release line.

## v1.3.25 - Unattended Delivery Gate and Background Speaker Markers

Highlights:

- Quality-gate failures now use a fail-closed unattended delivery state instead
  of human-review wording; failed jobs keep partial subtitle artifacts and resume
  from translation for the next automatic retry.
- Contextual speaker labels such as `ANNOUNCER:`, `HOST:`, `M.C.:`, `ON TV:`,
  `RADIO:`, `V.O.`, and `O.S.` are converted into compact Chinese markers such
  as `【主持人】`, `【电视】`, `【广播】`, `【旁白】`, and `【画外音】` before export.
- Translated SRT export now collapses two-line translated cues up to the QA line
  limit of 32 compact characters, while longer cues keep their line break.

Quality/Verification:

- Full local test suite passed: `1283 passed`.
- Local package target: `AI_Sub_Pro_v1.3.25.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.25.dmg` is the macOS package name for this release line.

## v1.3.24 - Professional QA Warning Automation

Highlights:

- Proper-name QA now treats ordinary deictic/classifier prefixes such as
  "this pair" / "this one" as subtitle context, preventing false inconsistent
  name warnings for repeated documentary creature names such as Nanuqsaurus.
- High-confidence consistency warnings now carry an `expected` target when a
  clear majority form exists; only the minority rows enter automatic QA repair.
- The quality gate no longer passes high-confidence consistency warnings after
  auto-repair if they still have an expected fix, while low-confidence
  heuristic warnings remain report-only.

Quality/Verification:

- Targeted and integration tests passed: `112 passed`.
- Real project QA recheck passed for `调音师` and `地球·劫后重生 S01E03`: `0 issues`.
- Local package target: `AI_Sub_Pro_v1.3.24.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.24.dmg` is the macOS package name for this release line.

## v1.3.23 - Export Quality Sound-Cue Parity

Highlights:

- Missing-translation checks now share the deterministic QA sound-description
  classifier, so music cues, sound effects, and lyric-marked non-dialogue rows do
  not block automatic completion.
- QA auto-repair now applies only non-empty exact-id repairs and runs a post-QA
  missing-dialogue retry before saving, preventing repaired jobs from losing
  ordinary dialogue translations.
- Frontend export quality checks now recognize the same sound/music cues as the
  backend, including animal sounds such as `[squawking]`, `[hissing]`, and
  `[dinosaur snarls]`.
- Translated and bilingual exports omit source sound/music description cues,
  avoiding burn-in artifacts such as `[growling]` or music symbols.

Quality/Verification:

- Targeted local tests passed: `2 passed`.
- Local package target: `AI_Sub_Pro_v1.3.23.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.23.dmg` is the macOS package name for this release line.

## v1.3.19 - Native File Drop Bridge

Highlights:

- Added a pywebview native drop bridge so macOS Finder drops provide real local
  file paths to the existing import flow.
- Native drop paths now reuse the same single-video and batch-video frontend
  handling as manual local paths.

Quality/Verification:

- Targeted local tests passed: `80 passed`.
- Local package target: `AI_Sub_Pro_v1.3.19.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.19.dmg` is the macOS package name for this release line.

## v1.3.18 - Desktop Drag Import Stability

Highlights:

- Desktop drag-and-drop now resolves Finder `file://` payloads to local video
  paths before project creation.
- When the desktop shell cannot provide a local path for a dragged video, the
  UI now refuses the large upload fallback and shows a clear picker instruction.
- The drop zone stops the follow-up click event after a drop, avoiding accidental
  native picker opens.

Quality/Verification:

- Targeted local tests passed: `67 passed`.
- Local package target: `AI_Sub_Pro_v1.3.18.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.18.dmg` is the macOS package name for this release line.

## v1.3.17 - Automatic Professional Quality Loop

Highlights:

- Professional mode is now the default automatic path: generated KB candidates
  are soft translation hints, not a pre-translation human review gate.
- Added deterministic cleanup for curated paleontology terms, safe
  auto-detected scientific term majority variants, and stable short place/name
  anchors.
- Updated quality-report UI copy to recommend automatic rework or deferred
  delivery instead of manual confirmation.

Quality/Verification:

- Targeted local tests passed: `175 passed`.
- Local package target: `AI_Sub_Pro_v1.3.17.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.17.dmg` is the macOS package name for this release line.

## v1.3.16 - Historical Subtitle Polish Pass

Highlights:

- Expanded deterministic non-dialogue cue detection for bracketed subtitle
  descriptions such as typing, giggling, kissing sounds, glass shatters,
  wings fluttering, waves lapping, and indistinct announcements.
- Refreshed and polished existing local translated SRT outputs with the
  configured QA auto-repair flow.
- Existing final translated projects now all pass the blocking quality gate:
  `26 / 26` passed, with `0` blocking issues remaining.

Quality/Verification:

- Targeted local tests passed: `118 passed`.
- Historical subtitle polish repaired `934` model-targeted blocks and applied
  `34` deterministic non-dialogue cleanups.
- Remaining historical report entries are non-blocking warnings only:
  `45` scientific-term consistency reminders and `73` proper-name reminders.
- Local package target: `AI_Sub_Pro_v1.3.16.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.16.dmg` is the macOS package name for this release line.

## v1.3.15 - Bracketed Sound Cue Cleanup

Highlights:

- Translation post-processing now removes bracketed sound/SDH cue fragments
  from translated dialogue, such as `[laughs]`, `[phone vibrating]`, and
  `（tense music）`, while preserving speaker labels like `[Henry]`.
- QA now recognizes square-bracket and parenthesized non-dialogue cues,
  including music marks, language/speaking notes, impact sounds, breathing,
  phone, door, weather, and animal-call cues.
- Existing local project outputs were refreshed: translated SRT files now have
  `0` pending bracketed sound-cue cleanup hits.

Quality/Verification:

- Targeted local tests passed: `118 passed`.
- Historical output dry-run verified `0` pending bracketed sound-cue cleanup
  blocks across `26` local translated projects.
- Local package target: `AI_Sub_Pro_v1.3.15.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.15.dmg` is the macOS package name for this release line.

## v1.3.14 - SRT QA Warning Refresh

Highlights:

- SRT parsing now preserves cue line breaks, preventing already-wrapped
  subtitles from being rechecked as one long line.
- Music-only cues such as `♪` are treated as non-dialogue sound cues instead
  of missing translations.
- Deterministic post-processing now blanks full sound-description cue
  translations before QA/export, including multi-line sound-only cues.
- Refreshed the local S02E07 project report and exported subtitles so its QA
  report has no remaining warnings.

Quality/Verification:

- Targeted local tests passed: `116 passed`.
- S02E07 QA report verified with `0` issues, `0` warnings, and `0`
  music-symbol hits in exported subtitles.
- Local package target: `AI_Sub_Pro_v1.3.14.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.14.dmg` is the macOS package name for this release line.

## v1.3.13 - Proper Name Normalization Pass

Highlights:

- Added a conservative deterministic post-translation pass for inferred proper
  names: it only normalizes minority variants when a strict majority target
  form can be extracted safely.
- The translation quality persistence flow now reruns QA after deterministic
  proper-name normalization, so future reports reflect the cleaned result.
- Existing local project outputs were reviewed and updated for known subtitle
  name/term consistency issues.

Quality/Verification:

- Targeted local tests passed: `56 passed`.
- Existing exported project subtitle files were verified with `0` music-symbol
  hits and `0` remaining `proper_name_inconsistent` report entries.
- Local package target: `AI_Sub_Pro_v1.3.13.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.13.dmg` is the macOS package name for this release line.

## v1.3.12 - Subtitle Music Symbol Cleanup

Highlights:

- Final SRT writers now strip music decoration symbols such as `♪`, `♫`, `♬`,
  `🎵`, and `🎶` from exported subtitles.
- Translation prompts explicitly tell providers not to emit those music
  decoration symbols in translated output.

Quality/Verification:

- Targeted local tests passed: `111 passed`.
- Existing exported project subtitle files were cleaned and verified with
  `0` music-symbol hits in final output SRT files.
- Local package target: `AI_Sub_Pro_v1.3.12.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.12.dmg` is the macOS package name for this release line.

## v1.3.11 - Quality Gate Warning Triage

Highlights:

- Report-only inferred consistency warnings no longer block project delivery or
  leave projects stuck in "needs review".
- QA reports now separate blocking issues from report-only warnings in their
  summary and unresolved-block counts.

Quality/Verification:

- Targeted local tests passed: `87 passed`.
- Local package target: `AI_Sub_Pro_v1.3.11.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.11.dmg` is the macOS package name for this release line.

## v1.3.10 - Batch Folder Translation

Highlights:

- The home source selector now includes a batch folder mode for recursive
  local video discovery.
- Batch jobs use the existing project creation and `start-full` workflow, with
  one task settings prompt for all discovered videos.
- Desktop builds expose a native folder picker for batch imports.

Quality/Verification:

- Targeted local tests passed: `108 passed`.
- Local package target: `AI_Sub_Pro_v1.3.10.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.10.dmg` is the macOS package name for this release line.

## v1.3.9 - Translation Quality Workflow Hardening

Highlights:

- Automatic knowledge-base suggestions now feed translation context without
  blocking the user with a mandatory pre-translation review queue.
- Scientific and Latin-term handling is stricter, reducing false glossary
  suggestions while preserving useful detected terminology.
- Translation QA now separates confirmed defects from inferred term/name
  warnings, so jobs can finish while still showing quality-review status when
  professional review is warranted.
- The frontend now surfaces the translation quality state instead of masking
  warnings as a clean final delivery.

Quality/Verification:

- Full test suite passed locally: `1219 passed in 219.75s`.
- Package script regression passed locally: `33 passed`.
- Local package target: `AI_Sub_Pro_v1.3.9.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.9.dmg` is the macOS package name for this release line.

## v1.3.8 - Download Location Prompt and Popover Layering

Highlights:

- Online video jobs now show a confirmation dialog before downloading,
  explaining that the source video is stored under
  `~/AI_Sub_Pro_Data/projects/<project-id>/original.mp4`, not the system
  Downloads folder.
- Project cards can open the project location for online-video jobs before
  the final burned video is ready, so users can inspect the downloaded source
  and intermediate files.
- The project-detail actions popover now uses a dedicated high z-index layer
  so expanded options are not covered by neighboring cards or panels.

Quality/Verification:

- Frontend/accessibility/settings regression passed: `116 passed`.
- Focused red-green regression passed: `5 passed`.
- Local package target: `AI_Sub_Pro_v1.3.8.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.8.dmg` is the macOS package name for this release line.

## v1.3.7 - Network Video Metadata and Native Subtitle Translation

Highlights:

- The home screen standalone TMDB trailer entry is replaced with an online
  video translation entry for YouTube links and direct video file URLs.
- A new direct URL trailer API creates download/transcribe/translate projects
  without requiring TMDB metadata, while existing TMDB enrichment remains
  available for film and TV project metadata.
- URL projects now probe network video metadata before creation when the user
  leaves title or source language on auto, then save source title, uploader,
  channel, duration, source language, and platform subtitle availability.
- Downloaded native subtitles are preferred across detected source languages,
  not just English; when adopted, the pipeline skips ASR and translates the
  platform subtitle file directly.
- Translation prompts now receive stronger content-type context, including
  academic, interview, tutorial, film/TV, legal adult guidance, and detected
  network source context.

Quality/Verification:

- Full test suite passed locally: `1111 passed in 202.29s`.
- Focused trailer/frontend/project-metadata regression passed: `176 passed`.
- Translator quality regression passed: `28 passed`.
- Package script regression passed: `33 passed`.
- Local package target: `AI_Sub_Pro_v1.3.7.dmg`.

Packages:

- `AI_Sub_Pro_v1.3.7.dmg` is the macOS package name for this release line.

## v1.3.5 - ASR Install Prompts and Model Catalog Sync

Highlights:

- System check now returns ASR install prompts when the user explicitly selects
  a local backend that is not installed, or when no local ASR backend exists.
- The settings page shows the ASR dependency prompt inline and raises one
  deduplicated toast per missing backend during a session.
- Whisper model choices now come from the backend capability catalog instead
  of being duplicated as hardcoded frontend options; custom configured models
  are preserved in the selectable list.
- Automatic mode remains quiet when at least one local ASR backend is available,
  so users are not spammed about optional backends they did not choose.

Quality/Verification:

- Full test suite passed: `1087 passed in 198.90s`.
- Focused ASR/settings/frontend regression passed: `202 passed in 24.24s`.
- Runtime source check passed: `/api/system-check` returned six ASR model
  options, no install prompt in auto mode with MLX available, and the settings
  UI rendered both dynamic model options and the ASR install prompt.
- Local DMG verification passed: `hdiutil verify dist/AI_Sub_Pro_v1.3.5.dmg`
  reported a valid checksum, and
  `shasum -a 256 -c AI_Sub_Pro_v1.3.5.dmg.sha256` passed from `dist/`.
- Local installed app verification passed: `/api/settings` reports app version
  `1.3.5`, ASR backend `auto`, and `/api/system-check` exposes
  `asr_model_options`.

Packages:

- `AI_Sub_Pro_v1.3.5.dmg` is attached for macOS users, with a matching
  `AI_Sub_Pro_v1.3.5.dmg.sha256` checksum file and
  `release-size-report.json`.
- Local artifact size: 328 MB DMG / 816 MB app.

## v1.3.4 - UI Auto-Collapse and ASR Backend Selection

Highlights:

- The macOS sidebar now automatically collapses on long-page downward scroll
  and expands again near the top, while mobile layout remains unchanged.
- Settings now expose an explicit local ASR backend selector:
  `auto`, `mlx_whisper`, `faster_whisper`, or `openai_whisper`.
- The ASR pipeline now honors that backend setting. `auto` preserves the
  existing MLX -> faster-whisper -> openai-whisper fallback order; an explicit
  backend fails visibly instead of silently switching engines.
- System check recommendations now report the configured ASR backend and
  whether the selected local dependency is installed.

Quality/Verification:

- Full test suite passed: `1084 passed in 192.63s`.
- Focused UI/ASR/settings regression passed: `199 passed in 20.91s`.
- Runtime desktop check passed: settings-page scroll collapsed the sidebar
  from 220px to 72px, restored it at the top, and showed the ASR backend
  selector.
- Local DMG verification passed: `hdiutil verify dist/AI_Sub_Pro_v1.3.4.dmg`
  reported a valid checksum, and
  `shasum -a 256 -c AI_Sub_Pro_v1.3.4.dmg.sha256` passed from `dist/`.
- Local installed app verification passed: `/api/settings` reports app version
  `1.3.4` and ASR backend `auto`.

Packages:

- `AI_Sub_Pro_v1.3.4.dmg` is attached for macOS users, with a matching
  `AI_Sub_Pro_v1.3.4.dmg.sha256` checksum file and
  `release-size-report.json`.
- Local artifact size: 330 MB DMG / 816 MB app.

## v1.3.3 - Packaged ASR Backend Fix

Highlights:

- Fixed packaged macOS builds that could fail transcription with
  `No working ASR backend found` because the default package excluded every
  local Whisper backend module.
- macOS and Windows packaging now bundle installed ASR backend packages by
  default, while large Whisper model files remain opt-in via
  `AISUBPRO_BUNDLE_LOCAL_ASR=1`.
- Packaging now fails fast when ASR backend bundling is enabled but no local
  backend is installed, preventing broken ASR packages from being published.
- Added `requirements-asr.txt` and wired the release workflow to install it so
  release builds have a fallback ASR backend available.

Quality/Verification:

- Full test suite passed: `1053 passed in 60.24s`.
- Focused settings/package suite passed: `33 passed in 1.04s`.
- Packaging-only suite passed: `32 passed in 0.24s`.
- Local DMG verification passed: `hdiutil verify dist/AI_Sub_Pro_v1.3.3.dmg`
  reported a valid checksum, and
  `shasum -a 256 -c AI_Sub_Pro_v1.3.3.dmg.sha256` passed from `dist/`.
- Local installed app verification passed: `/api/settings` reports app version
  `1.3.3`, and `/api/system-check` reports `mlx_whisper: true`,
  `asr_recommendation.ready: true`, backend `mlx_whisper`, and model source
  `cache`.

Packages:

- `AI_Sub_Pro_v1.3.3.dmg` is attached for macOS users, with a matching
  `AI_Sub_Pro_v1.3.3.dmg.sha256` checksum file and
  `release-size-report.json`.
- The attached macOS package includes an installed ASR backend package. It does
  not bundle local Whisper model files; models download on first use or load
  from the normal local cache. Local artifact size: 328 MB DMG / 816 MB app.
- Windows packaging currently requires a Windows machine and `build_win.bat`;
  no prebuilt Windows installer is attached to this release.

## v1.3.1 - Settings Version Display Patch

Highlights:

- Added the current app version to the Settings > Storage / Release section so
  users can confirm which installed build is running.
- Added read-only `app_info` metadata to `GET /api/settings`, including app
  name and version.
- Prevented read-only app metadata from being persisted when saving settings,
  keeping user `config.json` focused on editable preferences.
- Centralized the backend FastAPI version on `app/version.py` so future release
  bumps update the UI and API from the same source.

Quality/Verification:

- Full test suite passed: `1052 passed in 72.45s`.
- Focused settings/package suite passed: `164 passed in 12.50s`.
- Local installed app verification passed: `/api/settings` returns
  `{"name": "AI Sub Pro", "version": "1.3.1"}` under `app_info`.

Packages:

- `AI_Sub_Pro_v1.3.1.dmg` is attached for macOS users, with a matching
  `AI_Sub_Pro_v1.3.1.dmg.sha256` checksum file and
  `release-size-report.json`.
- The attached macOS package is the base app build. It does not bundle local
  Whisper model files or optional ASR backend packages.
- Windows packaging currently requires a Windows machine and `build_win.bat`;
  no prebuilt Windows installer is attached to this release.

## v1.3.0 - Translation Accuracy Evaluation And Retrieval Upgrade

Highlights:

- Added a local subtitle A/B comparison CLI that writes JSON and Markdown
  accuracy reports for source, old output, new output, and optional reference
  subtitles.
- Added safer local bilingual corpus import for JSONL, TSV, and CSV files with
  required source, license, language-pair metadata, row limits, duplicate
  handling, and import summaries.
- Upgraded phrase library and translation memory retrieval with SQLite FTS5
  when available plus deterministic n-gram fallback, bounded scoring, backend
  trace metadata, and retrieval example limits.
- Added deterministic proper-name consistency checks for recurring source names
  and surfaced inferred inconsistencies in translation QA reports.
- Added conservative QA auto-repair rounds, capped at two attempts, with a
  guard that preserves existing translations when repair providers return
  partial responses.
- Documented the new local evaluation and corpus-import workflows in English
  and Simplified Chinese.

Quality/Verification:

- Full test suite passed: `1050 passed in 64.46s`.
- Focused translation-accuracy suite passed: `158 passed in 4.19s`.
- Local `Brilliant Minds` evaluation report generation passed and wrote
  `translation_accuracy_report.json` plus `translation_accuracy_report.md`
  under `/tmp/ai-sub-pro-brilliant-minds-quality`.

Packages:

- `AI_Sub_Pro_v1.3.0.dmg` is attached for macOS users, with a matching
  `AI_Sub_Pro_v1.3.0.dmg.sha256` checksum file and
  `release-size-report.json`.
- The attached `.sha256` file and `release-size-report.json` are generated
  from the same local macOS build as the attached DMG.
- The attached macOS package is the base app build. It does not bundle local
  Whisper model files or optional ASR backend packages.
- Windows packaging currently requires a Windows machine and `build_win.bat`;
  no prebuilt Windows installer is attached to this release.

## v1.2.2 - Expanded Phrase Library Packs

Highlights:

- Expanded bundled synthetic phrase packs from 3 packs / 60 examples to 12
  packs / 600+ examples.
- Added Spanish, French, and German starter packs to Simplified Chinese.
- Added English medical, crime/procedural, and workplace domain packs.
- Phrase retrieval now accepts preferred tags and lightly boosts matching
  domain examples inferred from project metadata before prompt injection.
- Phrase prompt snippets now include pack tags, and trace data preserves pack
  id and tag metadata.
- Added a local phrase-pack import CLI that requires source, license, and
  language-pair metadata by default for safer public-corpus ingestion.

Quality/Verification:

- Full test suite passed: `931 passed in 68.49s`.
- Added regression tests for generator drift, import-tool metadata validation,
  bundled pack scale, multilingual retrieval, domain tag boosting, and domain
  prompt injection.

Packages:

- `AI_Sub_Pro_v1.2.2.dmg` is attached for macOS users, with a matching
  `AI_Sub_Pro_v1.2.2.dmg.sha256` checksum file and
  `release-size-report.json`.
- The attached `.sha256` file and `release-size-report.json` are generated
  from the same GitHub Actions build as the attached DMG.
- The attached macOS package is the base app build. It does not bundle local
  Whisper model files or optional ASR backend packages.
- Windows packaging currently requires a Windows machine and `build_win.bat`;
  no prebuilt Windows installer is attached to this release.

## v1.2.1 - Bundled Colloquial Packs And Translation Completion Fixes

Highlights:

- Added bundled synthetic subtitle phrase starter packs for English, Japanese,
  and Korean to Simplified Chinese.
- App startup now imports bundled phrase packs into the local SQLite phrase
  library once per pack version, so packaged builds get the examples without a
  manual setup step.
- Phrase pack imports now preserve pack id, version, tags, source, and license
  metadata while avoiding duplicate rows across repeated startups.
- Project detail/list reads now overlay live scheduler progress while a
  workflow is running, so frontend polling does not regress to stale
  `project.json` progress.
- Translation completion accounting now ignores blank sound-description rows
  such as `[Music]` and persists final progress/status fields when translation
  finishes.

Quality/Verification:

- Full test suite passed: `926 passed in 54.80s`.
- Added regression tests for pack idempotency, newer-version imports, bundled
  pack discovery, Japanese/Korean retrieval tokenization, and prompt injection.
- Added integration coverage for blank sound-description completion handling
  and runtime progress merging.

Packages:

- `AI_Sub_Pro_v1.2.1.dmg` is attached for macOS users, with a matching
  `AI_Sub_Pro_v1.2.1.dmg.sha256` checksum file and
  `release-size-report.json`.
- The attached `.sha256` file and `release-size-report.json` are generated
  from the same GitHub Actions build as the attached DMG.
- The attached macOS package is the base app build. It does not bundle local
  Whisper model files or optional ASR backend packages.
- Windows packaging currently requires a Windows machine and `build_win.bat`;
  no prebuilt Windows installer is attached to this release.

## v1.2.0 - Quality, Workflow, Editor, And Release Pipeline

This release publishes the v2 upgrade work as a packaged macOS build. It adds
deterministic quality evaluation, Knowledge Base review tooling, ASR intent
modes, recoverable long-running workflows, professional subtitle editing, and a
repeatable release pipeline.

Highlights:

- Added subtitle editor quality checks, merge, bulk find/replace, export
  warnings, keyboard-friendly controls, and a timeline strip for quicker review.
- Added project list filters, grouped settings anchors, and more specific
  provider/ASR/export/network error next-action text.
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
- Aggregate v2 merge verification passed: `902 passed in 104.00s`.
- Release branch verification passed: `903 passed in 118.10s`.
- Packaging script checks passed: `31 passed in 0.16s`.
- Local v1.2.0 DMG build passed with `AISUBPRO_BUNDLE_LOCAL_ASR=0`, and
  `hdiutil verify dist/AI_Sub_Pro_v1.2.0.dmg` reported a valid checksum.
- Release dry-run validation passed on GitHub Actions before the v2 merge.

Packages:

- `AI_Sub_Pro_v1.2.0.dmg` is attached for macOS users, with a matching
  `AI_Sub_Pro_v1.2.0.dmg.sha256` checksum file and
  `release-size-report.json`.
- Local release artifact verification recorded SHA256
  `e076b9776cccdcaf04051d863457b9d401addf6ea14417a265b55b31b97ac253` and
  size `88,518,339` bytes before tagging.
- The attached macOS package is the base app build. It does not bundle local
  Whisper model files or optional ASR backend packages.
- Windows packaging currently requires a Windows machine and `build_win.bat`;
  no prebuilt Windows installer is attached to this release.

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
