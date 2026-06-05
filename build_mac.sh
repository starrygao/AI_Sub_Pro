#!/bin/bash
# Build AI Sub Pro macOS .app bundle
# Uses pywebview for native window (NOT browser)
set -e
cd "$(dirname "$0")"
ROOT_DIR="$(pwd)"

echo "=== AI Sub Pro macOS Build ==="
echo ""

# Step 1: Check deps
echo "[1/4] Checking dependencies..."
python3 -c "import PyInstaller" 2>/dev/null || { echo "ERROR: pip3 install pyinstaller"; exit 1; }
python3 -c "import webview" 2>/dev/null || { echo "ERROR: pip3 install pywebview"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm not found. Install Node.js and run: npm install"; exit 1; }
FFMPEG_CANDIDATES=(
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg"
    "$(command -v ffmpeg || true)"
)
FFMPEG_PATH=""
for candidate in "${FFMPEG_CANDIDATES[@]}"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ] && "$candidate" -hide_banner -filters 2>/dev/null | grep -q " subtitles "; then
        FFMPEG_PATH="$candidate"
        break
    fi
done
if [ -z "$FFMPEG_PATH" ]; then
    echo "ERROR: ffmpeg with subtitles filter not found"
    echo "Install a subtitle-capable build, for example: brew install ffmpeg-full"
    exit 1
fi
FFPROBE_PATH="$(dirname "$FFMPEG_PATH")/ffprobe"
if [ ! -x "$FFPROBE_PATH" ]; then
    FFPROBE_PATH=$(which ffprobe) || { echo "ERROR: ffprobe not found"; exit 1; }
fi
echo "  ffmpeg:  $FFMPEG_PATH"
echo "  ffprobe: $FFPROBE_PATH"

BUNDLE_LOCAL_ASR="${AISUBPRO_BUNDLE_LOCAL_ASR:-0}"
BUNDLE_ASR_BACKENDS="${AISUBPRO_BUNDLE_ASR_BACKENDS:-1}"
REQUIRE_ASR_BACKEND="${AISUBPRO_REQUIRE_ASR_BACKEND:-1}"
if [ "$BUNDLE_LOCAL_ASR" = "1" ]; then
    BUNDLE_ASR_BACKENDS="1"
fi
ASR_MODEL_DATA_ARGS=()
ASR_BACKEND_ARGS=()
LOCAL_ASR_EXCLUDE_ARGS=()
ASR_BACKEND_FOUND=0
if [ "$BUNDLE_LOCAL_ASR" = "1" ]; then
    if [ -d "$ROOT_DIR/models/asr" ]; then
        ASR_MODEL_DATA_ARGS+=(--add-data "${ROOT_DIR}/models/asr:models/asr")
        echo "  bundled ASR models: $ROOT_DIR/models/asr"
    else
        echo "  bundled ASR models: none found under models/asr"
    fi
else
    echo "  bundled ASR models: disabled (set AISUBPRO_BUNDLE_LOCAL_ASR=1 to include models/asr)"
fi

if [ "$BUNDLE_ASR_BACKENDS" = "1" ]; then
    echo "  Local ASR backends: enabled (set AISUBPRO_BUNDLE_ASR_BACKENDS=0 to build without ASR backends)"
    if python3 -c "import faster_whisper" 2>/dev/null; then
        ASR_BACKEND_ARGS+=(--hidden-import faster_whisper --collect-all faster_whisper)
        ASR_BACKEND_FOUND=1
        echo "  faster-whisper: available (will be bundled)"
    else
        echo "  faster-whisper: not installed (optional backend skipped)"
    fi
    if python3 -c "import mlx_whisper" 2>/dev/null; then
        ASR_BACKEND_ARGS+=(--hidden-import mlx_whisper --collect-all mlx --collect-all mlx_whisper)
        ASR_BACKEND_FOUND=1
        echo "  mlx-whisper: available (will be bundled)"
    else
        echo "  mlx-whisper: not installed (optional backend skipped)"
    fi
    if python3 -c "import whisper" 2>/dev/null; then
        ASR_BACKEND_ARGS+=(--hidden-import whisper)
        ASR_BACKEND_FOUND=1
        echo "  openai-whisper: available (will be bundled)"
    else
        echo "  openai-whisper: not installed (optional backend skipped)"
    fi

    if [ "$ASR_BACKEND_FOUND" = "0" ]; then
        if [ "$REQUIRE_ASR_BACKEND" = "1" ]; then
            echo "ERROR: no local ASR backend installed to bundle"
            echo "Install one first, for example: python3 -m pip install -r requirements-asr.txt"
            echo "Or set AISUBPRO_BUNDLE_ASR_BACKENDS=0 to intentionally build without ASR."
            exit 1
        else
            echo "  Local ASR backends: none installed (continuing because AISUBPRO_REQUIRE_ASR_BACKEND=0)"
        fi
    fi
else
    LOCAL_ASR_EXCLUDE_ARGS=(
        --exclude-module torch
        --exclude-module torchaudio
        --exclude-module torchvision
        --exclude-module whisper
        --exclude-module faster_whisper
        --exclude-module mlx
        --exclude-module mlx_whisper
        --exclude-module ctranslate2
    )
    echo "  Local ASR backends: disabled (set AISUBPRO_BUNDLE_ASR_BACKENDS=1 to bundle installed ASR backends)"
fi

# Step 2: Frontend assets
echo ""
echo "[2/4] Building frontend assets..."
npm run build:css

# Step 3: Clean
echo ""
echo "[3/4] Cleaning previous build..."
clean_build_dir() {
    local path="$1"
    rm -rf "$path" 2>/dev/null || true
    if [ -d "$path" ]; then
        # macOS can recreate .DS_Store while Finder is looking at dist; do not
        # let that abort the build before PyInstaller gets a clean target.
        rm -rf "$path"/* "$path"/.[!.]* "$path"/..?* 2>/dev/null || true
        rmdir "$path" 2>/dev/null || true
    fi
}
clean_build_dir build
clean_build_dir dist
SPEC_DIR="build/spec"
mkdir -p "$SPEC_DIR"

# Step 4: PyInstaller
echo ""
echo "[4/4] Building with PyInstaller..."
python3 -m PyInstaller \
    --name "AI Sub Pro" \
    --windowed \
    --noconfirm \
    --clean \
    --specpath "$SPEC_DIR" \
    --add-data "${ROOT_DIR}/app/static:app/static" \
    --add-data "${ROOT_DIR}/app:app" \
    "${ASR_MODEL_DATA_ARGS[@]}" \
    --add-binary "${FFMPEG_PATH}:bin" \
    --add-binary "${FFPROBE_PATH}:bin" \
    --hidden-import uvicorn \
    --hidden-import uvicorn.logging \
    --hidden-import uvicorn.loops \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols \
    --hidden-import uvicorn.protocols.http \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets \
    --hidden-import uvicorn.protocols.websockets.auto \
    --hidden-import uvicorn.protocols.websockets.websockets_sansio_impl \
    --hidden-import uvicorn.lifespan \
    --hidden-import uvicorn.lifespan.on \
    --hidden-import fastapi \
    --hidden-import pydantic \
    --hidden-import starlette \
    --hidden-import starlette.routing \
    --hidden-import starlette.middleware \
    --hidden-import starlette.middleware.cors \
    --hidden-import starlette.responses \
    --hidden-import starlette.staticfiles \
    --hidden-import starlette.websockets \
    --hidden-import openai \
    --hidden-import httpx \
    --hidden-import anyio \
    --hidden-import anyio._backends \
    --hidden-import anyio._backends._asyncio \
    --hidden-import h11 \
    --hidden-import websockets \
    --hidden-import webview \
    --hidden-import webview.platforms.cocoa \
    "${ASR_BACKEND_ARGS[@]}" \
    --hidden-import yt_dlp \
    --hidden-import yt_dlp.utils \
    --hidden-import yt_dlp.extractor \
    --hidden-import yt_dlp_ejs \
    --hidden-import guessit \
    --hidden-import babelfish \
    --hidden-import rebulk \
    --collect-all guessit \
    --collect-all babelfish \
    --hidden-import brotli \
    --hidden-import Cryptodome \
    --hidden-import mutagen \
    --hidden-import certifi \
    --exclude-module pytest \
    --exclude-module guessit.test \
    --exclude-module guessit.test.rules \
    --exclude-module guessit.test.rules.processors_test \
    --exclude-module guessit.test.test_api \
    --exclude-module guessit.test.test_api_unicode_literals \
    --exclude-module guessit.test.test_benchmark \
    --exclude-module guessit.test.test_main \
    --exclude-module guessit.test.test_options \
    --exclude-module guessit.test.test_yml \
    --exclude-module tensorboard \
    --exclude-module torch.utils.tensorboard \
    "${LOCAL_ASR_EXCLUDE_ARGS[@]}" \
    --exclude-module webview.platforms.android \
    --exclude-module webview.platforms.win32 \
    --exclude-module webview.platforms.winforms \
    --exclude-module webview.platforms.edgechromium \
    --exclude-module webview.platforms.mshtml \
    --exclude-module webview.platforms.gtk \
    --exclude-module webview.platforms.qt \
    --exclude-module webview.platforms.cef \
    --exclude-module urllib3.contrib.emscripten \
    app/main.py

# No launcher needed - main.py handles pywebview native window directly

echo ""
echo "=== Build Complete! ==="
APP_SIZE=$(du -sh "dist/AI Sub Pro.app" | awk '{print $1}')
echo "  Output: dist/AI Sub Pro.app ($APP_SIZE)"
echo "  Run:    open 'dist/AI Sub Pro.app'"
echo ""
echo "  Note: ASR backends are bundled by default when installed."
echo "        Set AISUBPRO_BUNDLE_LOCAL_ASR=1 to bundle local ASR models."
echo "  Data is stored at: ~/AI_Sub_Pro_Data/"
