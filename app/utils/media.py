"""
FFmpeg / FFprobe media utilities.
"""
import json
import logging
import math
import subprocess
import shutil
import os
import sys
import platform
import tempfile
from dataclasses import dataclass, replace
from typing import List, Dict, Optional, Union

log = logging.getLogger(__name__)


@dataclass
class SubtitleTrack:
    """One subtitle track to burn. Used by burn_subtitles for bilingual output."""
    path: str
    font_name: str = "Helvetica"
    font_size: int = 20
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    outline_width: float = 1.5
    margin_v: int = 30
    alignment: int = 2


def compute_font_sizes(video_height: int) -> tuple:
    """Return (zh_size, en_size) given video pixel height. Min floor 18 for zh."""
    try:
        height = float(video_height)
    except (OverflowError, TypeError, ValueError):
        height = 0
    if not math.isfinite(height) or height <= 0:
        height = 0
    height = min(height, 4320)
    zh = max(18, int(height * 0.055))
    en = max(int(18 * 0.7), int(zh * 0.7))
    return zh, en


def resolve_font(lang: str) -> str:
    """Pick a sane default font per language + platform."""
    sys_ = platform.system()
    if lang == "zh":
        return {"Darwin": "PingFang SC", "Windows": "Microsoft YaHei"}.get(sys_, "DejaVu Sans")
    return {"Darwin": "Helvetica", "Windows": "Arial"}.get(sys_, "DejaVu Sans")


def _escape_ffmpeg_filter_path(path: str) -> str:
    """Escape a path for use inside ffmpeg 'subtitles=' filter (single-quoted wrapper)."""
    p = path.replace("\\", "/")
    p = p.replace(":", r"\:")
    p = p.replace("'", r"\'")
    return p


def build_filter_chain(tracks: List[SubtitleTrack]) -> str:
    """Build the ffmpeg -vf argument for one or more SubtitleTrack inputs."""
    parts = []
    for t in tracks:
        style = (
            f"FontName={t.font_name},FontSize={t.font_size},"
            f"PrimaryColour={t.primary_color},OutlineColour={t.outline_color},"
            f"Outline={t.outline_width},Shadow=0,"
            f"Alignment={t.alignment},MarginV={t.margin_v}"
        )
        parts.append(f"subtitles='{_escape_ffmpeg_filter_path(t.path)}':force_style='{style}'")
    return ",".join(parts)


def _copy_tracks_to_filter_safe_paths(tracks: List[SubtitleTrack], temp_dir: str) -> List[SubtitleTrack]:
    """Copy subtitle files to simple names so ffmpeg filter parsing is predictable."""
    safe_tracks = []
    for index, track in enumerate(tracks):
        ext = os.path.splitext(track.path)[1].lower()
        if ext not in {".srt", ".ass", ".ssa", ".vtt"}:
            ext = ".srt"
        safe_path = os.path.join(temp_dir, f"track_{index}{ext}")
        shutil.copyfile(track.path, safe_path)
        safe_tracks.append(replace(track, path=safe_path))
    return safe_tracks


def get_ffmpeg_path() -> str:
    """Get ffmpeg binary path - checks bundled first, then system."""
    if getattr(sys, '_MEIPASS', None):
        for candidate in [
            os.path.join(sys._MEIPASS, 'bin', 'ffmpeg'),
            os.path.join(sys._MEIPASS, 'ffmpeg'),
        ]:
            if os.path.exists(candidate):
                return candidate
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in [
        os.path.join(app_dir, 'bin', 'ffmpeg'),
        os.path.join(app_dir, '..', 'bin', 'ffmpeg'),
        '/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg',
        '/usr/local/opt/ffmpeg-full/bin/ffmpeg',
    ]:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("ffmpeg") or "ffmpeg"


def get_ffprobe_path() -> str:
    """Get ffprobe binary path - checks bundled first, then system."""
    if getattr(sys, '_MEIPASS', None):
        for candidate in [
            os.path.join(sys._MEIPASS, 'bin', 'ffprobe'),
            os.path.join(sys._MEIPASS, 'ffprobe'),
        ]:
            if os.path.exists(candidate):
                return candidate
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in [
        os.path.join(app_dir, 'bin', 'ffprobe'),
        os.path.join(app_dir, '..', 'bin', 'ffprobe'),
        '/opt/homebrew/opt/ffmpeg-full/bin/ffprobe',
        '/usr/local/opt/ffmpeg-full/bin/ffprobe',
    ]:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("ffprobe") or "ffprobe"


def ffmpeg_supports_subtitle_burn(ffmpeg: Optional[str] = None) -> bool:
    """Return True when ffmpeg has the libass-backed subtitles video filter."""
    try:
        result = subprocess.run(
            [ffmpeg or get_ffmpeg_path(), "-hide_banner", "-filters"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    return any(" subtitles " in f" {line} " for line in result.stdout.splitlines())


def check_ffmpeg() -> bool:
    ffmpeg = get_ffmpeg_path()
    ffprobe = get_ffprobe_path()
    try:
        r1 = subprocess.run([ffmpeg, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        r2 = subprocess.run([ffprobe, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return (
            r1.returncode == 0
            and r2.returncode == 0
            and ffmpeg_supports_subtitle_burn(ffmpeg)
        )
    except Exception:
        return False


def get_media_info(path: str) -> Dict:
    """Get full media info via ffprobe."""
    cmd = [
        get_ffprobe_path(), "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8")
        return json.loads(out)
    except Exception:
        return {}


def get_tracks(path: str, kind: str = "s") -> List[Dict]:
    """
    Get tracks by type. kind: 's'=subtitle, 'a'=audio, 'v'=video.
    Returns list of {index, codec, lang, title}.
    """
    cmd = [
        get_ffprobe_path(), "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", kind, path,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8")
        data = json.loads(out)
        tracks = []
        if not isinstance(data, dict) or not isinstance(data.get("streams"), list):
            return []
        for s in data["streams"]:
            if not isinstance(s, dict):
                continue
            tags = s.get("tags") if isinstance(s.get("tags"), dict) else {}
            index = s.get("index", 0)
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                index = 0
            channels = s.get("channels", 0)
            if isinstance(channels, bool) or not isinstance(channels, int) or channels < 0:
                channels = 0
            codec = s.get("codec_name")
            if not isinstance(codec, str) or not codec:
                codec = "unknown"
            lang = tags.get("language")
            if not isinstance(lang, str) or not lang:
                lang = "und"
            title = tags.get("title")
            if not isinstance(title, str):
                title = ""
            sample_rate = s.get("sample_rate")
            if not isinstance(sample_rate, str):
                sample_rate = ""
            tracks.append({
                "index": index,
                "codec": codec,
                "lang": lang,
                "title": title,
                "channels": channels,
                "sample_rate": sample_rate,
            })
        return tracks
    except Exception:
        return []


def get_duration(path: str) -> float:
    """Get media duration in seconds."""
    info = get_media_info(path)
    fmt = info.get("format", {}) if isinstance(info, dict) else {}
    if not isinstance(fmt, dict):
        return 0
    try:
        duration = float(fmt.get("duration", 0))
    except (OverflowError, ValueError, TypeError):
        return 0
    if not math.isfinite(duration) or duration <= 0:
        return 0
    return duration


def extract_audio(video_path: str, output_path: str, track_index: int = 0,
                  sample_rate: int = 16000, mono: bool = True) -> bool:
    """Extract audio track to WAV.

    track_index selects the Nth AUDIO stream (0 = first audio). Uses ffmpeg's
    audio-stream-relative selector `0:a:N`, so it correctly skips the video
    stream regardless of stream order in the input.
    """
    cmd = [
        get_ffmpeg_path(), "-y", "-i", video_path,
        "-map", f"0:a:{track_index}",
        "-vn", "-ac", "1" if mono else "2",
        "-ar", str(sample_rate), "-f", "wav",
        output_path,
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as e:
        log.warning("ffmpeg extract_audio failed (rc=%s, track=%s): %s",
                    e.returncode, track_index, (e.stderr or "")[-500:])
        return False
    except (FileNotFoundError, OSError) as e:
        log.warning("ffmpeg extract_audio could not run: %s", e)
        return False
    if not (os.path.exists(output_path) and os.path.getsize(output_path) > 0):
        log.warning("ffmpeg extract_audio produced empty output: %s", output_path)
        return False
    return True


TEXT_SUBTITLE_CODECS = frozenset({
    "subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text",
})


def is_text_subtitle_codec(codec: str) -> bool:
    """True for text-based subtitle codecs that ffmpeg can transcode to SRT.
    PGS / DVD / DVB / HDMV are image bitmaps and can't be converted without OCR."""
    return isinstance(codec, str) and codec.lower() in TEXT_SUBTITLE_CODECS


def extract_subtitle(video_path: str, output_path: str, track_index: int) -> bool:
    """Extract the Nth subtitle stream as SRT.

    `track_index` is *subtitle-relative* (0 = first subtitle stream),
    matching the audio-relative convention used by extract_audio.
    Forces the SRT muxer + `-c:s srt` so ASS/SSA/MOV_TEXT/WebVTT inputs
    are transcoded to plain SRT. Image-based codecs (PGS/DVD/DVB) cannot
    be converted this way and will return False — caller should fall
    back to ASR.
    """
    cmd = [
        get_ffmpeg_path(), "-y", "-i", video_path,
        "-map", f"0:s:{track_index}",
        "-c:s", "srt",
        "-f", "srt",
        output_path,
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as e:
        # Image-based codecs (PGS/DVD/DVB) fail here — caller falls back to ASR.
        log.info("ffmpeg extract_subtitle failed (rc=%s, track=%s): %s",
                 e.returncode, track_index, (e.stderr or "")[-500:])
        return False
    except (FileNotFoundError, OSError) as e:
        log.warning("ffmpeg extract_subtitle could not run: %s", e)
        return False
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


def extract_frames(video_path: str, output_dir: str, start_sec: int = 60,
                   duration: int = 30, interval: int = 10) -> List[str]:
    """Extract frames from video for visual analysis."""
    os.makedirs(output_dir, exist_ok=True)
    pattern = os.path.join(output_dir, "frame_%03d.jpg")
    cmd = [
        get_ffmpeg_path(), "-y",
        "-ss", str(start_sec), "-t", str(duration),
        "-i", video_path,
        "-vf", f"fps=1/{interval}",
        "-q:v", "2", pattern,
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as e:
        log.warning("ffmpeg extract_frames failed (rc=%s): %s",
                    e.returncode, (e.stderr or "")[-500:])
        return []
    except (FileNotFoundError, OSError) as e:
        log.warning("ffmpeg extract_frames could not run: %s", e)
        return []
    try:
        frames = sorted([
            os.path.join(output_dir, f)
            for f in os.listdir(output_dir)
            if f.startswith("frame_") and f.endswith(".jpg")
        ])
        return frames[:3]
    except OSError:
        return []


def burn_subtitles(video_path: str,
                   tracks: Union[str, List[SubtitleTrack]],
                   output_path: str,
                   callback=None) -> bool:
    """
    Burn (hardcode) subtitles into video using ffmpeg.

    `tracks` accepts either:
      - a string SRT path (back-compat: wrapped as a single SubtitleTrack), or
      - a List[SubtitleTrack] for bilingual / multi-track burning.

    Returns True on success.
    """
    # Normalize tracks argument
    if isinstance(tracks, str):
        srt_path_for_check = tracks
        tracks = [SubtitleTrack(path=tracks)]
    elif isinstance(tracks, list) and tracks and all(isinstance(x, SubtitleTrack) for x in tracks):
        srt_path_for_check = tracks[0].path
    else:
        raise TypeError("burn_subtitles: 'tracks' must be a SRT path string or List[SubtitleTrack]")

    # Verify at least the first track file exists (preserves prior behavior)
    for t in tracks:
        if not os.path.exists(t.path):
            return False

    ffmpeg = get_ffmpeg_path()
    if not ffmpeg_supports_subtitle_burn(ffmpeg):
        message = "当前 FFmpeg 不支持 subtitles 滤镜，无法烧录字幕"
        log.error("%s: %s", message, ffmpeg)
        if callback:
            callback(message)
        return False

    if callback:
        callback("正在烧录字幕到视频...")

    try:
        with tempfile.TemporaryDirectory(prefix="aisubpro-subtitles-") as safe_subtitle_dir:
            safe_tracks = _copy_tracks_to_filter_safe_paths(tracks, safe_subtitle_dir)
            srt_path_for_check = safe_tracks[0].path
            vf = build_filter_chain(safe_tracks)

            cmd = [
                ffmpeg, "-y", "-i", video_path,
                "-vf", vf,
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "copy",
                "-movflags", "+faststart",
                output_path,
            ]

            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            _, stderr = process.communicate()
            if process.returncode != 0:
                log.warning("ffmpeg burn primary failed (rc=%s): %s",
                            process.returncode, (stderr or b"")[-500:].decode("utf-8", "replace"))
                # Fallback: single-track burn with the same filter-safe copy.
                cmd2 = [
                    ffmpeg, "-y", "-i", video_path,
                    "-vf", f"subtitles='{_escape_ffmpeg_filter_path(srt_path_for_check)}'",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-c:a", "copy",
                    output_path,
                ]
                try:
                    subprocess.run(cmd2, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, text=True, check=True)
                except subprocess.CalledProcessError as e:
                    log.error("ffmpeg burn fallback failed (rc=%s): %s",
                              e.returncode, (e.stderr or "")[-500:])
                    raise

        if callback:
            callback("视频输出完成")
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        if callback:
            callback(f"烧录失败: {e}")
        return False
