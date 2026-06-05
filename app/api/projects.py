"""
Project management API routes.
"""
import os
import json
import math
import uuid
import shutil
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel, StrictInt

from app.config import PROJECTS_DIR
from app.engines.workflow_state import load_workflow_state, stage_log_path
from app.utils.project_store import (
    project_dir as _ps_project_dir,
    load_project as _ps_load_project,
    mutate_project,
    atomic_write_json,
    PID_PATTERN,
)
from app.utils.media import get_tracks, get_duration, get_media_info, is_text_subtitle_codec
from app.utils.srt import fmt_time, parse_srt_file, parse_time_strict, write_srt, write_bilingual_srt, SubtitleBlock

router = APIRouter(prefix="/api/projects", tags=["projects"])
log = logging.getLogger(__name__)

# Cap on /upload payload size. 8 GiB is comfortably above any realistic
# trailer/movie a user would actually upload through the web UI, while
# preventing a single POST from filling the disk. Tests monkeypatch this
# to a lower value to exercise the rejection path without writing GBs.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024
_VIDEO_UPLOAD_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts", ".m4v"}


_PROJECT_SAFE_DEFAULTS = {
    "source_type": "upload",
    "auto_run": False,
    "tmdb_id": None,
    "tmdb_type": None,
    "season_number": None,
    "tmdb_video_key": None,
    "youtube_url": None,
    "original_language": None,
    "parent_project_id": None,
    "pipeline_stage": None,
    "archived": False,
    "prefer_embedded_subtitle": True,
    "tmdb_candidates": None,
    "show_title": None,
    "poster_path": None,
    "asr_skipped": False,
    "asr_language": "auto",
    "target_language": "简体中文",
    "error": None,
}


_TARGET_LANG_TO_ISO = {
    "简体中文": {"zh", "chi", "zho", "cmn", "chs"},
    "繁體中文": {"zh", "chi", "zho", "cht"},
    "繁体中文": {"zh", "chi", "zho", "cht"},
    "English": {"en", "eng"},
    "日本語": {"ja", "jpn"},
    "Japanese": {"ja", "jpn"},
    "日语": {"ja", "jpn"},
    "한국어": {"ko", "kor"},
}


def _json_safe_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    return value


def _pick_subtitle_track(tracks: list, target_language: str) -> Optional[int]:
    """Pick the best embedded subtitle track to bypass ASR.

    Returns the 0-based index into `tracks` (the list returned by
    `get_tracks(path, 's')` — i.e. all subtitle streams in the input
    file). This index is suitable for ffmpeg's `-map 0:s:N` selector.
    The frontend must NOT pre-filter `subtitle_tracks` before indexing —
    use the raw list, otherwise the index misaligns when image-based
    tracks (PGS/DVD/DVB) sit ahead of text tracks.

    Selection rules:
      1. Drop image-based codecs (PGS/DVD/DVB) — they need OCR, can't transcode.
      2. Prefer English (most common source language for translation).
      3. Then prefer non-target-language tracks (no point translating to itself).
      4. Otherwise the first text-based track.
    Returns None if no usable text track exists.
    """
    target_iso = _TARGET_LANG_TO_ISO.get(target_language, set())
    text_subs = [
        (i, t) for i, t in enumerate(tracks)
        if is_text_subtitle_codec(t.get("codec"))
    ]
    if not text_subs:
        return None

    def lang(t):
        value = t.get("lang")
        return value.lower() if isinstance(value, str) else ""

    # Priority 1: English, unless English is the requested output language.
    if not ({"en", "eng"} & target_iso):
        for i, t in text_subs:
            if lang(t) in {"en", "eng"}:
                return i
    # Priority 2: any non-target language
    for i, t in text_subs:
        if lang(t) and lang(t) not in target_iso:
            return i
    # Priority 3: first text-based track
    return text_subs[0][0]


def _apply_safe_defaults(project: dict) -> dict:
    """Backward-compat: ensure new schema fields exist with sane defaults on load."""
    if not isinstance(project, dict):
        raise ValueError("Project file is invalid")
    project = _json_safe_value(project)
    for k, v in _PROJECT_SAFE_DEFAULTS.items():
        project.setdefault(k, v)
    for field in ("audio_tracks", "subtitle_tracks"):
        if not isinstance(project.get(field), list):
            project[field] = []
        else:
            project[field] = [t for t in project[field] if isinstance(t, dict)]
    for field in ("video_path", "output_video"):
        if project.get(field) is not None and not isinstance(project.get(field), str):
            project[field] = None
    for field in (
        "tmdb_video_key",
        "youtube_url",
        "original_language",
        "parent_project_id",
        "pipeline_stage",
        "show_title",
        "poster_path",
        "error",
    ):
        if project.get(field) is not None and not isinstance(project.get(field), str):
            project[field] = None
    if project.get("source_type") not in ("upload", "trailer"):
        project["source_type"] = "upload"
    for field, default in (("asr_language", "auto"), ("target_language", "简体中文")):
        value = project.get(field)
        if not isinstance(value, str) or not value.strip():
            project[field] = default
    if project.get("tmdb_candidates") is not None:
        if not isinstance(project.get("tmdb_candidates"), list):
            project["tmdb_candidates"] = None
        else:
            project["tmdb_candidates"] = [
                candidate for candidate in project["tmdb_candidates"]
                if isinstance(candidate, dict)
            ]

    def positive_int_or_none(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return None
        return value

    project["tmdb_id"] = positive_int_or_none(project.get("tmdb_id"))
    project["season_number"] = positive_int_or_none(project.get("season_number"))
    try:
        duration = float(project.get("duration", 0))
    except (OverflowError, TypeError, ValueError):
        duration = 0
    if not math.isfinite(duration):
        duration = 0
    project["duration"] = max(0, duration)
    if project.get("tmdb_type") not in (None, "movie", "tv"):
        project["tmdb_type"] = None
    for field, default in (
        ("archived", False),
        ("asr_skipped", False),
        ("prefer_embedded_subtitle", True),
        ("auto_run", False),
    ):
        if not isinstance(project.get(field), bool):
            project[field] = default
    audio_track_count = len(project.get("audio_tracks") or [])
    selected_audio_track = project.get("selected_audio_track")
    if (
        isinstance(selected_audio_track, bool)
        or not isinstance(selected_audio_track, int)
        or selected_audio_track < 0
        or (audio_track_count > 0 and selected_audio_track >= audio_track_count)
        or (audio_track_count == 0 and selected_audio_track != 0)
    ):
        project["selected_audio_track"] = 0

    subtitle_track_count = len(project.get("subtitle_tracks") or [])
    selected_subtitle_track = project.get("selected_subtitle_track")
    invalid_selected_subtitle_track = (
        selected_subtitle_track is not None
        and (
            isinstance(selected_subtitle_track, bool)
            or not isinstance(selected_subtitle_track, int)
            or selected_subtitle_track < 0
            or selected_subtitle_track >= subtitle_track_count
        )
    )
    if invalid_selected_subtitle_track:
        project["selected_subtitle_track"] = None

    raw_progress = project.get("progress", 0)
    try:
        progress = int(raw_progress) if not isinstance(raw_progress, bool) else 0
    except (OverflowError, TypeError, ValueError):
        progress = 0
    project["progress"] = max(0, min(100, progress))
    if not isinstance(project.get("progress_msg", ""), str):
        project["progress_msg"] = ""
    # Backfill: pre-existing projects detected subtitle tracks before the
    # auto-picker existed, so they have subtitle_tracks but a null
    # selected_subtitle_track. Run the picker once so the user can use the
    # embedded-subtitle bypass without re-creating the project.
    if (not invalid_selected_subtitle_track
            and project.get("selected_subtitle_track") is None
            and project.get("subtitle_tracks")):
        idx = _pick_subtitle_track(project["subtitle_tracks"],
                                    project.get("target_language", "简体中文"))
        if idx is not None:
            project["selected_subtitle_track"] = idx
    return project


class CreateProjectReq(BaseModel):
    video_path: str
    name: Optional[str] = None
    asr_language: Optional[str] = None
    target_language: Optional[str] = None


class SubtitleEdit(BaseModel):
    blocks: list


def _text_default(value: Optional[str], default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _parse_subtitle_time(value, field: str):
    text = str(value or "").strip()
    parsed = parse_time_strict(text)
    if parsed is None:
        raise HTTPException(400, f"invalid {field} time")
    return parsed


def _subtitle_text_field(item: dict, field: str) -> str:
    value = item.get(field, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HTTPException(400, f"{field} must be a string")
    return value


def _subtitle_bool_field(item: dict, field: str, default: bool = False) -> bool:
    value = item.get(field, default)
    if not isinstance(value, bool):
        raise HTTPException(400, f"{field} must be a boolean")
    return value


def _editable_source_srt_path(pdir: Path) -> Path:
    """Return the source SRT file that get_subtitles will reload after edits."""
    for fname in ("filtered.srt", "raw.srt"):
        path = pdir / fname
        if path.is_file():
            return path
    return pdir / "raw.srt"


def _write_editable_source_srt(
    blocks: list[SubtitleBlock],
    path: Path,
    *,
    include_filtered: bool = False,
) -> None:
    """Write the source timeline used by the editor.

    User-inserted rows can legitimately have an empty source text because the
    UI edits the translated cell. Keep those rows reloadable by falling back to
    translation text for the source SRT entry.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        seq = 1
        for block in blocks:
            if getattr(block, "filtered", False) and not include_filtered:
                continue
            text = getattr(block, "text", "")
            if not isinstance(text, str) or not text.strip():
                text = getattr(block, "translation", "")
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                if block.end <= block.start:
                    continue
            except (AttributeError, TypeError, OverflowError):
                continue
            f.write(f"{seq}\n")
            f.write(f"{fmt_time(block.start)} --> {fmt_time(block.end)}\n")
            f.write(f"{text.strip()}\n\n")
            seq += 1


def _write_filter_state(blocks: list[SubtitleBlock], path: Path) -> None:
    state = {}
    for block in blocks:
        if not getattr(block, "filtered", False):
            continue
        reason = getattr(block, "filter_reason", "")
        state[str(block.index)] = {
            "filtered": True,
            "reason": reason if isinstance(reason, str) else "",
        }
    atomic_write_json(path, state)


def _export_filename(project: dict, pid: str, suffix: str) -> str:
    raw_name = project.get("name") if isinstance(project, dict) else None
    stem = raw_name.strip() if isinstance(raw_name, str) else ""
    stem = re.sub(r"[/\\\x00-\x1f\x7f]+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip(" ._")
    if len(stem) > 120:
        stem = stem[:120].strip(" ._")
    if not stem:
        stem = pid
    return f"{stem}{suffix}"


def _read_export_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _has_video_extension(path_or_name: str) -> bool:
    return Path(path_or_name).suffix.lower() in _VIDEO_UPLOAD_EXTS


def _truncate_filename_stem(stem: str, max_bytes: int) -> str:
    value = stem
    while value and len(value.encode("utf-8")) > max_bytes:
        value = value[:-1]
    return value.rstrip(" .") or "upload"


def _new_project_id() -> str:
    for _ in range(100):
        pid = uuid.uuid4().hex[:8]
        if not (PROJECTS_DIR / pid).exists():
            return pid
    raise HTTPException(500, "Could not allocate project id")


def _project_dir(pid: str) -> Path:
    return _ps_project_dir(pid)


def _load_project(pid: str) -> dict:
    try:
        project = _ps_load_project(pid)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    except json.JSONDecodeError:
        raise HTTPException(400, "Project file is invalid")
    except ValueError as e:
        detail = str(e)
        if "invalid project id" in detail or "project id escapes" in detail:
            raise HTTPException(400, "Invalid project id")
        raise HTTPException(400, "Project file is invalid")
    try:
        return _merge_runtime_progress(pid, _apply_safe_defaults(project))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _merge_runtime_progress(pid: str, project: dict) -> dict:
    """Overlay persisted scheduler progress while a project is actively running.

    Project state is intentionally low-write during long model calls, while
    progress.json is updated frequently for the websocket. GET /api/projects/*
    also backs the frontend polling fallback, so merge the live progress there
    instead of letting stale project.json progress overwrite the websocket view.
    """
    if not (
        isinstance(project, dict)
        and (project.get("status") == "processing" or project.get("pipeline_stage"))
    ):
        return project

    try:
        from app.engines.scheduler import get_progress as _get_runtime_progress

        progress = _get_runtime_progress(pid)
    except Exception:
        return project
    if not isinstance(progress, dict):
        return project

    stage = progress.get("stage")
    if stage in {"download", "asr", "translate", "burn"}:
        project["pipeline_stage"] = stage
    if isinstance(progress.get("progress"), int) and not isinstance(progress.get("progress"), bool):
        project["progress"] = max(0, min(100, progress["progress"]))
    message = progress.get("message")
    if isinstance(message, str):
        project["progress_msg"] = message
    return project


def _save_project(pid: str, data: dict):
    atomic_write_json(PROJECTS_DIR / pid / "project.json", data)


def create_trailer_project(
    tmdb_id: int,
    tmdb_type: str,
    video_key: str,
    youtube_url: str,
    original_language: str,
    name: str,
    season_number=None,
    parent_project_id=None,
    asr_language: str = "auto",
    target_language: str = "简体中文",
) -> dict:
    """Create a new trailer-source project directory + project.json.

    Returns the full project dict. Does not register an HTTP route; callers
    (e.g. the trailer pipeline) invoke this helper directly.
    """
    pid = _new_project_id()
    pdir = PROJECTS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)

    project = {
        "id": pid,
        "name": name,
        "video_path": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "created",
        "progress": 0,
        "progress_msg": "",
        "duration": 0,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "selected_audio_track": 0,
        "selected_subtitle_track": None,
        "asr_language": _text_default(asr_language, "auto"),
        "target_language": _text_default(target_language, "简体中文"),
        "error": None,
        "output_video": None,
        # Trailer-specific
        "source_type": "trailer",
        "tmdb_id": tmdb_id,
        "tmdb_type": tmdb_type,
        "season_number": season_number,
        "tmdb_video_key": video_key,
        "youtube_url": youtube_url,
        "original_language": original_language,
        "auto_run": True,
        "parent_project_id": parent_project_id,
        "pipeline_stage": "download",
        "archived": False,
    }

    atomic_write_json(pdir / "project.json", project)

    return project


@router.get("")
def list_projects(include_archived: bool = Query(False)):
    """List all projects."""
    projects = []
    if not PROJECTS_DIR.exists():
        return projects
    for pdir in sorted(PROJECTS_DIR.iterdir(), reverse=True):
        if pdir.is_symlink() or not pdir.is_dir():
            continue
        pfile = pdir / "project.json"
        if pfile.exists():
            try:
                with open(pfile, "r", encoding="utf-8") as f:
                    project = _merge_runtime_progress(pdir.name, _apply_safe_defaults(json.load(f)))
                    if project.get("archived") and not include_archived:
                        continue
                    projects.append(project)
            except Exception:
                pass
    return projects


@router.post("")
async def create_project(req: CreateProjectReq):
    """Create a new project from a video file. Auto-enriches with TMDB
    metadata when guessit can extract a usable title from the filename."""
    video_path = req.video_path.strip()
    if not os.path.exists(video_path):
        raise HTTPException(400, f"Video file not found: {video_path}")
    if not os.path.isfile(video_path):
        raise HTTPException(400, f"Video path is not a file: {video_path}")
    if os.path.getsize(video_path) <= 0:
        raise HTTPException(400, f"Video file is empty: {video_path}")
    if not _has_video_extension(video_path):
        raise HTTPException(400, "Video file must use a supported video extension")

    pid = _new_project_id()
    name = (req.name or "").strip() or os.path.basename(video_path)

    # Detect tracks
    audio_tracks = get_tracks(video_path, "a")
    subtitle_tracks = get_tracks(video_path, "s")
    duration = get_duration(video_path)

    asr_language = _text_default(req.asr_language, "auto")
    target_language = _text_default(req.target_language, "简体中文")
    project = {
        "id": pid,
        "name": name,
        "video_path": video_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "created",
        "progress": 0,
        "progress_msg": "",
        "duration": round(duration, 1),
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
        "selected_audio_track": 0,
        "selected_subtitle_track": _pick_subtitle_track(subtitle_tracks, target_language),
        "prefer_embedded_subtitle": True,
        "asr_language": asr_language,
        "target_language": target_language,
        "error": None,
    }
    project = _apply_safe_defaults(project)

    # TMDB enrichment from filename. Best-effort: any failure (no key,
    # network, no parse) leaves the project as-is; UI can manually link later.
    try:
        from app.engines.tmdb_enrich import enrich_from_filename
        enrich = await enrich_from_filename(name)
        if enrich.get("auto_attached"):
            project["tmdb_id"] = enrich["tmdb_id"]
            project["tmdb_type"] = enrich["tmdb_type"]
            project["season_number"] = enrich.get("season_number")
            project["show_title"] = enrich.get("show_title")
            project["original_language"] = enrich.get("original_language")
            project["poster_path"] = enrich.get("poster_path")
        elif enrich.get("candidates"):
            project["tmdb_candidates"] = enrich["candidates"]
    except Exception:
        # Never block project creation on enrichment errors.
        pass

    project = _apply_safe_defaults(project)
    _save_project(pid, project)
    return project


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """Accept a video file upload and save to uploads dir, return the saved path."""
    uploads_dir = PROJECTS_DIR / "_uploads"
    if uploads_dir.is_symlink():
        raise HTTPException(400, "Upload directory is invalid")
    if uploads_dir.exists() and not uploads_dir.is_dir():
        raise HTTPException(400, "Upload directory is invalid")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    projects_real = PROJECTS_DIR.resolve()
    uploads_real = uploads_dir.resolve()
    try:
        uploads_real.relative_to(projects_real)
    except ValueError:
        raise HTTPException(400, "Upload directory is invalid")

    # Sanitize filename. Strip directory separators, then refuse any value
    # that would resolve outside uploads_dir (e.g., the bare string '..').
    raw_name = (file.filename or "").strip()
    safe_name = raw_name.replace("/", "_").replace("\\", "_")
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(400, "Invalid filename")
    if any(ord(ch) < 32 for ch in safe_name):
        raise HTTPException(400, "Invalid filename")
    if len(safe_name.encode("utf-8")) > 255:
        raise HTTPException(400, "Filename too long")
    if not _has_video_extension(safe_name):
        raise HTTPException(400, "Uploaded file must be a video")

    # Avoid overwrites and pre-existing symlinks. A broken symlink returns
    # False for exists(), so check is_symlink() separately before opening.
    base_dest = uploads_dir / safe_name
    stem = base_dest.stem
    suffix = base_dest.suffix
    i = 0
    while True:
        if i == 0:
            dest = base_dest
        else:
            collision_suffix = f"_{i}{suffix}"
            max_stem_bytes = 255 - len(collision_suffix.encode("utf-8"))
            dest = uploads_dir / f"{_truncate_filename_stem(stem, max_stem_bytes)}{collision_suffix}"
        if dest.exists() or dest.is_symlink():
            i += 1
            continue
        try:
            dest.resolve().parent.relative_to(uploads_real)
        except ValueError:
            raise HTTPException(400, "Invalid filename: path escapes uploads dir")
        try:
            upload_file = open(dest, "xb")
            break
        except FileExistsError:
            i += 1

    written = 0
    try:
        with upload_file as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MiB chunks
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    f.close()
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise HTTPException(
                        413, f"Upload exceeds {MAX_UPLOAD_BYTES} bytes"
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception:
        # On any other write error, don't leave a half-written file behind.
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    if written == 0:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(400, "Uploaded file is empty")

    return {"path": str(dest)}


@router.get("/{pid}")
def get_project(pid: str = PathParam(pattern=PID_PATTERN)):
    """Get project detail."""
    return _load_project(pid)


@router.get("/{pid}/workflow-state")
def get_workflow_state(pid: str = PathParam(pattern=PID_PATTERN)):
    """Get structured workflow state for a project."""
    _load_project(pid)
    return load_workflow_state(pid)


@router.get("/{pid}/logs/{stage}")
def download_workflow_log(stage: str, pid: str = PathParam(pattern=PID_PATTERN)):
    """Download a persisted workflow stage log."""
    _load_project(pid)
    try:
        path = stage_log_path(pid, stage)
    except ValueError:
        raise HTTPException(400, "Invalid workflow stage")
    log_dir = path.parent
    if log_dir.is_symlink():
        raise HTTPException(400, "Workflow log directory is invalid")
    if path.is_symlink():
        raise HTTPException(400, "Workflow log is invalid")
    if not path.is_file():
        raise HTTPException(404, "Workflow log not found")
    try:
        resolved_project_dir = _project_dir(pid).resolve()
        path.resolve().relative_to(resolved_project_dir)
    except ValueError:
        raise HTTPException(400, "Workflow log is invalid")
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=f"{pid}-{stage}.log",
    )


_PATCHABLE_FIELDS = {
    "prefer_embedded_subtitle",
    "selected_subtitle_track",
    "selected_audio_track",
    "asr_language",
    "target_language",
    "tmdb_id",
    "tmdb_type",
    "season_number",
    "tmdb_video_key",
    "show_title",
    "poster_path",
    "original_language",
    "tmdb_candidates",
    "name",
    "archived",
}

_CLEARABLE_FIELDS = {
    "tmdb_id",
    "tmdb_type",
    "season_number",
    "tmdb_video_key",
    "show_title",
    "poster_path",
    "original_language",
    "tmdb_candidates",
    "selected_subtitle_track",
}


class PatchProjectReq(BaseModel):
    prefer_embedded_subtitle: Optional[bool] = None
    selected_subtitle_track: Optional[StrictInt] = None
    selected_audio_track: Optional[StrictInt] = None
    asr_language: Optional[str] = None
    target_language: Optional[str] = None
    tmdb_id: Optional[StrictInt] = None
    tmdb_type: Optional[str] = None
    season_number: Optional[StrictInt] = None
    tmdb_video_key: Optional[str] = None
    show_title: Optional[str] = None
    poster_path: Optional[str] = None
    original_language: Optional[str] = None
    name: Optional[str] = None
    archived: Optional[bool] = None
    # Sentinel set: caller passes field names whose value should be set to
    # null/None (since None on the request means "not provided" in pydantic).
    clear: Optional[List[str]] = None


class TmdbSearchReq(BaseModel):
    query: str
    type: str  # "movie" or "tv"
    year: Optional[StrictInt] = None


def _validate_project_patch(project: dict, payload: dict) -> None:
    tmdb_id = payload.get("tmdb_id")
    if "tmdb_id" in payload and tmdb_id is not None and tmdb_id < 1:
        raise ValueError("tmdb_id must be positive")

    tmdb_type = payload.get("tmdb_type")
    if "tmdb_type" in payload and tmdb_type not in (None, "movie", "tv"):
        raise ValueError("invalid tmdb_type")

    season_number = payload.get("season_number")
    if "season_number" in payload and season_number is not None and season_number < 1:
        raise ValueError("season_number must be positive")

    name = payload.get("name")
    if "name" in payload and name is not None and not name.strip():
        raise ValueError("name must not be empty")

    for field, tracks_field in (
        ("selected_audio_track", "audio_tracks"),
        ("selected_subtitle_track", "subtitle_tracks"),
    ):
        if field not in payload or payload[field] is None:
            continue
        value = payload[field]
        tracks = project.get(tracks_field) or []
        if value < 0 or value >= len(tracks):
            raise ValueError(f"{field} out of range")


@router.post("/{pid}/tmdb-search")
async def tmdb_search_for_project(req: TmdbSearchReq, pid: str = PathParam(pattern=PID_PATTERN)):
    """Run a TMDB search with a user-provided query and persist the
    candidates onto the project. UI uses this when the auto-search
    based on the filename was wrong or empty."""
    project = _load_project(pid)
    from app.engines import tmdb
    from app.engines.tmdb_enrich import _normalize_candidate

    if req.type not in {"movie", "tv"}:
        raise HTTPException(400, "invalid type")
    if not req.query.strip():
        raise HTTPException(400, "query must not be empty")

    kind = req.type
    try:
        if kind == "tv":
            results = await tmdb.search_tv(req.query, year=req.year)
        else:
            results = await tmdb.search_movie(req.query, year=req.year)
    except Exception as e:
        raise HTTPException(502, f"TMDB search failed: {tmdb.public_error_message(e)}")

    candidates = _json_safe_value([
        c for c in (_normalize_candidate(r, kind) for r in results[:10])
        if c.get("tmdb_id") is not None and c.get("title")
    ])
    mutate_project(pid, lambda p: p.__setitem__("tmdb_candidates", candidates),
                   normalize=_apply_safe_defaults)
    return {"candidates": candidates}


@router.patch("/{pid}")
def patch_project(req: PatchProjectReq, pid: str = PathParam(pattern=PID_PATTERN)):
    """Partially update a project. Only whitelisted fields are accepted.
    Pass field names in `clear` to explicitly set those fields to null."""
    payload = req.model_dump(exclude_unset=True, exclude={"clear"})
    if isinstance(payload.get("name"), str):
        payload["name"] = payload["name"].strip()

    def _apply(project):
        _validate_project_patch(project, payload)
        for k, v in payload.items():
            if k in _PATCHABLE_FIELDS:
                project[k] = v
        for k in (req.clear or []):
            if k in _CLEARABLE_FIELDS:
                project[k] = None

    try:
        return mutate_project(pid, _apply, normalize=_apply_safe_defaults)
    except FileNotFoundError:
        raise HTTPException(404, "Project not found")
    except json.JSONDecodeError:
        raise HTTPException(400, "Project file is invalid")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/{pid}")
def delete_project(pid: str = PathParam(pattern=PID_PATTERN)):
    """Delete a project and its data."""
    try:
        pdir = _project_dir(pid)
    except ValueError:
        raise HTTPException(400, "Invalid project id")
    if not pdir.exists():
        raise HTTPException(404, "Project not found")
    if not (pdir / "project.json").exists():
        raise HTTPException(404, "Project not found")
    project = None
    try:
        project = _load_project(pid)
    except HTTPException:
        # A corrupt project file should still be removable.
        project = None
    try:
        from app.api.translate import is_task_registered
        registered = is_task_registered(pid)
    except Exception:
        registered = False
    if registered or (
        isinstance(project, dict)
        and (project.get("status") == "processing" or project.get("pipeline_stage"))
    ):
        raise HTTPException(409, "Project is processing; cancel it before deleting")
    shutil.rmtree(pdir)
    return {"status": "ok"}


@router.post("/{pid}/reveal")
def reveal_in_finder(pid: str = PathParam(pattern=PID_PATTERN)):
    """Open Finder/Explorer with the project's output (or project dir) selected.

    macOS: `open -R <file>` opens Finder and highlights the file.
    Windows: `explorer /select,<file>` does the same.
    Linux: `xdg-open <dir>` opens the containing directory.
    """
    import subprocess, sys
    pdir = _project_dir(pid)
    project = _load_project(pid)
    target = str(pdir)
    output_video = project.get("output_video")
    if output_video:
        raw_output_path = Path(output_video)
        output_path = (pdir / raw_output_path if not raw_output_path.is_absolute() else raw_output_path).resolve()
        try:
            output_path.relative_to(pdir.resolve())
            if output_path.exists():
                target = str(output_path)
        except ValueError:
            log.warning("Blocked reveal outside project dir for %s: %s", pid, output_path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", target])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", f"/select,{target}"])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(target) if os.path.isfile(target) else target])
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return {"status": "ok", "path": target}


@router.get("/{pid}/subtitles")
def get_subtitles(pid: str = PathParam(pattern=PID_PATTERN)):
    """Get current subtitle blocks."""
    pdir = _project_dir(pid)
    project = _load_project(pid)

    # Load original text from filtered/raw/native SRT
    original_blocks = None
    source_name = None
    for fname in ["filtered.srt", "raw.srt", "native.srt"]:
        srt_path = pdir / fname
        if srt_path.exists():
            try:
                original_blocks = parse_srt_file(str(srt_path))
                source_name = fname
                break
            except Exception as e:
                log.warning("Could not parse subtitle source %s/%s: %s", pid, fname, e)

    if original_blocks is None:
        return {"blocks": [], "source": None}

    blocks = original_blocks

    # Load translations from translated.srt if it exists
    # Match by timestamp since indices may differ between files
    trans_path = pdir / "translated.srt"
    if trans_path.exists():
        try:
            trans_blocks = parse_srt_file(str(trans_path))
        except Exception as e:
            log.warning("Could not parse translated subtitles for %s: %s", pid, e)
            trans_blocks = []
        trans_by_time = {}
        for tb in trans_blocks:
            key = int(tb.start.total_seconds() * 1000)
            trans_by_time[key] = tb.text
        for b in blocks:
            key = int(b.start.total_seconds() * 1000)
            if key in trans_by_time:
                b.translation = trans_by_time[key]

    # Load filter state only for unfiltered source timelines. filtered.srt has
    # already removed filtered rows and re-numbered entries, so reapplying the
    # old raw indexes would mark unrelated active rows as filtered.
    filter_path = pdir / "filter_state.json"
    if source_name != "filtered.srt" and filter_path.exists():
        try:
            with open(filter_path, "r", encoding="utf-8") as f:
                fstate = json.load(f)
        except Exception:
            fstate = {}
        if isinstance(fstate, dict):
            for blk in blocks:
                entry = fstate.get(str(blk.index))
                if not isinstance(entry, dict):
                    continue
                filtered = entry.get("filtered", False)
                reason = entry.get("reason", "")
                blk.filtered = filtered if isinstance(filtered, bool) else False
                blk.filter_reason = reason if isinstance(reason, str) else ""

    return {"blocks": [b.to_dict() for b in blocks], "source": source_name}


@router.get("/{pid}/quality-report")
def get_quality_report(pid: str = PathParam(pattern=PID_PATTERN)):
    """Return the latest translation QA report for a project."""
    _load_project(pid)
    path = _project_dir(pid) / "translation_qa_report.json"
    if not path.exists():
        return {"status": "missing", "issues": [], "summary": {"issue_count": 0}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(400, "Quality report is invalid")
    if not isinstance(data, dict):
        raise HTTPException(400, "Quality report is invalid")
    return data


@router.put("/{pid}/subtitles")
def save_subtitles(data: SubtitleEdit, pid: str = PathParam(pattern=PID_PATTERN)):
    """Save edited subtitles."""
    project = _load_project(pid)
    pdir = _project_dir(pid)
    pdir.mkdir(parents=True, exist_ok=True)
    previous_translated_blocks = []
    translated_path = pdir / "translated.srt"
    if translated_path.exists():
        try:
            previous_translated_blocks = parse_srt_file(str(translated_path))
        except Exception as e:
            log.warning("Could not load previous translations for memory learning %s: %s",
                        pid, e)

    # Rebuild blocks from data
    blocks = []
    for item in data.blocks:
        if not isinstance(item, dict):
            raise HTTPException(400, "subtitle block must be an object")
        index = item.get("index", len(blocks) + 1)
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise HTTPException(400, "index must be a positive integer")
        start = _parse_subtitle_time(item.get("start", "00:00:00,000"), "start")
        end = _parse_subtitle_time(item.get("end", "00:00:00,000"), "end")
        if end <= start:
            raise HTTPException(400, "end time must be after start time")
        b = SubtitleBlock(
            index=index,
            start=start,
            end=end,
            text=_subtitle_text_field(item, "text"),
            translation=_subtitle_text_field(item, "translation"),
            filtered=_subtitle_bool_field(item, "filtered"),
            filter_reason=_subtitle_text_field(item, "filter_reason"),
        )
        blocks.append(b)

    # Save the editable source timeline as well. Otherwise add/split/delete
    # edits are lost when GET /subtitles reloads from filtered/raw/native.
    source_path = _editable_source_srt_path(pdir)
    source_keeps_filter_state = source_path.name != "filtered.srt"
    _write_editable_source_srt(
        blocks,
        source_path,
        include_filtered=source_keeps_filter_state,
    )
    if source_keeps_filter_state or (pdir / "filter_state.json").exists():
        _write_filter_state(blocks, pdir / "filter_state.json")
    # Save translated version
    write_srt(blocks, str(pdir / "translated.srt"), use_translation=True)
    # Save bilingual version
    write_bilingual_srt(blocks, str(pdir / "bilingual.srt"))
    try:
        from app.engines.translation_memory import record_edited_subtitles
        learned = record_edited_subtitles(
            project=project,
            before_blocks=previous_translated_blocks,
            after_blocks=blocks,
        )
        if learned:
            log.info("learned %d translation memory edit(s) for project %s", learned, pid)
    except Exception as e:
        log.warning("translation memory learning failed for %s: %s", pid, e)

    return {"status": "ok", "count": len(blocks)}


@router.post("/{pid}/export")
def export_srt(pid: str = PathParam(pattern=PID_PATTERN), format: str = "translated"):
    """Export final SRT file."""
    if format not in {"original", "bilingual", "translated"}:
        raise HTTPException(400, "invalid format")

    pdir = _project_dir(pid)
    project = _load_project(pid)

    if format == "original":
        for fname in ["filtered.srt", "raw.srt", "native.srt"]:
            if (pdir / fname).is_file():
                return {"content": _read_export_text(pdir / fname), "filename": _export_filename(project, pid, ".srt")}
    elif format == "bilingual":
        if (pdir / "bilingual.srt").is_file():
            return {"content": _read_export_text(pdir / "bilingual.srt"), "filename": _export_filename(project, pid, ".bilingual.srt")}
    else:
        if (pdir / "translated.srt").is_file():
            return {"content": _read_export_text(pdir / "translated.srt"), "filename": _export_filename(project, pid, ".translated.srt")}

    raise HTTPException(404, "No subtitle file available for export")
