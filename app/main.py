"""
AI Sub Pro - FastAPI application entry point.
"""
import os
import sys
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Path as PathParam
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse


def _log_dir_for_env() -> Path:
    raw_data_dir = os.environ.get("AI_SUB_PRO_DATA_DIR", "").strip()
    if raw_data_dir:
        return Path(raw_data_dir).expanduser()
    return Path.home() / "AI_Sub_Pro_Data"


# Setup logging - also write to file
_log_dir = _log_dir_for_env()
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / "app.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(_log_file), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# Fix import paths
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config
from app.utils.media import check_ffmpeg
from app.utils.project_store import PID_PATTERN, project_dir
from app.engines.scheduler import get_progress as get_scheduler_progress
from app.api.projects import router as projects_router
from app.api.translate import router as translate_router
from app.api.settings import router as settings_router
from app.api.trailer import router as trailer_router
from app.api.knowledge import router as knowledge_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    _run_startup()
    yield


# Create FastAPI app
app = FastAPI(title="AI Sub Pro", version="1.2.0", lifespan=lifespan)


def _cors_origins() -> list[str]:
    raw = os.environ.get("AISUBPRO_CORS_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# CORS - same-origin UI normally needs none; allow only loopback browser origins
# by default so arbitrary websites cannot read/write the local API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(projects_router)
app.include_router(translate_router)
app.include_router(settings_router)
app.include_router(trailer_router)
app.include_router(knowledge_router)


def _extend_path_for_macos_bundle():
    """When launched from a .app bundle via Finder/launchd, PATH is minimal (no /opt/homebrew/bin etc).
    Pull in the user's shell PATH so bundled subprocess calls (claude CLI, system tools) work."""
    if sys.platform != "darwin":
        return
    # Add common install paths first (cheap, always safe)
    home = os.path.expanduser("~")
    candidates = [
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/local/sbin",
        f"{home}/.local/bin",
        f"{home}/.npm-global/bin",
        f"{home}/bin",
    ]
    current = os.environ.get("PATH", "")
    existing = set(current.split(os.pathsep))
    added = []
    for p in candidates:
        if p and os.path.isdir(p) and p not in existing:
            added.append(p)
            existing.add(p)
    # Also try to inherit the user's actual interactive shell PATH (covers nvm, pyenv, etc.)
    try:
        import subprocess
        shell = os.environ.get("SHELL", "/bin/zsh")
        r = subprocess.run([shell, "-l", "-i", "-c", "echo $PATH"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            for p in r.stdout.strip().split(os.pathsep):
                if p and os.path.isdir(p) and p not in existing:
                    added.append(p)
                    existing.add(p)
    except Exception as e:
        log.debug("shell PATH probe failed: %s", e)
    if added:
        os.environ["PATH"] = os.pathsep.join(added) + os.pathsep + current
        log.info("Extended PATH with %d dirs (e.g. %s)", len(added), added[0])


def _run_startup():
    Config.load()
    # Extend PATH to find user-installed tools (claude CLI, homebrew tools) when
    # the app was launched from a .app bundle (which runs with a minimal PATH).
    _extend_path_for_macos_bundle()
    # Add bundled ffmpeg/ffprobe to PATH so third-party libs (mlx_whisper etc.) can find them
    from app.utils.media import get_ffmpeg_path
    ffmpeg_dir = os.path.dirname(get_ffmpeg_path())
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        log.info("Added to PATH: %s", ffmpeg_dir)
    if not check_ffmpeg():
        log.warning("ffmpeg/ffprobe not found! Media features will not work.")
    log.info("AI Sub Pro started on http://127.0.0.1:18090")
    from app.engines.scheduler import load_progress_store_from_disk
    restored = load_progress_store_from_disk()
    log.info("restored progress for %d projects from disk", restored)


# WebSocket for real-time progress
@app.websocket("/ws/progress/{project_id}")
async def ws_progress(websocket: WebSocket, project_id: str):
    await websocket.accept()
    last_msg = None
    try:
        while True:
            current = get_scheduler_progress(project_id) or {}
            current_str = json.dumps(current)
            if current_str != last_msg:
                await websocket.send_json(current)
                last_msg = current_str
            await _wait_for_progress_client_activity(websocket)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _wait_for_progress_client_activity(websocket: WebSocket, timeout: float = 0.5):
    try:
        await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
    except asyncio.TimeoutError:
        pass


# Download output video
@app.get("/api/projects/{pid}/download-video")
def download_video(pid: str = PathParam(pattern=PID_PATTERN)):
    from app.api.projects import _apply_safe_defaults
    try:
        pdir = project_dir(pid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid project id") from exc
    pfile = pdir / "project.json"
    if not pfile.exists():
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        with open(pfile, "r", encoding="utf-8") as f:
            raw_project = json.load(f)
        if not isinstance(raw_project, dict):
            raise ValueError("project.json must contain an object")
        project = _apply_safe_defaults(raw_project)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("Invalid project file for download %s: %s", pid, exc)
        raise HTTPException(status_code=400, detail="Project file is invalid") from exc
    output_video = project.get("output_video", "")
    if output_video:
        raw_output_path = Path(output_video)
        output_path = (pdir / raw_output_path if not raw_output_path.is_absolute() else raw_output_path).resolve()
        try:
            output_path.relative_to(pdir)
        except ValueError:
            log.warning("Blocked download outside project dir for %s: %s", pid, output_path)
            output_path = None
    else:
        output_path = None
    if output_path and output_path.exists() and output_path.is_file():
        return FileResponse(
            str(output_path),
            media_type="video/mp4",
            filename=output_path.name,
        )
    raise HTTPException(status_code=404, detail="No output video available")


# Serve static files - handle both dev and PyInstaller bundled paths
def _find_static_dir() -> Path:
    """Find static directory in dev mode or PyInstaller bundle."""
    candidates = [
        Path(__file__).parent / "static",                          # dev: app/static
    ]
    # PyInstaller bundle: check _MEIPASS
    if getattr(sys, '_MEIPASS', None):
        meipass = Path(sys._MEIPASS)
        candidates.insert(0, meipass / "app" / "static")           # bundled: _internal/app/static
        candidates.insert(1, meipass / "static")
    for c in candidates:
        if c.exists() and (c / "index.html").exists():
            log.info("Static dir found: %s", c)
            return c
    log.warning("Static dir NOT found, tried: %s", [str(c) for c in candidates])
    return candidates[0]  # fallback

static_dir = _find_static_dir()

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return "<h1>AI Sub Pro</h1><p>Frontend not found. Static dir: " + str(static_dir) + "</p>"

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _graceful_shutdown_timeout() -> int:
    raw = os.environ.get("AISUBPRO_GRACEFUL_SHUTDOWN_TIMEOUT", "").strip()
    if not raw:
        return 3
    try:
        value = int(raw)
    except ValueError:
        log.warning("Invalid AISUBPRO_GRACEFUL_SHUTDOWN_TIMEOUT=%r; using 3 seconds", raw)
        return 3
    return max(1, min(value, 60))


def _uvicorn_run_kwargs(host: str, *, log_level: str = "info") -> dict:
    return {
        "host": host,
        "port": 18090,
        "log_level": log_level,
        "ws": "websockets-sansio",
        "timeout_graceful_shutdown": _graceful_shutdown_timeout(),
    }


def _start_server():
    """Start uvicorn in a background thread."""
    import uvicorn
    uvicorn.run(app, **_uvicorn_run_kwargs("127.0.0.1", log_level="info"))


def _headless_host() -> str:
    return os.environ.get("AISUBPRO_HOST", "").strip() or "127.0.0.1"


def _local_server_ready(timeout: float = 1.0) -> bool:
    import urllib.request

    try:
        response = urllib.request.urlopen("http://127.0.0.1:18090/", timeout=timeout)
        try:
            status = getattr(response, "status", 200)
            return 200 <= status < 500
        finally:
            response.close()
    except Exception:
        return False


if __name__ == "__main__":
    import threading
    import time

    # Check if running in headless / CLI mode
    headless = "--headless" in sys.argv or os.environ.get("AISUBPRO_HEADLESS")

    if headless:
        # CLI mode: just run uvicorn directly
        import uvicorn
        uvicorn.run(app, **_uvicorn_run_kwargs(_headless_host()))
    else:
        # Desktop mode: native window via pywebview
        server_thread = None
        server_ready = _local_server_ready()
        if not server_ready:
            server_thread = threading.Thread(target=_start_server, daemon=True)
            server_thread.start()

            # Wait for server to be ready before opening a native window.
            for _ in range(30):
                if _local_server_ready(timeout=0.5):
                    server_ready = True
                    break
                time.sleep(0.5)

        if not server_ready:
            log.error("AI Sub Pro server did not become ready at http://127.0.0.1:18090")
            sys.exit(1)

        try:
            import webview

            # Expose native APIs to JS
            class API:
                def select_video(self):
                    """Open native file picker for video files."""
                    result = window.create_file_dialog(
                        webview.OPEN_DIALOG,
                        file_types=(
                            "Video Files (*.mp4;*.mkv;*.avi;*.mov;*.wmv;*.flv;*.webm)",
                            "All Files (*.*)",
                        ),
                    )
                    if result and len(result) > 0:
                        return result[0]
                    return None

                def open_url(self, url):
                    """Open URL in system default browser."""
                    import webbrowser
                    webbrowser.open(url)

            api = API()
            window = webview.create_window(
                "AI Sub Pro",
                url="http://127.0.0.1:18090",
                width=1280,
                height=820,
                min_size=(900, 600),
                js_api=api,
                text_select=True,
            )
            webview.start(debug=False)
        except ImportError:
            # pywebview not available, fall back to browser
            log.warning("pywebview not installed, opening in browser")
            import webbrowser
            webbrowser.open("http://127.0.0.1:18090")
            if server_thread is not None:
                server_thread.join()
