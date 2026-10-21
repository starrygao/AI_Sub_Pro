"""ASR engine with local Whisper backends and packaged model resolution."""
import os
import sys
import logging
import time
import math
import re
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
ASR_BACKENDS = ("auto", "mlx_whisper", "faster_whisper", "openai_whisper")

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
    backend: str = "auto",
    language_callback: Optional[Callable] = None,
) -> List[SubtitleBlock]:
    """
    Transcribe audio to subtitle blocks.
    With backend="auto", tries backends in order:
    mlx_whisper -> faster-whisper -> openai-whisper. Explicit backends only
    try that backend so users are not silently moved to another ASR engine.

    Note: `vad_filter` is honored by faster-whisper. mlx_whisper and
    openai-whisper do not support it, so a warning is logged when the app
    falls back to those backends while VAD is enabled.

    `language_callback(language, probability)` reports only automatic native
    detection with nonempty speech. MLX/OpenAI reuse the model for a bounded
    speech-window probe because their transcription results omit confidence;
    the probability must support the transcription's detected language.

    If all backends fail and `error_log_dir` is provided, a per-project
    `asr_error.log` is written into that directory. When omitted, no file
    is written (avoids a previous bug where concurrent failing projects
    stomped a shared PROJECTS_DIR/asr_error.log).
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    lang = None if language == "auto" else language
    selected_backend = backend.strip() if isinstance(backend, str) else "auto"
    if selected_backend not in ASR_BACKENDS:
        log.warning("Unknown ASR backend %r; falling back to auto", backend)
        selected_backend = "auto"
    backend_order = (
        ("mlx_whisper", "faster_whisper", "openai_whisper")
        if selected_backend == "auto"
        else (selected_backend,)
    )

    errors = []
    language_options = {"language_callback": language_callback} if language_callback else {}

    for candidate in backend_order:
        try:
            if candidate == "mlx_whisper":
                return _transcribe_mlx(audio_path, lang, model_size, beam_size, callback, vad_filter=vad_filter, **language_options)
            if candidate == "faster_whisper":
                return _transcribe_faster_whisper(audio_path, lang, model_size, vad_filter, beam_size, callback, **language_options)
            if candidate == "openai_whisper":
                return _transcribe_openai(audio_path, lang, model_size, beam_size, callback, vad_filter=vad_filter, **language_options)
        except ImportError as e:
            label = "openai whisper" if candidate == "openai_whisper" else candidate
            msg = f"{label} ImportError: {e}"
            log.warning(msg)
            errors.append(msg)
        except Exception as e:
            import traceback
            label = "openai whisper" if candidate == "openai_whisper" else candidate
            msg = f"{label} failed: {e}\n{traceback.format_exc()}"
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


def _language_probe_audio(audio_path, segments):
    """Bound the extra native language probe to 30 seconds of recognized speech."""
    import subprocess
    import numpy as np
    from app.utils.media import get_ffmpeg_path
    speech = [s for s in segments if s.get("text", "").strip()]
    segment = max(speech, key=lambda s: float(s.get("end", 0)) - float(s.get("start", 0)))
    offset = max(0, float(segment.get("start", 0)))
    result = subprocess.run(
        [get_ffmpeg_path(), "-nostdin", "-v", "error", "-ss", str(offset),
         "-i", str(audio_path), "-t", "30", "-vn", "-ac", "1", "-ar", "16000",
         "-f", "f32le", "pipe:1"],
        capture_output=True, check=False, timeout=45,
    )
    if result.returncode or not result.stdout:
        raise RuntimeError("音频语言核验片段无法读取")
    return np.frombuffer(result.stdout, dtype=np.float32)


def _transcribe_mlx(
    audio_path: str, language: Optional[str], model_size: str,
    beam_size: int, callback, vad_filter: bool = False, language_callback=None
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
    if language_callback and language is None and any(s.get("text", "").strip() for s in segments):
        # MLX's transcription result discards language probabilities. Reuse its
        # cached model for a bounded native probe; never invent confidence.
        import mlx.core as mx
        from mlx_whisper.transcribe import ModelHolder
        from mlx_whisper.audio import log_mel_spectrogram, pad_or_trim, N_FRAMES, N_SAMPLES
        model = ModelHolder.get_model(path_or_repo, mx.float16)
        probe = mx.array(_language_probe_audio(audio_path, segments))
        mel = log_mel_spectrogram(probe, n_mels=model.dims.n_mels, padding=N_SAMPLES)
        _, probabilities = model.detect_language(pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16))
        detected = result.get("language")
        language_callback(detected, probabilities.get(detected))
    log.info("mlx_whisper: %d segments in %.1fs", len(segments), elapsed)

    if callback:
        callback(f"识别完成: {len(segments)} 条字幕, 耗时 {elapsed:.1f}s")

    return _segments_to_blocks(segments)


def _transcribe_openai(
    audio_path: str, language: Optional[str], model_size: str,
    beam_size: int, callback, vad_filter: bool = False, language_callback=None
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
    if language_callback and language is None and any(s.get("text", "").strip() for s in segments):
        probe = whisper.pad_or_trim(_language_probe_audio(audio_path, segments))
        mel = whisper.log_mel_spectrogram(probe, n_mels=model.dims.n_mels).to(model.device)
        _, probabilities = model.detect_language(mel)
        detected = result.get("language")
        language_callback(detected, probabilities.get(detected))
    log.info("openai whisper: %d segments in %.1fs", len(segments), elapsed)

    if callback:
        callback(f"识别完成: {len(segments)} 条字幕, 耗时 {elapsed:.1f}s")

    return _segments_to_blocks(segments)


def _transcribe_faster_whisper(
    audio_path: str, language: Optional[str], model_size: str,
    vad_filter: bool, beam_size: int, callback, language_callback=None
) -> List[SubtitleBlock]:
    """Transcribe using faster-whisper / CTranslate2."""
    from faster_whisper import WhisperModel

    if callback:
        callback(f"正在加载 faster-whisper {model_size} 模型...")

    start = time.time()
    thread_options = {}
    if os.environ.get("AISUBPRO_ASR_CPU_THREADS"):
        thread_options["cpu_threads"] = max(1, int(os.environ["AISUBPRO_ASR_CPU_THREADS"]))
    model = WhisperModel(model_size, device="auto", compute_type="auto", **thread_options)

    if callback:
        callback("开始语音识别 (faster-whisper)...")

    segments_iter, _info = model.transcribe(
        audio_path,
        language=language,
        vad_filter=vad_filter,
        beam_size=beam_size,
        word_timestamps=True,
    )
    segments = [
        {"start": seg.start, "end": seg.end, "text": seg.text,
         "words": [{"start": w.start, "end": w.end, "word": w.word}
                   for w in (getattr(seg, 'words', None) or [])]}
        for seg in segments_iter
    ]
    if language_callback and language is None and any(s["text"].strip() for s in segments):
        language_callback(getattr(_info, "language", None), getattr(_info, "language_probability", None))
    elapsed = time.time() - start
    log.info("faster-whisper: %d segments in %.1fs", len(segments), elapsed)

    if callback:
        callback(f"识别完成: {len(segments)} 条字幕, 耗时 {elapsed:.1f}s")

    return _segments_to_blocks(segments)


def _aligned_word_segments(segment: dict) -> list[dict]:
    """Use complete word alignment to avoid displaying captions over silence.

    Incomplete, out-of-bounds or non-monotonic alignment is not permission to
    truncate a transcript. Keep the original segment for QA in that case.
    """
    words = segment.get('words')
    if not isinstance(words, list) or not words:
        return [segment]
    try:
        start, end = float(segment['start']), float(segment['end'])
        aligned = []
        previous_end = start
        for word in words:
            a, b = float(word['start']), float(word['end'])
            text = word['word']
            if (not isinstance(text, str) or not text.strip()
                    or not math.isfinite(a) or not math.isfinite(b)
                    or not start <= a < b <= end or a < previous_end):
                return [segment]
            aligned.append((a, b, text))
            previous_end = b
        compact = lambda text: re.sub(r'\s+', '', text)
        if compact(''.join(w[2] for w in aligned)) != compact(segment['text']):
            return [segment]
    except (KeyError, TypeError, ValueError, OverflowError):
        return [segment]
    groups = []
    for a, b, text in aligned:
        if (not groups or a - groups[-1]['end'] > 1
                or b - groups[-1]['start'] > 7):
            groups.append({'start': a, 'end': b, 'text': text})
        else:
            groups[-1]['end'] = b
            groups[-1]['text'] += text
    return groups


def _segments_to_blocks(segments: list) -> List[SubtitleBlock]:
    """Convert whisper segments to SubtitleBlock list."""
    blocks = []
    aligned_segments = [part for segment in segments if isinstance(segment, dict)
                        for part in _aligned_word_segments(segment)]
    for seg in aligned_segments:
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
