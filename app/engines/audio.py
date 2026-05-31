"""
Audio preprocessing engine: extraction, demucs vocal separation, normalization.
"""
import os
import subprocess
import shutil
import logging

from app.utils.media import extract_audio

log = logging.getLogger(__name__)


def preprocess_audio(video_path: str, output_dir: str, track_index: int = 0,
                     use_demucs: bool = True, callback=None) -> str:
    """
    Full audio preprocessing pipeline.
    Returns path to the best available audio file (vocals or raw).
    """
    os.makedirs(output_dir, exist_ok=True)
    raw_wav = os.path.join(output_dir, "raw_audio.wav")

    # Step 1: Extract audio
    if callback:
        callback("正在提取音频轨道...")
    if not extract_audio(video_path, raw_wav, track_index=track_index):
        raise RuntimeError(f"Failed to extract audio track {track_index}")
    if not os.path.exists(raw_wav) or os.path.getsize(raw_wav) < 1000:
        raise RuntimeError("Extracted audio file is empty or too small")
    log.info("Audio extracted: %s", raw_wav)

    # Step 2: Demucs vocal separation (optional)
    if use_demucs and shutil.which("demucs"):
        if callback:
            callback("正在 Demucs 人声分离 (可能需要几分钟)...")
        try:
            demucs_out = os.path.join(output_dir, "demucs_out")
            cmd = [
                "demucs", "-n", "htdemucs", "--two-stems=vocals",
                "-o", demucs_out, raw_wav,
            ]
            proc = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, timeout=600,  # 10 min timeout
            )
            if proc.returncode != 0:
                log.warning("Demucs exited %d, using raw audio: %s",
                            proc.returncode, (proc.stderr or "")[-500:])
            else:
                vocals_path = os.path.join(
                    demucs_out, "htdemucs", "raw_audio", "vocals.wav"
                )
                if os.path.exists(vocals_path) and os.path.getsize(vocals_path) > 1000:
                    log.info("Demucs vocals extracted: %s", vocals_path)
                    if callback:
                        callback("人声分离完成")
                    return vocals_path
                else:
                    log.warning("Demucs output not found, using raw audio")
        except subprocess.TimeoutExpired:
            log.warning("Demucs timed out, using raw audio")
        except (FileNotFoundError, OSError) as e:
            log.warning("Demucs could not run (%s), using raw audio", e)
    else:
        if use_demucs:
            log.info("Demucs not available, skipping vocal separation")

    if callback:
        callback("音频预处理完成")
    return raw_wav


def cleanup_intermediate(output_dir: str) -> None:
    """Best-effort cleanup of per-project ASR intermediates.

    Removes ``raw_audio.wav`` and the entire ``demucs_out/`` tree from
    ``output_dir``. Called after burn success — by then the user-visible
    artifact (the subtitled video) is on disk and the audio can go.

    Failures are logged and swallowed: a stuck file must NEVER degrade a
    'completed' project to 'error'.
    """
    raw = os.path.join(output_dir, "raw_audio.wav")
    demucs = os.path.join(output_dir, "demucs_out")
    if os.path.exists(raw):
        try:
            os.remove(raw)
            log.info("cleanup_intermediate: removed %s", raw)
        except OSError as e:
            log.warning("cleanup_intermediate: raw_audio.wav remove failed: %s", e)
    if os.path.isdir(demucs):
        try:
            shutil.rmtree(demucs, ignore_errors=False)
            log.info("cleanup_intermediate: removed %s", demucs)
        except OSError as e:
            log.warning("cleanup_intermediate: demucs_out rmtree failed: %s", e)
