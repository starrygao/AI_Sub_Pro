# AI Sub Pro

Language: [English](README.md) | [简体中文](README.zh-CN.md)

AI Sub Pro is a local-first desktop and web tool for AI-assisted subtitle
workflows. It helps transcribe video audio, translate subtitles, edit subtitle
tracks, build bilingual output, and create trailer projects from TMDB and
YouTube metadata.

The app runs a local FastAPI backend with a browser or Electron/pywebview
frontend. Runtime data stays on the user's machine.

![AI Sub Pro home screen](docs/assets/ai-sub-pro-home.png)

## Documentation

- [Usage guide](docs/USAGE.md): install, configure, run, and export subtitles.
- [Demo and screenshots](docs/DEMO.md): visual tour of the main workflows.
- [Release notes](docs/RELEASE_NOTES.md): current public release summary.

## Features

- Upload local video files and manage project state locally.
- Extract embedded subtitle tracks when available.
- Transcribe audio with local Whisper backends: `mlx-whisper`,
  `faster-whisper`, or `openai-whisper`.
- Translate and polish subtitles with OpenAI-compatible providers, Claude CLI,
  or Codex CLI.
- Maintain a local knowledge base for names, terms, style rules, and glossary
  context.
- Search TMDB, download trailers with `yt-dlp`, and generate trailer
  translation projects.
- Export raw, filtered, translated, and bilingual `.srt` files.
- Burn subtitles into video output with `ffmpeg`.
- Run as a local web app, Electron shell, or packaged macOS/Windows build.

## Requirements

- Python 3.10 or newer.
- Node.js 18 or newer.
- `ffmpeg` and `ffprobe` on `PATH`.
- A subtitle-capable ffmpeg build is required for burn-in output.

Optional ASR backends:

- Apple Silicon: `mlx-whisper`.
- Cross-platform VAD and beam search: `faster-whisper`.
- Fallback: `openai-whisper`.

## Quick Start

```bash
git clone https://github.com/starrygao/AI_Sub_Pro.git
cd AI_Sub_Pro

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

npm install
npm run build:css

./start.sh
```

Open `http://127.0.0.1:18090` if the browser does not open automatically.

See the [usage guide](docs/USAGE.md) for provider setup, trailer projects,
knowledge-base workflows, exports, and troubleshooting.

For backend-only development:

```bash
python3 app/main.py --headless
```

For the Electron shell:

```bash
cd electron
npm install
npm run start
```

## Configuration

Settings are managed from the app UI. API keys and runtime state are written
to the local data directory and must not be committed.

In development mode, data is stored under `./data`. Packaged builds store data
under the user's application data directory. Override the data location with:

```bash
export AI_SUB_PRO_DATA_DIR=/absolute/path/to/runtime-data
```

Useful environment variables are documented in `.env.example`.

## Testing

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
npm install
npm run build:css
pytest
```

The tests include API, scheduling, subtitle parsing, provider behavior, project
store safety, and frontend JavaScript coverage.

## Packaging

macOS:

```bash
bash build_mac.sh
bash make_dmg.sh
```

Windows:

```bat
build_win.bat
```

Packaging scripts expect local toolchains and a working `ffmpeg`/`ffprobe`.
Large ASR model files are intentionally not checked in. Use
`AISUBPRO_ASR_MODEL_DIR` or `models/asr` locally when bundling offline models.

## Privacy and Safety

AI Sub Pro is intended to run on localhost. User videos, subtitles, generated
audio, project metadata, API keys, and knowledge-base data are local runtime
data. The repository intentionally excludes `data/`, `build/`, `dist/`, logs,
and model caches.

Before publishing a fork or release, scan for secrets and avoid committing
sample media from real projects.

## License

MIT. See `LICENSE`.
