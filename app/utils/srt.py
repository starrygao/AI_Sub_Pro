"""
SRT subtitle parsing and writing utilities.
"""
import re
from dataclasses import dataclass, field, asdict
from datetime import timedelta
from math import isfinite
from typing import List, Optional


@dataclass
class SubtitleBlock:
    index: int
    start: timedelta
    end: timedelta
    text: str
    translation: str = ""
    filtered: bool = False  # True if marked as non-translatable
    filter_reason: str = ""
    translation_error: str = ""  # B3: non-empty when translate_batch failed for this block

    def to_dict(self):
        return {
            "index": self.index,
            "start": fmt_time(self.start),
            "end": fmt_time(self.end),
            "start_ms": _timedelta_ms(self.start),
            "end_ms": _timedelta_ms(self.end),
            "text": self.text,
            "translation": self.translation,
            "filtered": self.filtered,
            "filter_reason": self.filter_reason,
            "translation_error": self.translation_error,
        }


_TIME_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})[,.](\d{3})$")
_VTT_TIME_RE = re.compile(r"^(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})$")
_ASS_TIME_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})\.(\d{1,3})$")
_MUSIC_SYMBOL_RE = re.compile(r"[♪♫♬🎵🎶]+")


def _timedelta_ms(td: timedelta) -> int:
    try:
        total = td.total_seconds()
    except (AttributeError, TypeError, OverflowError, ValueError):
        total = 0
    try:
        finite = isfinite(total)
    except (OverflowError, TypeError, ValueError):
        finite = False
    if not finite:
        total = 0
    return int(round(max(0, total) * 1000))


def parse_time_strict(s: str) -> Optional[timedelta]:
    """Parse a bounded SRT time string, returning None when invalid."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    m = _TIME_RE.match(s)
    if not m:
        return None
    try:
        h, mi, sec, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
    except ValueError:
        return None
    if mi >= 60 or sec >= 60:
        return None
    try:
        return timedelta(hours=h, minutes=mi, seconds=sec, milliseconds=ms)
    except OverflowError:
        return None


def parse_time(s: str) -> timedelta:
    """Parse SRT time string '00:01:23,456' to timedelta."""
    parsed = parse_time_strict(s)
    if parsed is None:
        return timedelta(0)
    return parsed


def fmt_time(td: timedelta) -> str:
    """Format timedelta to SRT time string '00:01:23,456'."""
    total_ms = _timedelta_ms(td)
    h, rem = divmod(total_ms, 3600 * 1000)
    mi, rem = divmod(rem, 60 * 1000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{mi:02d}:{s:02d},{ms:03d}"


def parse_vtt_time_strict(s: str) -> Optional[timedelta]:
    """Parse a WebVTT time string, accepting HH:MM:SS.mmm or MM:SS.mmm."""
    if not isinstance(s, str):
        return None
    text = s.strip()
    m = _VTT_TIME_RE.match(text)
    if not m:
        return None
    try:
        h = int(m[1]) if m[1] is not None else 0
        mi = int(m[2])
        sec = int(m[3])
        ms = int(m[4])
    except ValueError:
        return None
    if sec >= 60:
        return None
    if m[1] is not None and mi >= 60:
        return None
    try:
        return timedelta(hours=h, minutes=mi, seconds=sec, milliseconds=ms)
    except OverflowError:
        return None


def fmt_vtt_time(td: timedelta) -> str:
    """Format timedelta to WebVTT time string '00:01:23.456'."""
    total_ms = _timedelta_ms(td)
    h, rem = divmod(total_ms, 3600 * 1000)
    mi, rem = divmod(rem, 60 * 1000)
    sec, ms = divmod(rem, 1000)
    return f"{h:02d}:{mi:02d}:{sec:02d}.{ms:03d}"


def parse_ass_time_strict(s: str) -> Optional[timedelta]:
    """Parse an ASS/SSA time string such as '0:01:23.45'."""
    if not isinstance(s, str):
        return None
    text = s.strip()
    m = _ASS_TIME_RE.match(text)
    if not m:
        return None
    try:
        h, mi, sec = int(m[1]), int(m[2]), int(m[3])
        ms = int((m[4] + "000")[:3])
    except ValueError:
        return None
    if mi >= 60 or sec >= 60:
        return None
    try:
        return timedelta(hours=h, minutes=mi, seconds=sec, milliseconds=ms)
    except OverflowError:
        return None


def parse_srt(content: str) -> List[SubtitleBlock]:
    """Parse SRT content string into SubtitleBlock list."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="ignore")
    if not isinstance(content, str):
        return []
    blocks = []
    raw_blocks = re.split(r"\n\s*\n", content.strip())
    for raw in raw_blocks:
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        # Find the timecode line
        time_idx = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                time_idx = i
                break
        if time_idx < 0:
            continue
        # Parse index
        try:
            idx = int(lines[0]) if time_idx > 0 else len(blocks) + 1
        except ValueError:
            idx = len(blocks) + 1
        # Parse times
        tm = re.match(
            r"(\d+:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{3})",
            lines[time_idx],
        )
        if not tm:
            continue
        start = parse_time_strict(tm.group(1))
        end = parse_time_strict(tm.group(2))
        if start is None or end is None:
            continue
        if end <= start:
            continue
        text = " ".join(lines[time_idx + 1 :])
        if text:
            blocks.append(SubtitleBlock(index=idx, start=start, end=end, text=text))
    return blocks


def parse_vtt(content: str) -> List[SubtitleBlock]:
    """Parse WebVTT content string into SubtitleBlock list."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="ignore")
    if not isinstance(content, str):
        return []
    text = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").strip()
    if not text:
        return []
    blocks: List[SubtitleBlock] = []
    raw_blocks = re.split(r"\n\s*\n", text)
    for raw in raw_blocks:
        lines = [line.strip() for line in raw.split("\n") if line.strip()]
        if not lines:
            continue
        first = lines[0].upper()
        if first.startswith("WEBVTT") and not any("-->" in line for line in lines):
            continue
        if _is_vtt_control_block(lines[0]):
            continue
        time_idx = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                time_idx = i
                break
        if time_idx < 0:
            continue
        start_text, end_part = lines[time_idx].split("-->", 1)
        end_text = end_part.strip().split()[0] if end_part.strip() else ""
        start = parse_vtt_time_strict(start_text.strip())
        end = parse_vtt_time_strict(end_text)
        if start is None or end is None or end <= start:
            continue
        cue_text = " ".join(lines[time_idx + 1 :]).strip()
        if cue_text:
            blocks.append(
                SubtitleBlock(index=len(blocks) + 1, start=start, end=end, text=cue_text)
            )
    return blocks


def _is_vtt_control_block(first_line: str) -> bool:
    marker = first_line.strip().upper()
    return marker == "STYLE" or marker == "REGION" or marker == "NOTE" or marker.startswith("NOTE ")


def parse_ass(content: str) -> List[SubtitleBlock]:
    """Parse ASS/SSA dialogue events into SubtitleBlock list.

    Styling is intentionally flattened because the app stores an editable text
    timeline before translation.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="ignore")
    if not isinstance(content, str):
        return []
    text = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if not text.strip():
        return []

    blocks: List[SubtitleBlock] = []
    in_events = False
    fields = _default_ass_fields()
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_events = line.strip("[]").strip().lower() == "events"
            continue
        if not in_events:
            continue
        kind, _, payload = line.partition(":")
        kind = kind.strip().lower()
        payload = payload.strip()
        if kind == "format":
            parsed_fields = [item.strip().lower() for item in payload.split(",") if item.strip()]
            if {"start", "end", "text"}.issubset(parsed_fields):
                fields = parsed_fields
            continue
        if kind != "dialogue":
            continue
        parts = [part.strip() for part in payload.split(",", max(0, len(fields) - 1))]
        if len(parts) < len(fields):
            continue
        row = {field: parts[i] for i, field in enumerate(fields)}
        start = parse_ass_time_strict(row.get("start", ""))
        end = parse_ass_time_strict(row.get("end", ""))
        if start is None or end is None or end <= start:
            continue
        cue_text = _flatten_ass_text(row.get("text", ""))
        if cue_text:
            blocks.append(
                SubtitleBlock(index=len(blocks) + 1, start=start, end=end, text=cue_text)
            )
    return blocks


def _default_ass_fields() -> list[str]:
    return [
        "layer",
        "start",
        "end",
        "style",
        "name",
        "marginl",
        "marginr",
        "marginv",
        "effect",
        "text",
    ]


def _flatten_ass_text(value: str) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\{[^{}]*\}", "", value)
    text = re.sub(r"\\[Nn]", " ", text)
    text = text.replace(r"\h", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def srt_to_vtt(content: str) -> str:
    """Convert SRT text to a WebVTT document."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="ignore")
    if not isinstance(content, str):
        return "WEBVTT\n\n"
    text = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    out_lines = ["WEBVTT", ""]
    if not text:
        return "WEBVTT\n\n"
    has_cue = False
    raw_blocks = re.split(r"\n\s*\n", text)
    for raw in raw_blocks:
        lines = [line.rstrip() for line in raw.split("\n")]
        time_idx = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                time_idx = i
                break
        if time_idx < 0:
            continue
        tm = re.match(
            r"\s*(\d+:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{3})",
            lines[time_idx],
        )
        if not tm:
            continue
        start = parse_time_strict(tm.group(1))
        end = parse_time_strict(tm.group(2))
        if start is None or end is None or end <= start:
            continue
        cue_lines = lines[time_idx + 1 :]
        while cue_lines and not cue_lines[0].strip():
            cue_lines.pop(0)
        while cue_lines and not cue_lines[-1].strip():
            cue_lines.pop()
        if not any(line.strip() for line in cue_lines):
            continue
        out_lines.append(f"{fmt_vtt_time(start)} --> {fmt_vtt_time(end)}")
        out_lines.extend(cue_lines)
        out_lines.append("")
        has_cue = True
    if not has_cue:
        return "WEBVTT\n\n"
    return "\n".join(out_lines).rstrip() + "\n"


def parse_srt_file(path: str) -> List[SubtitleBlock]:
    """Parse SRT file into SubtitleBlock list."""
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        return parse_srt(f.read())


def write_srt(blocks: List[SubtitleBlock], path: str, use_translation: bool = False):
    """Write SubtitleBlock list to SRT file."""
    with open(path, "w", encoding="utf-8") as f:
        seq = 1
        for b in blocks:
            if getattr(b, "filtered", False):
                continue
            text = _subtitle_text(getattr(b, "translation", "") if use_translation else getattr(b, "text", ""))
            if not text:
                continue
            start = getattr(b, "start", timedelta(0))
            end = getattr(b, "end", timedelta(0))
            if not _has_positive_duration(start, end):
                continue
            f.write(f"{seq}\n")
            f.write(f"{fmt_time(start)} --> {fmt_time(end)}\n")
            f.write(f"{text}\n\n")
            seq += 1


def write_mono_srt(blocks, out_path: str, use_translation: bool = True) -> int:
    """Write a single-language SRT. Returns count of entries written.

    - Always skips filtered blocks.
    - If use_translation=True: writes b.translation (skips if empty).
    - If use_translation=False: writes b.text (source language).
    """
    from pathlib import Path
    out_lines = []
    seq = 1
    for b in blocks:
        if getattr(b, "filtered", False):
            continue
        text = _subtitle_text(getattr(b, "translation", "") if use_translation else getattr(b, "text", ""))
        if not text:
            continue
        start = getattr(b, "start", timedelta(0))
        end = getattr(b, "end", timedelta(0))
        if not _has_positive_duration(start, end):
            continue
        out_lines.append(f"{seq}\n{fmt_time(start)} --> {fmt_time(end)}\n{text}\n")
        seq += 1
    Path(out_path).write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    return seq - 1


def write_bilingual_srt(blocks: List[SubtitleBlock], path: str):
    """Write bilingual SRT (original on top, translation below)."""
    with open(path, "w", encoding="utf-8") as f:
        idx = 1
        for b in blocks:
            if getattr(b, "filtered", False):
                continue
            text = _subtitle_text(getattr(b, "text", ""))
            translation = _subtitle_text(getattr(b, "translation", ""))
            if not text and not translation:
                continue
            start = getattr(b, "start", timedelta(0))
            end = getattr(b, "end", timedelta(0))
            if not _has_positive_duration(start, end):
                continue
            f.write(f"{idx}\n")
            f.write(f"{fmt_time(start)} --> {fmt_time(end)}\n")
            if translation:
                f.write(f"{translation}\n")
            if text:
                f.write(f"{text}\n")
            f.write("\n")
            idx += 1


def apply_offset(blocks: List[SubtitleBlock], offset_ms: int) -> List[SubtitleBlock]:
    """Apply time offset to all blocks."""
    try:
        off = timedelta(milliseconds=int(offset_ms))
    except (TypeError, ValueError, OverflowError):
        off = timedelta(0)
    shifted = []
    for b in blocks:
        try:
            b.start = max(timedelta(0), b.start + off)
            b.end = max(timedelta(0), b.end + off)
        except (AttributeError, TypeError, OverflowError):
            continue
        if b.end > b.start:
            shifted.append(b)
    return shifted


def _subtitle_text(value) -> str:
    if not isinstance(value, str):
        return ""
    text = _MUSIC_SYMBOL_RE.sub("", value)
    lines = []
    for line in text.splitlines():
        cleaned = re.sub(r"\s{2,}", " ", line).strip()
        cleaned = re.sub(r"^(?:[-–—]\s*){2,}", "", cleaned).strip()
        cleaned = re.sub(r"(?:\s*[-–—])+$", "", cleaned).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines).strip()


def _has_positive_duration(start, end) -> bool:
    try:
        return end > start
    except (TypeError, OverflowError):
        return False
