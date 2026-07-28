"""Shared structural subtitle-line classification helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_DASH_CHARS = r"\-‐‑‒–—―"
_DIALOGUE_MARKER_RE = re.compile(
    rf"^\s*[{_DASH_CHARS}](?![{_DASH_CHARS}])\s*\S"
)
_SPEAKER_LABEL_RE = re.compile(r"^\s*[^:：\r\n]{1,48}[:：]\s*\S")


@dataclass(frozen=True)
class SpeakerLineStructure:
    kinds: tuple[str, ...]

    @property
    def line_count(self) -> int:
        return len(self.kinds)

    def expected_description(self) -> str:
        unique_kinds = set(self.kinds)
        if len(unique_kinds) == 1:
            return f"{self.line_count} {self.kinds[0]} lines"
        return f"{self.line_count} speaker lines"


def _clean_lines(value: str | Iterable[str]) -> list[str]:
    raw_lines = value.splitlines() if isinstance(value, str) else value
    return [
        line.strip()
        for line in (raw_lines or [])
        if isinstance(line, str) and line.strip()
    ]


def classify_speaker_lines(
    value: str | Iterable[str],
) -> SpeakerLineStructure | None:
    """Classify cues where every one of at least two lines is a speaker line."""
    lines = _clean_lines(value)
    if len(lines) < 2:
        return None
    kinds = []
    for line in lines:
        if _DIALOGUE_MARKER_RE.match(line):
            kinds.append("dialogue-marker")
        elif _SPEAKER_LABEL_RE.match(line):
            kinds.append("speaker-label")
        else:
            return None
    return SpeakerLineStructure(tuple(kinds))


def preserves_speaker_line_structure(
    translation: str,
    source_structure: SpeakerLineStructure,
) -> bool:
    target_structure = classify_speaker_lines(translation)
    return (
        target_structure is not None
        and target_structure.kinds == source_structure.kinds
    )
