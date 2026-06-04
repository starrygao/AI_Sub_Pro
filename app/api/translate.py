"""
Translation pipeline control API routes.
Handles long-running ASR and translation tasks.
"""
import os
import json
import asyncio
import logging
import math
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
from app.api.projects import _apply_safe_defaults
from app.utils.project_store import atomic_write_json, mutate_project, PID_PATTERN
from app.engines.scheduler import (
    get_progress as _scheduler_get_progress,
    update_progress as _scheduler_update_progress,
    progress_store,  # re-export for compatibility with older internal imports
    slot,
    is_cancelled,
    reset_cancel,
    request_cancel,
)
from app.utils.errors import redact_error_message

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["pipeline"])

# Active tasks tracker
active_tasks: Dict[str, threading.Thread] = {}
_tasks_lock = threading.Lock()


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
        raise RuntimeError(f"cancelled by user pid={pid}")


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


def _persist_workflow_options(
    pid: str,
    *,
    audio_track: Optional[int] = None,
    language: Optional[str] = None,
    target_language: Optional[str] = None,
) -> None:
    """Persist manually selected run options before launching a worker."""
    def _apply(project: dict) -> None:
        if audio_track is not None:
            project["selected_audio_track"] = audio_track
        if language is not None:
            project["asr_language"] = language
        if target_language is not None:
            project["target_language"] = target_language

    mutate_project(pid, _apply, normalize=_apply_safe_defaults)


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

            # Fast path: use embedded subtitle if present + enabled.
            if _try_bypass_asr_with_embedded_subtitle(pid, project, pdir):
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

    except Exception as e:
        log.exception("ASR pipeline failed for %s", pid)
        error_msg = _safe_error_message(e)
        try:
            mutate_project(pid, lambda p: p.update({"status": "error",
                                                     "error": error_msg}),
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
    active = [b for b in blocks if not b.filtered and (b.text or "").strip()]
    if not active:
        return None
    if any(b.translation for b in active):
        return None
    return next((b.translation_error for b in active if b.translation_error), None)


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


def _auto_repair_quality_issues(cfg: dict, translator, blocks, report, target_language: str, project_kb) -> list[dict]:
    trans_cfg = cfg.get("translation", {}) if isinstance(cfg, dict) else {}
    if not isinstance(trans_cfg, dict) or not trans_cfg.get("qa_auto_repair", False):
        return []
    if not report.issues:
        return []
    try:
        from app.engines.translation_qa import build_repair_items, build_repair_prompt
        from app.engines.providers.result_contract import reconcile_translation_results

        repair_items = build_repair_items(blocks, report.issues)
        if not repair_items:
            return []
        prompt = build_repair_prompt(
            target_language,
            repair_items,
            report.issues,
            kb_terms=_project_kb_terms(project_kb),
        )
        primary = getattr(translator, "primary", None)
        if primary is None or not hasattr(primary, "translate_batch"):
            return []
        raw_results = primary.translate_batch(repair_items, prompt)
        results = reconcile_translation_results(
            raw_results if isinstance(raw_results, list) else [],
            repair_items,
        )
        if hasattr(translator, "_apply_results"):
            target_blocks = [
                block for block in blocks
                if any(str(item.get("id")) == str(getattr(block, "index", "")) for item in repair_items)
            ]
            translator._apply_results(target_blocks, results)
        else:
            by_id = {
                str(result.get("id")): result.get("translation", "")
                for result in results
                if isinstance(result, dict) and isinstance(result.get("translation"), str)
            }
            for block in blocks:
                translation = by_id.get(str(getattr(block, "index", "")))
                if translation:
                    block.translation = translation
        repaired = [
            {"id": result.get("id"), "translation": result.get("translation", "")}
            for result in results
            if isinstance(result, dict) and result.get("translation")
        ]
        return repaired
    except Exception as e:
        log.warning("translation QA auto-repair failed: %s", e)
        return []


def _persist_translation_quality_report(pid: str, pdir: str, project: dict, blocks, target_language: str, translator, cfg: dict) -> None:
    """Run deterministic QA and persist local report artifacts.

    QA reporting must not make an otherwise usable translation fail. Any
    unexpected report error is logged and ignored so translated.srt/bilingual.srt
    still get written.
    """
    try:
        from app.engines.knowledge import _get_singleton
        from app.engines.translation_qa import run_quality_checks, save_quality_report

        project_kb = _get_singleton().select_for_project(project)
        trace_obj = getattr(translator, "last_quality_trace", None)
        trace = trace_obj.to_dict() if hasattr(trace_obj, "to_dict") else {}
        report = run_quality_checks(
            blocks,
            project_kb=project_kb,
            target_language=target_language,
            trace=trace,
        )
        repaired = _auto_repair_quality_issues(
            cfg,
            translator,
            blocks,
            report,
            target_language,
            project_kb,
        )
        if repaired:
            report = run_quality_checks(
                blocks,
                project_kb=project_kb,
                target_language=target_language,
                trace=trace,
            )
            report.repaired_blocks = repaired
        root = Path(pdir)
        save_quality_report(
            report,
            json_path=root / "translation_qa_report.json",
            markdown_path=root / "translation_qa_report.md",
        )
    except Exception as e:
        log.warning("translation QA report failed for %s: %s", pid, e)


def _run_translate_pipeline(pid: str, target_language: str, owns_registration: bool = True):
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

            # Load subtitle blocks
            _emit_progress(pid, "translate", 0, "正在加载字幕...")
            _check_cancel(pid)
            from app.utils.srt import parse_srt_file
            blocks = None
            source_name = None
            for fname in ["filtered.srt", "raw.srt", "native.srt"]:
                fpath = os.path.join(pdir, fname)
                if os.path.exists(fpath):
                    blocks = parse_srt_file(fpath)
                    source_name = fname
                    break

            if not blocks:
                raise RuntimeError("No subtitle file found. Run ASR first.")

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

            # KB v2: the translator now reads the shared KnowledgeBase
            # singleton directly via `select_for_project` + `build_prompt_snippet`
            # (see `app/engines/translator.py`). Legacy kb_data is passed as
            # None so the v2 injection path is the only one that fires.
            kb_data = None

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

            # Surface total failure instead of reporting a false success
            # (e.g. wrong API key / model — every block fails silently).
            fail_msg = _translation_failed_completely(blocks)
            if fail_msg:
                raise RuntimeError(f"翻译失败: {fail_msg}")

            _persist_translation_quality_report(pid, pdir, project, blocks, target_language, translator, cfg)

            # Save results
            _emit_progress(pid, "translate", 95, "正在保存结果...")
            write_srt(blocks, os.path.join(pdir, "translated.srt"), use_translation=True)

            from app.utils.srt import write_bilingual_srt
            write_bilingual_srt(blocks, os.path.join(pdir, "bilingual.srt"))

            active_count = sum(1 for b in blocks if not b.filtered and (b.text or "").strip())
            translated_count = sum(1 for b in blocks if b.translation and not b.filtered)
            failed_count = active_count - translated_count
            done_msg = f"翻译完成: {translated_count} 条"
            if failed_count > 0:
                done_msg += f"(失败 {failed_count} 条)"
            _emit_progress(pid, "translate", 100, done_msg)

            mutate_project(pid, lambda p: p.update({"status": "translated", "error": None}),
                           normalize=_apply_safe_defaults)

    except Exception as e:
        log.exception("Translation pipeline failed for %s", pid)
        error_msg = _safe_error_message(e)
        try:
            mutate_project(pid, lambda p: p.update({"status": "error",
                                                     "error": error_msg}),
                           normalize=_apply_safe_defaults)
        except Exception:
            pass
        _emit_progress(pid, "translate", 0, f"错误: {_safe_error_message(e, 100)}")
    finally:
        if owns_registration:
            unregister_task(pid)


def _build_bilingual_tracks(pid: str):
    """For trailer projects: generate available zh/en SRT tracks."""
    pdir = PROJECTS_DIR / pid
    zh_path = pdir / "zh.srt"
    en_path = pdir / "en.srt"

    # Regenerate zh/en SRTs from translated.srt / filtered.srt.
    # translated.srt already contains the target-language text; filtered.srt
    # contains the source-language (English for trailers) text. Timestamps match
    # because both were written from the same block list during translate stage.
    translated = pdir / "translated.srt"
    filtered = pdir / "filtered.srt"
    if translated.exists():
        zh_path.write_bytes(translated.read_bytes())
    if filtered.exists():
        en_path.write_bytes(filtered.read_bytes())

    # Dynamic sizing. Without a cheap video-height probe here, use 1080 as a sane
    # default — compute_font_sizes clamps below 18 anyway.
    video_height = 1080
    zh_size, en_size = compute_font_sizes(video_height)

    tracks = []
    if zh_path.exists():
        tracks.append(SubtitleTrack(
            path=str(zh_path),
            font_name=resolve_font("zh"),
            font_size=zh_size,
            outline_width=2.0,
            margin_v=70,
        ))
    if en_path.exists():
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


def _mark_burn_unavailable(pid: str, reason: str = "无字幕文件可烧录") -> None:
    mutate_project(pid, lambda p: p.update({"status": "translated",
                                             "error": f"字幕烧录失败: {reason}"}),
                   normalize=_apply_safe_defaults)


def _run_burn_pipeline(pid: str):
    """Burn subtitles into video.

    Trailer projects: bilingual burn (zh top + en bottom) from zh.srt/en.srt.
    Upload projects: single-track burn with legacy visual style (bilingual.srt
    preferred over translated.srt).

    On success: status=completed, output_video set.
    On burn failure: status=translated with an error note (translation still usable).
    """
    with slot("burn", pid):
        _emit_progress(pid, "burn", 0, "正在烧录字幕到视频...")
        _check_cancel(pid)

        project = _load_project(pid)
        pdir = str(PROJECTS_DIR / pid)
        video_path = project["video_path"]

        if project.get("source_type") == "trailer":
            # Trailer: bilingual (zh big on top, en small below).
            translated = os.path.join(pdir, "translated.srt")
            filtered = os.path.join(pdir, "filtered.srt")
            if not (os.path.exists(translated) or os.path.exists(filtered)):
                _mark_burn_unavailable(pid)
                _emit_progress(pid, "burn", 100, "翻译完成 (无字幕文件可烧录)")
                return
            tracks = _build_bilingual_tracks(pid)
        else:
            # Upload: single-track legacy style. Prefer bilingual.srt if present.
            srt_path = os.path.join(pdir, "bilingual.srt")
            if not os.path.exists(srt_path):
                srt_path = os.path.join(pdir, "translated.srt")
            if not os.path.exists(srt_path):
                _mark_burn_unavailable(pid)
                _emit_progress(pid, "burn", 100, "翻译完成 (无字幕文件可烧录)")
                return
            tracks = [_build_upload_legacy_track(srt_path)]

        base_name = os.path.splitext(os.path.basename(video_path))[0]
        output_video = os.path.join(pdir, f"{base_name}_subtitled.mp4")
        success = burn_subtitles(
            video_path, tracks, output_video,
            callback=lambda msg: _emit_progress(pid, "burn", 50, msg),
        )
        if success:
            _out = output_video
            mutate_project(pid, lambda p: p.update({"status": "completed",
                                                     "output_video": _out,
                                                     "error": None}),
                           normalize=_apply_safe_defaults)
            _emit_progress(pid, "burn", 100, "全部完成! 字幕已烧录到视频")
            from app.engines.audio import cleanup_intermediate
            cleanup_intermediate(pdir)
        else:
            # Burning failed but translation succeeded - still usable
            mutate_project(pid, lambda p: p.update({"status": "translated",
                                                     "error": "字幕烧录失败，但翻译已完成"}),
                           normalize=_apply_safe_defaults)
            _emit_progress(pid, "burn", 100, "翻译完成，但字幕烧录失败")


def _run_full_pipeline(pid: str, audio_track: int, language: str, target_language: str):
    """Run full pipeline: ASR + Filter + Translate + Burn subtitles."""
    try:
        _run_asr_pipeline(pid, audio_track, language, owns_registration=False)
        # Check if ASR succeeded
        project = _load_project(pid)
        if project["status"] == "error":
            return
        _check_cancel(pid)
        _run_translate_pipeline(pid, target_language, owns_registration=False)

        # Check if translation succeeded
        project = _load_project(pid)
        if project["status"] == "error":
            return
        _check_cancel(pid)

        _run_burn_pipeline(pid)

    except Exception as e:
        log.exception("Full pipeline failed for %s", pid)
        error_msg = _safe_error_message(e)
        try:
            mutate_project(pid, lambda p: p.update({"status": "error",
                                                     "error": error_msg}),
                           normalize=_apply_safe_defaults)
        except Exception:
            pass
        _emit_progress(pid, "burn", 0, f"错误: {_safe_error_message(e, 100)}")
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
    try:
        t = try_register_task(pid, lambda: threading.Thread(
            target=_run_translate_pipeline, args=(pid, target_lang), daemon=True),
            reset_cancellation=True)
    except TaskAlreadyRunning:
        raise HTTPException(409, "Task already running for this project")
    try:
        _persist_workflow_options(pid, target_language=target_lang)
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
        )
    except Exception:
        unregister_task(pid)
        raise
    t.start()
    return {"status": "started", "message": "Full pipeline started"}


@router.post("/{pid}/cancel")
def cancel_task(pid: str = PathParam(pattern=PID_PATTERN)):
    """Cancel running task (best effort, cooperative via scheduler cancel events)."""
    project = _load_project(pid)
    cancellable_pipeline = (
        project.get("status") == "processing"
        or bool(project.get("pipeline_stage"))
    )
    if is_task_registered(pid) or cancellable_pipeline:
        # Signal worker threads via scheduler cancel events — they'll observe at
        # the next _check_cancel checkpoint and raise.
        request_cancel(pid)
        try:
            mutate_project(pid, lambda p: p.update({"status": "error",
                                                     "pipeline_stage": None,
                                                     "error": "Cancelled by user"}),
                           normalize=_apply_safe_defaults)
        except Exception:
            pass
        stage = project.get("pipeline_stage") if isinstance(project.get("pipeline_stage"), str) else "asr"
        _emit_progress(pid, stage, 0, "已取消")
        return {"status": "cancelled"}
    return {"status": "no_task"}


@router.post("/{pid}/burn")
def start_burn(pid: str = PathParam(pattern=PID_PATTERN)):
    """Burn subtitles into video (standalone)."""
    project = _load_project(pid)
    _reject_busy_project(project)

    def _burn_task():
        try:
            with slot("burn", pid):
                _emit_progress(pid, "burn", 0, "正在烧录字幕到视频...")
                _check_cancel(pid)
                pdir = str(PROJECTS_DIR / pid)
                video_path = project["video_path"]

                if project.get("source_type") == "trailer":
                    translated = os.path.join(pdir, "translated.srt")
                    filtered = os.path.join(pdir, "filtered.srt")
                    if not (os.path.exists(translated) or os.path.exists(filtered)):
                        _mark_burn_unavailable(pid)
                        _emit_progress(pid, "burn", 0, "字幕烧录失败 (无字幕文件)")
                        return
                    tracks = _build_bilingual_tracks(pid)
                else:
                    srt_path = os.path.join(pdir, "bilingual.srt")
                    if not os.path.exists(srt_path):
                        srt_path = os.path.join(pdir, "translated.srt")
                    if not os.path.exists(srt_path):
                        _mark_burn_unavailable(pid)
                        _emit_progress(pid, "burn", 0, "字幕烧录失败 (无字幕文件)")
                        return
                    tracks = [_build_upload_legacy_track(srt_path)]

                base_name = os.path.splitext(os.path.basename(video_path))[0]
                output_video = os.path.join(pdir, f"{base_name}_subtitled.mp4")
                success = burn_subtitles(
                    video_path, tracks, output_video,
                    callback=lambda msg: _emit_progress(pid, "burn", 50, msg),
                )
                if success:
                    _out = output_video
                    mutate_project(pid, lambda p: p.update({"status": "completed",
                                                             "output_video": _out,
                                                             "error": None}),
                                   normalize=_apply_safe_defaults)
                    _emit_progress(pid, "burn", 100, "字幕烧录完成!")
                    from app.engines.audio import cleanup_intermediate
                    cleanup_intermediate(pdir)
                else:
                    # Burn failed but translation is still valid — mirror
                    # _run_burn_pipeline so the UI sees a real failure state
                    # instead of stale 'translated' with no error note.
                    mutate_project(pid, lambda p: p.update({"status": "translated",
                                                             "error": "字幕烧录失败，但翻译已完成"}),
                                   normalize=_apply_safe_defaults)
                    _emit_progress(pid, "burn", 0, "字幕烧录失败")
        except Exception as e:
            error_msg = _safe_error_message(e, 120)
            try:
                mutate_project(pid, lambda p: p.update({"status": "translated",
                                                         "error": f"字幕烧录异常: {error_msg}"}),
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
    t.start()
    return {"status": "started", "message": "Burning subtitles into video"}


@router.get("/{pid}/progress")
def get_progress(pid: str = PathParam(pattern=PID_PATTERN)):
    """Get current progress for a project."""
    return _scheduler_get_progress(pid) or {"progress": 0, "message": ""}
