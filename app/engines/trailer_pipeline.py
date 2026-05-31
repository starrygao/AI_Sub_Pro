"""Trailer-project orchestrator: download -> ASR -> translate -> burn.

On per-stage failure, records error on project.json and stops. Does NOT re-raise
(caller is a background thread spawned by the /api/trailer/start endpoint).
"""
import logging
import re
from pathlib import Path

from app.api.projects import _load_project
from app.config import PROJECTS_DIR
from app.utils.project_store import mutate_project
from app.engines.scheduler import slot, update_progress, reset_cancel, is_cancelled
from app.engines.trailer_downloader import download_trailer
from app.utils.errors import redact_error_message

log = logging.getLogger(__name__)


def _adopt_youtube_subtitles(pdir: Path) -> bool:
    """If yt-dlp downloaded YouTube native subtitles alongside the video, copy them
    into `filtered.srt` (and `raw.srt`) so the translate stage uses them and ASR is skipped.
    Returns True if subtitles were adopted.
    """
    # yt-dlp names subs as `<stem>.<lang>.<ext>` e.g. original.en.srt / original.en-US.vtt
    candidates = sorted(pdir.glob("original.en*.srt")) + sorted(pdir.glob("original.en*.vtt"))
    if not candidates:
        return False
    target = pdir / "filtered.srt"
    for src in candidates:
        log.info("adopting YouTube subtitles for ASR bypass: %s", src.name)

        try:
            if src.suffix == ".srt":
                target.write_bytes(src.read_bytes())
            else:
                # VTT -> SRT: lightweight in-place conversion (we don't shell out to ffmpeg here
                # because YouTube VTT is well-formed and a regex pass handles it cleanly).
                target.write_text(_vtt_to_srt(src.read_text(encoding="utf-8")), encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log.warning("could not read YouTube subtitle candidate (%s): %s", src.name, e)
            target.unlink(missing_ok=True)
            continue

        try:
            from app.utils.srt import parse_srt_file
            blocks = parse_srt_file(str(target))
        except Exception as e:
            log.warning("adopted YouTube subtitle is not parseable (%s): %s", src.name, e)
            target.unlink(missing_ok=True)
            continue
        if not blocks:
            log.warning("adopted YouTube subtitle is empty: %s", src.name)
            target.unlink(missing_ok=True)
            continue

        # Mirror to raw.srt too (some pipeline paths read it)
        (pdir / "raw.srt").write_bytes(target.read_bytes())
        return True
    return False


def _vtt_to_srt(vtt_text: str) -> str:
    """Convert WebVTT to SRT. Strips header, converts `00:00:00.000` -> `00:00:00,000`,
    renumbers blocks, and drops VTT-only cue settings."""
    lines = vtt_text.splitlines()
    blocks = []
    current = []
    for ln in lines:
        if ln.strip() == "" and current:
            blocks.append(current)
            current = []
        elif ln.strip() and not ln.startswith("WEBVTT") and not ln.startswith("Kind:") and not ln.startswith("Language:") and not ln.startswith("NOTE"):
            current.append(ln)
    if current:
        blocks.append(current)

    out = []
    seq = 1
    ts_re = re.compile(
        r"(?:(\d{2}):)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*"
        r"(?:(\d{2}):)?(\d{2}):(\d{2})\.(\d{3})"
    )

    def fmt(h, m, s, ms):
        return f"{h or '00'}:{m}:{s},{ms}"

    for blk in blocks:
        # find timestamp line, drop any cue id line above it
        ts_idx = None
        for i, ln in enumerate(blk):
            m = ts_re.search(ln)
            if m:
                ts_idx = i
                blk[i] = (
                    f"{fmt(m.group(1), m.group(2), m.group(3), m.group(4))} --> "
                    f"{fmt(m.group(5), m.group(6), m.group(7), m.group(8))}"
                )
                break
        if ts_idx is None:
            continue
        text_lines = blk[ts_idx + 1:]
        # strip VTT inline tags like <c> </c> and <00:00:01.234>
        text_lines = [re.sub(r"<[^>]+>", "", t) for t in text_lines]
        text_joined = "\n".join(t for t in text_lines if t.strip())
        if not text_joined.strip():
            continue
        out.append(f"{seq}\n{blk[ts_idx]}\n{text_joined}\n")
        seq += 1
    return "\n".join(out)


def _save_partial(pid: str, **fields) -> None:
    """Atomically merge `fields` into the project under the per-pid lock."""
    from app.api.projects import _apply_safe_defaults
    mutate_project(pid, lambda p: p.update(fields), normalize=_apply_safe_defaults)


def _check_cancelled(pid: str) -> None:
    if is_cancelled(pid):
        raise RuntimeError(f"cancelled by user pid={pid}")


def _run_asr_for_project(pid: str) -> None:
    """Invoke existing ASR pipeline on a project. Deferred import to avoid circular."""
    from app.api.translate import _run_asr_pipeline
    proj = _load_project(pid)
    audio_track = proj.get("selected_audio_track", 0) or 0
    language = proj.get("asr_language", "auto") or "auto"
    _run_asr_pipeline(pid, audio_track, language)


def _run_translate_for_project(pid: str) -> None:
    from app.api.translate import _run_translate_pipeline
    proj = _load_project(pid)
    target_lang = proj.get("target_language", "简体中文") or "简体中文"
    _run_translate_pipeline(pid, target_lang)


def _run_burn_for_project(pid: str) -> None:
    """Burn stage. Prefers the dedicated helper, falls back to _burn_task if exposed."""
    from app.api import translate as api_translate
    if hasattr(api_translate, "_run_burn_pipeline"):
        api_translate._run_burn_pipeline(pid)
    elif hasattr(api_translate, "_burn_task"):
        api_translate._burn_task(pid)
    else:
        raise RuntimeError("No burn entry point found in app.api.translate")


def _coerce_max_height(value) -> int:
    if isinstance(value, bool):
        return 1080
    try:
        height = int(value)
    except (TypeError, ValueError, OverflowError):
        return 1080
    if height < 0 or height > 4320:
        return 1080
    return height


def _download_stage(pid: str) -> None:
    proj = _load_project(pid)
    url = proj.get("youtube_url") or ""
    pdir = PROJECTS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)
    out_path = str(pdir / "original.mp4")

    # Resolve max_height from config (defaults to 1080)
    from app.config import Config
    max_height = _coerce_max_height(Config.get("trailer", "max_video_height"))

    def on_progress(pct, msg):
        update_progress(pid, "download", pct, msg)

    _save_partial(pid, pipeline_stage="download", status="processing")
    update_progress(pid, "download", 0, "starting download")

    with slot("download", pid):
        try:
            download_trailer(url, out_path, progress_callback=on_progress, max_height=max_height)
        except Exception as e:
            raise RuntimeError(f"download failed: {redact_error_message(e, 120)}")

    _check_cancelled(pid)
    _save_partial(pid, video_path=out_path, pipeline_stage="asr")
    update_progress(pid, "download", 100, "download complete")

    # If YouTube provided native subtitles, adopt them so we can skip the ASR stage.
    if _adopt_youtube_subtitles(pdir):
        _save_partial(pid, asr_skipped=True)
        update_progress(pid, "asr", 100, "使用 YouTube 原生字幕,跳过 ASR")
        log.info("ASR will be skipped pid=%s (adopted YouTube subtitles)", pid)


def _check_stage_status(pid: str, stage_name: str) -> None:
    """Raise if the project's status is 'error' -- stops pipeline from advancing.

    Delegates like `_run_asr_pipeline` / `_run_translate_pipeline` catch internal
    failures and record `status=error` on project.json without re-raising. Without
    this check, the orchestrator would blindly advance to the next stage on missing
    inputs. This helper turns that recorded error back into an exception so the
    outer try/except can halt the pipeline uniformly.
    """
    proj = _load_project(pid)
    if proj.get("status") == "error":
        raise RuntimeError(f"{stage_name} stage failed: {proj.get('error') or 'unknown'}")


def run_trailer_pipeline(pid: str) -> None:
    """Run the full 4-stage pipeline for a trailer project. Exceptions captured."""
    if is_cancelled(pid):
        _save_partial(pid, status="error", error="Cancelled by user", pipeline_stage=None)
        update_progress(pid, "download", 0, "已取消")
        return
    reset_cancel(pid)
    try:
        _check_cancelled(pid)
        _download_stage(pid)
        _check_stage_status(pid, "download")
        _check_cancelled(pid)

        # ASR can be skipped if download stage already adopted YouTube native subtitles.
        proj = _load_project(pid)
        if not proj.get("asr_skipped"):
            _save_partial(pid, pipeline_stage="asr")
            _check_cancelled(pid)
            _run_asr_for_project(pid)
            _check_stage_status(pid, "asr")
        else:
            log.info("skipping ASR stage pid=%s (YouTube subtitles adopted)", pid)

        _save_partial(pid, pipeline_stage="translate")
        _check_cancelled(pid)
        _run_translate_for_project(pid)
        _check_stage_status(pid, "translate")

        _save_partial(pid, pipeline_stage="burn")
        _check_cancelled(pid)
        _run_burn_for_project(pid)
        _check_stage_status(pid, "burn")

        _save_partial(pid, status="completed", pipeline_stage=None)
        update_progress(pid, "burn", 100, "trailer pipeline complete")
    except Exception as e:
        log.exception("trailer pipeline failed pid=%s", pid)
        try:
            # If status is ALREADY "error" (set by a delegate), don't overwrite the original message
            proj = _load_project(pid)
            if proj.get("status") != "error":
                _save_partial(
                    pid,
                    status="error",
                    error=f"{type(e).__name__}: {redact_error_message(e, 200)}",
                    pipeline_stage=None,
                )
            else:
                _save_partial(pid, pipeline_stage=None)
        except Exception:
            log.exception("failed to persist error state pid=%s", pid)
