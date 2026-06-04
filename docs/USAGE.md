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
- Translation memory and local phrase-library retrieval.
- Optional post-translation QA auto-repair.
- TMDB API key for trailer search.

## Process a Local Video

1. Drag a video into the home screen or paste a local video path.
2. Confirm ASR source language and target subtitle language.
3. Click **Start** or open the project and use **One-click process**.
4. Review source and translated subtitle rows in the editor.
5. Export translated, bilingual, or original `.srt` files.
6. Burn subtitles into a video when `ffmpeg` is available.

If the video already has a text subtitle track, AI Sub Pro can skip ASR and
use the embedded subtitle as the source timeline.

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

## Translation Quality Loop

AI Sub Pro can automatically improve translation consistency around the editor
workflow:

- **Automatic KB suggestions** inspect project metadata and subtitle text to
  propose character, place, organization, title, phrase, and style entries.
  Suggestions are stored in the project directory as `kb_suggestions.json` until
  you accept or reject them.
- **Translation memory** learns from subtitle edits you save in the editor. The
  original source line, machine draft, and final user-approved translation stay
  in a local SQLite database and are retrieved before future translations.
- **Local phrase library retrieval** can use phrase examples that you import
  locally. Public corpora such as OpenSubtitles or Tatoeba should be imported
  only when their license/source metadata is preserved.
- **QA reports** are written after translation as
  `translation_qa_report.json` and `translation_qa_report.md` in the project
  directory. The deterministic checks cover missing translations, English
  residue, duplicate IDs, KB term misses, long subtitles, and sound-description
  handling.
- **Auto-repair** is optional. When enabled in Settings, the app sends only the
  failed subtitle rows back to the selected provider for a targeted repair pass.

Run the deterministic evaluation corpus locally:

```bash
python3 -m app.evaluation.cli \
  --corpus tests/fixtures/golden_corpus/translation_quality_loop.json \
  --format markdown
```

The default evaluation command uses stored fixture outputs and does not call a
paid or network translation provider.

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
contracts, project-store safety, translation QA, evaluation metrics, and
frontend JavaScript behavior.

## Troubleshooting

- **Port already in use**: stop the existing AI Sub Pro process on `127.0.0.1:18090`.
- **No media features**: verify `ffmpeg` and `ffprobe` are on `PATH`.
- **Translation fails**: confirm the selected provider is configured and logged in.
- **ASR is slow on first run**: local Whisper models may need to download.
- **Burn-in fails**: use an `ffmpeg` build with subtitle rendering support.
