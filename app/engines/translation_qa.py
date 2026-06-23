"""Deterministic subtitle translation QA and repair prompt helpers."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from app.evaluation.metrics import proper_name_consistency_score
from app.engines.content_profiles import infer_content_profiles
from app.engines.domain_terms import (
    find_domain_terms,
    find_scientific_terms,
    match_is_overridden_by_project_kb,
)
from app.engines.kb_models import ProjectKb
from app.engines.project_metadata import manual_term_pairs
from app.engines.subtitle_style_profiles import (
    SubtitleStyleProfile,
    infer_subtitle_style_profile,
)
from app.utils.project_store import atomic_write_json


@dataclass
class QualityIssue:
    type: str
    severity: str
    block_id: Optional[int]
    message: str
    source_text: str = ""
    translation: str = ""
    expected: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TranslationQaReport:
    status: str
    issues: list[QualityIssue] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    repaired_blocks: list[dict] = field(default_factory=list)
    unresolved_blocks: list[int] = field(default_factory=list)
    trace: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
            "summary": dict(self.summary),
            "repaired_blocks": list(self.repaired_blocks),
            "unresolved_blocks": list(self.unresolved_blocks),
            "trace": dict(self.trace),
        }

    def to_markdown(self) -> str:
        lines = [
            "# Translation QA Report",
            "",
            f"- Status: {self.status}",
            f"- Issues: {len(self.issues)}",
        ]
        by_type = self.summary.get("by_type", {})
        if isinstance(by_type, dict) and by_type:
            lines.append("")
            lines.append("## Issue Counts")
            for key in sorted(by_type):
                lines.append(f"- {key}: {by_type[key]}")
        if self.issues:
            lines.append("")
            lines.append("## Issues")
            for issue in self.issues:
                block = f"#{issue.block_id}" if issue.block_id is not None else "global"
                lines.append(f"- [{issue.severity}] {issue.type} {block}: {issue.message}")
        return "\n".join(lines) + "\n"


def _clean_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


_ENGLISH_RE = re.compile(r"[A-Za-z]{3,}")
_SOUND_RE = re.compile(r"^\s*[-–—]?\s*\[[^\]]+\]\s*$")
_SOUND_SEQUENCE_RE = re.compile(r"^\s*(?:\[[^\]]+\]\s*)+$")
_BRACKETED_TRANSLATION_SEGMENT_RE = re.compile(r"[\[【（(]([^\]】）)\r\n]{1,80})[\]】）)]")
_ASS_OVERRIDE_RE = re.compile(r"\{\\[^}]+\}")
_MUSIC_MARK_RE = re.compile(r"[♪♫♬🎵🎶]+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CJK_TEXT_RE = re.compile(r"[\u3400-\u9fff]+")
_REPEATED_CJK_RE = re.compile(r"([\u4e00-\u9fff])(?:[，,、\s]*\1){2,}")
_ASCII_PUNCT_RE = re.compile(r"[?!,;:]")
_SCIENTIFIC_TARGET_SUFFIXES = (
    "兽",
    "獸",
    "龙",
    "龍",
    "鳄",
    "鱷",
    "蕨",
    "类",
    "類",
    "属",
    "屬",
    "种",
    "種",
    "纪",
    "紀",
    "鱼",
    "魚",
    "鸟",
    "鳥",
    "虫",
    "蟲",
    "亚",
    "亞",
)
_SCIENTIFIC_CONTEXT_ANCHOR_CHARS = set("一只个個头頭群在从從到有没沒无無不是和与與及它他她我你")
_SCIENTIFIC_CHUNK_PREFIX_NOISE = set("一只个個头頭群")
_CORE_TERM_RULES = (
    {
        "source": "D-Day",
        "pattern": re.compile(r"\bD[- ]?Day\b", re.IGNORECASE),
        "target": "D日",
    },
)
_TECH_ALLOWED_ENGLISH_TOKENS = {
    "api",
    "cli",
    "cpu",
    "css",
    "csv",
    "dns",
    "docker",
    "firebase",
    "git",
    "github",
    "gitlab",
    "gpu",
    "graphql",
    "html",
    "http",
    "https",
    "ios",
    "ip",
    "java",
    "javascript",
    "json",
    "jsonl",
    "jwt",
    "kubernetes",
    "linux",
    "localhost",
    "macos",
    "mysql",
    "node",
    "npm",
    "oauth",
    "pdf",
    "pip",
    "postgres",
    "protobuf",
    "python",
    "react",
    "redis",
    "sdk",
    "sql",
    "sqlite",
    "ssh",
    "ssl",
    "swift",
    "tcp",
    "tls",
    "toml",
    "typescript",
    "udp",
    "uri",
    "url",
    "uuid",
    "websocket",
    "windows",
    "xcode",
    "xml",
    "yaml",
}
_AUTO_REPAIR_REPORT_ONLY_ISSUE_TYPES = {
    "proper_name_inconsistent",
    "scientific_term_inconsistent",
    "sound_description_translated",
}
_SOUND_LABEL_KEYWORDS = (
    "音乐",
    "乐曲",
    "配乐",
    "摇滚乐",
    "歌声",
    "唱歌",
    "哼唱",
    "音效",
    "音响",
    "声音",
    "声",
    "人声",
    "铃声",
    "电话响",
    "手机响",
    "振动",
    "震动",
    "铃响",
    "铃",
    "响起",
    "响",
    "鸣笛",
    "警笛",
    "广播",
    "电台",
    "对话听不清",
    "对白听不清",
    "听不清",
    "说阿拉伯语",
    "说法语",
    "说俄语",
    "说波斯语",
    "说外语",
    "用阿拉伯语",
    "用法语",
    "用俄语",
    "用波斯语",
    "阿语",
    "波斯语",
    "外语",
    "交谈",
    "说话声",
    "嘈杂",
    "喧闹",
    "喧嚷",
    "人群",
    "含混",
    "嘘声",
    "掌声",
    "欢呼",
    "尖叫",
    "喊叫",
    "喊声",
    "大喊",
    "喊",
    "叫声",
    "叫",
    "尖啸",
    "啸",
    "咆哮",
    "吼",
    "哭",
    "哭泣",
    "啜泣",
    "抽泣",
    "啜泣声",
    "呜咽",
    "婴儿",
    "笑声",
    "大笑",
    "轻笑",
    "嗤笑",
    "笑",
    "叹气",
    "喘息",
    "吸气",
    "呼吸",
    "咳嗽",
    "呻吟",
    "低语",
    "窃窃私语",
    "脚步",
    "脚步声",
    "敲门",
    "敲击",
    "敲",
    "门开",
    "开门",
    "关门",
    "门关",
    "门铃",
    "电梯",
    "引擎",
    "轮胎",
    "枪声",
    "枪响",
    "爆炸",
    "撞击",
    "重击",
    "敲打",
    "咔",
    "咚",
    "砰",
    "哐",
    "哔",
    "沙沙",
    "噼啪",
    "咯吱",
    "咔嗒",
    "玻璃碎",
    "按键",
    "键盘",
    "纸张",
    "监护仪",
    "警报",
    "噪音",
    "抽屉",
    "水声",
    "流水",
    "滴水",
    "打字",
    "键入",
    "文件",
    "纸页",
    "车辆",
    "车门",
    "飞机",
    "船笛",
    "号角",
    "动物叫",
    "鸟鸣",
    "虫鸣",
)
_SOUND_LABEL_EN_RE = re.compile(
    r"\b("
    r"music|song|singing|humming|ring(?:s|ing)?|vibrat(?:e|es|ing|ed)?|"
    r"phone|bell|chime|alarm|siren|radio|broadcast|voice|voices|crowd|"
    r"in (?:arabic|farsi|persian|french|russian|spanish|german|italian|chinese|mandarin|cantonese)|"
    r"sound(?:s)?|chatter|conversation|inaudible|indistinct(?:ly)?|applause|cheer(?:s|ing)?|"
    r"speak(?:s|ing)?|talk(?:s|ing)?|plead(?:s|ing)?|"
    r"scoff(?:s|ing)?|clear(?:s|ing)? throat|throat|sniffle(?:s|ing)?|"
    r"inhale(?:s|d|ing)?|exhale(?:s|d|ing)?|gasp(?:s|ing)?|"
    r"yell(?:s|ing)?|whimper(?:s|ing)?|grunt(?:s|ing)?|growl(?:s|ing)?|"
    r"roar(?:s|ing)?|honk(?:s|ing)?|clink(?:s|ing)?|squawk(?:s|ing)?|"
    r"squeak(?:s|ing)?|shriek(?:s|ing)?|call(?:s|ing)?|cries|"
    r"insect(?:s)?|cricket(?:s)?|trill(?:s|ing)?|chirp(?:s|ing)?|"
    r"chitter(?:s|ing)?|coo(?:s|ing)?|murmur(?:s|ing)?|"
    r"bullet(?:s)?|ricochet(?:s|ing)?|"
    r"thunder|rumbl(?:e|es|ing)?|engine|rev(?:s|ving)?|"
    r"tire(?:s)?|screech(?:es|ing)?|key(?:s)?|jingle(?:s|ing)?|"
    r"line click(?:s|ing)?|click(?:s|ing)?|lock(?:s)?|hang(?:s|ing)? up|"
    r"thump(?:s|ing)?|thudd(?:ing)?|squelch(?:es|ing)?|clang(?:s|ing)?|"
    r"clunk(?:s|ing)?|bang(?:s|ing)?|snap(?:s|ping)?|"
    r"paper(?:s)?|crinkle(?:s|ing)?|shuffle(?:s|ing)?|"
    r"scratch(?:es|ing)?|scribbl(?:e|es|ing)?|typ(?:e|es|ing)?|"
    r"clack(?:s|ing)?|keyboard|computer|laptop|"
    r"rewind(?:s|ing)?|fast-forward(?:s|ing)?|rain|patter(?:s|ing)?|birdsong|"
    r"tick(?:s|ing)?|gunfire|wail(?:s|ing)?|snort(?:s|ing)?|"
    r"rattl(?:e|es|ing)?|wind|howl(?:s|ing)?|theme|playing|"
    r"mutter(?:s|ing)?|incantation|snarl(?:s|ing)?|crackl(?:e|es|ing)?|"
    r"creak(?:s|ing)?|hum(?:s|ming)?|musical sting|static|"
    r"stone(?:s)?|branch(?:es)?|bone(?:s)?|crunch(?:es|ing)?|"
    r"tape|rip(?:s|ping)?|water|wave(?:s)?|lap(?:s|ping)?|run(?:s|ning)?|drip(?:s|ping)?|"
    r"bubbl(?:e|es|ing)?|detector|drawer|open(?:s|ing)?|close(?:s|ing)?|"
    r"door(?:s)?|gate|elevator|ding(?:s|ing)?|vehicle(?:s)?|car|truck|"
    r"approach(?:es|ing)?|plane|descend(?:s|ing)?|jet|whirr(?:s|ing)?|"
    r"bag|zip(?:s|ping)?|unzip(?:s|ping)?|buzz(?:es|ing)?|dial(?:s|ing)?|"
    r"cuff(?:s)?|strain(?:s|ing)?|retch(?:es|ing)?|shudder(?:s|ing)?|"
    r"wheez(?:e|es|ing)?|crow|caw(?:s|ing)?|sheep|bleat(?:s|ing)?|"
    r"chicken(?:s)?|cluck(?:s|ing)?|swing|hiss(?:es|ing)?|"
    r"whistle(?:s|ing)?|horn|chok(?:e|es|ing)?|gulp(?:s|ing)?|"
    r"convers(?:e|es|ing)|clamor(?:s|ing)?|exclaim(?:s|ing)?|"
    r"shatter(?:s|ing)?|flutter(?:s|ing)?|kiss(?:es|ing)?|"
    r"laugh(?:s|ing)?|laughter|chuckl(?:e|es|ing)|giggl(?:e|es|ing)|cry(?:ing)?|sob(?:s|bing)?|"
    r"scream(?:s|ing)?|shout(?:s|ing)?|whisper(?:s|ing)?|sigh(?:s|ing)?|"
    r"breath(?:e|es|ing)?|pant(?:s|ing)?|cough(?:s|ing)?|moan(?:s|ing)?|"
    r"groan(?:s|ing)?|door|knock(?:s|ing)?|footstep(?:s)?|gunshot(?:s)?|"
    r"explosion(?:s)?|crash(?:es|ing)?|thud(?:s)?|clatter(?:s|ing)?|"
    r"beep(?:s|ing)?|buzz(?:es|ing)?|rustl(?:e|es|ing)?"
    r")\b",
    re.IGNORECASE,
)


def _is_report_only_issue(issue: QualityIssue) -> bool:
    return (
        getattr(issue, "severity", "") == "warning"
        and getattr(issue, "type", "") in _AUTO_REPAIR_REPORT_ONLY_ISSUE_TYPES
    )


def _is_blocking_issue(issue: QualityIssue) -> bool:
    return not _is_report_only_issue(issue)


def _is_chinese_target(target_language: str) -> bool:
    text = _clean_text(target_language).lower()
    return text in {
        "简体中文",
        "繁体中文",
        "繁體中文",
        "中文",
        "zh",
        "zh-cn",
        "zh-hans",
        "zh-hans-cn",
        "zh-tw",
        "zh-hant",
        "zh-hant-tw",
        "simplified chinese",
        "traditional chinese",
        "chs",
        "cht",
        "zho",
        "cmn",
    }


def _has_technical_tutorial_context(meta_info: Optional[dict]) -> bool:
    return any(
        profile.id in {"technical_tutorial", "academic_lecture"}
        for profile in infer_content_profiles(meta_info if isinstance(meta_info, dict) else {})
    )


def _is_allowed_technical_token(token: str) -> bool:
    normalized = _clean_text(token).casefold()
    if normalized in _TECH_ALLOWED_ENGLISH_TOKENS:
        return True
    return bool(token.isupper() and 3 <= len(token) <= 10)


def _is_allowed_acronym_token(token: str) -> bool:
    return bool(token.isupper() and 3 <= len(token) <= 10)


def _english_residue_match(translation: str, *, allow_technical_terms: bool = False):
    for match in _ENGLISH_RE.finditer(translation or ""):
        if _is_allowed_acronym_token(match.group(0)):
            continue
        if allow_technical_terms and _is_allowed_technical_token(match.group(0)):
            continue
        return match
    return None


def _sound_description_probe_text(value: str) -> str:
    text = _HTML_TAG_RE.sub("", value or "")
    text = _ASS_OVERRIDE_RE.sub("", text)
    text = _MUSIC_MARK_RE.sub("", text)
    text = re.sub(r"(^|\s)[-–—]\s*(?=\[)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:[-–—]\s*)+", "", text).strip()
    text = re.sub(r"(?:\s*[-–—])+$", "", text).strip()
    return text


def _is_sound_description(source: str) -> bool:
    probe = _sound_description_probe_text(source)
    if not probe:
        return bool(_MUSIC_MARK_RE.search(source or ""))
    if _MUSIC_MARK_RE.search(source or ""):
        return True

    segments = list(_BRACKETED_TRANSLATION_SEGMENT_RE.finditer(probe))
    if segments:
        remainder = _BRACKETED_TRANSLATION_SEGMENT_RE.sub("", probe)
        return (
            _is_translation_separator_only(remainder)
            and all(_is_sound_translation_label(match.group(1)) for match in segments)
        )

    return _is_unbracketed_sound_description_label(probe)


def _is_sound_translation_label(label: str) -> bool:
    text = _HTML_TAG_RE.sub("", label or "")
    text = _ASS_OVERRIDE_RE.sub("", text)
    text = _MUSIC_MARK_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    if not text:
        return False
    if any(keyword in text for keyword in _SOUND_LABEL_KEYWORDS):
        return True
    return bool(_SOUND_LABEL_EN_RE.search(text))


def _is_unbracketed_sound_description_label(value: str) -> bool:
    text = _clean_text(value)
    if not _is_sound_translation_label(text):
        return False
    if _CJK_TEXT_RE.search(text):
        compact = _compact_subtitle_text(text)
        return bool(compact and len(compact) <= 12)
    words = re.findall(r"[A-Za-z]+", text)
    if len(words) <= 3:
        return True
    letters = re.sub(r"[^A-Za-z]", "", text)
    return bool(letters and letters == letters.upper())


def _is_translation_separator_only(value: str) -> bool:
    text = _ASS_OVERRIDE_RE.sub("", value or "")
    text = re.sub(r"[\s\-–—、，,。.!！?？:：;；/\\|~·]+", "", text)
    return not text


def clean_sound_description_translation_text(value: str) -> str:
    """Remove translated bracketed sound-description labels while preserving dialogue."""
    if not isinstance(value, str) or not value:
        return ""

    cleaned_lines: list[str] = []
    for line in value.splitlines():
        changed = False

        def replace_sound_label(match) -> str:
            nonlocal changed
            label = match.group(1)
            if _is_sound_translation_label(label):
                changed = True
                return ""
            return match.group(0)

        cleaned = _BRACKETED_TRANSLATION_SEGMENT_RE.sub(replace_sound_label, line)
        if changed:
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
            cleaned = re.sub(r"^(?:[-–—]\s*)+", "", cleaned).strip()
            cleaned = re.sub(r"(?:\s*[-–—])+$", "", cleaned).strip()
            cleaned = re.sub(r"^[、，,。.!！?？:：;；]+\s*", "", cleaned).strip()
            if _is_translation_separator_only(cleaned):
                cleaned = ""
        else:
            cleaned = line.strip()
        if cleaned:
            cleaned_lines.append(cleaned)
    return "\n".join(cleaned_lines).strip()


def normalize_sound_description_translations(blocks: Iterable) -> list[dict]:
    """Clean non-dialogue sound-description translations before QA/export."""
    applied: list[dict] = []
    for block in blocks or []:
        if getattr(block, "filtered", False):
            continue
        source = _clean_text(getattr(block, "text", ""))
        translation = _clean_text(getattr(block, "translation", ""))
        if not source or not translation:
            continue
        if _is_sound_description(source):
            block.translation = ""
            applied.append({
                "id": getattr(block, "index", None),
                "source": source,
                "from": translation,
                "to": "",
                "reason": "sound_description_blank",
            })
            continue
        cleaned_translation = clean_sound_description_translation_text(translation)
        if cleaned_translation != translation:
            block.translation = cleaned_translation
            applied.append({
                "id": getattr(block, "index", None),
                "source": source,
                "from": translation,
                "to": cleaned_translation,
                "reason": "translation_sound_description_clean",
            })
    return applied


def _kb_terms(project_kb: Optional[ProjectKb]) -> list[tuple[str, str]]:
    if project_kb is None:
        return []
    pairs = []
    for attr in ("characters", "places", "brands", "slang"):
        for entry in getattr(project_kb, attr, []) or []:
            source = _clean_text(getattr(entry, "source", ""))
            target = _clean_text(getattr(entry, "target", ""))
            if source and target:
                pairs.append((source, target))
    return pairs


def _issue_counts(issues: list[QualityIssue]) -> dict:
    counts = {}
    for issue in issues:
        counts[issue.type] = counts.get(issue.type, 0) + 1
    return counts


_FAR_CATEGORY_BY_TYPE = {
    "missing_translation": "functional",
    "duplicate_id": "functional",
    "kb_term_missing": "functional",
    "manual_term_missing": "functional",
    "canonical_term_missing": "functional",
    "core_term_inconsistent": "functional",
    "scientific_term_inconsistent": "functional",
    "proper_name_inconsistent": "functional",
    "english_residue": "acceptability",
    "sound_description_translated": "acceptability",
    "punctuation_style": "acceptability",
    "line_too_long": "readability",
    "reading_speed_too_fast": "readability",
    "too_many_lines": "readability",
    "weak_semantic_line_break": "readability",
    "repetition_not_compressed": "readability",
}


def _far_counts(issues: list[QualityIssue]) -> dict:
    counts = {"functional": 0, "acceptability": 0, "readability": 0}
    for issue in issues:
        category = _FAR_CATEGORY_BY_TYPE.get(issue.type)
        if category:
            counts[category] += 1
    return counts


def _core_term_issues(source: str, translation: str, block_id: int | None) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for rule in _CORE_TERM_RULES:
        pattern = rule["pattern"]
        target = rule["target"]
        if not pattern.search(source):
            continue
        if target in translation:
            continue
        issues.append(QualityIssue(
            type="core_term_inconsistent",
            severity="warning",
            block_id=block_id,
            message=f"expected {rule['source']} → {target}",
            source_text=source,
            translation=translation,
            expected=target,
        ))
    return issues


def _cjk_compact_text(value: str) -> str:
    return "".join(_CJK_TEXT_RE.findall(_compact_subtitle_text(value)))


def _scientific_target_length_limit(source: str) -> int:
    letter_count = len(re.sub(r"[^A-Za-z]", "", source or ""))
    return max(4, min(10, (letter_count + 1) // 2 + 2))


def _cjk_substrings(text: str, min_length: int = 3, max_length: int = 10) -> set[str]:
    if len(text) < min_length:
        return set()
    result: set[str] = set()
    for start in range(len(text)):
        max_end = min(len(text), start + max_length)
        for end in range(start + min_length, max_end + 1):
            result.add(text[start:end])
    return result


def _looks_like_scientific_context_anchor(anchor: str) -> bool:
    return any(char in _SCIENTIFIC_CONTEXT_ANCHOR_CHARS for char in anchor)


def _common_scientific_anchor(cjk_translations: list[str]) -> str:
    if not cjk_translations:
        return ""
    for min_length in (3, 2):
        shared = _cjk_substrings(cjk_translations[0], min_length=min_length)
        for text in cjk_translations[1:]:
            shared &= _cjk_substrings(text, min_length=min_length)
            if not shared:
                break
        if not shared:
            continue
        for anchor in sorted(shared, key=lambda item: (-len(item), item)):
            if _looks_like_scientific_context_anchor(anchor):
                continue
            return anchor
    return ""


def _ends_with_scientific_target_suffix(text: str) -> bool:
    return any(text.endswith(suffix) for suffix in _SCIENTIFIC_TARGET_SUFFIXES)


def _scientific_signature_from_anchor(cjk_text: str, anchor: str, source: str) -> str:
    start = cjk_text.find(anchor)
    if start < 0:
        return ""
    max_end = min(len(cjk_text), start + _scientific_target_length_limit(source))
    min_end = min(max_end, start + max(2, len(anchor)))
    for end in range(start + 2, min_end + 1):
        chunk = cjk_text[start:end]
        if _ends_with_scientific_target_suffix(chunk):
            return chunk
    for end in range(min_end, max_end + 1):
        chunk = cjk_text[start:end]
        if _ends_with_scientific_target_suffix(chunk):
            return chunk
    return cjk_text[start:max_end] or anchor


def _scientific_suffix_chunks(cjk_text: str) -> list[str]:
    chunks: set[str] = set()
    for end in range(len(cjk_text)):
        prefix = cjk_text[:end + 1]
        if not _ends_with_scientific_target_suffix(prefix):
            continue
        for length in range(2, min(10, end + 1) + 1):
            if length <= end + 1:
                chunks.add(cjk_text[end - length + 1:end + 1])
    return sorted(chunks, key=_scientific_suffix_chunk_sort_key)


def _scientific_suffix_chunk_sort_key(chunk: str) -> tuple[int, int, int, str]:
    noise = 1 if chunk and chunk[0] in _SCIENTIFIC_CHUNK_PREFIX_NOISE and len(chunk) > 2 else 0
    if len(chunk) == 3:
        length_rank = 0
    elif len(chunk) == 2:
        length_rank = 1
    else:
        length_rank = 2 + len(chunk)
    return noise, length_rank, len(chunk), chunk


def _scientific_target_signature(translation: str, source: str, shared_anchor: str = "") -> str:
    cjk_text = _cjk_compact_text(translation)
    if not cjk_text:
        return _compact_subtitle_text(translation)
    if shared_anchor and shared_anchor in cjk_text:
        signature = _scientific_signature_from_anchor(cjk_text, shared_anchor, source)
        if signature:
            return signature
    chunks = _scientific_suffix_chunks(cjk_text)
    if chunks:
        return chunks[0]
    limit = _scientific_target_length_limit(source)
    return cjk_text[:limit]


def _scientific_term_consistency_issues(
    source_by_id: dict[str, str],
    translation_by_id: dict[str, str],
) -> list[QualityIssue]:
    observations_by_source: dict[str, list[dict]] = {}
    canonical_source: dict[str, str] = {}
    for block_id, source_text in source_by_id.items():
        seen_in_block: set[str] = set()
        for match in find_scientific_terms(source_text):
            key = match.source.casefold()
            if key in seen_in_block:
                continue
            seen_in_block.add(key)
            translation = translation_by_id.get(block_id, "")
            if not translation.strip():
                continue
            canonical_source.setdefault(key, match.source)
            observations_by_source.setdefault(key, []).append({
                "block_id": block_id,
                "source_text": source_text,
                "translation": translation,
            })

    issues: list[QualityIssue] = []
    for key, observations in observations_by_source.items():
        if len(observations) < 2:
            continue
        source = canonical_source.get(key, key)
        cjk_translations = [
            _cjk_compact_text(item["translation"])
            for item in observations
            if _cjk_compact_text(item["translation"])
        ]
        shared_anchor = _common_scientific_anchor(cjk_translations)
        target_forms: list[str] = []
        for item in observations:
            signature = _scientific_target_signature(
                item["translation"],
                source,
                shared_anchor,
            )
            item["target_signature"] = signature
            if signature and signature not in target_forms:
                target_forms.append(signature)

        if len(target_forms) <= 1:
            continue
        message = (
            f"auto-detected scientific term {source} uses inconsistent target forms: "
            f"{', '.join(target_forms)}"
        )
        for item in observations:
            block_value = item.get("block_id")
            block_id = int(block_value) if str(block_value).isdigit() else None
            issues.append(QualityIssue(
                type="scientific_term_inconsistent",
                severity="warning",
                block_id=block_id,
                message=message,
                source_text=item.get("source_text", ""),
                translation=_clean_text(item.get("translation", "")),
            ))
    return issues


def _compact_subtitle_text(value: str) -> str:
    return re.sub(r"\s+", "", _HTML_TAG_RE.sub("", value or ""))


def _subtitle_lines(value: str) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _duration_seconds(block) -> float:
    start = getattr(block, "start", None)
    end = getattr(block, "end", None)
    try:
        seconds = (end - start).total_seconds()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return 0.0
    return seconds if seconds > 0 else 0.0


def _weak_semantic_break(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False
    compact_lines = [_compact_subtitle_text(line) for line in lines]
    total = sum(len(line) for line in compact_lines)
    if total < 6:
        return False
    return any(0 < len(line) <= 2 for line in compact_lines)


def _style_profile_summary(profile: SubtitleStyleProfile | None) -> dict:
    if profile is None:
        return {}
    return profile.to_trace()


def run_quality_checks(
    blocks: Iterable,
    *,
    project_kb: Optional[ProjectKb] = None,
    target_language: str = "简体中文",
    max_chars: int = 32,
    meta_info: Optional[dict] = None,
    style_profile: Optional[SubtitleStyleProfile] = None,
    trace: Optional[dict] = None,
) -> TranslationQaReport:
    issues: list[QualityIssue] = []
    seen_ids = set()
    kb_terms = _kb_terms(project_kb)
    manual_terms = manual_term_pairs(meta_info if isinstance(meta_info, dict) else {})
    chinese_target = _is_chinese_target(target_language)
    technical_tutorial_context = _has_technical_tutorial_context(meta_info)
    active_style_profile = style_profile or infer_subtitle_style_profile(target_language, meta_info)
    effective_max_chars = max_chars
    if active_style_profile is not None and active_style_profile.max_line_chars > 0:
        effective_max_chars = min(max_chars, active_style_profile.max_line_chars) if max_chars > 0 else active_style_profile.max_line_chars
    source_by_id: dict[str, str] = {}
    translation_by_id: dict[str, str] = {}

    for block in blocks or []:
        if getattr(block, "filtered", False):
            continue
        block_id = getattr(block, "index", None)
        source = _clean_text(getattr(block, "text", ""))
        translation = _clean_text(getattr(block, "translation", ""))

        if isinstance(block_id, int):
            block_key = str(block_id)
            source_by_id.setdefault(block_key, source)
            translation_by_id.setdefault(block_key, translation)

        if isinstance(block_id, int):
            if block_id in seen_ids:
                issues.append(QualityIssue(
                    type="duplicate_id",
                    severity="error",
                    block_id=block_id,
                    message="duplicate subtitle id",
                    source_text=source,
                    translation=translation,
                ))
            seen_ids.add(block_id)

        sound_description = _is_sound_description(source)
        if source and not translation and not sound_description:
            issues.append(QualityIssue(
                type="missing_translation",
                severity="error",
                block_id=block_id if isinstance(block_id, int) else None,
                message="source subtitle has no translation",
                source_text=source,
                translation=translation,
            ))

        if sound_description and translation:
            issues.append(QualityIssue(
                type="sound_description_translated",
                severity="warning",
                block_id=block_id if isinstance(block_id, int) else None,
                message="sound-description block should be blank or handled by subtitle rules",
                source_text=source,
                translation=translation,
            ))

        if (
            not sound_description
            and
            chinese_target
            and translation
            and _english_residue_match(
                translation,
                allow_technical_terms=technical_tutorial_context,
            )
        ):
            issues.append(QualityIssue(
                type="english_residue",
                severity="warning",
                block_id=block_id if isinstance(block_id, int) else None,
                message="target subtitle still contains English text",
                source_text=source,
                translation=translation,
            ))

        lines = _subtitle_lines(translation) or ([translation] if translation else [])
        compact_translation = _compact_subtitle_text(translation)
        if not sound_description and effective_max_chars > 0 and any(
            len(_compact_subtitle_text(line)) > effective_max_chars for line in lines
        ):
            issues.append(QualityIssue(
                type="line_too_long",
                severity="warning",
                block_id=block_id if isinstance(block_id, int) else None,
                message=f"translation line exceeds {effective_max_chars}",
                source_text=source,
                translation=translation,
                expected=str(effective_max_chars),
            ))

        if active_style_profile is not None and translation and not sound_description:
            if len(lines) > active_style_profile.max_lines:
                issues.append(QualityIssue(
                    type="too_many_lines",
                    severity="warning",
                    block_id=block_id if isinstance(block_id, int) else None,
                    message=f"subtitle has {len(lines)} lines; expected at most {active_style_profile.max_lines}",
                    source_text=source,
                    translation=translation,
                    expected=str(active_style_profile.max_lines),
                ))

            duration = _duration_seconds(block)
            if duration > 0 and compact_translation:
                cps = len(compact_translation) / duration
                if cps > active_style_profile.max_chars_per_second:
                    issues.append(QualityIssue(
                        type="reading_speed_too_fast",
                        severity="warning",
                        block_id=block_id if isinstance(block_id, int) else None,
                        message=(
                            f"reading speed {cps:.1f} chars/sec exceeds "
                            f"{active_style_profile.max_chars_per_second:.1f}"
                        ),
                        source_text=source,
                        translation=translation,
                        expected=f"{active_style_profile.max_chars_per_second:.1f}",
                    ))

            if _weak_semantic_break(lines):
                issues.append(QualityIssue(
                    type="weak_semantic_line_break",
                    severity="warning",
                    block_id=block_id if isinstance(block_id, int) else None,
                    message="line break splits a very short fragment; prefer phrase or punctuation boundaries",
                    source_text=source,
                    translation=translation,
                ))

            if _REPEATED_CJK_RE.search(translation):
                issues.append(QualityIssue(
                    type="repetition_not_compressed",
                    severity="warning",
                    block_id=block_id if isinstance(block_id, int) else None,
                    message="repeated short expression may need subtitle compression",
                    source_text=source,
                    translation=translation,
                ))

            if chinese_target and _ASCII_PUNCT_RE.search(translation):
                issues.append(QualityIssue(
                    type="punctuation_style",
                    severity="warning",
                    block_id=block_id if isinstance(block_id, int) else None,
                    message="Chinese subtitles should prefer full-width Chinese punctuation",
                    source_text=source,
                    translation=translation,
                    expected="Chinese punctuation",
                ))

        lower_source = source.lower()
        for term_source, term_target in kb_terms:
            if term_source.lower() in lower_source and term_target not in translation:
                issues.append(QualityIssue(
                    type="kb_term_missing",
                    severity="error",
                    block_id=block_id if isinstance(block_id, int) else None,
                    message=f"expected KB term {term_source} → {term_target}",
                    source_text=source,
                    translation=translation,
                    expected=term_target,
                ))

        for term_source, term_target in manual_terms:
            if term_source.lower() in lower_source and term_target not in translation:
                issues.append(QualityIssue(
                    type="manual_term_missing",
                    severity="error",
                    block_id=block_id if isinstance(block_id, int) else None,
                    message=f"expected manual term {term_source} -> {term_target}",
                    source_text=source,
                    translation=translation,
                    expected=term_target,
                ))

        if chinese_target and source and translation:
            issues.extend(_core_term_issues(
                source,
                translation,
                block_id if isinstance(block_id, int) else None,
            ))
            for match in find_domain_terms(source):
                if match_is_overridden_by_project_kb(match, project_kb):
                    continue
                term = match.term
                if term.target_is_present(translation):
                    continue
                issues.append(QualityIssue(
                    type="canonical_term_missing",
                    severity="warning",
                    block_id=block_id if isinstance(block_id, int) else None,
                    message=f"expected curated term {match.matched_source} → {term.target}",
                    source_text=source,
                    translation=translation,
                    expected=term.target,
                ))

    if chinese_target:
        issues.extend(_scientific_term_consistency_issues(source_by_id, translation_by_id))
        proper_name_issues = proper_name_consistency_score(source_by_id, translation_by_id)
        for item in proper_name_issues["issues"]:
            target_forms = [form for form in item.get("target_forms", []) if form]
            message = f"inferred proper name {item['source']} uses inconsistent target forms"
            if target_forms:
                message = f"{message}: {', '.join(target_forms)}"
            for observation in item.get("observations", []):
                block_value = observation.get("block_id")
                block_id = int(block_value) if str(block_value).isdigit() else None
                issues.append(QualityIssue(
                    type="proper_name_inconsistent",
                    severity="warning",
                    block_id=block_id,
                    message=message,
                    source_text=item["source"],
                    translation=_clean_text(observation.get("translation", "")),
                ))

    blocking_issues = [issue for issue in issues if _is_blocking_issue(issue)]
    report_only_count = max(0, len(issues) - len(blocking_issues))
    status = "ok" if not blocking_issues else "needs_review"
    report = TranslationQaReport(
        status=status,
        issues=issues,
        summary={
            "issue_count": len(issues),
            "blocking_issue_count": len(blocking_issues),
            "report_only_warning_count": report_only_count,
            "by_type": _issue_counts(issues),
            "far": _far_counts(issues),
            "style_profile": _style_profile_summary(active_style_profile),
        },
        unresolved_blocks=sorted({
            issue.block_id for issue in blocking_issues if isinstance(issue.block_id, int)
        }),
        trace=trace or {},
    )
    return report


def save_quality_report(
    report: TranslationQaReport,
    *,
    json_path: Path,
    markdown_path: Optional[Path] = None,
) -> None:
    atomic_write_json(Path(json_path), report.to_dict())
    if markdown_path is not None:
        Path(markdown_path).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_path).write_text(report.to_markdown(), encoding="utf-8")


def build_repair_items(blocks: Iterable, issues: list[QualityIssue]) -> list[dict]:
    failing_ids = {issue.block_id for issue in issues if isinstance(issue.block_id, int)}
    reading_speed_by_id = {
        issue.block_id: issue
        for issue in issues
        if issue.type == "reading_speed_too_fast" and isinstance(issue.block_id, int)
    }
    items = []
    for block in blocks or []:
        block_id = getattr(block, "index", None)
        if block_id not in failing_ids:
            continue
        translation = _clean_text(getattr(block, "translation", ""))
        item = {
            "id": block_id,
            "original": _clean_text(getattr(block, "text", "")),
            "draft": translation,
        }
        reading_issue = reading_speed_by_id.get(block_id)
        duration = _duration_seconds(block)
        if reading_issue is not None and duration > 0:
            try:
                max_cps = float(reading_issue.expected)
            except (TypeError, ValueError, OverflowError):
                max_cps = 0.0
            if max_cps > 0:
                item.update({
                    "duration_seconds": round(duration, 2),
                    "current_compact_chars": len(_compact_subtitle_text(translation)),
                    "max_compact_chars": max(1, int(duration * max_cps)),
                    "max_chars_per_second": round(max_cps, 1),
                })
        items.append(item)
    return items


def repairable_quality_issues(issues: list[QualityIssue]) -> list[QualityIssue]:
    repairable: list[QualityIssue] = []
    for issue in issues or []:
        if issue.type in _AUTO_REPAIR_REPORT_ONLY_ISSUE_TYPES:
            continue
        repairable.append(issue)
    return repairable


def build_repair_prompt(
    target_language: str,
    items: list[dict],
    issues: list[QualityIssue],
    *,
    kb_terms: Optional[dict[str, str]] = None,
) -> str:
    by_id = {}
    for issue in issues:
        if isinstance(issue.block_id, int):
            by_id.setdefault(issue.block_id, []).append(issue)

    parts = [
        f"你是一位{target_language}字幕审校。只修复下面列出的失败字幕块。",
        "必须保持 id 原样，不要新增、删除或重编号。",
        "仅输出 JSON 数组，格式: [{\"id\": N, \"translation\": \"修复后的译文\"}]。",
    ]
    if kb_terms:
        parts.append("必须遵守术语:")
        for source, target in kb_terms.items():
            parts.append(f"- {source} → {target}")
    issue_types = {issue.type for issue in issues}
    if "reading_speed_too_fast" in issue_types:
        parts.append(
            "读速超标时必须压缩译文：保留核心信息，删除可省略称呼、语气词和重复表达；"
            "双人对话要保留问答关系，但优先压到读速阈值以内。"
        )
        parts.append(
            "如果待修复项包含 max_compact_chars，修复后的 compact 字数"
            "（去掉空格、换行和 HTML 标签后）必须小于等于该值。"
        )
        parts.append(
            "这是硬性验收条件，超过 max_compact_chars 会再次判失败；"
            "称谓或职衔密集时优先保留姓名/姓氏和必要头衔，删除可省略的重复头衔；"
            "争吵、追问等双人对话优先改成短句。"
        )
    if "line_too_long" in issue_types:
        parts.append("行长超标时优先在语义边界换行或压缩，不要为了换行添加新信息。")
    if "core_term_inconsistent" in issue_types:
        parts.append("核心术语不一致时必须使用 Issue 中 expected 指定的译法，并统一同一源术语。")
    parts.append("")
    parts.append("待修复字幕:")
    for item in items:
        block_id = item.get("id")
        parts.append(json.dumps(item, ensure_ascii=False))
        for issue in by_id.get(block_id, []):
            expected = f" | expected: {issue.expected}" if _clean_text(issue.expected) else ""
            parts.append(f"  Issue: {issue.type} - {issue.message}{expected}")
    return "\n".join(parts)
