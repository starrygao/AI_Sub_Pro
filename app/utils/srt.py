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
            "start_ms": int(self.start.total_seconds() * 1000),
            "end_ms": int(self.end.total_seconds() * 1000),
            "text": self.text,
            "translation": self.translation,
            "filtered": self.filtered,
            "filter_reason": self.filter_reason,
            "translation_error": self.translation_error,
        }


_TIME_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})[,.](\d{3})$")


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
    total = max(0, total)
    h = int(total // 3600)
    mi = int((total % 3600) // 60)
    s = int(total % 60)
    ms = int((total * 1000) % 1000)
    return f"{h:02d}:{mi:02d}:{s:02d},{ms:03d}"


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
    return value.strip()


def _has_positive_duration(start, end) -> bool:
    try:
        return end > start
    except (TypeError, OverflowError):
        return False
