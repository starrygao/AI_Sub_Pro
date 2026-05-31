"""ASR engine with local Whisper backends and packaged model resolution."""
import os
import sys
import logging
import time
import math
from pathlib import Path
from typing import List, Optional, Callable
from datetime import timedelta

from app.utils.srt import SubtitleBlock
from app.utils.text import clean_sdh

log = logging.getLogger(__name__)

# mlx_whisper and openai-whisper do NOT expose a `vad_filter` kwarg; only
# faster_whisper does. We warn once if VAD is enabled and the selected backend
# cannot honor it, so the setting does not silently have no effect.
_BACKENDS_SUPPORTING_VAD = ("faster_whisper",)
_vad_warning_emitted = False
_mlx_beam_warning_emitted = False

# openai-whisper's default beam_size is 5 when no `beam_size` is passed to
# `model.transcribe()` (it falls back to greedy temperature sampling); we
# also treat 5 as the "default" here so users who never touched this config
# are not spammed with an info log about it being ignored by mlx_whisper.
_DEFAULT_BEAM_SIZE = 5

MLX_MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}

MODEL_DOWNLOAD_HINTS = {
    "tiny": "~150MB",
    "base": "~300MB",
    "small": "~900MB",
    "medium": "~1.5GB",
    "large-v3": "~3GB",
    "large-v3-turbo": "~1.6GB",
}


def _hf_cache_dir(repo_id: str) -> Path:
    return Path.home() / ".cache" / "huggingface" / "hub" / f"models--{repo_id.replace('/', '--')}"


def _candidate_bundle_roots() -> list[Path]:
    roots: list[Path] = []
    raw_env = os.environ.get("AISUBPRO_ASR_MODEL_DIR", "").strip()
    if raw_env:
        roots.append(Path(raw_env).expanduser())
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        roots.append(Path(meipass) / "models" / "asr" / "mlx")
    roots.append(Path(__file__).resolve().parents[2] / "models" / "asr" / "mlx")
    return roots


def _repo_slug(repo_id: str) -> str:
    return repo_id.replace("/", "--")


def _mlx_repo_for_model(model_size: str) -> str:
    model = model_size.strip() if isinstance(model_size, str) else "large-v3-turbo"
    if model in MLX_MODEL_REPOS:
        return MLX_MODEL_REPOS[model]
    if "/" in model:
        return model
    return f"mlx-community/whisper-{model}-mlx"


def resolve_mlx_model_source(model_size: str) -> dict:
    """Resolve the MLX Whisper model source.

    Bundled model directories are checked first so a packaged .app can run ASR
    without downloading from Hugging Face. Supported layouts:

    - models/asr/mlx/<model_size>
    - models/asr/mlx/<repo-id-with---as-separator>
    """
    model = model_size.strip() if isinstance(model_size, str) and model_size.strip() else "large-v3-turbo"
    path_candidate = Path(model).expanduser()
    if path_candidate.exists():
        return {"path_or_repo": str(path_candidate), "source": "path", "available": True, "path": str(path_candidate)}

    repo_id = _mlx_repo_for_model(model)
    for root in _candidate_bundle_roots():
        for candidate in (root / model, root / _repo_slug(repo_id)):
            if candidate.exists():
                return {
                    "path_or_repo": str(candidate),
                    "repo_id": repo_id,
                    "source": "bundled",
                    "available": True,
                    "path": str(candidate),
                }

    cache_dir = _hf_cache_dir(repo_id)
    return {
        "path_or_repo": repo_id,
        "repo_id": repo_id,
        "source": "cache" if cache_dir.exists() else "download",
        "available": cache_dir.exists(),
        "path": str(cache_dir),
    }


def _warn_vad_unsupported_once(backend_name: str) -> None:
    """Log an INFO-level warning exactly once per process that VAD is not
    honored by the active whisper backend."""
    global _vad_warning_emitted
    if _vad_warning_emitted:
        return
    _vad_warning_emitted = True
    log.warning(
        "vad_filter=True is configured but the active ASR backend (%s) does "
        "not support VAD natively; this option is being ignored. Install "
        "faster-whisper and switch backend for VAD support.",
        backend_name,
    )


def _warn_mlx_beam_size_once(beam_size: int) -> None:
    """Log an INFO-level message exactly once per process that the
    configured `beam_size` cannot be passed through to mlx_whisper."""
    global _mlx_beam_warning_emitted
    if _mlx_beam_warning_emitted:
        return
    _mlx_beam_warning_emitted = True
    log.info(
        "mlx_whisper does not accept beam_size; configured beam_size=%d is "
        "being ignored (mlx_whisper uses temperature-based decoding). "
        "Install faster-whisper if you need beam search.",
        beam_size,
    )


def transcribe(
    audio_path: str,
    language: str = "auto",
    model_size: str = "large-v3-turbo",
    vad_filter: bool = True,
    beam_size: int = 5,
    callback: Optional[Callable] = None,
    error_log_dir: Optional[str] = None,
) -> List[SubtitleBlock]:
    """
    Transcribe audio to subtitle blocks.
    Tries backends in order: mlx_whisper -> faster-whisper -> openai-whisper.

    Note: `vad_filter` is honored by faster-whisper. mlx_whisper and
    openai-whisper do not support it, so a warning is logged when the app
    falls back to those backends while VAD is enabled.

    If all backends fail and `error_log_dir` is provided, a per-project
    `asr_error.log` is written into that directory. When omitted, no file
    is written (avoids a previous bug where concurrent failing projects
    stomped a shared PROJECTS_DIR/asr_error.log).
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    lang = None if language == "auto" else language

    errors = []

    # Try mlx_whisper first (fastest on Apple Silicon)
    try:
        return _transcribe_mlx(audio_path, lang, model_size, beam_size, callback, vad_filter=vad_filter)
    except ImportError as e:
        msg = f"mlx_whisper ImportError: {e}"
        log.warning(msg)
        errors.append(msg)
    except Exception as e:
        import traceback
        msg = f"mlx_whisper failed: {e}\n{traceback.format_exc()}"
        log.warning(msg)
        errors.append(msg)

    # Try faster-whisper. This is the cross-platform backend that supports
    # VAD and beam search, and is already bundled by the Windows build script.
    try:
        return _transcribe_faster_whisper(audio_path, lang, model_size, vad_filter, beam_size, callback)
    except ImportError as e:
        msg = f"faster_whisper ImportError: {e}"
        log.warning(msg)
        errors.append(msg)
    except Exception as e:
        import traceback
        msg = f"faster_whisper failed: {e}\n{traceback.format_exc()}"
        log.warning(msg)
        errors.append(msg)

    # Try openai whisper
    try:
        return _transcribe_openai(audio_path, lang, model_size, beam_size, callback, vad_filter=vad_filter)
    except ImportError as e:
        msg = f"openai whisper ImportError: {e}"
        log.warning(msg)
        errors.append(msg)
    except Exception as e:
        import traceback
        msg = f"openai whisper failed: {e}\n{traceback.format_exc()}"
        log.warning(msg)
        errors.append(msg)

    # Write detailed error log
    error_detail = "\n---\n".join(errors)
    log.error("All ASR backends failed:\n%s", error_detail)
    if error_log_dir:
        try:
            log_path = os.path.join(error_log_dir, "asr_error.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(error_detail)
            log.error("ASR error log written to: %s", log_path)
        except Exception:
            pass

    raise RuntimeError(f"No working ASR backend found.\n{error_detail}")


def _transcribe_mlx(
    audio_path: str, language: Optional[str], model_size: str,
    beam_size: int, callback, vad_filter: bool = False
) -> List[SubtitleBlock]:
    """Transcribe using mlx_whisper (Apple Silicon optimized)."""
    import mlx_whisper

    if vad_filter:
        _warn_vad_unsupported_once("mlx_whisper")

    model_source = resolve_mlx_model_source(model_size)
    path_or_repo = model_source["path_or_repo"]

    if model_source["source"] == "bundled":
        if callback:
            callback(f"正在加载内置 Whisper {model_size} 模型...")
        log.info("Using bundled MLX Whisper model: %s", model_source["path"])
    elif model_source["source"] == "path":
        if callback:
            callback(f"正在加载本地 Whisper 模型: {model_source['path']}")
        log.info("Using local MLX Whisper model path: %s", model_source["path"])
    elif model_source["source"] == "download":
        size_hint = MODEL_DOWNLOAD_HINTS.get(model_size, "模型文件")
        if callback:
            callback(f"首次使用，正在下载 Whisper {model_size} 模型 ({size_hint})，请耐心等待...")
        log.info("MLX Whisper model not cached, will download: %s", path_or_repo)
    else:
        if callback:
            callback(f"正在加载 Whisper {model_size} 模型...")

    if callback:
        callback("开始语音识别 (mlx-whisper)...")

    opts = {
        "path_or_hf_repo": path_or_repo,
        "verbose": False,
    }
    if language:
        opts["language"] = language

    # mlx_whisper does NOT implement beam search. Its DecodingTask raises
    # NotImplementedError("Beam search decoder is not yet implemented")
    # whenever options.beam_size is not None — even beam_size=1 trips it.
    # Greedy decoding is selected by *omitting* beam_size entirely. So we
    # never put it in opts; if the user configured a non-default value,
    # warn once so they know it had no effect on this backend.
    if beam_size != _DEFAULT_BEAM_SIZE and beam_size != 1:
        _warn_mlx_beam_size_once(beam_size)

    start = time.time()
    result = mlx_whisper.transcribe(audio_path, **opts)
    elapsed = time.time() - start

    segments = result.get("segments", [])
    log.info("mlx_whisper: %d segments in %.1fs", len(segments), elapsed)

    if callback:
        callback(f"识别完成: {len(segments)} 条字幕, 耗时 {elapsed:.1f}s")

    return _segments_to_blocks(segments)


def _transcribe_openai(
    audio_path: str, language: Optional[str], model_size: str,
    beam_size: int, callback, vad_filter: bool = False
) -> List[SubtitleBlock]:
    """Transcribe using openai whisper library."""
    import whisper

    if vad_filter:
        _warn_vad_unsupported_once("openai-whisper")

    if callback:
        callback(f"正在加载 whisper {model_size} 模型...")

    model = whisper.load_model(model_size)

    if callback:
        callback("开始语音识别 (openai-whisper)...")

    opts = {
        "fp16": False,
        "beam_size": beam_size,
        "verbose": False,
    }
    if language:
        opts["language"] = language

    start = time.time()
    result = model.transcribe(audio_path, **opts)
    elapsed = time.time() - start

    segments = result.get("segments", [])
    log.info("openai whisper: %d segments in %.1fs", len(segments), elapsed)

    if callback:
        callback(f"识别完成: {len(segments)} 条字幕, 耗时 {elapsed:.1f}s")

    return _segments_to_blocks(segments)


def _transcribe_faster_whisper(
    audio_path: str, language: Optional[str], model_size: str,
    vad_filter: bool, beam_size: int, callback
) -> List[SubtitleBlock]:
    """Transcribe using faster-whisper / CTranslate2."""
    from faster_whisper import WhisperModel

    if callback:
        callback(f"正在加载 faster-whisper {model_size} 模型...")

    start = time.time()
    model = WhisperModel(model_size, device="auto", compute_type="auto")

    if callback:
        callback("开始语音识别 (faster-whisper)...")

    segments_iter, _info = model.transcribe(
        audio_path,
        language=language,
        vad_filter=vad_filter,
        beam_size=beam_size,
    )
    segments = [
        {"start": seg.start, "end": seg.end, "text": seg.text}
        for seg in segments_iter
    ]
    elapsed = time.time() - start
    log.info("faster-whisper: %d segments in %.1fs", len(segments), elapsed)

    if callback:
        callback(f"识别完成: {len(segments)} 条字幕, 耗时 {elapsed:.1f}s")

    return _segments_to_blocks(segments)


def _segments_to_blocks(segments: list) -> List[SubtitleBlock]:
    """Convert whisper segments to SubtitleBlock list."""
    blocks = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        raw_text = seg.get("text", "")
        if not isinstance(raw_text, str):
            continue
        text = raw_text.strip()
        text = clean_sdh(text)
        if not text:
            continue
        try:
            start_seconds = float(seg.get("start", 0))
            end_seconds = float(seg.get("end", 0))
        except (OverflowError, TypeError, ValueError):
            continue
        if not (math.isfinite(start_seconds) and math.isfinite(end_seconds)):
            continue
        if start_seconds < 0:
            continue
        if end_seconds <= start_seconds:
            continue
        try:
            start = timedelta(seconds=start_seconds)
            end = timedelta(seconds=end_seconds)
        except OverflowError:
            continue
        blocks.append(SubtitleBlock(
            index=len(blocks) + 1,
            start=start,
            end=end,
            text=text,
        ))
    return blocks
