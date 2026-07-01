"""Subtitle style profiles for deterministic QA and prompt guidance."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SubtitleStyleProfile:
    id: str
    label: str
    max_line_chars: int
    max_lines: int
    max_chars_per_second: float
    rules: tuple[str, ...]

    def to_trace(self) -> dict:
        return {
            "id": self.id,
            "scope": "subtitle_style",
            "max_line_chars": self.max_line_chars,
            "max_lines": self.max_lines,
            "max_chars_per_second": self.max_chars_per_second,
        }


_ZH_CN_GENERAL = SubtitleStyleProfile(
    id="zh_cn_general",
    label="Simplified Chinese subtitle style",
    max_line_chars=30,
    max_lines=2,
    max_chars_per_second=9.0,
    rules=(
        "Prefer one subtitle line when the translation fits within about 30 Chinese characters.",
        "Use two subtitle lines only for genuinely long or hard-to-read cues.",
        "Keep reading speed at or below 9.0 characters per second.",
        "When two lines are necessary, break at punctuation or phrase boundaries.",
        "Compress repeated short exclamations unless repetition carries meaning.",
        "Use Chinese punctuation in Chinese subtitles.",
    ),
)

_ZH_CN_CHILDREN = SubtitleStyleProfile(
    id="zh_cn_children",
    label="Simplified Chinese children subtitle style",
    max_line_chars=24,
    max_lines=2,
    max_chars_per_second=7.0,
    rules=(
        "Prefer one subtitle line when the translation fits within about 24 Chinese characters.",
        "Use two subtitle lines only for genuinely long or hard-to-read cues.",
        "Keep reading speed at or below 7.0 characters per second for children/family content.",
        "Prefer simple vocabulary; when two lines are necessary, break at semantic boundaries.",
    ),
)


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _metadata_blob(meta_info: dict | None) -> str:
    if not isinstance(meta_info, dict):
        return ""
    values: list[str] = []
    for key in (
        "name",
        "show_title",
        "title",
        "original_title",
        "overview",
        "plot",
        "tmdb_type",
        "media_type",
        "source_type",
        "category",
    ):
        value = meta_info.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    for key in ("genres", "genre", "tags", "categories"):
        value = meta_info.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str) and item.strip())
    return " ".join(values).casefold()


def _metadata_has(meta_info: dict | None, *needles: str) -> bool:
    blob = _metadata_blob(meta_info)
    tokens = {token for token in re.split(r"[^a-z0-9+-]+", blob) if token}
    for needle in needles:
        folded = needle.casefold()
        if " " in folded or "-" in folded:
            if folded in blob:
                return True
        elif folded in tokens or folded in blob:
            return True
    return False


def _is_simplified_chinese(target_language: str) -> bool:
    text = _clean_text(target_language).lower()
    return text in {
        "简体中文",
        "中文",
        "zh",
        "zh-cn",
        "zh-hans",
        "zh-hans-cn",
        "simplified chinese",
        "chs",
        "zho",
        "cmn",
    }


def infer_subtitle_style_profile(
    target_language: str,
    meta_info: dict | None = None,
) -> SubtitleStyleProfile | None:
    if not _is_simplified_chinese(target_language):
        return None
    if _metadata_has(meta_info, "kids", "children", "child", "family", "preschool", "儿童", "少儿"):
        return _ZH_CN_CHILDREN
    return _ZH_CN_GENERAL


def build_subtitle_style_prompt_snippet(
    target_language: str,
    meta_info: dict | None = None,
) -> tuple[str, list[dict]]:
    profile = infer_subtitle_style_profile(target_language, meta_info)
    if profile is None:
        return "", []
    lines = [
        "Subtitle style constraints (QA-enforced when timing is available; lower priority than source meaning and project KB):",
    ]
    lines.extend(f"  - {rule}" for rule in profile.rules)
    return "\n".join(lines), [profile.to_trace()]
