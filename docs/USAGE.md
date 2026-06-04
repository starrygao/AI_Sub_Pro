# Usage Guide

Language: [English](USAGE.md) | [简体中文](USAGE.zh-CN.md)

AI Sub Pro runs locally and keeps project files, API keys, subtitle exports,
and knowledge-base data on the user's machine.

## Prebuilt Packages

Prebuilt packages are attached to GitHub Releases when available.

- macOS users can download all `AI_Sub_Pro_v1.1.1.dmg.part-*` assets
  (`part-aa` through `part-ar`) from the `v1.1.1` release, join them with
  `cat AI_Sub_Pro_v1.1.1.dmg.part-* > AI_Sub_Pro_v1.1.1.dmg`, open the DMG,
  drag **AI Sub Pro** into **Applications**, then right-click and choose **Open**
  on first launch if Gatekeeper blocks an unsigned build.
- Windows users can run a published Windows package when available. The current
  release does not include a prebuilt Windows installer yet; build from source
  on a Windows machine with `build_win.bat`.

Default packages are base-app builds. They do not include local Whisper model
files or optional ASR backend packages. Offline-oriented packages must be built
explicitly with `AISUBPRO_BUNDLE_LOCAL_ASR=1` and should be labeled as optional
ASR packages in the release notes.

## Install

Requirements:

- Python 3.10 or newer.
- Node.js 18 or newer.
- `ffmpeg` and `ffprobe` on `PATH`.
- Optional ASR backend: `mlx-whisper`, `faster-whisper`, or `openai-whisper`.

```bash
git clone https://github.com/<your-user>/AI_Sub_Pro.git
cd AI_Sub_Pro

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

npm install
npm run build:css
```

## Run

```bash
./start.sh
```

Open `http://127.0.0.1:18090` if the browser does not open automatically.

Backend-only mode:

```bash
python3 app/main.py --headless
```

Electron shell:

```bash
cd electron
npm install
npm run start
```

## Configure Providers

Open **Settings** in the app and configure one translation provider:

- OpenAI-compatible API key and model.
- Claude CLI, if `claude` is installed and logged in locally.
- Codex CLI, if `codex` is installed and logged in locally.

You can also configure:

- Display language: follow system, Simplified Chinese, or English.
- Whisper model and source language.
- Target subtitle language.
- Translation batch size and context window.
- Repetition and interjection filters.
- TMDB API key for trailer search.

## ASR Modes

The ASR mode expresses intent rather than naming one fixed backend:

- **Speed first** chooses the fastest available local backend. On Apple
  Silicon this is usually `mlx-whisper` with `large-v3-turbo`.
- **Accuracy first** prefers a larger model and a backend with VAD or beam
  search support when available.
- **Offline first** prefers bundled or cached models and reports when a model
  download is required.

`/api/system-check` reports detected ASR backends, model cache status, and the
current backend/model recommendation. Tests simulate these checks without
downloading models.

For source builds, optional ASR backends can be installed in the local Python
environment. For packaged builds, those optional local ASR packages and
`models/asr` are bundled only when the package maintainer sets
`AISUBPRO_BUNDLE_LOCAL_ASR=1`; otherwise models may download on first use or be
read from the normal local cache.

## Process a Local Video

1. Drag a video into the home screen or paste a local video path.
2. Confirm ASR source language and target subtitle language.
3. Click **Start** or open the project and use **One-click process**.
4. Review source and translated subtitle rows in the editor.
5. Export translated, bilingual, or original `.srt` files.
6. Burn subtitles into a video when `ffmpeg` is available.

If the video already has a text subtitle track, AI Sub Pro can skip ASR and
use the embedded subtitle as the source timeline.

## Workflow Recovery

Long-running workflows write structured progress to `workflow_state.json` in
the project runtime data. The state records each stage, bounded per-stage logs,
the failing stage when a workflow stops, and the last verified artifact that can
be used for recovery.

The project page can show the failing stage, download the captured logs, retry a
failed stage, or resume processing from the last verified artifact. Retry and
resume use the same per-task locks as normal processing, so only one workflow
operation can run for a project at a time.

## Trailer Workflow

Use **Trailer translation** on the home screen to create projects from TMDB and
YouTube metadata.

1. Search by title or TMDB ID.
2. Select the matching movie, show, season, or trailer.
3. Let the app download metadata and trailer media through `yt-dlp`.
4. Review, translate, export, and burn subtitles like a normal project.

## Knowledge Base

The knowledge-base view stores local rules for consistent translations:

- Character names.
- Places and organizations.
- Brand names.
- Slang and recurring phrases.
- Project-level style rules.

The translator uses these entries as context while processing subtitle batches.
Project pages can also scan TMDB metadata and the current subtitles for
suggested knowledge-base entries. Review each suggestion, edit the preferred
translation or note, then accept selected entries into the project KB or reject
entries that should not be suggested again.

After translation, the project Knowledge Base panel can show the latest usage
trace when trace data is available. The trace explains which KB entries matched
the source subtitles and were included during translation.

## Data Locations

Development mode stores runtime data under `./data`.

Packaged builds store runtime data under the user's application data directory.
Override the runtime directory with:

```bash
export AI_SUB_PRO_DATA_DIR=/absolute/path/to/runtime-data
```

Do not commit runtime data, API keys, generated media, or model caches.

## Test

```bash
pytest
```

The test suite covers API routes, scheduling, subtitle parsing, provider
contracts, project-store safety, and frontend JavaScript behavior.

## Translation Quality Evaluation

Run the deterministic golden-corpus evaluation after changing translator,
provider, or knowledge-base behavior:

```bash
mkdir -p build/evaluation
python3 -m app.evaluation.cli --corpus tests/fixtures/golden_corpus/milestone1.json --json-out build/evaluation/milestone1.json --markdown-out build/evaluation/milestone1.md
```

The default milestone corpus uses checked-in candidate outputs and does not
call network services or paid translation providers. Reports include
terminology coverage, row alignment, missing translations, format preservation,
and manual scoring placeholders for reviewer notes.

## Troubleshooting

- **Port already in use**: stop the existing AI Sub Pro process on `127.0.0.1:18090`.
- **No media features**: verify `ffmpeg` and `ffprobe` are on `PATH`.
- **Translation fails**: confirm the selected provider is configured and logged in.
- **ASR is slow on first run**: local Whisper models may need to download.
- **Burn-in fails**: use an `ffmpeg` build with subtitle rendering support.
