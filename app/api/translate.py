"""
Translation pipeline control API routes.
Handles long-running ASR and translation tasks.
"""
import os
import json
import asyncio
import logging
import math
import re
import tempfile
import threading
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException, Path as PathParam
from pydantic import BaseModel, Field, StrictInt
from typing import Optional

from app.config import Config, PROJECTS_DIR
from app.utils.srt import write_srt, SubtitleBlock, fmt_time
from app.utils.media import (
    SubtitleTrack,
    burn_subtitles,
    compute_font_sizes,
    resolve_font,
)
from app.api.settings import require_translation_ready
from app.api.projects import (
    _apply_safe_defaults,
    _is_forced_or_commentary_subtitle,
    _pick_subtitle_track,
)
from app.utils.project_store import atomic_write_json, mutate_project, PID_PATTERN, project_dir
from app.engines.kb_trace import write_kb_usage_trace
from app.engines.scheduler import (
    get_progress as _scheduler_get_progress,
    update_progress as _scheduler_update_progress,
    progress_store,  # re-export for compatibility with older internal imports
    slot,
    is_cancelled,
    reset_cancel,
    request_cancel,
)
from app.engines.workflow_state import (
    cancel_workflow,
    fail_stage,
    finish_stage,
    load_workflow_state,
    reset_workflow,
    save_workflow_state,
    start_stage,
)
from app.utils.errors import redact_error_message

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["pipeline"])

# Active tasks tracker
active_tasks: Dict[str, threading.Thread] = {}
_tasks_lock = threading.Lock()
_SOUND_DESCRIPTION_RE = re.compile(r"^\s*[-–—]?\s*\[[^\]]+\]\s*$")
_KB_REVIEW_REQUIRED_CODE = "kb_review_required"
_QA_AUTO_REPAIR_MAX_BLOCKS = 20
_QA_REPORT_ONLY_WARNING_TYPES = {
    "proper_name_inconsistent",
    "scientific_term_inconsistent",
}
_QA_EXPECTED_REPAIRABLE_WARNING_TYPES = {
    "proper_name_inconsistent",
    "scientific_term_inconsistent",
}


class TaskCancelled(RuntimeError):
    """Raised when a user-requested cancellation reaches a worker checkpoint."""


def _safe_error_message(exc, limit: int = 200) -> str:
    return redact_error_message(exc, limit)


class TaskAlreadyRunning(Exception):
    """Raised when a pipeline task is already registered for a project."""

    def __init__(self, pid: str):
        super().__init__(f"task already running for {pid}")
        self.pid = pid


def try_register_task(pid: str, factory, *, reset_cancellation: bool = False):
    """Atomically register a pipeline thread for `pid`.

    Raises TaskAlreadyRunning if one is already registered. The returned thread
    is NOT started — the caller starts it after this returns.
    """
    with _tasks_lock:
        if pid in active_tasks:
            raise TaskAlreadyRunning(pid)
        if reset_cancellation:
            reset_cancel(pid)
        t = factory()
        active_tasks[pid] = t
    return t


def unregister_task(pid: str) -> None:
    """Remove `pid` from the active-task registry (safe if absent)."""
    with _tasks_lock:
        active_tasks.pop(pid, None)


def is_task_registered(pid: str) -> bool:
    with _tasks_lock:
        return pid in active_tasks


def _emit_progress(pid: str, stage: str, local_pct: int, msg: str) -> None:
    """Route progress through scheduler (locked + persisted + stage-mapped)."""
    _scheduler_update_progress(pid, stage=stage, local_pct=local_pct, msg=msg)


def _check_cancel(pid: str) -> None:
    """Raise if the user requested cancellation for this pid."""
    if is_cancelled(pid):
        raise TaskCancelled(f"cancelled by user pid={pid}")


def _is_task_cancelled(exc: BaseException) -> bool:
    if isinstance(exc, TaskCancelled):
        return True
    message = str(exc).lower()
    return "cancelled by user" in message or "canceled by user" in message


def _resolve_filter_language(lang, original_language, blocks):
    """Resolve language used by downstream filter logic.

    Priority:
      1. Explicit non-auto language
      2. original_language from project (e.g., from TMDB)
      3. Auto-detect from block texts
      4. Fallback 'ja' (legacy behavior for filter compatibility)
    """
    if lang and lang != "auto":
        return lang
    if original_language:
        return original_language
    texts = [b.text for b in blocks if not getattr(b, "filtered", False) and getattr(b, "text", "")]
    if texts:
        from app.utils.text import detect_language_hint
        hint = detect_language_hint(texts)
        if hint and hint != "auto":
            return hint
    return "ja"


class ASRRequest(BaseModel):
    audio_track: Optional[StrictInt] = None
    language: Optional[str] = None


class TranslateRequest(BaseModel):
    target_language: Optional[str] = None


class FullPipelineRequest(BaseModel):
    audio_track: Optional[StrictInt] = None
    language: Optional[str] = None
    target_language: Optional[str] = None
    workflow_mode: Optional[str] = None


class RetryRequest(BaseModel):
    stage: Optional[str] = None


def _load_project(pid: str) -> dict:
    from app.utils.project_store import load_project as _ps_load_project
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
        return _apply_safe_defaults(project)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _reject_busy_project(project: dict) -> None:
    if project.get("status") == "processing" or project.get("pipeline_stage"):
        raise HTTPException(409, "Project is already running")


def _safe_project_artifact_path(pid: str, filename: str) -> Optional[Path]:
    rel = Path(filename)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    try:
        pdir = project_dir(pid)
        candidate = pdir / rel
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(pdir) or not resolved.is_file():
        return None
    return resolved


def _first_safe_project_artifact(pid: str, filenames: list[str]) -> tuple[Optional[str], Optional[Path]]:
    for filename in filenames:
        path = _safe_project_artifact_path(pid, filename)
        if path is not None:
            return filename, path
    return None, None


def _remove_safe_project_files(pid: str, filenames: list[str]) -> None:
    pdir = project_dir(pid)
    for filename in filenames:
        rel = Path(filename)
        if rel.is_absolute() or ".." in rel.parts:
            continue
        path = pdir / rel
        try:
            if path.is_symlink():
                log.warning("refusing to remove symlink artifact pid=%s file=%s", pid, filename)
                continue
            if path.is_file():
                path.unlink()
        except OSError as e:
            log.warning("failed to remove stale artifact pid=%s file=%s: %s", pid, filename, e)


def _project_source_type(project: dict) -> str:
    value = project.get("source_type") if isinstance(project, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else "upload"


def _project_supports_video_burn(project: dict) -> bool:
    return _project_source_type(project) not in {"audio", "subtitle"}


_WORKFLOW_MODES = {"translate_burn", "translate_only"}


def _resolve_workflow_mode(value, project: dict, *, can_burn: bool = True) -> str:
    raw = value
    if raw is None and isinstance(project, dict):
        raw = project.get("workflow_mode")
    if isinstance(raw, str) and raw.strip():
        mode = raw.strip()
        if mode not in _WORKFLOW_MODES:
            raise HTTPException(400, "workflow_mode must be translate_burn or translate_only")
    else:
        mode = "translate_burn"
    return mode if can_burn else "translate_only"


def _safe_generated_project_output_path(pid: str, filename: str) -> Optional[Path]:
    rel = Path(filename)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    try:
        pdir = project_dir(pid)
        path = pdir / rel
        if not path.parent.resolve(strict=True).is_relative_to(pdir):
            return None
        if path.is_symlink():
            log.warning(
                "refusing to overwrite symlinked generated output pid=%s file=%s",
                pid,
                filename,
            )
            return None
        if path.exists() and not path.is_file():
            log.warning(
                "refusing to overwrite non-regular generated output pid=%s file=%s",
                pid,
                filename,
            )
            return None
    except (OSError, ValueError) as e:
        log.warning("failed to resolve generated output pid=%s file=%s: %s", pid, filename, e)
        return None
    return path


def _write_generated_project_artifact(
    pid: str,
    filename: str,
    data: bytes,
    pdir: Path,
) -> Optional[Path]:
    rel = Path(filename)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    tmp: Optional[Path] = None
    try:
        path = pdir / rel
        if path.is_symlink():
            log.warning(
                "refusing to overwrite symlinked generated artifact pid=%s file=%s",
                pid,
                filename,
            )
            return None
        if path.exists() and not path.is_file():
            log.warning(
                "refusing to overwrite non-regular generated artifact pid=%s file=%s",
                pid,
                filename,
            )
            return None
        if not path.parent.resolve().is_relative_to(pdir):
            return None
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp = Path(f.name)
            f.write(data)
        os.replace(tmp, path)
        tmp = None
    except (OSError, ValueError) as e:
        log.warning("failed to write generated artifact pid=%s file=%s: %s", pid, filename, e)
        return None
    finally:
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return _safe_project_artifact_path(pid, filename)


def _latest_failed_stage(pid: str) -> str:
    state = load_workflow_state(pid)
    stages = state.get("stages", {}) if isinstance(state, dict) else {}
    if isinstance(stages, dict):
        for stage in ("burn", "translate", "asr", "download"):
            item = stages.get(stage)
            if isinstance(item, dict) and item.get("status") == "failed":
                return stage
    return "asr"


def _resume_stage_for_project(pid: str, project: Optional[dict] = None) -> str:
    if isinstance(project, dict) and project.get("translation_quality_status") == "needs_review":
        return "translate"
    if _project_supports_video_burn(project or {}) and _first_safe_project_artifact(pid, ["translated.srt", "bilingual.srt"])[0]:
        return "burn"
    if _first_safe_project_artifact(pid, ["filtered.srt", "raw.srt", "native.srt"])[0]:
        return "translate"
    if _project_source_type(project or {}) == "subtitle":
        return "translate"
    return "asr"


def _add_launch_stage(response: dict, stage: str) -> dict:
    body = dict(response)
    body["stage"] = stage
    return body


def _persist_workflow_options(
    pid: str,
    *,
    audio_track: Optional[int] = None,
    language: Optional[str] = None,
    target_language: Optional[str] = None,
    workflow_mode: Optional[str] = None,
) -> None:
    """Persist manually selected run options before launching a worker."""
    def _apply(project: dict) -> None:
        if audio_track is not None:
            project["selected_audio_track"] = audio_track
        if language is not None:
            project["asr_language"] = language
        if target_language is not None:
            project["target_language"] = target_language
        if workflow_mode is not None:
            project["workflow_mode"] = workflow_mode

    mutate_project(pid, _apply, normalize=_apply_safe_defaults)


def _reset_workflow_for_action(pid: str, action: str) -> dict:
    stages_by_action = {
        "asr": ["asr"],
        "translate": ["translate"],
        "asr_translate": ["asr", "translate"],
        "full": ["asr", "translate", "burn"],
        "burn": ["burn"],
    }
    try:
        stages = stages_by_action[action]
    except KeyError as exc:
        raise ValueError(f"unknown workflow action: {action!r}") from exc
    existing = load_workflow_state(pid)
    existing_stages = existing.get("stages", {}) if isinstance(existing, dict) else {}
    retry_counts = {}
    if isinstance(existing_stages, dict):
        for stage in stages:
            item = existing_stages.get(stage)
            retry_count = item.get("retry_count") if isinstance(item, dict) else None
            if isinstance(retry_count, int) and not isinstance(retry_count, bool) and retry_count > 0:
                retry_counts[stage] = retry_count

    state = reset_workflow(pid, stages)
    if not retry_counts:
        return state

    for stage, retry_count in retry_counts.items():
        state["stages"][stage]["retry_count"] = retry_count
    return save_workflow_state(pid, state)


def _resolve_cancel_stage(pid: str, project: dict) -> str:
    raw_stage = project.get("pipeline_stage")
    if raw_stage in {"download", "asr", "translate", "burn"}:
        return raw_stage

    try:
        state = load_workflow_state(pid)
    except Exception as e:
        log.warning("workflow load failed while resolving cancel stage pid=%s: %s", pid, e)
        return "asr"

    stages = state.get("stages", {}) if isinstance(state, dict) else {}
    if not isinstance(stages, dict):
        return "asr"

    for stage in ("burn", "translate", "asr", "download"):
        item = stages.get(stage)
        if isinstance(item, dict) and item.get("status") == "running":
            return stage

    for stage in ("download", "asr", "translate", "burn"):
        item = stages.get(stage)
        if isinstance(item, dict) and item.get("status") != "succeeded":
            return stage

    single_stage = [
        (stage, item)
        for stage, item in stages.items()
        if stage in {"download", "asr", "translate", "burn"} and isinstance(item, dict)
    ]
    if len(single_stage) == 1 and single_stage[0][1].get("status") == "pending":
        return single_stage[0][0]

    return "asr"


def _workflow_stage_with_status(pid: str, statuses: set[str]) -> Optional[str]:
    try:
        state = load_workflow_state(pid)
    except Exception as e:
        log.warning("workflow load failed while resolving status stage pid=%s: %s", pid, e)
        return None
    stages = state.get("stages", {}) if isinstance(state, dict) else {}
    if not isinstance(stages, dict):
        return None
    for stage in ("burn", "translate", "asr", "download"):
        item = stages.get(stage)
        if isinstance(item, dict) and item.get("status") in statuses:
            return stage
    return None


def _stage_for_cancelled_exception(pid: str, fallback_stage: str) -> str:
    project = _load_project(pid)
    raw_stage = project.get("pipeline_stage")
    return (
        _workflow_stage_with_status(pid, {"cancelled"})
        or (raw_stage if raw_stage in {"download", "asr", "translate", "burn"} else None)
        or _workflow_stage_with_status(pid, {"running"})
        or fallback_stage
    )


def _best_effort_start_stage(pid: str, stage: str, *, input_artifact: str = "") -> None:
    try:
        start_stage(pid, stage, input_artifact=input_artifact)
    except Exception as e:
        log.warning("workflow start failed pid=%s stage=%s: %s", pid, stage, e)


def _best_effort_finish_stage(
    pid: str,
    stage: str,
    *,
    output_artifact: str = "",
    resume_eligible: bool = True,
) -> None:
    try:
        finish_stage(
            pid,
            stage,
            output_artifact=output_artifact,
            resume_eligible=resume_eligible,
        )
    except Exception as e:
        log.warning("workflow finish failed pid=%s stage=%s: %s", pid, stage, e)


def _best_effort_fail_stage(pid: str, stage: str, exc: BaseException | str) -> None:
    try:
        fail_stage(pid, stage, exc)
    except Exception as e:
        log.warning("workflow fail failed pid=%s stage=%s: %s", pid, stage, e)


def _best_effort_cancel_workflow(pid: str, stage: str) -> None:
    try:
        cancel_workflow(pid, stage)
    except Exception as e:
        log.warning("workflow cancel failed pid=%s stage=%s: %s", pid, stage, e)


def _best_effort_mark_exception(pid: str, stage: str, exc: BaseException) -> None:
    if is_cancelled(pid) or _is_task_cancelled(exc):
        _best_effort_cancel_workflow(pid, stage)
    else:
        _best_effort_fail_stage(pid, stage, exc)


def _cancelled_project_fields(pid: str, stage: str) -> dict:
    """Return project fields for a user-cancelled task without marking failure."""
    if stage == "burn" and _first_safe_project_artifact(pid, ["translated.srt", "bilingual.srt"])[0]:
        return {
            "status": "translated",
            "error": None,
            "progress": 100,
            "progress_msg": "已取消烧录，翻译字幕仍可用",
            "pipeline_stage": None,
            **_translation_artifact_fields(pid),
        }
    return {
        "status": "cancelled",
        "error": None,
        "progress_msg": "已取消",
        "pipeline_stage": None,
    }


def _mark_project_cancelled(pid: str, stage: str) -> dict:
    fields = _cancelled_project_fields(pid, stage)
    mutate_project(pid, lambda p: p.update(fields), normalize=_apply_safe_defaults)
    return fields


def _resolve_audio_track(project: dict, requested: Optional[int]) -> int:
    value = requested if requested is not None else project.get("selected_audio_track", 0)
    if value is None:
        value = 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HTTPException(400, "audio_track must be a non-negative integer")

    tracks = project.get("audio_tracks") or []
    if tracks and value >= len(tracks):
        raise HTTPException(400, "audio_track out of range")
    if not tracks and value != 0:
        raise HTTPException(400, "audio_track out of range")
    return value


def _resolve_text_option(
    requested: Optional[str],
    fallback: Optional[str],
    default: str,
    field: str,
) -> str:
    if requested is not None:
        if not isinstance(requested, str):
            raise HTTPException(400, f"{field} must be a string")
        value = requested.strip()
        if not value:
            raise HTTPException(400, f"{field} must not be empty")
        return value
    value = (fallback if isinstance(fallback, str) else default).strip()
    return value or default


def _coerce_bool_option(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _coerce_int_option(value, default: int, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    if isinstance(value, bool):
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(numeric):
        return default
    result = int(numeric)
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _coerce_str_option(value, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _try_bypass_asr_with_embedded_subtitle(pid: str, project: dict, pdir: str) -> bool:
    """If the project has a selected embedded subtitle track and the user
    hasn't disabled it, extract it as raw.srt + filtered.srt and skip ASR.

    Returns True if bypass succeeded (translate stage will pick up
    filtered.srt). Returns False if there's no track, the user opted out,
    or ffmpeg couldn't transcode the track — caller falls back to ASR.
    """
    if not project.get("prefer_embedded_subtitle", True):
        return False
    sub_idx = project.get("selected_subtitle_track")
    if sub_idx is None:
        return False
    tracks = project.get("subtitle_tracks") if isinstance(project.get("subtitle_tracks"), list) else []
    if tracks:
        if isinstance(sub_idx, bool) or not isinstance(sub_idx, int) or sub_idx < 0 or sub_idx >= len(tracks):
            sub_idx = _pick_subtitle_track(tracks, project.get("target_language") or "简体中文")
            if sub_idx is None:
                return False
        else:
            selected_track = tracks[sub_idx] if isinstance(tracks[sub_idx], dict) else {}
            if _is_forced_or_commentary_subtitle(selected_track):
                replacement = _pick_subtitle_track(
                    tracks,
                    project.get("target_language") or "简体中文",
                )
                if replacement is None:
                    log.info(
                        "pid=%s selected embedded subtitle track %s is forced/commentary; "
                        "falling back to ASR",
                        pid,
                        sub_idx,
                    )
                    return False
                if replacement != sub_idx:
                    log.info(
                        "pid=%s switched embedded subtitle track %s -> %s to avoid forced/commentary track",
                        pid,
                        sub_idx,
                        replacement,
                    )
                    sub_idx = replacement
                    project["selected_subtitle_track"] = replacement
                    mutate_project(
                        pid,
                        lambda p: p.update({"selected_subtitle_track": replacement}),
                        normalize=_apply_safe_defaults,
                    )
    video_path = project.get("video_path")
    if not video_path or not os.path.exists(video_path):
        return False

    from app.utils.media import extract_subtitle
    from app.utils.srt import parse_srt_file

    raw_path = os.path.join(pdir, "raw.srt")
    _emit_progress(pid, "asr", 10, "正在提取内嵌字幕...")
    if not extract_subtitle(video_path, raw_path, sub_idx):
        log.info("pid=%s embedded subtitle extraction failed (track %s); falling back to ASR",
                 pid, sub_idx)
        return False

    # Sanity-check the SRT is parseable & non-empty.
    try:
        blocks = parse_srt_file(raw_path)
    except Exception as e:
        log.warning("pid=%s embedded subtitle parse failed: %s; falling back to ASR", pid, e)
        return False
    if not blocks:
        log.warning("pid=%s embedded subtitle yielded 0 blocks; falling back to ASR", pid)
        return False

    # Mirror to filtered.srt — embedded subs are presumed clean, no filter pass.
    import shutil as _shutil
    _shutil.copy(raw_path, os.path.join(pdir, "filtered.srt"))
    _emit_progress(pid, "asr", 100, f"已使用内嵌字幕,跳过 ASR ({len(blocks)} 条)")

    mutate_project(pid, lambda p: p.update({"status": "asr_done", "error": None}),
                   normalize=_apply_safe_defaults)
    log.info("pid=%s ASR bypassed via embedded subtitle track %s (%d blocks)",
             pid, sub_idx, len(blocks))
    return True


def _run_asr_pipeline(pid: str, audio_track: int, language: str, owns_registration: bool = True):
    """Run ASR pipeline in background thread.

    `owns_registration` is False when invoked as a sub-step of the full
    pipeline, so the active-task registration is released by the caller, not
    here — otherwise the pid would be deregistered mid-pipeline.
    """
    try:
        with slot("asr", pid):
            mutate_project(pid, lambda p: p.update({"status": "processing"}),
                           normalize=_apply_safe_defaults)
            project = _load_project(pid)
            pdir = str(PROJECTS_DIR / pid)
            video_path = project["video_path"]
            _best_effort_start_stage(
                pid,
                "asr",
                input_artifact=project.get("video_path", ""),
            )

            # Fast path: use embedded subtitle if present + enabled.
            if _try_bypass_asr_with_embedded_subtitle(pid, project, pdir):
                _best_effort_finish_stage(
                    pid,
                    "asr",
                    output_artifact="filtered.srt",
                    resume_eligible=True,
                )
                return

            # Step 1: Audio preprocessing
            _emit_progress(pid, "asr", 0, "正在预处理音频...")
            _check_cancel(pid)
            from app.engines.audio import preprocess_audio
            cfg = Config.to_dict()
            raw_asr_cfg = cfg.get("asr", {})
            asr_cfg = raw_asr_cfg if isinstance(raw_asr_cfg, dict) else {}
            use_demucs = _coerce_bool_option(asr_cfg.get("use_demucs"), True)

            audio_path = preprocess_audio(
                video_path, pdir, track_index=audio_track,
                use_demucs=use_demucs,
                callback=lambda msg: _emit_progress(pid, "asr", 10, msg),
            )

            # Step 2: ASR
            _check_cancel(pid)
            _emit_progress(pid, "asr", 20, "正在语音识别...")
            from app.engines.asr import transcribe

            configured_language = _coerce_str_option(asr_cfg.get("language"), "auto")
            blocks = transcribe(
                audio_path,
                language=language if language != "auto" else configured_language,
                model_size=_coerce_str_option(asr_cfg.get("model_size"), "large-v3-turbo"),
                vad_filter=_coerce_bool_option(asr_cfg.get("vad_filter"), True),
                beam_size=_coerce_int_option(asr_cfg.get("beam_size"), 5, minimum=1, maximum=20),
                callback=lambda msg: _emit_progress(pid, "asr", 60, msg),
                error_log_dir=pdir,
                backend=_coerce_str_option(asr_cfg.get("backend"), "auto"),
            )
            _check_cancel(pid)

            # Step 3: Apply offset
            offset_ms = _coerce_int_option(asr_cfg.get("offset_ms"), 0)
            if offset_ms != 0:
                from app.utils.srt import apply_offset
                blocks = apply_offset(blocks, offset_ms)

            # Save raw ASR result
            raw_path = os.path.join(pdir, "raw.srt")
            write_srt(blocks, raw_path)

            # Step 4: Filter
            _emit_progress(pid, "asr", 85, "正在智能过滤...")
            _check_cancel(pid)
            from app.engines.filter import filter_subtitles, get_filter_stats

            raw_trans_cfg = cfg.get("translation", {})
            trans_cfg = raw_trans_cfg if isinstance(raw_trans_cfg, dict) else {}
            detected_lang = _resolve_filter_language(
                lang=language,
                original_language=project.get("original_language") if isinstance(project, dict) else None,
                blocks=blocks,
            )

            blocks = filter_subtitles(
                blocks,
                language=detected_lang,
                filter_repetitive=trans_cfg.get("filter_repetitive", True),
                repetitive_threshold=trans_cfg.get("repetitive_threshold", 3),
                filter_interjections=trans_cfg.get("filter_interjections", True),
            )

            # Save filtered result
            write_srt(blocks, os.path.join(pdir, "filtered.srt"))

            # Save filter state
            filter_state = {}
            for b in blocks:
                if b.filtered:
                    filter_state[str(b.index)] = {"filtered": True, "reason": b.filter_reason}
            atomic_write_json(Path(pdir) / "filter_state.json", filter_state)

            stats = get_filter_stats(blocks)
            _emit_progress(pid, "asr", 100, f"识别完成: {stats['active']}条有效, {stats['filtered']}条已过滤")

            mutate_project(pid, lambda p: p.update({"status": "asr_done", "error": None}),
                           normalize=_apply_safe_defaults)
            _best_effort_finish_stage(
                pid,
                "asr",
                output_artifact="filtered.srt",
                resume_eligible=True,
            )

    except TaskCancelled as e:
        log.info("ASR pipeline cancelled for %s", pid)
        _best_effort_mark_exception(pid, "asr", e)
        try:
            _mark_project_cancelled(pid, "asr")
        except Exception:
            pass
        _emit_progress(pid, "asr", 0, "已取消")
    except Exception as e:
        log.exception("ASR pipeline failed for %s", pid)
        _best_effort_mark_exception(pid, "asr", e)
        error_msg = _safe_error_message(e)
        try:
            mutate_project(pid, lambda p: p.update({"status": "error",
                                                     "error": error_msg,
                                                     "pipeline_stage": None,
                                                     "progress_msg": f"错误: {_safe_error_message(e, 100)}"}),
                           normalize=_apply_safe_defaults)
        except Exception:
            pass
        _emit_progress(pid, "asr", 0, f"错误: {_safe_error_message(e, 100)}")
    finally:
        if owns_registration:
            unregister_task(pid)


def _translation_failed_completely(blocks) -> Optional[str]:
    """Return an error message when there were translatable blocks but every
    one of them failed — none translated AND at least one carries an error.

    Returns None when some blocks translated, when there were no translatable
    blocks, or when blocks are simply empty with no recorded error (e.g. an
    all-music clip) — those are not failures. Used so the pipeline reports a
    real error instead of a false 'completed' when e.g. the API key is wrong.
    """
    active = [b for b in blocks if _is_translatable_block(b)]
    if not active:
        return None
    if any(b.translation for b in active):
        return None
    return next((b.translation_error for b in active if b.translation_error), None)


def _translation_completion_counts(blocks) -> tuple[int, int, int]:
    active = [b for b in blocks if _is_translatable_block(b)]
    translated = sum(1 for b in active if b.translation)
    return len(active), translated, len(active) - translated


def _incomplete_translation_message(blocks) -> Optional[str]:
    active_count, translated_count, failed_count = _translation_completion_counts(blocks)
    if not active_count or failed_count == 0:
        return None

    total_failure = _translation_failed_completely(blocks)
    if total_failure:
        return f"翻译失败: {total_failure}"

    return f"翻译未完成: {translated_count}/{active_count} 条成功，{failed_count} 条缺失"


def _preview_ids(ids: list[int], limit: int = 12) -> str:
    shown = ", ".join(str(item) for item in ids[:limit])
    if len(ids) > limit:
        shown = f"{shown}, ..."
    return shown


def _has_exportable_duration(block) -> bool:
    try:
        return getattr(block, "end") > getattr(block, "start")
    except Exception:
        return False


def _expected_translation_export_ids(blocks) -> list[int]:
    ids = []
    for block in blocks or []:
        block_id = getattr(block, "index", None)
        if not isinstance(block_id, int) or isinstance(block_id, bool):
            continue
        if not _has_exportable_duration(block):
            continue
        if _is_translatable_block(block):
            ids.append(block_id)
    return ids


def _translation_export_integrity_message(blocks, write_report) -> Optional[str]:
    expected_ids = _expected_translation_export_ids(blocks)
    if not expected_ids:
        return None
    written_ids = set(getattr(write_report, "written_ids", []) or [])
    missing_ids = [block_id for block_id in expected_ids if block_id not in written_ids]
    if not missing_ids:
        return None
    return (
        f"翻译导出不完整: {len(expected_ids) - len(missing_ids)}/{len(expected_ids)} 条可交付字幕写入，"
        f"{len(missing_ids)} 条导出缺失 (id: {_preview_ids(missing_ids)})"
    )


_FINAL_MISSING_TRANSLATION_RETRY_NOTE = (
    "最终补翻要求: 这些字幕在主翻译和批内补翻后仍缺译。"
    "本轮只处理当前 JSON 中的条目；每个普通对白 id 必须返回非空 translation，"
    "不要省略、不要合并、不要改 id。"
)


def _missing_translation_retry_rounds(cfg: dict) -> int:
    trans_cfg = cfg.get("translation") if isinstance(cfg, dict) else {}
    if not isinstance(trans_cfg, dict):
        trans_cfg = {}
    return _coerce_int_option(
        trans_cfg.get("missing_translation_retries", 2),
        2,
        minimum=0,
        maximum=4,
    )


def _missing_translation_retry_batch_size(cfg: dict) -> int:
    trans_cfg = cfg.get("translation") if isinstance(cfg, dict) else {}
    if not isinstance(trans_cfg, dict):
        trans_cfg = {}
    return _coerce_int_option(
        trans_cfg.get("missing_translation_retry_batch_size", 5),
        5,
        minimum=1,
        maximum=20,
    )


def _missing_translation_retry_max_blocks(cfg: dict) -> int:
    trans_cfg = cfg.get("translation") if isinstance(cfg, dict) else {}
    if not isinstance(trans_cfg, dict):
        trans_cfg = {}
    return _coerce_int_option(
        trans_cfg.get("missing_translation_retry_max_blocks", 200),
        200,
        minimum=0,
        maximum=5000,
    )


def _retry_context_for_blocks(blocks, batch_blocks, window: int = 3) -> tuple[list[dict], list[str]]:
    positions = {id(block): i for i, block in enumerate(blocks)}
    batch_positions = [positions[id(block)] for block in batch_blocks if id(block) in positions]
    if not batch_positions:
        return [], []

    start = min(batch_positions)
    end = max(batch_positions)
    before = []
    for block in reversed(blocks[:start]):
        if _is_translatable_block(block) and block.translation:
            before.append({"original": block.text, "translated": block.translation})
            if len(before) >= window:
                break
    before.reverse()

    after = []
    for block in blocks[end + 1:]:
        if _is_translatable_block(block):
            after.append(block.text)
            if len(after) >= window:
                break
    return before, after


def _retry_missing_translations_before_quality(
    cfg: dict,
    translator,
    blocks,
    target_language: str,
    project: dict,
    kb_data: Optional[dict],
    progress_callback=None,
) -> list[dict]:
    rounds = _missing_translation_retry_rounds(cfg)
    if rounds <= 0:
        return []

    primary = getattr(translator, "primary", None)
    build_prompt = getattr(translator, "_build_prompt", None)
    if primary is None or not hasattr(primary, "translate_batch") or not callable(build_prompt):
        return []

    from app.engines.providers.result_contract import reconcile_translation_results

    batch_size = _missing_translation_retry_batch_size(cfg)
    max_retry_blocks = _missing_translation_retry_max_blocks(cfg)
    applied = []

    def _retry_batch(batch_blocks) -> None:
        items = [{"id": block.index, "original": block.text} for block in batch_blocks]
        context_before, context_after = _retry_context_for_blocks(blocks, batch_blocks)
        prompt = build_prompt(
            target_language,
            project if isinstance(project, dict) else {},
            kb_data if isinstance(kb_data, dict) else {},
            context_before,
            context_after,
            items=items,
        )
        prompt = f"{prompt}\n\n{_FINAL_MISSING_TRANSLATION_RETRY_NOTE}"
        try:
            raw_results = primary.translate_batch(items, prompt)
        except Exception as exc:
            err = _safe_error_message(exc)
            for block in batch_blocks:
                if not getattr(block, "translation_error", ""):
                    block.translation_error = err
            log.warning("final missing translation retry failed: %s", err)
            return

        results = reconcile_translation_results(
            raw_results if isinstance(raw_results, list) else [],
            items,
        )
        block_by_id = {str(block.index): block for block in batch_blocks}
        for result in results:
            if not isinstance(result, dict):
                continue
            block = block_by_id.get(str(result.get("id", "")))
            if block is None:
                continue
            translation = result.get("translation", "")
            error = result.get("error", "")
            if isinstance(translation, str) and translation.strip():
                block.translation = translation
                block.translation_error = ""
                applied.append({"id": block.index, "translation": translation})
            elif isinstance(error, str) and error and not getattr(block, "translation_error", ""):
                block.translation_error = error

    for round_index in range(rounds):
        missing_blocks = [
            block for block in blocks
            if _is_translatable_block(block) and not getattr(block, "translation", "")
        ]
        if not missing_blocks:
            break
        if max_retry_blocks > 0 and len(missing_blocks) > max_retry_blocks:
            active_count = sum(1 for block in blocks if _is_translatable_block(block))
            message = (
                f"全片缺译过多: {len(missing_blocks)}/{active_count} 条，"
                f"超过补翻上限 {max_retry_blocks}，跳过耗时补翻"
            )
            if progress_callback is not None:
                try:
                    progress_callback(90, message)
                except Exception:
                    pass
            log.warning("skip final missing translation retry: %s", message)
            for block in missing_blocks:
                if not getattr(block, "translation_error", ""):
                    block.translation_error = message
            break

        if progress_callback is not None:
            try:
                progress_callback(
                    90,
                    f"全片补翻缺失: 第 {round_index + 1}/{rounds} 轮 ({len(missing_blocks)} 条)",
                )
            except Exception:
                pass

        for start in range(0, len(missing_blocks), batch_size):
            batch_blocks = missing_blocks[start:start + batch_size]
            _retry_batch(batch_blocks)

    remaining_blocks = [
        block for block in blocks
        if _is_translatable_block(block) and not getattr(block, "translation", "")
    ]
    if remaining_blocks and batch_size > 1:
        for idx, block in enumerate(remaining_blocks, start=1):
            if progress_callback is not None:
                try:
                    progress_callback(90, f"逐条补翻缺失: {idx}/{len(remaining_blocks)}")
                except Exception:
                    pass
            _retry_batch([block])
    return applied


def _is_translatable_block(block) -> bool:
    """Return False for filtered/blank/sound-description rows that may stay empty."""
    if getattr(block, "filtered", False):
        return False
    text = getattr(block, "text", "")
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        from app.engines.translation_qa import is_sound_description_source
        return not is_sound_description_source(text)
    except Exception:
        return not _SOUND_DESCRIPTION_RE.match(text)


def _find_subtitle_source(pid: str) -> tuple[Optional[str], Optional[str]]:
    source_name, source_path = _first_safe_project_artifact(
        pid,
        ["filtered.srt", "raw.srt", "native.srt"],
    )
    return source_name, str(source_path) if source_path is not None else None


def _kb_suggestions_path(pid: str) -> Path:
    return project_dir(pid) / "kb_suggestions.json"


def _load_rejected_kb_suggestion_sources(pid: str) -> set[str]:
    path = project_dir(pid) / "kb_suggestion_decisions.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict) or not isinstance(data.get("rejected_sources"), list):
        return set()
    return {
        source.strip().casefold()
        for source in data.get("rejected_sources", [])
        if isinstance(source, str) and source.strip()
    }


def _subtitle_dicts_for_kb_preflight(source_path: str) -> list[dict]:
    from app.utils.srt import parse_srt_file

    blocks = parse_srt_file(source_path)
    return [
        {
            "index": getattr(block, "index", None),
            "text": getattr(block, "text", ""),
        }
        for block in blocks
        if getattr(block, "text", "")
    ]


def _merge_generated_kb_suggestions(generated, persisted):
    persisted_by_id = {
        getattr(item, "id", ""): item
        for item in persisted
        if getattr(item, "id", "")
    }
    seen_ids = set()
    merged = []
    for item in generated:
        previous = persisted_by_id.get(getattr(item, "id", ""))
        if previous is not None:
            item.status = getattr(previous, "status", "pending") or "pending"
            if getattr(previous, "target", ""):
                item.target = previous.target
            if getattr(previous, "notes", ""):
                item.notes = previous.notes
        merged.append(item)
        seen_ids.add(getattr(item, "id", ""))

    for item in persisted:
        if getattr(item, "id", "") not in seen_ids:
            merged.append(item)
    return merged


def _has_existing_kb_target(suggestion) -> bool:
    entries = getattr(suggestion, "existing_entries", []) or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        target = entry.get("target")
        if isinstance(source, str) and source.strip() and isinstance(target, str) and target.strip():
            return True
    return False


def _suggestion_has_translation_value(suggestion) -> bool:
    source = getattr(suggestion, "source", "")
    target = getattr(suggestion, "target", "")
    notes = getattr(suggestion, "notes", "")
    if isinstance(target, str) and target.strip():
        return True
    if isinstance(notes, str) and notes.strip():
        return True

    evidence = [
        item
        for item in (getattr(suggestion, "evidence", []) or [])
        if isinstance(item, str)
    ]
    if any(item.startswith("subtitle:") for item in evidence):
        return isinstance(source, str) and len(source.split()) >= 2
    return any(item in {"cast", "character", "overview", "domain_term"} for item in evidence)


def _suggestion_needs_kb_review(suggestion, rejected_sources: set[str]) -> bool:
    source = getattr(suggestion, "source", "")
    if not isinstance(source, str) or not source.strip():
        return False
    if source.strip().casefold() in rejected_sources:
        return False
    if _has_existing_kb_target(suggestion):
        return False

    status = (getattr(suggestion, "status", "") or "").strip().casefold()
    if status == "rejected":
        return False
    if status == "accepted":
        target = getattr(suggestion, "target", "")
        return not (isinstance(target, str) and target.strip())
    return _suggestion_has_translation_value(suggestion)


def _kb_review_required_detail(pid: str, count: int, total: int) -> dict:
    return {
        "code": _KB_REVIEW_REQUIRED_CODE,
        "project_id": pid,
        "suggestions_count": count,
        "total_suggestions": total,
        "message": (
            f"翻译前需要先审校自动知识库建议：发现 {count} 条候选。"
            "请在项目的“自动知识库建议”或知识库页面接受/填写译文，或拒绝这些建议后再翻译。"
        ),
    }


def _requires_kb_suggestion_review(config: Optional[dict] = None) -> bool:
    # Auto KB suggestions are translation hints, not a human preflight gate.
    # Accepted project KB entries still act as hard terminology constraints.
    return False


def _ensure_kb_review_ready(
    pid: str,
    project: dict,
    *,
    as_http: bool,
    config: Optional[dict] = None,
) -> None:
    _, source_path = _find_subtitle_source(pid)
    if not source_path:
        return

    try:
        subtitles = _subtitle_dicts_for_kb_preflight(source_path)
    except Exception as exc:
        log.warning("KB preflight could not parse subtitle source pid=%s: %s", pid, exc)
        return
    if not subtitles:
        return

    from app.engines.knowledge import _get_singleton
    from app.engines.kb_suggestions import extract_kb_suggestions, load_suggestions, save_suggestions

    path = _kb_suggestions_path(pid)
    existing_kb = _get_singleton().select_for_project(project)
    generated = extract_kb_suggestions(project, subtitles, existing_kb)
    suggestions = _merge_generated_kb_suggestions(generated, load_suggestions(path))
    save_suggestions(path, suggestions)
    rejected = _load_rejected_kb_suggestion_sources(pid)
    if not _requires_kb_suggestion_review(config):
        review_count = sum(
            1 for item in suggestions
            if _suggestion_needs_kb_review(item, rejected)
        )
        if review_count:
            log.info(
                "KB suggestions generated for %s but translation is not blocked "
                "(review_required=false, reviewable=%d, total=%d)",
                pid,
                review_count,
                len(suggestions),
        )
        return

    review_needed = [
        item for item in suggestions
        if _suggestion_needs_kb_review(item, rejected)
    ]
    if not review_needed:
        return

    detail = _kb_review_required_detail(pid, len(review_needed), len(suggestions))
    if as_http:
        raise HTTPException(status_code=409, detail=detail)
    raise RuntimeError(detail["message"])


def _auto_kb_candidate_terms(pid: str, limit: int = 40) -> list[dict]:
    """Return generated KB suggestions as soft translation context.

    These are not hard terminology constraints. Accepted project KB entries
    still win through the v2 KB snippet; pending suggestions only help the
    translator keep likely names/places consistent during the current run.
    """
    try:
        from app.engines.kb_suggestions import load_suggestions

        suggestions = load_suggestions(_kb_suggestions_path(pid))
    except Exception as exc:
        log.warning("failed to load auto KB candidates for %s: %s", pid, exc)
        return []

    rejected = _load_rejected_kb_suggestion_sources(pid)
    rows: list[dict] = []
    seen: set[str] = set()
    for item in suggestions:
        source = getattr(item, "source", "")
        if not isinstance(source, str) or not source.strip():
            continue
        source = source.strip()
        source_key = source.casefold()
        if source_key in rejected or source_key in seen:
            continue
        status = (getattr(item, "status", "") or "pending").strip().casefold()
        if status == "rejected":
            continue
        target = getattr(item, "target", "")
        category = getattr(item, "category", "") or getattr(item, "type", "")
        confidence = getattr(item, "confidence", None)
        row = {
            "source": source,
            "target": target.strip() if isinstance(target, str) else "",
            "category": category.strip() if isinstance(category, str) else "",
            "status": status if status in {"pending", "accepted"} else "pending",
        }
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and math.isfinite(confidence):
            row["confidence"] = round(float(confidence), 3)
        rows.append(row)
        seen.add(source_key)
        if len(rows) >= limit:
            break
    return rows


def _project_kb_terms(project_kb) -> dict:
    terms = {}
    if project_kb is None:
        return terms
    for attr in ("characters", "places", "brands", "slang"):
        for entry in getattr(project_kb, attr, []) or []:
            source = getattr(entry, "source", "")
            target = getattr(entry, "target", "")
            if isinstance(source, str) and isinstance(target, str) and source.strip() and target.strip():
                terms[source.strip()] = target.strip()
    return terms


def _repair_round_limit(cfg: dict) -> int:
    trans_cfg = cfg.get("translation", {}) if isinstance(cfg, dict) else {}
    raw = trans_cfg.get("qa_auto_repair_rounds", 3) if isinstance(trans_cfg, dict) else 3
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        value = 3
    return max(3, min(value, 4))


def _repair_item_limit(cfg: dict) -> int:
    trans_cfg = cfg.get("translation", {}) if isinstance(cfg, dict) else {}
    raw = (
        trans_cfg.get("qa_auto_repair_max_blocks", _QA_AUTO_REPAIR_MAX_BLOCKS)
        if isinstance(trans_cfg, dict)
        else _QA_AUTO_REPAIR_MAX_BLOCKS
    )
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        value = _QA_AUTO_REPAIR_MAX_BLOCKS
    return max(0, min(value, 50))


def _qa_auto_repair_enabled(cfg: dict) -> bool:
    trans_cfg = cfg.get("translation", {}) if isinstance(cfg, dict) else {}
    if not isinstance(trans_cfg, dict):
        return True
    return trans_cfg.get("qa_auto_repair") is not False


def _semantic_qa_enabled(cfg: dict) -> bool:
    trans_cfg = cfg.get("translation", {}) if isinstance(cfg, dict) else {}
    if not isinstance(trans_cfg, dict):
        return False
    return trans_cfg.get("semantic_qa") is True


def _semantic_qa_batch_size(cfg: dict) -> int:
    trans_cfg = cfg.get("translation", {}) if isinstance(cfg, dict) else {}
    raw = trans_cfg.get("semantic_qa_batch_size", 40) if isinstance(trans_cfg, dict) else 40
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        value = 40
    return max(5, min(value, 80))


def _semantic_qa_max_blocks(cfg: dict) -> int:
    trans_cfg = cfg.get("translation", {}) if isinstance(cfg, dict) else {}
    raw = trans_cfg.get("semantic_qa_max_blocks", 0) if isinstance(trans_cfg, dict) else 0
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        value = 0
    return max(0, min(value, 5000))


def _issue_counts_by_type(issues) -> dict:
    counts = {}
    for issue in issues or []:
        issue_type = getattr(issue, "type", "")
        if issue_type:
            counts[issue_type] = counts.get(issue_type, 0) + 1
    return counts


def _refresh_quality_report_issue_summary(report) -> None:
    issues = list(getattr(report, "issues", []) or [])
    blocking = [
        issue for issue in issues
        if getattr(issue, "severity", "") in {"error", "severe"}
        or not _is_report_only_quality_warning(issue)
    ]
    report.status = "ok" if not blocking else "needs_review"
    report.unresolved_blocks = sorted({
        issue.block_id for issue in blocking if isinstance(issue.block_id, int)
    })
    summary = getattr(report, "summary", None)
    if not isinstance(summary, dict):
        summary = {}
        report.summary = summary
    summary.update({
        "issue_count": len(issues),
        "blocking_issue_count": len(blocking),
        "report_only_warning_count": max(0, len(issues) - len(blocking)),
        "by_type": _issue_counts_by_type(issues),
    })


def _semantic_qa_prompt(target_language: str) -> str:
    return "\n".join([
        f"你是一位严格的字幕语义质检员，检查译文是否准确对应原文，目标语言是{target_language}。",
        "用户会给 JSON 数组；每项包含 id、original 和 draft。",
        "只判断语义对应关系，不检查行长、标点、风格或读速。",
        "如果 draft 准确表达 original 的核心意思，返回 OK。",
        "如果 draft 与 original 明显无关、错位、漏掉核心动作/对象/问答关系，返回 MISMATCH: 简短中文原因。",
        "如果信息不足但高度可疑，返回 UNCERTAIN: 简短中文原因。",
        "必须保持 id 原样，不要新增、删除或重编号。",
        "仅输出 JSON 数组，格式: [{\"id\": N, \"translation\": \"OK\"}]。",
    ])


def _semantic_qa_items(blocks, cfg: dict) -> list[dict]:
    items = []
    for block in blocks or []:
        block_id = getattr(block, "index", None)
        if not isinstance(block_id, int) or isinstance(block_id, bool):
            continue
        if not _is_translatable_block(block):
            continue
        source = getattr(block, "text", "")
        translation = getattr(block, "translation", "")
        if not isinstance(source, str) or not source.strip():
            continue
        if not isinstance(translation, str) or not translation.strip():
            continue
        items.append({
            "id": block_id,
            "original": source,
            "draft": translation,
        })
    max_blocks = _semantic_qa_max_blocks(cfg)
    if max_blocks > 0:
        return items[:max_blocks]
    return items


def _semantic_issue_from_verdict(item: dict, verdict: str, error: str = ""):
    from app.engines.translation_qa import QualityIssue

    block_id = item.get("id")
    source = item.get("original", "")
    translation = item.get("draft", "")
    clean_verdict = verdict.strip() if isinstance(verdict, str) else ""
    clean_error = error.strip() if isinstance(error, str) else ""

    if clean_error and not clean_verdict:
        return QualityIssue(
            type="semantic_qa_failed",
            severity="warning",
            block_id=block_id if isinstance(block_id, int) else None,
            message=f"semantic QA did not return a usable verdict: {_safe_error_message(clean_error, 120)}",
            source_text=source if isinstance(source, str) else "",
            translation=translation if isinstance(translation, str) else "",
        )

    normalized = clean_verdict.strip().lower()
    if normalized == "ok" or normalized.startswith("ok "):
        return None
    if normalized.startswith("mismatch") or normalized.startswith("不匹配") or normalized.startswith("错译"):
        reason = clean_verdict.split(":", 1)[-1].strip() if ":" in clean_verdict else clean_verdict
        return QualityIssue(
            type="semantic_mismatch",
            severity="error",
            block_id=block_id if isinstance(block_id, int) else None,
            message=reason or "translation does not match source meaning",
            source_text=source if isinstance(source, str) else "",
            translation=translation if isinstance(translation, str) else "",
        )
    if normalized.startswith("uncertain") or normalized.startswith("可疑") or normalized.startswith("不确定"):
        reason = clean_verdict.split(":", 1)[-1].strip() if ":" in clean_verdict else clean_verdict
        return QualityIssue(
            type="semantic_uncertain",
            severity="warning",
            block_id=block_id if isinstance(block_id, int) else None,
            message=reason or "semantic QA could not confirm source-target alignment",
            source_text=source if isinstance(source, str) else "",
            translation=translation if isinstance(translation, str) else "",
        )

    return QualityIssue(
        type="semantic_uncertain",
        severity="warning",
        block_id=block_id if isinstance(block_id, int) else None,
        message=f"semantic QA returned ambiguous verdict: {_safe_error_message(clean_verdict, 120)}",
        source_text=source if isinstance(source, str) else "",
        translation=translation if isinstance(translation, str) else "",
    )


def _run_semantic_quality_checks(
    cfg: dict,
    translator,
    blocks,
    target_language: str,
    *,
    progress_callback=None,
) -> tuple[list, dict]:
    if not _semantic_qa_enabled(cfg):
        return [], {"enabled": False}
    primary = getattr(translator, "primary", None)
    if primary is None or not hasattr(primary, "translate_batch"):
        return [], {"enabled": True, "skipped_reason": "provider_unavailable"}

    items = _semantic_qa_items(blocks, cfg)
    trace = {
        "enabled": True,
        "checked_blocks": 0,
        "issue_count": 0,
        "batch_size": _semantic_qa_batch_size(cfg),
        "batches": [],
    }
    if not items:
        return [], trace

    try:
        from app.engines.providers.result_contract import reconcile_translation_results
        from app.engines.translation_qa import QualityIssue
    except Exception as exc:
        trace["skipped_reason"] = f"import_failed: {_safe_error_message(exc)}"
        return [], trace

    issues = []
    prompt = _semantic_qa_prompt(target_language)
    batch_size = trace["batch_size"]
    item_by_id = {str(item["id"]): item for item in items}
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        if progress_callback is not None:
            try:
                progress_callback(92, f"正在语义复核: {min(start + len(batch), len(items))}/{len(items)}")
            except Exception:
                pass
        batch_trace = {
            "batch": len(trace["batches"]) + 1,
            "attempted_blocks": len(batch),
            "issues": 0,
        }
        trace["batches"].append(batch_trace)
        try:
            raw_results = primary.translate_batch(batch, prompt)
            results = reconcile_translation_results(
                raw_results if isinstance(raw_results, list) else [],
                batch,
            )
        except Exception as exc:
            message = _safe_error_message(exc)
            issues.append(QualityIssue(
                type="semantic_qa_failed",
                severity="warning",
                block_id=None,
                message=f"semantic QA batch failed: {message}",
            ))
            batch_trace["error"] = message
            batch_trace["issues"] = 1
            continue

        for result in results:
            if not isinstance(result, dict):
                continue
            item = item_by_id.get(str(result.get("id", "")))
            if item is None:
                continue
            issue = _semantic_issue_from_verdict(
                item,
                result.get("translation", ""),
                result.get("error", ""),
            )
            if issue is not None:
                issues.append(issue)
                batch_trace["issues"] += 1
    trace["checked_blocks"] = len(items)
    trace["issue_count"] = len(issues)
    return issues, trace


def _run_quality_checks_with_semantics(
    cfg: dict,
    translator,
    blocks,
    target_language: str,
    project_kb,
    project: dict,
    trace: dict,
    *,
    progress_callback=None,
):
    from app.engines.translation_qa import run_quality_checks

    report = run_quality_checks(
        blocks,
        project_kb=project_kb,
        target_language=target_language,
        meta_info=project,
        trace=trace,
    )
    semantic_issues, semantic_trace = _run_semantic_quality_checks(
        cfg,
        translator,
        blocks,
        target_language,
        progress_callback=progress_callback,
    )
    if semantic_trace:
        trace["semantic_qa"] = semantic_trace
    if semantic_issues:
        report.issues.extend(semantic_issues)
        _refresh_quality_report_issue_summary(report)
    return report


def _quality_issue_counts(report) -> tuple[int, int, int]:
    issues = list(getattr(report, "issues", []) or [])
    error_count = sum(1 for issue in issues if getattr(issue, "severity", "") in {"error", "severe"})
    warning_count = sum(1 for issue in issues if getattr(issue, "severity", "") == "warning")
    return len(issues), error_count, warning_count


def _quality_score(report) -> tuple[int, int, int]:
    issue_count, error_count, _warning_count = _quality_issue_counts(report)
    unresolved = len(getattr(report, "unresolved_blocks", []) or [])
    return error_count, issue_count, unresolved


def _is_report_only_quality_warning(issue) -> bool:
    if getattr(issue, "severity", "") != "warning":
        return False
    issue_type = getattr(issue, "type", "")
    if issue_type in _QA_EXPECTED_REPAIRABLE_WARNING_TYPES:
        expected = getattr(issue, "expected", "")
        return not (isinstance(expected, str) and expected.strip())
    return issue_type in _QA_REPORT_ONLY_WARNING_TYPES


def _finalize_quality_conclusion(report, repaired: list[dict], repair_enabled: bool) -> None:
    issue_count, error_count, warning_count = _quality_issue_counts(report)
    unresolved_count = len(getattr(report, "unresolved_blocks", []) or [])
    repaired_count = len(repaired or [])
    blocking_warnings = [
        issue for issue in (getattr(report, "issues", []) or [])
        if getattr(issue, "severity", "") == "warning"
        and not _is_report_only_quality_warning(issue)
    ]
    if error_count:
        verdict = "failed"
        conclusion = f"不达标：仍有 {error_count} 个错误、{unresolved_count} 个问题位置。"
    elif blocking_warnings:
        verdict = "needs_review"
        conclusion = (
            f"未达专业交付标准：自动返工后仍有 {len(blocking_warnings)} 个阻塞警告、"
            f"{unresolved_count} 个问题位置，建议继续自动返工或暂缓交付。"
        )
    else:
        verdict = "passed"
        conclusion = "达标：自动检查通过。"
        if warning_count:
            conclusion = f"达标：自动检查通过，保留 {warning_count} 个非阻塞提醒。"
        if repaired_count:
            conclusion = f"达标：已自动重点返工 {repaired_count} 条并复检通过。"

    report.summary.update({
        "issue_count": issue_count,
        "error_count": error_count,
        "warning_count": warning_count,
        "blocking_warning_count": len(blocking_warnings),
        "repaired_blocks": repaired_count,
        "unresolved_blocks": unresolved_count,
        "conclusion": conclusion,
        "quality_gate": {
            "verdict": verdict,
            "passed": verdict == "passed",
            "auto_repair_enabled": bool(repair_enabled),
            "auto_repaired_blocks": repaired_count,
            "unresolved_blocks": unresolved_count,
        },
    })


def _translation_quality_gate_status(pid: str) -> tuple[bool, str]:
    report_path = _safe_project_artifact_path(pid, "translation_qa_report.json")
    if report_path is None:
        return False, "翻译质量检查未生成报告，已停止烧录。"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "翻译质量检查报告无效，已停止烧录。"
    if not isinstance(report, dict):
        return False, "翻译质量检查报告无效，已停止烧录。"

    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    gate = summary.get("quality_gate") if isinstance(summary.get("quality_gate"), dict) else {}
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    passed = gate.get("passed") is True or (report.get("status") == "ok" and not issues)
    conclusion = summary.get("conclusion")
    if not isinstance(conclusion, str) or not conclusion.strip():
        conclusion = "翻译质量检查通过。" if passed else ""
    if passed:
        return True, conclusion.strip()

    issue_count = summary.get("issue_count")
    if not isinstance(issue_count, int) or isinstance(issue_count, bool):
        issue_count = len(issues)
    unresolved_count = summary.get("unresolved_blocks")
    if not isinstance(unresolved_count, int) or isinstance(unresolved_count, bool):
        unresolved_count = len(report.get("unresolved_blocks") or [])
    if conclusion:
        return False, f"翻译质量未达标：{conclusion.strip()} 已停止烧录。"
    return False, f"翻译质量未达标：仍有 {issue_count} 个问题、{unresolved_count} 个问题位置，已停止烧录。"


def _mark_translation_quality_failed(pid: str, message: str) -> None:
    detail = message.strip() or "翻译质量未达标，已停止烧录。"
    _best_effort_fail_stage(pid, "translate", detail)
    mutate_project(
        pid,
        lambda p: p.update({
            "status": "error",
            "error": detail,
            "progress": 100,
            "progress_msg": detail,
            "translation_quality_status": "needs_review",
            "translation_quality_message": detail,
            "pipeline_stage": None,
            **_translation_artifact_fields(pid),
        }),
        normalize=_apply_safe_defaults,
    )
    _emit_progress(pid, "translate", 100, detail)


def _apply_nonempty_repair_results(blocks, results) -> list[dict]:
    by_id = {str(getattr(block, "index", "")): block for block in blocks or []}
    applied = []
    unmatched = 0
    for result in results or []:
        if not isinstance(result, dict):
            continue
        translation = result.get("translation", "")
        if not isinstance(translation, str) or not translation.strip():
            continue
        block = by_id.get(str(result.get("id", "")))
        if block is None:
            unmatched += 1
            continue
        block.translation = translation
        block.translation_error = ""
        applied.append({"id": getattr(block, "index", result.get("id")), "translation": translation})
    if unmatched:
        log.warning("translation QA auto-repair ignored %d unmatched result id(s)", unmatched)
    return applied


def _auto_repair_quality_issues(
    cfg: dict,
    translator,
    blocks,
    report,
    target_language: str,
    project_kb,
    repair_trace: dict | None = None,
) -> list[dict]:
    if not _qa_auto_repair_enabled(cfg):
        return []
    if not report.issues:
        return []
    try:
        from app.engines.providers.result_contract import reconcile_translation_results
        from app.engines.translation_qa import (
            build_repair_items,
            build_repair_prompt,
            repairable_quality_issues,
        )

        repair_issues = repairable_quality_issues(report.issues)
        all_repair_items = build_repair_items(blocks, repair_issues)
        max_blocks = _repair_item_limit(cfg)
        if repair_trace is not None:
            repair_trace.update({
                "candidate_blocks": len(all_repair_items),
                "max_blocks": max_blocks,
                "attempted_blocks": 0,
                "skipped_blocks": len(all_repair_items),
                "batches": [],
            })
        if not all_repair_items:
            return []
        if max_blocks <= 0:
            if repair_trace is not None:
                repair_trace["skipped_reason"] = "repair_disabled_by_zero_limit"
            return []
        primary = getattr(translator, "primary", None)
        if primary is None or not hasattr(primary, "translate_batch"):
            if repair_trace is not None:
                repair_trace["skipped_reason"] = "repair_provider_unavailable"
            return []

        applied_results = []
        attempted_blocks = 0
        batch_traces = repair_trace.get("batches") if isinstance(repair_trace, dict) else None
        for start in range(0, len(all_repair_items), max_blocks):
            repair_items = all_repair_items[start:start + max_blocks]
            if not repair_items:
                continue
            attempted_blocks += len(repair_items)
            prompt = build_repair_prompt(
                target_language,
                repair_items,
                repair_issues,
                kb_terms=_project_kb_terms(project_kb),
            )
            raw_results = primary.translate_batch(repair_items, prompt)
            results = reconcile_translation_results(
                raw_results if isinstance(raw_results, list) else [],
                repair_items,
            )
            batch_results = _apply_nonempty_repair_results(blocks, results)
            applied_results.extend(batch_results)
            if isinstance(batch_traces, list):
                batch_traces.append({
                    "batch": len(batch_traces) + 1,
                    "attempted_blocks": len(repair_items),
                    "applied_blocks": len(batch_results),
                })
        if repair_trace is not None:
            repair_trace["attempted_blocks"] = attempted_blocks
            repair_trace["skipped_blocks"] = max(0, len(all_repair_items) - attempted_blocks)
            repair_trace["applied_blocks"] = len(applied_results)
        if not applied_results:
            return []
        return applied_results
    except Exception as e:
        log.warning("translation QA auto-repair failed: %s", e)
        return []


def _persist_translation_quality_report(
    pid: str,
    pdir: str,
    project: dict,
    blocks,
    target_language: str,
    translator,
    cfg: dict,
    progress_callback=None,
) -> list[dict]:
    """Run deterministic QA and persist report artifacts without failing translation."""
    try:
        from app.engines.knowledge import _get_singleton
        from app.engines.proper_name_normalizer import normalize_inferred_proper_name_variants
        from app.engines.translation_qa import (
            normalize_curated_domain_term_translations,
            normalize_scientific_term_translations,
            normalize_sound_description_translations,
            save_quality_report,
        )

        project_kb = _get_singleton().select_for_project(project)
        trace_obj = getattr(translator, "last_quality_trace", None)
        trace = trace_obj.to_dict() if hasattr(trace_obj, "to_dict") else {}
        if not isinstance(trace, dict):
            trace = {}
        repaired = []
        sound_repaired = normalize_sound_description_translations(blocks)
        if sound_repaired:
            repaired.extend(sound_repaired)
            trace.setdefault("deterministic_postprocess", {})[
                "sound_description_blank_blocks"
            ] = sound_repaired
        normalized_curated_terms = normalize_curated_domain_term_translations(
            blocks,
            project_kb=project_kb,
        )
        if normalized_curated_terms:
            repaired.extend(normalized_curated_terms)
            trace.setdefault("deterministic_postprocess", {})[
                "curated_domain_term_normalized_blocks"
            ] = normalized_curated_terms
        normalized_science = normalize_scientific_term_translations(blocks)
        if normalized_science:
            repaired.extend(normalized_science)
            trace.setdefault("deterministic_postprocess", {})[
                "scientific_term_normalized_blocks"
            ] = normalized_science
        normalized_names = normalize_inferred_proper_name_variants(blocks)
        if normalized_names:
            repaired.extend(normalized_names)
            trace.setdefault("deterministic_postprocess", {})[
                "proper_name_normalized_blocks"
            ] = normalized_names
        report = _run_quality_checks_with_semantics(
            cfg,
            translator,
            blocks,
            target_language,
            project_kb,
            project,
            trace,
            progress_callback=progress_callback,
        )
        repair_enabled = _qa_auto_repair_enabled(cfg)
        if repair_enabled and report.issues:
            repair_rounds = trace.setdefault("auto_repair_rounds", [])
            previous_score = _quality_score(report)
            round_limit = _repair_round_limit(cfg)
            for round_index in range(round_limit):
                if progress_callback is not None:
                    try:
                        progress_callback(92 + round_index, f"质量未达标，正在自动重点返工 ({round_index + 1}/{round_limit})...")
                    except Exception:
                        pass
                issue_count, error_count, warning_count = _quality_issue_counts(report)
                round_trace = {
                    "round": round_index + 1,
                    "reason": "quality_not_passed",
                    "before_issue_count": issue_count,
                    "before_error_count": error_count,
                    "before_warning_count": warning_count,
                    "before_unresolved_blocks": len(getattr(report, "unresolved_blocks", []) or []),
                }
                repair_rounds.append(round_trace)
                round_repaired = _auto_repair_quality_issues(
                    cfg,
                    translator,
                    blocks,
                    report,
                    target_language,
                    project_kb,
                    repair_trace=round_trace,
                )
                if not round_repaired:
                    round_trace["result"] = "no_repair_applied"
                    break
                repaired.extend(round_repaired)
                report = _run_quality_checks_with_semantics(
                    cfg,
                    translator,
                    blocks,
                    target_language,
                    project_kb,
                    project,
                    trace,
                    progress_callback=progress_callback,
                )
                current_score = _quality_score(report)
                after_issue_count, after_error_count, after_warning_count = _quality_issue_counts(report)
                round_trace.update({
                    "after_issue_count": after_issue_count,
                    "after_error_count": after_error_count,
                    "after_warning_count": after_warning_count,
                    "after_unresolved_blocks": len(getattr(report, "unresolved_blocks", []) or []),
                    "result": "improved" if current_score < previous_score else "not_improved",
                })
                if current_score >= previous_score:
                    break
                previous_score = current_score
                if current_score == (0, 0, 0):
                    break
        post_normalized_curated_terms = normalize_curated_domain_term_translations(
            blocks,
            project_kb=project_kb,
        )
        if post_normalized_curated_terms:
            repaired.extend(post_normalized_curated_terms)
            trace.setdefault("deterministic_postprocess", {}).setdefault(
                "curated_domain_term_normalized_blocks",
                [],
            ).extend(post_normalized_curated_terms)
            report = _run_quality_checks_with_semantics(
                cfg,
                translator,
                blocks,
                target_language,
                project_kb,
                project,
                trace,
                progress_callback=progress_callback,
            )
        post_normalized_science = normalize_scientific_term_translations(blocks)
        if post_normalized_science:
            repaired.extend(post_normalized_science)
            trace.setdefault("deterministic_postprocess", {}).setdefault(
                "scientific_term_normalized_blocks",
                [],
            ).extend(post_normalized_science)
            report = _run_quality_checks_with_semantics(
                cfg,
                translator,
                blocks,
                target_language,
                project_kb,
                project,
                trace,
                progress_callback=progress_callback,
            )
        post_normalized_names = normalize_inferred_proper_name_variants(blocks)
        if post_normalized_names:
            repaired.extend(post_normalized_names)
            trace.setdefault("deterministic_postprocess", {}).setdefault(
                "proper_name_normalized_blocks",
                [],
            ).extend(post_normalized_names)
            report = _run_quality_checks_with_semantics(
                cfg,
                translator,
                blocks,
                target_language,
                project_kb,
                project,
                trace,
                progress_callback=progress_callback,
            )
        if repaired:
            report.repaired_blocks = repaired
        report.trace = trace
        _finalize_quality_conclusion(report, repaired, repair_enabled)

        root = Path(pdir)
        save_quality_report(
            report,
            json_path=root / "translation_qa_report.json",
            markdown_path=root / "translation_qa_report.md",
        )
        return repaired
    except Exception as e:
        log.warning("translation QA report failed for %s: %s", pid, e)
        return []


def _run_translate_pipeline(
    pid: str,
    target_language: str,
    owns_registration: bool = True,
    strict_quality_gate: bool = False,
):
    """Run translation pipeline in background thread.

    `owns_registration` is False when invoked as a sub-step of the full
    pipeline (see `_run_asr_pipeline`).
    """
    try:
        with slot("translate", pid):
            mutate_project(pid, lambda p: p.update({"status": "processing"}),
                           normalize=_apply_safe_defaults)
            project = _load_project(pid)
            pdir = str(PROJECTS_DIR / pid)
            cfg = Config.to_dict()
            source_name, source_path = _find_subtitle_source(pid)
            _best_effort_start_stage(
                pid,
                "translate",
                input_artifact=source_name or "",
            )

            # Load subtitle blocks
            _emit_progress(pid, "translate", 0, "正在加载字幕...")
            _check_cancel(pid)
            from app.utils.srt import parse_srt_file
            blocks = None
            if source_path:
                blocks = parse_srt_file(source_path)

            if not blocks:
                raise RuntimeError("No subtitle file found. Run ASR first.")

            _ensure_kb_review_ready(pid, project, as_http=False, config=cfg)

            # Restore filter state only for unfiltered timelines. filtered.srt
            # has already removed filtered rows and re-numbered entries, so
            # applying raw indexes here would suppress unrelated active rows.
            filter_path = os.path.join(pdir, "filter_state.json")
            if source_name != "filtered.srt" and os.path.exists(filter_path):
                try:
                    with open(filter_path, "r", encoding="utf-8") as f:
                        fstate = json.load(f)
                except Exception:
                    fstate = {}
                if isinstance(fstate, dict):
                    for b in blocks:
                        entry = fstate.get(str(b.index))
                        if not isinstance(entry, dict):
                            continue
                        filtered = entry.get("filtered", False)
                        reason = entry.get("reason", "")
                        b.filtered = filtered if isinstance(filtered, bool) else False
                        b.filter_reason = reason if isinstance(reason, str) else ""

            # KB v2 still supplies hard constraints from the shared project KB.
            # Generated suggestions are passed as soft session hints so the
            # automatic path can use likely names/places before manual review.
            candidate_terms = _auto_kb_candidate_terms(pid)
            kb_data = {"candidate_terms": candidate_terms} if candidate_terms else None

            # Initialize translator
            _emit_progress(pid, "translate", 5, "正在初始化翻译引擎...")
            _check_cancel(pid)
            from app.engines.translator import SubtitleTranslator
            translator = SubtitleTranslator(cfg)

            # Translate. translator.translate yields pct in [0,100] which maps
            # directly to the translate stage's local percentage.
            def _translate_cb(pct, msg):
                _check_cancel(pid)
                _emit_progress(pid, "translate", pct, msg)

            blocks = translator.translate(
                blocks,
                target_lang=target_language,
                meta_info=project,
                kb_data=kb_data,
                callback=_translate_cb,
            )
            _check_cancel(pid)

            final_missing_repaired = _retry_missing_translations_before_quality(
                cfg,
                translator,
                blocks,
                target_language,
                project,
                kb_data,
                progress_callback=lambda pct, msg: _emit_progress(pid, "translate", pct, msg),
            )
            if final_missing_repaired:
                log.info(
                    "final missing translation retry repaired %d block(s) for %s",
                    len(final_missing_repaired),
                    pid,
                )
            _check_cancel(pid)

            _emit_progress(pid, "translate", 92, "正在检查翻译质量...")
            repaired = _persist_translation_quality_report(
                pid,
                pdir,
                project,
                blocks,
                target_language,
                translator,
                cfg,
                progress_callback=lambda pct, msg: _emit_progress(pid, "translate", pct, msg),
            )
            if repaired:
                log.info("translation QA repaired %d block(s) for %s", len(repaired), pid)

            if _incomplete_translation_message(blocks):
                post_quality_missing_repaired = _retry_missing_translations_before_quality(
                    cfg,
                    translator,
                    blocks,
                    target_language,
                    project,
                    kb_data,
                    progress_callback=lambda pct, msg: _emit_progress(pid, "translate", pct, msg),
                )
                if post_quality_missing_repaired:
                    log.info(
                        "post-QA missing translation retry repaired %d block(s) for %s",
                        len(post_quality_missing_repaired),
                        pid,
                    )
                _emit_progress(pid, "translate", 92, "正在复检翻译质量...")
                repaired = _persist_translation_quality_report(
                    pid,
                    pdir,
                    project,
                    blocks,
                    target_language,
                    translator,
                    cfg,
                    progress_callback=lambda pct, msg: _emit_progress(pid, "translate", pct, msg),
                )
                if repaired:
                    log.info("translation QA repaired %d block(s) after post-QA retry for %s", len(repaired), pid)

            active_count, translated_count, failed_count = _translation_completion_counts(blocks)
            incomplete_msg = _incomplete_translation_message(blocks)
            quality_passed, quality_message = _translation_quality_gate_status(pid)

            # Save results
            _emit_progress(pid, "translate", 95, "正在保存结果...")
            from app.utils.srt import write_bilingual_srt

            def _write_partial_outputs() -> None:
                _remove_safe_project_files(pid, ["translated.srt", "bilingual.srt"])
                write_srt(
                    blocks,
                    os.path.join(pdir, "partial_translated.srt"),
                    use_translation=True,
                )
                write_bilingual_srt(blocks, os.path.join(pdir, "partial_bilingual.srt"))
                _mark_translation_artifacts(pid)

            if incomplete_msg or not quality_passed:
                _write_partial_outputs()
            else:
                _remove_safe_project_files(pid, ["partial_translated.srt", "partial_bilingual.srt"])
                write_report = write_srt(
                    blocks,
                    os.path.join(pdir, "translated.srt"),
                    use_translation=True,
                    return_report=True,
                )
                export_msg = _translation_export_integrity_message(blocks, write_report)
                if export_msg:
                    incomplete_msg = export_msg
                    _write_partial_outputs()
                else:
                    write_bilingual_srt(blocks, os.path.join(pdir, "bilingual.srt"))
                    _mark_translation_artifacts(pid)
            try:
                write_kb_usage_trace(Path(pdir), translator.get_kb_usage_trace())
            except Exception as e:
                log.warning("failed to persist KB usage trace for %s: %s", pid, e)

            if incomplete_msg:
                raise RuntimeError(incomplete_msg)

            if not quality_passed:
                _mark_translation_quality_failed(pid, quality_message)
                return

            done_msg = f"翻译完成: {translated_count} 条"
            if failed_count > 0:
                done_msg += f"(失败 {failed_count} 条)"
            _emit_progress(pid, "translate", 100, done_msg)

            mutate_project(
                pid,
                lambda p: p.update({
                    "status": "translated",
                    "error": None,
                    "progress": 100,
                    "progress_msg": done_msg,
                    "translation_quality_status": "passed" if quality_passed else "needs_review",
                    "translation_quality_message": quality_message,
                    "pipeline_stage": None,
                    **_translation_artifact_fields(pid),
                }),
                normalize=_apply_safe_defaults,
            )
            _best_effort_finish_stage(
                pid,
                "translate",
                output_artifact="translated.srt",
                resume_eligible=True,
            )

    except TaskCancelled as e:
        log.info("Translation pipeline cancelled for %s", pid)
        _best_effort_mark_exception(pid, "translate", e)
        try:
            _mark_project_cancelled(pid, "translate")
        except Exception:
            pass
        _emit_progress(pid, "translate", 0, "已取消")
    except Exception as e:
        log.exception("Translation pipeline failed for %s", pid)
        _best_effort_mark_exception(pid, "translate", e)
        error_msg = _safe_error_message(e)
        try:
            mutate_project(pid, lambda p: p.update({"status": "error",
                                                     "error": error_msg,
                                                     "pipeline_stage": None,
                                                     "progress_msg": f"错误: {_safe_error_message(e, 100)}"}),
                           normalize=_apply_safe_defaults)
        except Exception:
            pass
        _emit_progress(pid, "translate", 0, f"错误: {_safe_error_message(e, 100)}")
    finally:
        if owns_registration:
            unregister_task(pid)


def _build_bilingual_tracks(pid: str):
    """For trailer projects: generate available zh/en SRT tracks."""
    pdir = project_dir(pid)

    # Regenerate zh/en SRTs from translated.srt / filtered.srt.
    # translated.srt already contains the target-language text; filtered.srt
    # contains the source-language (English for trailers) text. Timestamps match
    # because both were written from the same block list during translate stage.
    translated = _safe_project_artifact_path(pid, "translated.srt")
    filtered = _safe_project_artifact_path(pid, "filtered.srt")
    zh_path = None
    en_path = None
    if translated is not None:
        zh_path = _write_generated_project_artifact(pid, "zh.srt", translated.read_bytes(), pdir)
    if filtered is not None:
        en_path = _write_generated_project_artifact(pid, "en.srt", filtered.read_bytes(), pdir)

    # Dynamic sizing. Without a cheap video-height probe here, use 1080 as a sane
    # default — compute_font_sizes clamps below 18 anyway.
    video_height = 1080
    zh_size, en_size = compute_font_sizes(video_height)

    tracks = []
    if zh_path is not None:
        tracks.append(SubtitleTrack(
            path=str(zh_path),
            font_name=resolve_font("zh"),
            font_size=zh_size,
            outline_width=2.0,
            margin_v=70,
        ))
    if en_path is not None:
        tracks.append(SubtitleTrack(
            path=str(en_path),
            font_name=resolve_font("en"),
            font_size=en_size,
            outline_width=1.5,
            margin_v=30,
        ))
    return tracks


def _build_upload_legacy_track(srt_path: str) -> "SubtitleTrack":
    """Preserve the pre-Phase-3 visual style for upload projects.

    Hiragino Sans GB / 22 / Outline=2 — matches the look users had before the
    bilingual burn refactor.
    """
    return SubtitleTrack(
        path=srt_path,
        font_name="Hiragino Sans GB",
        font_size=22,
        outline_width=2.0,
        margin_v=30,
    )


def _mark_stage_running(pid: str, stage: str, *, message: str = "", progress: Optional[int] = None) -> None:
    def _update(project: dict) -> None:
        payload = {
            "status": "processing",
            "pipeline_stage": stage,
            "error": None,
        }
        if isinstance(progress, int) and not isinstance(progress, bool):
            payload["progress"] = max(0, min(100, progress))
        if isinstance(message, str) and message:
            payload["progress_msg"] = message
        project.update(payload)

    mutate_project(pid, _update, normalize=_apply_safe_defaults)


def _translation_artifact_fields(pid: str) -> dict[str, Optional[str]]:
    fields: dict[str, Optional[str]] = {
        "translated_srt": None,
        "bilingual_srt": None,
    }
    for key, artifact in (
        ("translated_srt", "translated.srt"),
        ("bilingual_srt", "bilingual.srt"),
    ):
        path = _safe_project_artifact_path(pid, artifact)
        if path is not None and path.is_file():
            fields[key] = str(path)
    return fields


def _mark_translation_artifacts(pid: str) -> None:
    fields = _translation_artifact_fields(pid)
    mutate_project(pid, lambda p: p.update(fields), normalize=_apply_safe_defaults)


def _mark_burn_completed(pid: str, output_video: str, message: str) -> None:
    artifact_fields = _translation_artifact_fields(pid)
    mutate_project(pid, lambda p: p.update({"status": "completed",
                                             "output_video": output_video,
                                             "error": None,
                                             "progress": 100,
                                             "progress_msg": message,
                                             "pipeline_stage": None,
                                             **artifact_fields}),
                   normalize=_apply_safe_defaults)


def _mark_burn_unavailable(pid: str, reason: str = "无字幕文件可烧录") -> None:
    mutate_project(pid, lambda p: p.update({"status": "translated",
                                             "error": f"字幕烧录失败: {reason}",
                                             "progress": 100,
                                             "progress_msg": "翻译完成，但字幕烧录失败",
                                             "pipeline_stage": None}),
                   normalize=_apply_safe_defaults)


def _mark_burn_failed(pid: str, reason: str) -> None:
    mutate_project(pid, lambda p: p.update({"status": "translated",
                                             "error": reason,
                                             "progress": 100,
                                             "progress_msg": "翻译完成，但字幕烧录失败",
                                             "pipeline_stage": None}),
                   normalize=_apply_safe_defaults)


def _run_burn_pipeline(pid: str):
    """Burn subtitles into video.

    Trailer projects: bilingual burn (zh top + en bottom) from zh.srt/en.srt.
    Upload projects: single-track burn with legacy visual style (bilingual.srt
    preferred over translated.srt).

    On success: status=completed, output_video set.
    On burn failure: status=translated with an error note (translation still usable).
    """
    try:
        with slot("burn", pid):
            project = _load_project(pid)
            pdir = str(PROJECTS_DIR / pid)
            video_path = project["video_path"]
            _best_effort_start_stage(pid, "burn", input_artifact=video_path)
            _mark_stage_running(pid, "burn", message="正在烧录字幕到视频...", progress=75)

            _emit_progress(pid, "burn", 0, "正在烧录字幕到视频...")
            _check_cancel(pid)

            if project.get("source_type") == "trailer":
                # Trailer: bilingual (zh big on top, en small below).
                if not _first_safe_project_artifact(pid, ["translated.srt", "filtered.srt"])[0]:
                    reason = "无字幕文件可烧录"
                    _mark_burn_unavailable(pid, reason)
                    _best_effort_fail_stage(pid, "burn", reason)
                    _emit_progress(pid, "burn", 100, "翻译完成 (无字幕文件可烧录)")
                    return
                tracks = _build_bilingual_tracks(pid)
            else:
                # Upload: single-track legacy style. Prefer bilingual.srt if present.
                _, srt_path = _first_safe_project_artifact(pid, ["bilingual.srt", "translated.srt"])
                if srt_path is None:
                    reason = "无字幕文件可烧录"
                    _mark_burn_unavailable(pid, reason)
                    _best_effort_fail_stage(pid, "burn", reason)
                    _emit_progress(pid, "burn", 100, "翻译完成 (无字幕文件可烧录)")
                    return
                tracks = [_build_upload_legacy_track(str(srt_path))]

            base_name = os.path.splitext(os.path.basename(video_path))[0]
            output_path = _safe_generated_project_output_path(pid, f"{base_name}_subtitled.mp4")
            if output_path is None:
                reason = "字幕烧录失败: 输出路径无效"
                _mark_burn_failed(pid, reason)
                _best_effort_fail_stage(pid, "burn", reason)
                _emit_progress(pid, "burn", 100, "翻译完成，但字幕烧录失败")
                return
            output_video = str(output_path)
            success = burn_subtitles(
                video_path, tracks, output_video,
                callback=lambda msg: _emit_progress(pid, "burn", 50, msg),
            )
            if success:
                _mark_burn_completed(pid, output_video, "全部完成! 字幕已烧录到视频")
                _best_effort_finish_stage(
                    pid,
                    "burn",
                    output_artifact=output_video,
                    resume_eligible=True,
                )
                _emit_progress(pid, "burn", 100, "全部完成! 字幕已烧录到视频")
                from app.engines.audio import cleanup_intermediate
                cleanup_intermediate(pdir)
            else:
                # Burning failed but translation succeeded - still usable
                reason = "字幕烧录失败，但翻译已完成"
                _mark_burn_failed(pid, reason)
                _best_effort_fail_stage(pid, "burn", reason)
                _emit_progress(pid, "burn", 100, "翻译完成，但字幕烧录失败")
    except TaskCancelled as e:
        log.info("Burn pipeline cancelled for %s", pid)
        _best_effort_mark_exception(pid, "burn", e)
        try:
            fields = _mark_project_cancelled(pid, "burn")
            message = fields.get("progress_msg") if isinstance(fields.get("progress_msg"), str) else "已取消"
        except Exception:
            message = "已取消"
        _emit_progress(pid, "burn", 0, message)
    except Exception as e:
        _best_effort_mark_exception(pid, "burn", e)
        raise


def _run_full_pipeline(pid: str, audio_track: int, language: str, target_language: str):
    """Run full pipeline: ASR + Filter + Translate + Burn subtitles."""
    try:
        _run_asr_pipeline(pid, audio_track, language, owns_registration=False)
        # Check if ASR succeeded
        project = _load_project(pid)
        if project["status"] == "error":
            return
        _check_cancel(pid)
        _run_translate_pipeline(
            pid,
            target_language,
            owns_registration=False,
            strict_quality_gate=True,
        )

        # Check if translation succeeded
        project = _load_project(pid)
        if project["status"] == "error":
            return
        if project.get("translation_quality_status") == "needs_review":
            return
        _check_cancel(pid)

        _run_burn_pipeline(pid)

    except TaskCancelled as e:
        log.info("Full pipeline cancelled for %s", pid)
        stage = _stage_for_cancelled_exception(pid, "asr")
        _best_effort_mark_exception(pid, stage, e)
        try:
            fields = _mark_project_cancelled(pid, stage)
            message = fields.get("progress_msg") if isinstance(fields.get("progress_msg"), str) else "已取消"
        except Exception:
            message = "已取消"
        _emit_progress(pid, stage, 0, message)
    except Exception as e:
        log.exception("Full pipeline failed for %s", pid)
        error_msg = _safe_error_message(e)
        try:
            mutate_project(pid, lambda p: p.update({"status": "error",
                                                     "error": error_msg,
                                                     "pipeline_stage": None,
                                                     "progress_msg": f"错误: {_safe_error_message(e, 100)}"}),
                           normalize=_apply_safe_defaults)
        except Exception:
            pass
        _emit_progress(pid, "burn", 0, f"错误: {_safe_error_message(e, 100)}")
    finally:
        unregister_task(pid)


def _run_asr_translate_pipeline(pid: str, audio_track: int, language: str, target_language: str):
    """Run ASR + translation without burning subtitles into a video."""
    try:
        _run_asr_pipeline(pid, audio_track, language, owns_registration=False)
        project = _load_project(pid)
        if project["status"] == "error":
            return
        _check_cancel(pid)
        _run_translate_pipeline(pid, target_language, owns_registration=False)
    except TaskCancelled as e:
        log.info("ASR+translate pipeline cancelled for %s", pid)
        stage = _stage_for_cancelled_exception(pid, "asr")
        _best_effort_mark_exception(pid, stage, e)
        try:
            fields = _mark_project_cancelled(pid, stage)
            message = fields.get("progress_msg") if isinstance(fields.get("progress_msg"), str) else "已取消"
        except Exception:
            message = "已取消"
        _emit_progress(pid, stage, 0, message)
    except Exception as e:
        log.exception("ASR+translate pipeline failed for %s", pid)
        error_msg = _safe_error_message(e)
        try:
            mutate_project(
                pid,
                lambda p: p.update({"status": "error",
                                    "error": error_msg,
                                    "pipeline_stage": None,
                                    "progress_msg": f"错误: {_safe_error_message(e, 100)}"}),
                normalize=_apply_safe_defaults,
            )
        except Exception:
            pass
        _emit_progress(pid, "translate", 0, f"错误: {_safe_error_message(e, 100)}")
    finally:
        unregister_task(pid)


@router.post("/{pid}/start-asr")
def start_asr(pid: str = PathParam(pattern=PID_PATTERN), req: ASRRequest = ASRRequest()):
    """Start ASR pipeline."""
    project = _load_project(pid)
    _reject_busy_project(project)
    audio_track = _resolve_audio_track(project, req.audio_track)
    language = _resolve_text_option(req.language, project.get("asr_language"), "auto", "language")
    try:
        t = try_register_task(pid, lambda: threading.Thread(
            target=_run_asr_pipeline, args=(pid, audio_track, language), daemon=True),
            reset_cancellation=True)
    except TaskAlreadyRunning:
        raise HTTPException(409, "Task already running for this project")
    try:
        _persist_workflow_options(pid, audio_track=audio_track, language=language)
        _reset_workflow_for_action(pid, "asr")
    except Exception:
        unregister_task(pid)
        raise
    t.start()
    return {"status": "started", "message": "ASR pipeline started"}


@router.post("/{pid}/start-translate")
def start_translate(pid: str = PathParam(pattern=PID_PATTERN), req: TranslateRequest = TranslateRequest()):
    """Start translation pipeline."""
    project = _load_project(pid)
    _reject_busy_project(project)
    target_lang = _resolve_text_option(
        req.target_language,
        project.get("target_language"),
        "简体中文",
        "target_language",
    )
    require_translation_ready()
    _ensure_kb_review_ready(pid, project, as_http=True, config=Config.to_dict())
    try:
        t = try_register_task(pid, lambda: threading.Thread(
            target=_run_translate_pipeline, args=(pid, target_lang), daemon=True),
            reset_cancellation=True)
    except TaskAlreadyRunning:
        raise HTTPException(409, "Task already running for this project")
    try:
        _persist_workflow_options(pid, target_language=target_lang)
        _reset_workflow_for_action(pid, "translate")
    except Exception:
        unregister_task(pid)
        raise
    t.start()
    return {"status": "started", "message": "Translation started"}


@router.post("/{pid}/start-full")
def start_full(pid: str = PathParam(pattern=PID_PATTERN), req: FullPipelineRequest = FullPipelineRequest()):
    """Start full pipeline (ASR + translate)."""
    project = _load_project(pid)
    _reject_busy_project(project)
    workflow_mode = _resolve_workflow_mode(
        req.workflow_mode,
        project,
        can_burn=_project_supports_video_burn(project),
    )
    if _project_source_type(project) == "audio":
        return start_transcribe_translate(pid, req)
    if _project_source_type(project) == "subtitle":
        response = start_translate(
            pid,
            TranslateRequest(target_language=req.target_language),
        )
        _persist_workflow_options(pid, workflow_mode="translate_only")
        return _add_launch_stage(response, "translate")
    if workflow_mode == "translate_only":
        return start_transcribe_translate(
            pid,
            FullPipelineRequest(
                audio_track=req.audio_track,
                language=req.language,
                target_language=req.target_language,
                workflow_mode="translate_only",
            ),
        )
    audio_track = _resolve_audio_track(project, req.audio_track)
    language = _resolve_text_option(req.language, project.get("asr_language"), "auto", "language")
    target_lang = _resolve_text_option(
        req.target_language,
        project.get("target_language"),
        "简体中文",
        "target_language",
    )
    require_translation_ready()
    try:
        t = try_register_task(pid, lambda: threading.Thread(
            target=_run_full_pipeline,
            args=(pid, audio_track, language, target_lang),
            daemon=True,
        ), reset_cancellation=True)
    except TaskAlreadyRunning:
        raise HTTPException(409, "Task already running for this project")
    try:
        _persist_workflow_options(
            pid,
            audio_track=audio_track,
            language=language,
            target_language=target_lang,
            workflow_mode=workflow_mode,
        )
        _reset_workflow_for_action(pid, "full")
    except Exception:
        unregister_task(pid)
        raise
    t.start()
    return {"status": "started", "message": "Full pipeline started"}


@router.post("/{pid}/start-transcribe-translate")
def start_transcribe_translate(pid: str = PathParam(pattern=PID_PATTERN), req: FullPipelineRequest = FullPipelineRequest()):
    """Start ASR + translation without the video burn stage."""
    project = _load_project(pid)
    _reject_busy_project(project)
    workflow_mode = _resolve_workflow_mode(req.workflow_mode, project, can_burn=False)
    audio_track = _resolve_audio_track(project, req.audio_track)
    language = _resolve_text_option(req.language, project.get("asr_language"), "auto", "language")
    target_lang = _resolve_text_option(
        req.target_language,
        project.get("target_language"),
        "简体中文",
        "target_language",
    )
    require_translation_ready()
    try:
        t = try_register_task(pid, lambda: threading.Thread(
            target=_run_asr_translate_pipeline,
            args=(pid, audio_track, language, target_lang),
            daemon=True,
        ), reset_cancellation=True)
    except TaskAlreadyRunning:
        raise HTTPException(409, "Task already running for this project")
    try:
        _persist_workflow_options(
            pid,
            audio_track=audio_track,
            language=language,
            target_language=target_lang,
            workflow_mode=workflow_mode,
        )
        _reset_workflow_for_action(pid, "asr_translate")
    except Exception:
        unregister_task(pid)
        raise
    t.start()
    return {
        "status": "started",
        "message": "Transcription and translation started",
        "stage": "asr_translate",
    }


def _launch_resume_stage(pid: str, project: dict, stage: str) -> dict:
    if stage == "asr":
        response = start_asr(pid, ASRRequest(language=project.get("asr_language")))
    elif stage == "translate":
        response = start_translate(
            pid,
            TranslateRequest(target_language=project.get("target_language")),
        )
    elif stage == "burn":
        if not _project_supports_video_burn(project):
            raise HTTPException(400, "Project source does not support video burn")
        response = start_burn(pid)
    else:
        raise HTTPException(400, "stage must be asr, translate, or burn")
    return _add_launch_stage(response, stage)


@router.post("/{pid}/retry")
def retry_project(pid: str = PathParam(pattern=PID_PATTERN), req: RetryRequest = RetryRequest()):
    """Retry the latest failed workflow stage, or a requested supported stage."""
    project = _load_project(pid)
    if is_task_registered(pid):
        raise HTTPException(409, "Task already running for this project")
    _reject_busy_project(project)
    requested_stage = req.stage.strip() if isinstance(req.stage, str) else ""
    stage = requested_stage or _latest_failed_stage(pid)
    return _launch_resume_stage(pid, project, stage)


@router.post("/{pid}/resume")
def resume_project(pid: str = PathParam(pattern=PID_PATTERN)):
    """Resume the workflow from the best available local artifact."""
    project = _load_project(pid)
    if is_task_registered(pid):
        raise HTTPException(409, "Task already running for this project")
    _reject_busy_project(project)
    stage = _resume_stage_for_project(pid, project)
    return _launch_resume_stage(pid, project, stage)


@router.post("/{pid}/cancel")
def cancel_task(pid: str = PathParam(pattern=PID_PATTERN)):
    """Cancel running task (best effort, cooperative via scheduler cancel events)."""
    project = _load_project(pid)
    cancellable_pipeline = (
        project.get("status") == "processing"
        or bool(project.get("pipeline_stage"))
    )
    if is_task_registered(pid) or cancellable_pipeline:
        stage = _resolve_cancel_stage(pid, project)
        # Signal worker threads via scheduler cancel events — they'll observe at
        # the next _check_cancel checkpoint and raise.
        request_cancel(pid)
        _best_effort_cancel_workflow(pid, stage)
        fields = {"status": "cancelled", "progress_msg": "已取消"}
        try:
            fields = _mark_project_cancelled(pid, stage)
        except Exception:
            pass
        message = fields.get("progress_msg") if isinstance(fields.get("progress_msg"), str) else "已取消"
        _emit_progress(pid, stage, 0, message)
        return {
            "status": "cancelled",
            "project_status": fields.get("status", "cancelled"),
            "message": message,
        }
    return {"status": "no_task"}


@router.post("/{pid}/burn")
def start_burn(pid: str = PathParam(pattern=PID_PATTERN)):
    """Burn subtitles into video (standalone)."""
    project = _load_project(pid)
    _reject_busy_project(project)
    if not _project_supports_video_burn(project):
        raise HTTPException(400, "Project source does not support video burn")

    def _burn_task():
        try:
            with slot("burn", pid):
                pdir = str(PROJECTS_DIR / pid)
                video_path = project["video_path"]
                _best_effort_start_stage(pid, "burn", input_artifact=video_path)
                _mark_stage_running(pid, "burn", message="正在烧录字幕到视频...", progress=75)

                _emit_progress(pid, "burn", 0, "正在烧录字幕到视频...")
                _check_cancel(pid)

                if project.get("source_type") == "trailer":
                    if not _first_safe_project_artifact(pid, ["translated.srt", "filtered.srt"])[0]:
                        reason = "无字幕文件可烧录"
                        _mark_burn_unavailable(pid)
                        _best_effort_fail_stage(pid, "burn", reason)
                        _emit_progress(pid, "burn", 0, "字幕烧录失败 (无字幕文件)")
                        return
                    tracks = _build_bilingual_tracks(pid)
                else:
                    _, srt_path = _first_safe_project_artifact(pid, ["bilingual.srt", "translated.srt"])
                    if srt_path is None:
                        reason = "无字幕文件可烧录"
                        _mark_burn_unavailable(pid)
                        _best_effort_fail_stage(pid, "burn", reason)
                        _emit_progress(pid, "burn", 0, "字幕烧录失败 (无字幕文件)")
                        return
                    tracks = [_build_upload_legacy_track(str(srt_path))]

                base_name = os.path.splitext(os.path.basename(video_path))[0]
                output_path = _safe_generated_project_output_path(pid, f"{base_name}_subtitled.mp4")
                if output_path is None:
                    reason = "字幕烧录失败: 输出路径无效"
                    _mark_burn_failed(pid, reason)
                    _best_effort_fail_stage(pid, "burn", reason)
                    _emit_progress(pid, "burn", 0, "字幕烧录失败")
                    return
                output_video = str(output_path)
                success = burn_subtitles(
                    video_path, tracks, output_video,
                    callback=lambda msg: _emit_progress(pid, "burn", 50, msg),
                )
                if success:
                    _mark_burn_completed(pid, output_video, "字幕烧录完成!")
                    _best_effort_finish_stage(
                        pid,
                        "burn",
                        output_artifact=output_video,
                        resume_eligible=True,
                    )
                    _emit_progress(pid, "burn", 100, "字幕烧录完成!")
                    from app.engines.audio import cleanup_intermediate
                    cleanup_intermediate(pdir)
                else:
                    # Burn failed but translation is still valid — mirror
                    # _run_burn_pipeline so the UI sees a real failure state
                    # instead of stale 'translated' with no error note.
                    reason = "字幕烧录失败，但翻译已完成"
                    _mark_burn_failed(pid, reason)
                    _best_effort_fail_stage(pid, "burn", reason)
                    _emit_progress(pid, "burn", 0, "字幕烧录失败")
        except TaskCancelled as e:
            log.info("Standalone burn cancelled for %s", pid)
            _best_effort_mark_exception(pid, "burn", e)
            try:
                fields = _mark_project_cancelled(pid, "burn")
                message = fields.get("progress_msg") if isinstance(fields.get("progress_msg"), str) else "已取消"
            except Exception:
                message = "已取消"
            _emit_progress(pid, "burn", 0, message)
        except Exception as e:
            _best_effort_mark_exception(pid, "burn", e)
            error_msg = _safe_error_message(e, 120)
            try:
                mutate_project(pid, lambda p: p.update({"status": "translated",
                                                         "error": f"字幕烧录异常: {error_msg}",
                                                         "pipeline_stage": None,
                                                         "progress_msg": f"错误: {_safe_error_message(e, 100)}"}),
                               normalize=_apply_safe_defaults)
            except Exception:
                pass
            _emit_progress(pid, "burn", 0, f"错误: {_safe_error_message(e, 100)}")
        finally:
            unregister_task(pid)

    try:
        t = try_register_task(
            pid,
            lambda: threading.Thread(target=_burn_task, daemon=True),
            reset_cancellation=True,
        )
    except TaskAlreadyRunning:
        raise HTTPException(409, "Task already running for this project")
    try:
        _reset_workflow_for_action(pid, "burn")
    except Exception:
        unregister_task(pid)
        raise
    t.start()
    return {"status": "started", "message": "Burning subtitles into video"}


@router.get("/{pid}/progress")
def get_progress(pid: str = PathParam(pattern=PID_PATTERN)):
    """Get current progress for a project."""
    return _scheduler_get_progress(pid) or {"progress": 0, "message": ""}
