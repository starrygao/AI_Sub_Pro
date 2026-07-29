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
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel, StrictInt

from app.config import Config, PROJECTS_DIR
from app.engines.project_metadata import (
    CONTENT_TYPE_OPTIONS,
    infer_content_metadata_from_filename,
    normalize_content_type,
    should_skip_tmdb_enrichment,
)
from app.engines.translation_strategy import build_translation_strategy
from app.engines.translation_qa import is_sound_description_source
from app.engines.workflow_state import load_workflow_state, stage_log_path
from app.utils.project_store import (
    project_dir as _ps_project_dir,
    load_project as _ps_load_project,
    mutate_project,
    atomic_write_json,
    durable_replace,
    durable_unlink,
    get_project_lock,
    PID_PATTERN,
)
from app.utils.translation_delivery import (
    hide_invalid_translation_artifact_fields,
    mark_translation_delivery_invalid,
    promote_staged_files,
    translation_delivery_lock,
    translation_delivery_is_invalid,
)
from app.utils.translation_certification import (
    validate_translation_delivery,
)
from app.utils.media import get_tracks, get_duration, get_media_info, is_text_subtitle_codec
from app.utils.srt import (
    fmt_time,
    parse_ass,
    parse_srt,
    parse_srt_file,
    parse_time_strict,
    parse_vtt,
    srt_to_vtt,
    write_srt,
    write_bilingual_srt,
    SubtitleBlock,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])
log = logging.getLogger(__name__)

# Cap on /upload payload size. 8 GiB is comfortably above any realistic
# trailer/movie a user would actually upload through the web UI, while
# preventing a single POST from filling the disk. Tests monkeypatch this
# to a lower value to exercise the rejection path without writing GBs.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024
MAX_SUBTITLE_UPLOAD_BYTES = 32 * 1024 * 1024
MAX_AUDIO_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
_FORCED_SUBTITLE_TITLE_RE = re.compile(
    r"\b(forced|foreign\s+only|signs?\s*(?:&|and)\s*songs?)\b",
    re.IGNORECASE,
)
_COMMENTARY_SUBTITLE_TITLE_RE = re.compile(
    r"\b(commentary|director'?s?\s+commentary)\b",
    re.IGNORECASE,
)
_SDH_SUBTITLE_TITLE_RE = re.compile(
    r"\b(sdh|cc|closed\s+captions?|hearing\s+impaired|descriptive)\b",
    re.IGNORECASE,
)
_VIDEO_UPLOAD_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts", ".m4v"}
_SUBTITLE_UPLOAD_EXTS = {".srt", ".vtt", ".ass", ".ssa"}
_AUDIO_UPLOAD_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm"}


_PROJECT_SAFE_DEFAULTS = {
    "source_type": "upload",
    "auto_run": False,
    "workflow_mode": "translate_burn",
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
    "network_metadata": None,
    "source_title": None,
    "source_uploader": None,
    "source_channel": None,
    "source_duration": None,
    "source_webpage_url": None,
    "source_extractor": None,
    "source_language": None,
    "source_has_subtitles": False,
    "subtitle_source": None,
    "native_subtitle_language": None,
    "network_video_plan": None,
    "content_type": "auto",
    "academic_field": "",
    "content_notes": "",
    "manual_terms": "",
    "metadata_source": "",
    "translated_srt": None,
    "bilingual_srt": None,
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

_WORKFLOW_MODES = {"translate_burn", "translate_only"}


def _normalize_workflow_mode(value) -> str:
    if isinstance(value, str) and value.strip() in _WORKFLOW_MODES:
        return value.strip()
    return "translate_burn"


def _json_safe_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    return value


def _subtitle_track_title(track: dict) -> str:
    title = track.get("title") if isinstance(track, dict) else ""
    return title.strip() if isinstance(title, str) else ""


def _is_forced_or_commentary_subtitle(track: dict) -> bool:
    title = _subtitle_track_title(track)
    return bool(
        title
        and (
            _FORCED_SUBTITLE_TITLE_RE.search(title)
            or _COMMENTARY_SUBTITLE_TITLE_RE.search(title)
        )
    )


def _subtitle_track_penalty(track: dict) -> int:
    title = _subtitle_track_title(track)
    if title and _SDH_SUBTITLE_TITLE_RE.search(title):
        return 5
    return 0


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
      2. Drop forced/commentary tracks — they are usually incomplete or not
         the program dialogue; fall back to ASR if those are the only tracks.
      3. Prefer regular English (most common source language for translation).
      4. Then prefer regular non-target-language tracks.
      5. Prefer SDH/CC only when there is no regular source track.
    Returns None if no usable text track exists.
    """
    target_iso = _TARGET_LANG_TO_ISO.get(target_language, set())
    text_subs = [
        (i, t) for i, t in enumerate(tracks)
        if is_text_subtitle_codec(t.get("codec"))
        and not _is_forced_or_commentary_subtitle(t)
    ]
    if not text_subs:
        return None

    def lang(t):
        value = t.get("lang")
        return value.lower() if isinstance(value, str) else ""

    def score(item):
        i, t = item
        track_lang = lang(t)
        if not ({"en", "eng"} & target_iso) and track_lang in {"en", "eng"}:
            lang_score = 0
        elif track_lang and track_lang not in target_iso:
            lang_score = 10
        elif track_lang in target_iso:
            lang_score = 20
        else:
            lang_score = 15
        return (lang_score + _subtitle_track_penalty(t), i)

    return min(text_subs, key=score)[0]


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
    for field in ("video_path", "output_video", "translated_srt", "bilingual_srt"):
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
        "source_title",
        "source_uploader",
        "source_channel",
        "source_webpage_url",
        "source_extractor",
        "source_language",
        "subtitle_source",
        "native_subtitle_language",
        "academic_field",
        "content_notes",
        "manual_terms",
        "metadata_source",
    ):
        if project.get(field) is not None and not isinstance(project.get(field), str):
            project[field] = None
    if not isinstance(project.get("network_metadata"), dict):
        project["network_metadata"] = {}
    if project.get("network_video_plan") is not None and not isinstance(project.get("network_video_plan"), dict):
        project["network_video_plan"] = None
    project["content_type"] = normalize_content_type(project.get("content_type"))
    for field, limit in (
        ("academic_field", 80),
        ("content_notes", 1200),
        ("manual_terms", 2400),
        ("metadata_source", 40),
    ):
        value = project.get(field)
        if value is None:
            project[field] = ""
        elif isinstance(value, str):
            project[field] = value.strip()[:limit]
        else:
            project[field] = ""
    for field, limit in (
        ("source_title", 160),
        ("source_uploader", 160),
        ("source_channel", 160),
        ("source_webpage_url", 500),
        ("source_extractor", 80),
        ("source_language", 32),
        ("subtitle_source", 40),
        ("native_subtitle_language", 32),
    ):
        value = project.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            project[field] = value.strip()[:limit] or None
        else:
            project[field] = None
    if project.get("source_type") not in ("upload", "trailer", "subtitle", "audio"):
        project["source_type"] = "upload"
    project["workflow_mode"] = _normalize_workflow_mode(project.get("workflow_mode"))
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
    source_duration = project.get("source_duration")
    if source_duration is not None:
        try:
            source_duration = float(source_duration)
        except (OverflowError, TypeError, ValueError):
            source_duration = None
        if source_duration is not None and (not math.isfinite(source_duration) or source_duration < 0):
            source_duration = None
        if isinstance(source_duration, float) and source_duration.is_integer():
            source_duration = int(source_duration)
    project["source_duration"] = source_duration
    if project.get("tmdb_type") not in (None, "movie", "tv"):
        project["tmdb_type"] = None
    for field, default in (
        ("archived", False),
        ("asr_skipped", False),
        ("prefer_embedded_subtitle", True),
        ("auto_run", False),
        ("source_has_subtitles", False),
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
    content_type: Optional[str] = None
    academic_field: Optional[str] = None
    content_notes: Optional[str] = None
    manual_terms: Optional[str] = None


class DiscoverLocalVideosReq(BaseModel):
    folder_path: str
    recursive: bool = True
    limit: Optional[StrictInt] = 200


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


def _subtitle_editor_payload(block: SubtitleBlock) -> dict:
    payload = block.to_dict()
    payload["sound_description"] = is_sound_description_source(block.text)
    return payload


def _editable_source_srt_path(pdir: Path) -> Path:
    """Return the source SRT file that get_subtitles will reload after edits."""
    for fname in ("filtered.srt", "raw.srt"):
        path = pdir / fname
        if path.is_file():
            return path
    return pdir / "raw.srt"


def _subtitle_time_ms(value) -> int:
    try:
        total = value.total_seconds()
    except (AttributeError, TypeError, OverflowError, ValueError):
        return 0
    try:
        if not math.isfinite(total):
            return 0
    except (OverflowError, TypeError, ValueError):
        return 0
    return int(round(max(0, total) * 1000))


def _lookup_subtitle_time(mapping: dict[int, str], start_ms: int, tolerance_ms: int = 2) -> Optional[str]:
    if start_ms in mapping:
        return mapping[start_ms]
    for delta in range(1, max(0, tolerance_ms) + 1):
        for candidate in (start_ms - delta, start_ms + delta):
            if candidate in mapping:
                return mapping[candidate]
    return None


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


def _subtitle_export_payload(path: Path, project: dict, pid: str, suffix: str, container: str) -> dict:
    content = _read_export_text(path)
    filename_suffix = suffix
    if container == "vtt":
        content = srt_to_vtt(content)
        filename_suffix = suffix.removesuffix(".srt") + ".vtt"
    return {
        "content": content,
        "filename": _export_filename(project, pid, filename_suffix),
    }


def _has_video_extension(path_or_name: str) -> bool:
    return Path(path_or_name).suffix.lower() in _VIDEO_UPLOAD_EXTS


def _has_subtitle_extension(path_or_name: str) -> bool:
    return Path(path_or_name).suffix.lower() in _SUBTITLE_UPLOAD_EXTS


def _has_audio_extension(path_or_name: str) -> bool:
    return Path(path_or_name).suffix.lower() in _AUDIO_UPLOAD_EXTS


def _safe_upload_name(filename: Optional[str], fallback: str) -> str:
    raw_name = (filename or "").strip()
    safe_name = raw_name.replace("/", "_").replace("\\", "_")
    if not safe_name or safe_name in (".", ".."):
        safe_name = fallback
    if any(ord(ch) < 32 for ch in safe_name):
        safe_name = "".join("_" if ord(ch) < 32 else ch for ch in safe_name)
    if len(safe_name.encode("utf-8")) > 255:
        suffix = Path(safe_name).suffix
        max_stem_bytes = 255 - len(suffix.encode("utf-8"))
        safe_name = f"{_truncate_filename_stem(Path(safe_name).stem, max_stem_bytes)}{suffix}"
    return safe_name.strip(" ._") or fallback


async def _read_upload_limited(file: UploadFile, *, limit: int, label: str) -> bytes:
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, f"{label} exceeds {limit} bytes")
    if not data:
        raise HTTPException(400, f"{label} is empty")
    return bytes(data)


async def _write_upload_limited(file: UploadFile, dest: Path, *, limit: int, label: str) -> int:
    written = 0
    try:
        with open(dest, "xb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    f.close()
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise HTTPException(413, f"{label} exceeds {limit} bytes")
                f.write(chunk)
    except HTTPException:
        raise
    except Exception:
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
        raise HTTPException(400, f"{label} is empty")
    return written


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
        project = _merge_runtime_progress(pid, _apply_safe_defaults(project))
        return hide_invalid_translation_artifact_fields(project, _project_dir(pid))
    except ValueError as e:
        raise HTTPException(400, str(e))


_RUNNING_PIPELINE_STAGES = {"download", "asr", "translate", "burn"}
_RUNNING_STAGE_PRIORITY = ("burn", "translate", "asr", "download")


def _running_workflow_stage(pid: str) -> Optional[str]:
    try:
        state_path = PROJECTS_DIR / pid / "workflow_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    except Exception:
        return None
    stages = state.get("stages") if isinstance(state, dict) else {}
    if not isinstance(stages, dict):
        return None
    for stage in _RUNNING_STAGE_PRIORITY:
        item = stages.get(stage)
        if isinstance(item, dict) and item.get("status") == "running":
            return stage
    return None


def _merge_runtime_progress(pid: str, project: dict) -> dict:
    """Overlay persisted scheduler progress while a project is actively running.

    Project state is intentionally low-write during long model calls, while
    progress.json is updated frequently for the websocket. GET /api/projects/*
    also backs the frontend polling fallback, so merge the live progress there
    instead of letting stale project.json progress overwrite the websocket view.
    """
    if not isinstance(project, dict):
        return project

    terminal_status = project.get("status") in {"completed", "error"}
    runtime_stage = None if terminal_status else _running_workflow_stage(pid)
    should_merge = (
        project.get("status") == "processing"
        or bool(project.get("pipeline_stage"))
        or bool(runtime_stage)
    )
    if not should_merge:
        return project

    try:
        from app.engines.scheduler import get_progress as _get_runtime_progress

        progress = _get_runtime_progress(pid)
    except Exception:
        return project
    if not isinstance(progress, dict):
        return project

    stage = progress.get("stage")
    effective_stage = runtime_stage or (stage if stage in _RUNNING_PIPELINE_STAGES else None)
    if effective_stage:
        project["pipeline_stage"] = effective_stage
        if project.get("status") not in {"processing", "completed", "error"}:
            project["status"] = "processing"
    if isinstance(progress.get("progress"), int) and not isinstance(progress.get("progress"), bool):
        project["progress"] = max(0, min(100, progress["progress"]))
    message = progress.get("message")
    if isinstance(message, str):
        project["progress_msg"] = message
    return project


def _save_project(pid: str, data: dict):
    atomic_write_json(PROJECTS_DIR / pid / "project.json", data)


def _network_metadata_languages(network_metadata: Optional[dict], key: str) -> list[str]:
    if not isinstance(network_metadata, dict):
        return []
    raw_items = network_metadata.get(key)
    if not isinstance(raw_items, list):
        return []

    languages: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, str):
            continue
        language = raw.strip()
        if not language or language.lower() in {"auto", "und", "unknown", "none", "null"}:
            continue
        normalized = language.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        languages.append(language)
    return languages[:20]


def _network_subtitle_probe_status(
    network_metadata: Optional[dict],
    subtitle_languages: list[str],
    automatic_caption_languages: list[str],
) -> str:
    if subtitle_languages or automatic_caption_languages:
        return "available"
    if isinstance(network_metadata, dict):
        has_subtitles = network_metadata.get("has_subtitles")
        if has_subtitles is True:
            return "available"
        if has_subtitles is False:
            return "not_found"
    return "unknown"


def _network_subtitle_strategy_label(
    status: str,
    subtitle_languages: list[str],
    automatic_caption_languages: list[str],
) -> str:
    if status == "available":
        detected = []
        if subtitle_languages:
            detected.append("原生字幕：" + ", ".join(subtitle_languages))
        if automatic_caption_languages:
            detected.append("自动字幕：" + ", ".join(automatic_caption_languages))
        detected_label = "；".join(detected) if detected else "平台字幕"
        return f"检测到平台字幕（{detected_label}）；会优先下载字幕并翻译，失败再进入 ASR 听写。"
    if status == "not_found":
        return "未检测到平台字幕；下载视频后进入 ASR 听写。"
    return "优先获取平台原生字幕；没有字幕再进入 ASR 听写。"


def _network_video_plan(pdir: Path, network_metadata: Optional[dict] = None) -> dict:
    download_path = pdir / "original.mp4"
    subtitle_languages = _network_metadata_languages(network_metadata, "subtitle_languages")
    automatic_caption_languages = _network_metadata_languages(network_metadata, "automatic_caption_languages")
    subtitle_probe_status = _network_subtitle_probe_status(
        network_metadata,
        subtitle_languages,
        automatic_caption_languages,
    )
    return {
        "save_scope": "project_library",
        "download_filename": "original.mp4",
        "download_path": str(download_path),
        "download_location_label": "项目文件夹 original.mp4",
        "download_path_hint": "~/AI_Sub_Pro_Data/projects/<项目ID>/original.mp4",
        "subtitle_strategy": "native_subtitles_then_asr",
        "subtitle_strategy_label": _network_subtitle_strategy_label(
            subtitle_probe_status,
            subtitle_languages,
            automatic_caption_languages,
        ),
        "subtitle_probe_status": subtitle_probe_status,
        "detected_subtitle_languages": subtitle_languages,
        "detected_automatic_caption_languages": automatic_caption_languages,
        "native_subtitle_priority": True,
    }


def _network_content_metadata(name: str, youtube_url: str, network_metadata: Optional[dict]) -> dict:
    parts: list[str] = []
    has_network_metadata = False
    if isinstance(network_metadata, dict):
        for key in ("title", "uploader", "channel", "extractor_key", "source_type"):
            value = network_metadata.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
                has_network_metadata = True
    if isinstance(name, str) and name.strip():
        parts.append(name.strip())

    try:
        url_path_name = Path(urlparse(str(youtube_url or "")).path).name
    except Exception:
        url_path_name = ""
    if url_path_name:
        parts.append(url_path_name)

    inferred = infer_content_metadata_from_filename(" ".join(parts))
    if inferred.get("metadata_source") == "filename":
        inferred["metadata_source"] = "network_metadata" if has_network_metadata else "url"
    return inferred


def create_trailer_project(
    tmdb_id: Optional[int],
    tmdb_type: Optional[str],
    video_key: Optional[str],
    youtube_url: str,
    original_language: str,
    name: str,
    season_number=None,
    parent_project_id=None,
    asr_language: str = "auto",
    target_language: str = "简体中文",
    network_metadata: Optional[dict] = None,
    workflow_mode: str = "translate_burn",
) -> dict:
    """Create a new trailer-source project directory + project.json.

    Returns the full project dict. Does not register an HTTP route; callers
    (e.g. the trailer pipeline) invoke this helper directly.
    """
    pid = _new_project_id()
    pdir = PROJECTS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)
    network_metadata = network_metadata if isinstance(network_metadata, dict) else {}
    inferred_content_metadata = _network_content_metadata(name, youtube_url, network_metadata)

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
        "network_metadata": network_metadata,
        "network_video_plan": _network_video_plan(pdir, network_metadata),
        "source_title": network_metadata.get("title"),
        "source_uploader": network_metadata.get("uploader"),
        "source_channel": network_metadata.get("channel"),
        "source_duration": network_metadata.get("duration"),
        "source_webpage_url": network_metadata.get("webpage_url"),
        "source_extractor": network_metadata.get("extractor_key"),
        "source_language": network_metadata.get("language"),
        "source_has_subtitles": bool(network_metadata.get("has_subtitles")),
        "subtitle_source": None,
        "native_subtitle_language": None,
        "content_type": inferred_content_metadata.get("content_type", "auto"),
        "academic_field": inferred_content_metadata.get("academic_field", ""),
        "metadata_source": inferred_content_metadata.get("metadata_source", ""),
        # Trailer-specific
        "source_type": "trailer",
        "tmdb_id": tmdb_id,
        "tmdb_type": tmdb_type,
        "season_number": season_number,
        "tmdb_video_key": video_key,
        "youtube_url": youtube_url,
        "original_language": original_language,
        "auto_run": True,
        "workflow_mode": _normalize_workflow_mode(workflow_mode),
        "parent_project_id": parent_project_id,
        "pipeline_stage": "download",
        "archived": False,
    }

    project = _apply_safe_defaults(project)
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
                    project = hide_invalid_translation_artifact_fields(project, pdir)
                    if project.get("archived") and not include_archived:
                        continue
                    projects.append(project)
            except Exception:
                pass
    return projects


@router.post("")
async def create_project(req: CreateProjectReq):
    """Create a new project from a video file.

    Filename/content metadata is inferred first. TMDB is then used only as
    best-effort film/TV enrichment, so lectures/tutorials are not forced
    through an entertainment metadata path.
    """
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
    inferred_metadata = infer_content_metadata_from_filename(name)
    requested_content_type = normalize_content_type(req.content_type)
    has_manual_metadata = any(
        isinstance(value, str) and value.strip()
        for value in (
            req.content_type,
            req.academic_field,
            req.content_notes,
            req.manual_terms,
        )
    )
    content_type = (
        requested_content_type
        if requested_content_type != "auto"
        else inferred_metadata.get("content_type", "auto")
    )
    academic_field = _text_default(
        req.academic_field,
        inferred_metadata.get("academic_field", ""),
    )
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
        "content_type": content_type,
        "academic_field": academic_field,
        "content_notes": (req.content_notes or "").strip() if isinstance(req.content_notes, str) else "",
        "manual_terms": (req.manual_terms or "").strip() if isinstance(req.manual_terms, str) else "",
        "metadata_source": "manual" if has_manual_metadata else inferred_metadata.get("metadata_source", ""),
    }
    project = _apply_safe_defaults(project)

    # TMDB enrichment from filename. Best-effort: any failure (no key,
    # network, no parse) leaves the project as-is; UI can manually link later.
    try:
        if not should_skip_tmdb_enrichment(project):
            from app.engines.tmdb_enrich import enrich_from_filename
            enrich = await enrich_from_filename(name)
            if enrich.get("auto_attached"):
                project["tmdb_id"] = enrich["tmdb_id"]
                project["tmdb_type"] = enrich["tmdb_type"]
                project["season_number"] = enrich.get("season_number")
                project["show_title"] = enrich.get("show_title")
                project["original_language"] = enrich.get("original_language")
                project["poster_path"] = enrich.get("poster_path")
                if project.get("content_type") == "auto":
                    project["content_type"] = "series" if enrich.get("tmdb_type") == "tv" else "movie"
                    if not project.get("metadata_source"):
                        project["metadata_source"] = "tmdb"
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


@router.post("/discover-local-videos")
async def discover_local_videos(req: DiscoverLocalVideosReq):
    """Return supported local video files inside a user-selected folder."""
    raw_folder = str(req.folder_path or "").strip()
    if not raw_folder:
        raise HTTPException(400, "Folder path is required")

    folder = Path(raw_folder).expanduser()
    if not folder.exists():
        raise HTTPException(400, f"Folder not found: {raw_folder}")
    if not folder.is_dir():
        raise HTTPException(400, f"Path is not a folder: {raw_folder}")

    limit = req.limit if isinstance(req.limit, int) else 200
    limit = max(1, min(limit, 500))
    try:
        root = folder.resolve()
    except OSError:
        raise HTTPException(400, f"Folder is not accessible: {raw_folder}")

    try:
        iterator = root.rglob("*") if req.recursive else root.iterdir()
        candidates = sorted(iterator, key=lambda p: str(p).lower())
    except OSError as exc:
        raise HTTPException(400, f"Folder is not accessible: {exc}")

    videos = []
    truncated = False
    for candidate in candidates:
        if len(videos) >= limit:
            truncated = True
            break
        try:
            if candidate.name.startswith(".") or not candidate.is_file():
                continue
            if candidate.suffix.lower() not in _VIDEO_UPLOAD_EXTS:
                continue
            stat = candidate.stat()
            if stat.st_size <= 0:
                continue
        except OSError:
            continue
        videos.append({
            "path": str(candidate),
            "name": candidate.name,
            "size": stat.st_size,
        })

    return {
        "folder_path": str(root),
        "recursive": bool(req.recursive),
        "limit": limit,
        "truncated": truncated,
        "count": len(videos),
        "videos": videos,
    }


@router.post("/import-subtitle")
async def import_subtitle_project(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    original_language: Optional[str] = Form(None),
    target_language: Optional[str] = Form(None),
    content_type: Optional[str] = Form(None),
    academic_field: Optional[str] = Form(None),
    content_notes: Optional[str] = Form(None),
    manual_terms: Optional[str] = Form(None),
):
    """Create a subtitle-only project from an uploaded subtitle file."""
    safe_name = _safe_upload_name(file.filename, "subtitles.srt")
    if not _has_subtitle_extension(safe_name):
        raise HTTPException(400, "Subtitle file must use an SRT, VTT, ASS, or SSA extension")

    data = await _read_upload_limited(
        file,
        limit=MAX_SUBTITLE_UPLOAD_BYTES,
        label="Subtitle file",
    )
    subtitle_ext = Path(safe_name).suffix.lower()
    if subtitle_ext == ".vtt":
        blocks = parse_vtt(data)
    elif subtitle_ext in {".ass", ".ssa"}:
        blocks = parse_ass(data)
    else:
        blocks = parse_srt(data)
    if not blocks:
        raise HTTPException(400, "Subtitle file must contain valid subtitle blocks")

    pid = _new_project_id()
    pdir = PROJECTS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)

    display_name = _text_default(name, safe_name)
    target_lang = _text_default(target_language, "简体中文")
    inferred_metadata = infer_content_metadata_from_filename(display_name)
    requested_content_type = normalize_content_type(content_type)
    has_manual_metadata = any(
        isinstance(value, str) and value.strip()
        for value in (content_type, academic_field, content_notes, manual_terms)
    )
    resolved_content_type = (
        requested_content_type
        if requested_content_type != "auto"
        else inferred_metadata.get("content_type", "auto")
    )
    duration = max((block.end.total_seconds() for block in blocks), default=0)

    write_srt(blocks, str(pdir / "raw.srt"))
    write_srt(blocks, str(pdir / "filtered.srt"))

    project = {
        "id": pid,
        "name": display_name,
        "video_path": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "created",
        "progress": 0,
        "progress_msg": "",
        "duration": round(duration, 1),
        "audio_tracks": [],
        "subtitle_tracks": [],
        "selected_audio_track": 0,
        "selected_subtitle_track": None,
        "prefer_embedded_subtitle": False,
        "asr_language": _text_default(original_language, "auto"),
        "target_language": target_lang,
        "error": None,
        "output_video": None,
        "source_type": "subtitle",
        "original_language": _text_default(original_language, ""),
        "source_title": display_name,
        "source_language": _text_default(original_language, ""),
        "source_has_subtitles": True,
        "subtitle_source": f"uploaded_{subtitle_ext.lstrip('.')}" if subtitle_ext != ".srt" else "uploaded",
        "native_subtitle_language": _text_default(original_language, ""),
        "asr_skipped": True,
        "content_type": resolved_content_type,
        "academic_field": _text_default(
            academic_field,
            inferred_metadata.get("academic_field", ""),
        ),
        "content_notes": (content_notes or "").strip() if isinstance(content_notes, str) else "",
        "manual_terms": (manual_terms or "").strip() if isinstance(manual_terms, str) else "",
        "metadata_source": "manual" if has_manual_metadata else inferred_metadata.get("metadata_source", ""),
    }
    project = _apply_safe_defaults(project)
    _save_project(pid, project)
    return project


@router.post("/import-audio")
async def import_audio_project(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    original_language: Optional[str] = Form(None),
    target_language: Optional[str] = Form(None),
    content_type: Optional[str] = Form(None),
    academic_field: Optional[str] = Form(None),
    content_notes: Optional[str] = Form(None),
    manual_terms: Optional[str] = Form(None),
):
    """Create an ASR-ready project from an uploaded audio file."""
    safe_name = _safe_upload_name(file.filename, "audio.mp3")
    if not _has_audio_extension(safe_name):
        raise HTTPException(400, "Uploaded audio file must use an audio extension")

    pid = _new_project_id()
    pdir = PROJECTS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)
    ext = Path(safe_name).suffix.lower()
    audio_path = pdir / f"original{ext}"

    try:
        await _write_upload_limited(
            file,
            audio_path,
            limit=MAX_AUDIO_UPLOAD_BYTES,
            label="Audio file",
        )
    except Exception:
        try:
            shutil.rmtree(pdir, ignore_errors=True)
        except Exception:
            pass
        raise

    display_name = _text_default(name, safe_name)
    target_lang = _text_default(target_language, "简体中文")
    source_lang = _text_default(original_language, "")
    asr_lang = _text_default(original_language, "auto")
    inferred_metadata = infer_content_metadata_from_filename(display_name)
    requested_content_type = normalize_content_type(content_type)
    has_manual_metadata = any(
        isinstance(value, str) and value.strip()
        for value in (content_type, academic_field, content_notes, manual_terms)
    )
    resolved_content_type = (
        requested_content_type
        if requested_content_type != "auto"
        else inferred_metadata.get("content_type", "auto")
    )

    audio_tracks = get_tracks(str(audio_path), "a")
    if not audio_tracks:
        audio_tracks = [{
            "index": 0,
            "codec": ext.lstrip(".") or "unknown",
            "lang": source_lang or "und",
            "title": "",
            "channels": 0,
            "sample_rate": "",
        }]
    duration = get_duration(str(audio_path))

    project = {
        "id": pid,
        "name": display_name,
        "video_path": str(audio_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "created",
        "progress": 0,
        "progress_msg": "",
        "duration": round(duration, 1),
        "audio_tracks": audio_tracks,
        "subtitle_tracks": [],
        "selected_audio_track": 0,
        "selected_subtitle_track": None,
        "prefer_embedded_subtitle": False,
        "asr_language": asr_lang,
        "target_language": target_lang,
        "error": None,
        "output_video": None,
        "source_type": "audio",
        "original_language": source_lang,
        "source_title": display_name,
        "source_language": source_lang,
        "source_duration": round(duration, 1),
        "source_has_subtitles": False,
        "subtitle_source": None,
        "native_subtitle_language": "",
        "asr_skipped": False,
        "content_type": resolved_content_type,
        "academic_field": _text_default(
            academic_field,
            inferred_metadata.get("academic_field", ""),
        ),
        "content_notes": (content_notes or "").strip() if isinstance(content_notes, str) else "",
        "manual_terms": (manual_terms or "").strip() if isinstance(manual_terms, str) else "",
        "metadata_source": "manual" if has_manual_metadata else inferred_metadata.get("metadata_source", ""),
    }
    project = _apply_safe_defaults(project)
    _save_project(pid, project)
    return project


@router.get("/{pid}")
def get_project(pid: str = PathParam(pattern=PID_PATTERN)):
    """Get project detail."""
    return _load_project(pid)


@router.get("/{pid}/workflow-state")
def get_workflow_state(pid: str = PathParam(pattern=PID_PATTERN)):
    """Get structured workflow state for a project."""
    _load_project(pid)
    return load_workflow_state(pid)


@router.get("/{pid}/translation-strategy")
def get_translation_strategy(pid: str = PathParam(pattern=PID_PATTERN)):
    """Explain which translation strategy metadata will apply to a project."""
    project = _load_project(pid)
    return build_translation_strategy(project, Config.to_dict())


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
    "content_type",
    "academic_field",
    "content_notes",
    "manual_terms",
    "metadata_source",
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
    "content_type",
    "academic_field",
    "content_notes",
    "manual_terms",
    "metadata_source",
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
    content_type: Optional[str] = None
    academic_field: Optional[str] = None
    content_notes: Optional[str] = None
    manual_terms: Optional[str] = None
    metadata_source: Optional[str] = None
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

    content_type = payload.get("content_type")
    if "content_type" in payload and content_type not in CONTENT_TYPE_OPTIONS:
        raise ValueError("invalid content_type")

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
    for field in (
        "name",
        "content_type",
        "academic_field",
        "content_notes",
        "manual_terms",
        "metadata_source",
    ):
        if isinstance(payload.get(field), str):
            payload[field] = payload[field].strip()

    def _apply(project):
        _validate_project_patch(project, payload)
        for k, v in payload.items():
            if k in _PATCHABLE_FIELDS:
                project[k] = v
        for k in (req.clear or []):
            if k == "content_type":
                project[k] = "auto"
            elif k in {"academic_field", "content_notes", "manual_terms", "metadata_source"}:
                project[k] = ""
            elif k in _CLEARABLE_FIELDS:
                project[k] = None

    with translation_delivery_lock(pid, blocking=False) as acquired:
        if not acquired:
            raise HTTPException(
                409,
                "Project state update is temporarily unavailable",
            )
        from app.api.translate import is_task_launch_pending

        if is_task_launch_pending(pid):
            raise HTTPException(
                409,
                "Project task launch is still being committed",
            )
        try:
            return mutate_project(
                pid,
                _apply,
                normalize=_apply_safe_defaults,
            )
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
    """Get one delivery-locked snapshot of current subtitle blocks."""
    with translation_delivery_lock(pid, blocking=False) as acquired:
        if not acquired:
            raise HTTPException(
                409,
                "Translation delivery is being committed",
            )
        return _get_subtitles_locked(pid)


def _get_subtitles_locked(pid: str):
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
    trans_blocks = []
    validation = validate_translation_delivery(project, pdir)
    if validation.expects_certification and not validation.valid:
        raise HTTPException(409, validation.message)
    if validation.valid and trans_path.exists():
        try:
            trans_blocks = parse_srt_file(str(trans_path))
        except Exception as e:
            log.warning(
                "Could not parse translated subtitles for %s: %s",
                pid,
                e,
            )
    if trans_blocks:
        trans_by_time = {}
        for tb in trans_blocks:
            key = _subtitle_time_ms(tb.start)
            trans_by_time[key] = tb.text
        for b in blocks:
            translation = _lookup_subtitle_time(trans_by_time, _subtitle_time_ms(b.start))
            if translation is not None:
                b.translation = translation

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

    return {
        "blocks": [_subtitle_editor_payload(block) for block in blocks],
        "source": source_name,
    }


@router.get("/{pid}/quality-report")
def get_quality_report(pid: str = PathParam(pattern=PID_PATTERN)):
    """Return the latest translation QA report for a project."""
    pdir = _project_dir(pid)
    with translation_delivery_lock(pid, blocking=False) as acquired:
        if not acquired:
            raise HTTPException(409, "Translation delivery is in progress or invalid")
        project = _load_project(pid)
        if translation_delivery_is_invalid(pdir):
            raise HTTPException(409, "Translation delivery is in progress or invalid")
        path = pdir / "translation_qa_report.json"
        if not path.exists():
            return {"status": "missing", "issues": [], "summary": {"issue_count": 0}}
        validation = validate_translation_delivery(
            project,
            pdir,
            require_passed=False,
        )
        if not validation.valid or validation.report is None:
            return _invalid_quality_report_payload(validation.message, project)
        return validation.report


def _invalid_quality_report_payload(message: str, project: dict) -> dict:
    policy = project.get("translation_quality_policy")
    if policy not in {"fast", "strict"}:
        policy = "strict"
    detail = message.strip() or "翻译质量检查报告无效，已停止交付。"
    return {
        "status": "invalid",
        "validation_message": detail,
        "issues": [],
        "unresolved_blocks": [],
        "summary": {
            "issue_count": 0,
            "error_count": 0,
            "warning_count": 0,
            "unresolved_blocks": 0,
            "conclusion": detail,
            "quality_gate": {
                "policy": policy,
                "verdict": "failed",
                "passed": False,
                "requires_human_review": False,
                "delivery_mode": "unattended",
                "unresolved_blocks": 0,
                "next_action": "auto_retry_or_stop",
            },
        },
    }


@router.put("/{pid}/subtitles")
def save_subtitles(data: SubtitleEdit, pid: str = PathParam(pattern=PID_PATTERN)):
    """Save edited subtitles."""
    with translation_delivery_lock(pid, blocking=False) as acquired:
        if not acquired:
            raise HTTPException(409, "Translation delivery is in progress or invalid")
        with get_project_lock(pid):
            project = _load_project(pid)
            pdir = _project_dir(pid)
            if translation_delivery_is_invalid(pdir):
                raise HTTPException(409, "Translation delivery is in progress or invalid")
            from app.api.translate import is_task_registered
            if (
                project.get("status") == "processing"
                or bool(project.get("pipeline_stage"))
                or is_task_registered(pid)
            ):
                raise HTTPException(
                    409,
                    "Project is processing; subtitle edits are disabled",
                )
            return _save_subtitles_locked(data, pid, project, pdir)


def _subtitle_edit_stage_path(pdir: Path, final_name: str) -> Path:
    return pdir / f".{final_name}.{uuid.uuid4().hex}.subtitle-edit.tmp"


def _snapshot_subtitle_edit_paths(
    paths: list[Path],
) -> dict[Path, Optional[bytes]]:
    snapshots = {}
    for path in paths:
        if path.is_symlink() or path.is_dir():
            raise RuntimeError(f"invalid subtitle edit target: {path.name}")
        snapshots[path] = path.read_bytes() if path.is_file() else None
    return snapshots


def _restore_subtitle_edit_path(path: Path, content: Optional[bytes]) -> None:
    if content is None:
        durable_unlink(path)
        return
    handle = tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.restore.",
        suffix=".tmp",
        delete=False,
    )
    staged = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
        durable_replace(staged, path)
    finally:
        if staged.exists():
            staged.unlink()


def _stale_subtitle_edit_project(project: dict) -> dict:
    updated = _apply_safe_defaults(dict(project))
    updated.update({
        "translation_quality_status": "stale",
        "translation_quality_message": "字幕已编辑，需要重新运行翻译质量检查。",
        "translation_quality_content_hash": "",
        "translation_quality_source_generation_hash": "",
    })
    return updated


def _verify_subtitle_edit_stages(stages: dict[Path, Path]) -> None:
    for final_path, stage_path in stages.items():
        if stage_path.is_symlink() or not stage_path.is_file():
            raise RuntimeError(
                f"subtitle edit staging verification failed: {final_path.name}"
            )
        if final_path.suffix == ".srt":
            parse_srt_file(str(stage_path))
        elif final_path.suffix == ".json":
            value = json.loads(stage_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise RuntimeError(
                    f"subtitle edit staging verification failed: {final_path.name}"
                )


def _save_subtitles_locked(
    data: SubtitleEdit,
    pid: str,
    project: dict,
    pdir: Path,
):
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

    source_path = _editable_source_srt_path(pdir)
    source_keeps_filter_state = source_path.name != "filtered.srt"
    filter_path = pdir / "filter_state.json"
    write_filter_state = source_keeps_filter_state or filter_path.exists()
    translated_path = pdir / "translated.srt"
    bilingual_path = pdir / "bilingual.srt"
    project_path = pdir / "project.json"
    report_path = pdir / "translation_qa_report.json"
    quality_policy = project.get("translation_quality_policy")
    updated_project = project
    if (
        quality_policy == "strict"
        or report_path.is_file()
        or project.get("translation_quality_status")
    ):
        updated_project = _stale_subtitle_edit_project(project)

    final_paths = [source_path]
    if write_filter_state:
        final_paths.append(filter_path)
    final_paths.extend([translated_path, bilingual_path, project_path])
    snapshots = _snapshot_subtitle_edit_paths(final_paths)
    stages = {
        path: _subtitle_edit_stage_path(pdir, path.name)
        for path in final_paths
    }
    promoted: list[Path] = []
    sentinel = mark_translation_delivery_invalid(pdir)
    try:
        _write_editable_source_srt(
            blocks,
            stages[source_path],
            include_filtered=source_keeps_filter_state,
        )
        if write_filter_state:
            _write_filter_state(blocks, stages[filter_path])
        write_srt(
            blocks,
            str(stages[translated_path]),
            use_translation=True,
        )
        write_bilingual_srt(blocks, str(stages[bilingual_path]))
        atomic_write_json(stages[project_path], updated_project)
        _verify_subtitle_edit_stages(stages)
        promoted.extend(final_paths)
        promote_staged_files([
            (stages[final_path], final_path)
            for final_path in final_paths
        ])
        durable_unlink(sentinel)
    except Exception:
        rollback_errors = []
        if not translation_delivery_is_invalid(pdir):
            try:
                mark_translation_delivery_invalid(pdir)
            except Exception as sentinel_error:
                rollback_errors.append(sentinel_error)
        for final_path in reversed(promoted):
            try:
                _restore_subtitle_edit_path(
                    final_path,
                    snapshots[final_path],
                )
            except Exception as rollback_error:
                rollback_errors.append(rollback_error)
        try:
            mutate_project(
                pid,
                lambda current: current.update(
                    _stale_subtitle_edit_project(current)
                ),
                normalize=_apply_safe_defaults,
            )
        except Exception as stale_error:
            rollback_errors.append(stale_error)
        if rollback_errors:
            log.error(
                "subtitle edit rollback incomplete for %s: %s",
                pid,
                "; ".join(str(error) for error in rollback_errors),
            )
        raise
    finally:
        for stage_path in stages.values():
            try:
                if stage_path.exists():
                    stage_path.unlink()
            except OSError:
                pass
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

    response = {
        "status": "ok",
        "count": len(blocks),
        "blocks": [_subtitle_editor_payload(block) for block in blocks],
    }
    for field in (
        "translation_quality_policy",
        "translation_quality_status",
        "translation_quality_message",
        "translation_quality_run_id",
        "translation_quality_content_hash",
    ):
        response[field] = updated_project.get(field)
    return response


@router.post("/{pid}/export")
def export_srt(
    pid: str = PathParam(pattern=PID_PATTERN),
    format: str = "translated",
    container: str = "srt",
):
    """Export final subtitle file."""
    if format not in {"original", "bilingual", "translated"}:
        raise HTTPException(400, "invalid format")
    if container not in {"srt", "vtt"}:
        raise HTTPException(400, "invalid container")

    pdir = _project_dir(pid)

    if format == "original":
        project = _load_project(pid)
        for fname in ["filtered.srt", "raw.srt", "native.srt"]:
            if (pdir / fname).is_file():
                return _subtitle_export_payload(pdir / fname, project, pid, ".srt", container)
        raise HTTPException(404, "No subtitle file available for export")

    with translation_delivery_lock(pid, blocking=False) as acquired:
        if not acquired:
            raise HTTPException(
                409,
                "Translation delivery is in progress or invalid",
            )
        project = _load_project(pid)
        validation = validate_translation_delivery(project, pdir)
        if not validation.valid:
            raise HTTPException(
                409,
                f"Translation quality gate rejected export: {validation.message}",
            )

        if format == "bilingual":
            if (pdir / "bilingual.srt").is_file():
                return _subtitle_export_payload(
                    pdir / "bilingual.srt",
                    project,
                    pid,
                    ".bilingual.srt",
                    container,
                )
        elif (pdir / "translated.srt").is_file():
            return _subtitle_export_payload(
                pdir / "translated.srt",
                project,
                pid,
                ".translated.srt",
                container,
            )

        raise HTTPException(404, "No subtitle file available for export")
