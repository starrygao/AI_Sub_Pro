"""Deterministic subtitle translation QA and repair prompt helpers."""
from __future__ import annotations

import hashlib
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
from app.utils.subtitle_structure import (
    classify_speaker_lines,
    preserves_speaker_line_structure,
)


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
    run_id: str = ""
    content_hash: str = ""
    source_generation_hash: str = ""
    configuration_hash: str = ""
    delivery_artifact_hashes: dict = field(default_factory=dict)
    issues: list[QualityIssue] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    repaired_blocks: list[dict] = field(default_factory=list)
    unresolved_blocks: list[int] = field(default_factory=list)
    trace: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "content_hash": self.content_hash,
            "source_generation_hash": self.source_generation_hash,
            "configuration_hash": self.configuration_hash,
            "delivery_artifact_hashes": dict(
                self.delivery_artifact_hashes
            ),
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
        if self.run_id:
            lines.append(f"- Run ID: {self.run_id}")
        if self.content_hash:
            lines.append(f"- Content Hash: {self.content_hash}")
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


def quality_content_hash(blocks: Iterable) -> str:
    """Return a deterministic identity for the exact source/translation pairs."""
    records = []
    for block in blocks or []:
        block_id = getattr(block, "index", None)
        if not isinstance(block_id, int) or isinstance(block_id, bool):
            continue
        source = getattr(block, "text", "")
        translation = getattr(block, "translation", "")
        records.append({
            "id": block_id,
            "source": source if isinstance(source, str) else "",
            "translation": translation if isinstance(translation, str) else "",
        })
    payload = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


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
_SENTENCE_END_PUNCT_RE = re.compile(r"[.!?。！？]\s*$")
_SEMANTIC_ELLIPSIS_RE = re.compile(r"(?:\.{2,}|…+)[\"'”’)\]}】）]*\s*$")
_SEMANTIC_TERMINAL_RE = re.compile(r"[.!?。！？][\"'”’)\]}】）]*\s*$")
_LOWERCASE_CONTINUATION_RE = re.compile(r"^[\"'“‘(\[{]*[a-z]")
_DUAL_SPEAKER_ON_CONTINUATION_RE = re.compile(
    r"^[\"'“‘(\[{]*on\b"
)
_DIALOGUE_DASH_PREFIX_RE = re.compile(r"^\s*[-‐‑‒–—―]\s*")
_SINGLE_SPEAKER_START_RE = re.compile(
    r"^\s*(?:[-‐‑‒–—―]\s*\S|[A-Z][A-Za-z0-9 .'\-]{0,47}[:：]\s*\S)"
)
_BRACKETED_SPEAKER_START_RE = re.compile(
    r"^\s*(?:[-‐‑‒–—―]\s*)?\[[^\]\r\n]{1,48}\]\s*\S"
)
_UPPERCASE_CONTINUATION_RE = re.compile(r"^[\"'“‘(\[{]*[A-Z]")
_INCOMPLETE_TRAILING_WORD_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|to|of|for|with|that|if|when|"
    r"because|and|or|but|what|who|which|whose|my|our|your|his|her|their|"
    r"a|an|the)\s*$",
    re.IGNORECASE,
)
_MAX_SEMANTIC_GROUP_CUES = 3
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
    "齿",
    "齒",
    "亚",
    "亞",
)
_SCIENTIFIC_CONTEXT_ANCHOR_CHARS = set("一只个個头頭群在从從到有没沒无無不是和与與及它他她我你")
_SCIENTIFIC_CHUNK_PREFIX_NOISE = set("一只个個头頭群名叫为為是有没沒无無幼年成年雌雄小")
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
_TRANSLATION_META_TOKENS = {
    "answer",
    "bracket",
    "clean",
    "construct",
    "draft",
    "exact",
    "line",
    "marker",
    "need",
    "original",
    "output",
    "rewrite",
    "source",
    "speaker",
    "target",
    "translate",
    "translation",
    "verbatim",
}
_TRANSLATION_META_FUNCTION_WORDS = {
    "and",
    "as",
    "be",
    "is",
    "it",
    "of",
    "says",
    "should",
    "the",
    "this",
    "to",
    "we",
}
_AUTO_REPAIR_REPORT_ONLY_ISSUE_TYPES = {
    "proper_name_inconsistent",
    "scientific_term_inconsistent",
    "sound_description_translated",
}
_EXPECTED_REPAIRABLE_CONSISTENCY_TYPES = {
    "proper_name_inconsistent",
    "scientific_term_inconsistent",
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
    "无可闻对话",
    "无可闻对白",
    "无可听见对话",
    "无可听见对白",
    "听不到对话",
    "听不到对白",
    "无清晰对话",
    "无清晰对白",
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
    r"sound(?:s)?|chatter|conversation|inaudible|indistinct(?:ly)?|"
    r"(?:no|without) (?:audible|discernible|intelligible) dialogue|"
    r"applause|cheer(?:s|ing)?|"
    r"speak(?:s|ing)?|talk(?:s|ing)?|plead(?:s|ing)?|"
    r"scoff(?:s|ing)?|clear(?:s|ing)? throat|throat|"
    r"sniff(?:s|ed|ing|l(?:e|es|ed|ing))?|"
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
    r"thump(?:s|ing)?|thudd(?:ing)?|pound(?:s|ed|ing)?|"
    r"gurgl(?:e|es|ed|ing)?|croak(?:s|ed|ing)?|"
    r"squelch(?:es|ing)?|clang(?:s|ing)?|clank(?:s|ed|ing)?|"
    r"clunk(?:s|ing)?|bang(?:s|ing)?|snap(?:s|ping)?|"
    r"pop(?:s|ped|ping)?|"
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
    r"whistl(?:e|es|ed|ing)|horn|chok(?:e|es|ing)?|gulp(?:s|ing)?|"
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
_MUSIC_DESCRIPTION_STYLE = (
    r"(?:instrumental|upbeat|latin|tense|gentle|soft|somber|dramatic|"
    r"ominous|distant|background|theme|orchestral)"
)
_MUSIC_DESCRIPTION_STATE = (
    r"(?:continues?|plays?|playing|swells?|fades?|fading|rises?|builds?)"
)
_MUSIC_DESCRIPTION_QUALIFIER = (
    r"(?:faintly|softly|quietly|loudly|distantly|"
    r"in\s+(?:the\s+)?(?:background|distance))"
)
_MUSIC_DESCRIPTION_EN_PATTERN = (
    rf"(?:(?:{_MUSIC_DESCRIPTION_STYLE})\s+)*music"
    rf"(?:\s+{_MUSIC_DESCRIPTION_STATE})?"
    rf"(?:\s+{_MUSIC_DESCRIPTION_QUALIFIER})?"
)
_NOTE_WRAPPED_MUSIC_DESCRIPTION_EN_RE = re.compile(
    r"^(?:(?:instrumental|tense|gentle|background|theme)\s+)*"
    r"music(?:\s+(?:continues?|playing))?$",
    re.IGNORECASE,
)
_NOTE_WRAPPED_MUSIC_DESCRIPTION_CJK_RE = re.compile(
    r"^(?:(?:纯|背景|紧张|轻柔|主题)){0,3}音乐(?:继续|响起|播放|持续)?$"
)
_MULTILINE_BRACKETED_MUSIC_DESCRIPTION_EN_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?\[\s*"
    rf"{_MUSIC_DESCRIPTION_EN_PATTERN}\s*\]\s*$",
    re.IGNORECASE,
)
_SAFE_UNBRACKETED_SOUND_LABELS = (
    "无可闻对话",
    "无可闻对白",
    "无可听见对话",
    "无可听见对白",
    "无清晰对话",
    "无清晰对白",
)
_CONTEXTUAL_SPEAKER_PREFIX_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?"
    r"(?P<label>[A-Za-z][A-Za-z0-9 ./'&-]{0,44}|[\u3400-\u9fff]{1,12})"
    r"(?:\s*\([^)\r\n]{1,40}\))?\s*[:：]\s*\S",
    re.IGNORECASE,
)
_CONTEXTUAL_BRACKET_CUE_RE = re.compile(
    r"^\s*(?:[-–—]\s*)?(?:\[(?P<bracket>[^\]\r\n]{1,48})\]|"
    r"[（(](?P<paren>[^）)\r\n]{1,48})[）)])\s*\S",
    re.IGNORECASE,
)
_CONTEXTUAL_MARKER_RE = re.compile(
    r"^\s*(?:【[^】\r\n]{1,12}】|\[[^\]\r\n]{1,20}\]|[（(][^）)\r\n]{1,20}[）)])"
)
_CONTEXTUAL_TARGET_LABEL_RE = re.compile(
    r"^\s*(?:主持人|主持|司仪|DJ|酒保|电视|新闻|广播|旁白|画外音|电话|人群|歌声)[:：]\s*"
)


def _is_report_only_issue(issue: QualityIssue) -> bool:
    return getattr(issue, "severity", "") == "warning"


def _is_blocking_issue(issue: QualityIssue) -> bool:
    return getattr(issue, "severity", "") in {"error", "severe"}


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


def _contextual_marker_from_label(label: str) -> str:
    text = _clean_text(label)
    if not text:
        return ""
    if any(keyword in text for keyword in ("主持", "司仪", "报幕")):
        return "【主持人】"
    if any(keyword in text for keyword in ("电视", "屏幕")):
        return "【电视】"
    if any(keyword in text for keyword in ("新闻", "记者", "主播")):
        return "【新闻】"
    if any(keyword in text for keyword in ("广播", "电台", "扩音", "喇叭")):
        return "【广播】"
    if any(keyword in text for keyword in ("旁白", "画外", "话外")):
        return "【旁白】"
    if "电话" in text:
        return "【电话】"
    if any(keyword in text for keyword in ("人群", "观众")):
        return "【人群】"
    if "酒保" in text:
        return "【酒保】"

    normalized = re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()
    if not normalized:
        return ""
    words = set(normalized.split())
    if {"PA", "INTERCOM", "LOUDSPEAKER"} & words or "OVER PA" in normalized:
        return "【广播】"
    if {"TV", "TELEVISION", "SCREEN"} & words or "ON TV" in normalized:
        return "【电视】"
    if {"NEWS", "ANCHOR", "REPORTER", "NEWSCASTER"} & words:
        return "【新闻】"
    if {"RADIO", "BROADCAST", "BROADCASTER"} & words:
        return "【广播】"
    if {"HOST", "ANNOUNCER", "EMCEE", "PRESENTER", "MC"} & words or "M C" in normalized:
        return "【主持人】"
    if "DJ" in words:
        return "【DJ】"
    if "BARTENDER" in words:
        return "【酒保】"
    if {"VOICE", "VOICEOVER", "VO", "NARRATOR"} & words or "V O" in normalized:
        return "【旁白】"
    if (
        {"OFFSCREEN", "OFFCAMERA", "OS"} & words
        or "O S" in normalized
        or "OFF SCREEN" in normalized
        or "OFF CAMERA" in normalized
    ):
        return "【画外音】"
    if {"PHONE", "CALLER", "VOICEMAIL"} & words:
        return "【电话】"
    if {"CROWD", "AUDIENCE", "PATRONS"} & words:
        return "【人群】"
    if {"SINGER", "VOCALIST"} & words:
        return "【歌声】"
    return ""


def _contextual_marker_from_source(source: str) -> str:
    text = _ASS_OVERRIDE_RE.sub("", source or "")
    text = _HTML_TAG_RE.sub("", text).strip()
    if not text:
        return ""
    match = _CONTEXTUAL_SPEAKER_PREFIX_RE.match(text)
    if match:
        marker = _contextual_marker_from_label(match.group("label"))
        if marker:
            return marker
    match = _CONTEXTUAL_BRACKET_CUE_RE.match(text)
    if not match:
        return ""
    label = match.group("bracket") or match.group("paren") or ""
    return _contextual_marker_from_label(label)


def _translation_with_contextual_marker(translation: str, marker: str) -> str:
    text = _clean_text(translation)
    if not text or _CONTEXTUAL_MARKER_RE.match(text):
        return text
    label_match = _CONTEXTUAL_TARGET_LABEL_RE.match(text)
    if label_match:
        body = text[label_match.end():].strip()
        return f"{marker}{body}" if body else marker
    return f"{marker}{text}"


def annotate_contextual_speaker_translations(
    blocks: Iterable,
    *,
    target_language: str = "简体中文",
) -> list[dict]:
    """Prefix offscreen/broadcast/host dialogue with compact source markers."""
    if not _is_chinese_target(target_language):
        return []
    applied: list[dict] = []
    for block in blocks or []:
        if getattr(block, "filtered", False):
            continue
        source = _clean_text(getattr(block, "text", ""))
        translation = _clean_text(getattr(block, "translation", ""))
        if not source or not translation:
            continue
        marker = _contextual_marker_from_source(source)
        if not marker:
            continue
        updated = _translation_with_contextual_marker(translation, marker)
        if updated == translation:
            continue
        block.translation = updated
        applied.append({
            "id": getattr(block, "index", None),
            "source": source,
            "from": translation,
            "to": updated,
            "marker": marker,
            "reason": "contextual_speaker_marker",
        })
    return applied


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


def _translation_meta_contamination_match(translation: str):
    """Return a strong sentence/meta English match without flagging lone names."""
    matches = [
        match
        for match in _ENGLISH_RE.finditer(translation or "")
        if not _is_allowed_acronym_token(match.group(0))
        and not _is_allowed_technical_token(match.group(0))
    ]
    if not matches:
        return None
    tokens = [match.group(0).casefold() for match in matches]
    meta_count = sum(token in _TRANSLATION_META_TOKENS for token in tokens)
    function_count = sum(
        token in _TRANSLATION_META_FUNCTION_WORDS
        for token in tokens
    )
    if (
        (meta_count >= 2 and len(tokens) >= 3)
        or (len(tokens) >= 5 and function_count >= 2)
    ):
        return matches[0]
    return None


def translation_candidate_contract_error(
    source: str,
    translation: str,
    *,
    target_language: str,
) -> str:
    """Classify deterministic defects that make a provider candidate unusable."""
    if not isinstance(translation, str) or not translation:
        return ""
    source_structure = classify_speaker_lines(source)
    if (
        source_structure is not None
        and not preserves_speaker_line_structure(
            translation,
            source_structure,
        )
    ):
        return "candidate_contract:speaker_structure"
    if (
        _is_chinese_target(target_language)
        and _translation_meta_contamination_match(translation)
    ):
        return "candidate_contract:meta_contamination"
    return ""


def _sound_description_probe_text(value: str) -> str:
    text = _HTML_TAG_RE.sub("", value or "")
    text = _ASS_OVERRIDE_RE.sub("", text)
    text = _MUSIC_MARK_RE.sub("", text)
    text = re.sub(r"(^|\s)[-–—]\s*(?=\[)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:[-–—]\s*)+", "", text).strip()
    text = re.sub(r"(?:\s*[-–—])+$", "", text).strip()
    return text


def _is_sound_description_line(source: str) -> bool:
    probe = _sound_description_probe_text(source)
    if not probe:
        return bool(_MUSIC_MARK_RE.search(source or ""))

    segments = list(_BRACKETED_TRANSLATION_SEGMENT_RE.finditer(probe))
    if segments:
        remainder = _BRACKETED_TRANSLATION_SEGMENT_RE.sub("", probe)
        if (
            _is_translation_separator_only(remainder)
            and all(_is_sound_translation_label(match.group(1)) for match in segments)
        ):
            return True

    if _MUSIC_MARK_RE.search(source or ""):
        normalized_probe = re.sub(r"\s+", " ", probe).strip()
        compact_probe = re.sub(r"\s+", "", probe)
        return bool(
            _NOTE_WRAPPED_MUSIC_DESCRIPTION_EN_RE.fullmatch(normalized_probe)
            or _NOTE_WRAPPED_MUSIC_DESCRIPTION_CJK_RE.fullmatch(compact_probe)
        )

    if segments:
        return False

    return _is_unbracketed_sound_description_label(probe)


def _is_sound_description(source: str) -> bool:
    multiline_probe = _HTML_TAG_RE.sub("", source or "")
    multiline_probe = _ASS_OVERRIDE_RE.sub("", multiline_probe)
    if (
        len(multiline_probe.splitlines()) > 1
        and _MULTILINE_BRACKETED_MUSIC_DESCRIPTION_EN_RE.fullmatch(
            multiline_probe
        )
    ):
        return True
    lines = [
        line
        for line in (source or "").splitlines()
        if _sound_description_probe_text(line)
        or _MUSIC_MARK_RE.search(line)
    ]
    return bool(lines) and all(_is_sound_description_line(line) for line in lines)


def is_sound_description_source(source: str) -> bool:
    """Return True when a source cue is a non-dialogue sound/music description."""
    return _is_sound_description(source)


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
    if find_domain_terms(text) or find_scientific_terms(text):
        return False
    if _CJK_TEXT_RE.search(text):
        compact = _compact_subtitle_text(text)
        return bool(compact and len(compact) <= 12)
    words = re.findall(r"[A-Za-z]+", text)
    letters = re.sub(r"[^A-Za-z]", "", text)
    if _SENTENCE_END_PUNCT_RE.search(text) and letters != letters.upper():
        return False
    if words and words[0].casefold() in {
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "my",
        "your",
        "his",
        "her",
        "our",
        "their",
    }:
        return False
    if len(words) <= 3:
        return True
    return bool(letters and letters == letters.upper())


def _is_high_confidence_unbracketed_target_label(value: str) -> bool:
    text = _clean_text(value)
    if text in _SAFE_UNBRACKETED_SOUND_LABELS:
        return True
    if _CJK_TEXT_RE.search(text) or not _is_sound_translation_label(text):
        return False
    letters = re.sub(r"[^A-Za-z]", "", text)
    return bool(letters and letters == letters.upper())


def _sound_description_label_match_key(value: str) -> str:
    text = _sound_description_probe_text(value)
    return re.sub(r"[^A-Za-z0-9\u3400-\u9fff]+", "", text).casefold()


def _source_has_corresponding_sound_label(source_text: str, target_label: str) -> bool:
    target_key = _sound_description_label_match_key(target_label)
    if not target_key:
        return False

    for match in _BRACKETED_TRANSLATION_SEGMENT_RE.finditer(source_text or ""):
        source_label = match.group(1)
        if (
            _is_sound_translation_label(source_label)
            and _sound_description_label_match_key(source_label) == target_key
        ):
            return True

    source_probe = _sound_description_probe_text(source_text)
    return (
        _is_high_confidence_unbracketed_target_label(source_probe)
        and _sound_description_label_match_key(source_probe) == target_key
    )


def _is_translation_separator_only(value: str) -> bool:
    text = _ASS_OVERRIDE_RE.sub("", value or "")
    text = re.sub(r"[\s\-–—、，,。.!！?？:：;；/\\|~·]+", "", text)
    return not text


def clean_sound_description_translation_text(
    value: str,
    *,
    source_text: str = "",
) -> str:
    """Remove safe sound-description labels while preserving dialogue."""
    if not isinstance(value, str) or not value:
        return ""

    def clean_remainder(remainder: str) -> str:
        cleaned = re.sub(r"\s{2,}", " ", remainder).strip()
        cleaned = re.sub(r"^(?:[-–—:：]\s*)+", "", cleaned).strip()
        cleaned = re.sub(r"(?:\s*[-–—])+$", "", cleaned).strip()
        cleaned = re.sub(r"^[、，,。.!！?？:：;；]+\s*", "", cleaned).strip()
        return "" if _is_translation_separator_only(cleaned) else cleaned

    def clean_unbracketed(line: str) -> str:
        text = line.strip()
        if text in _SAFE_UNBRACKETED_SOUND_LABELS:
            return ""
        for label in _SAFE_UNBRACKETED_SOUND_LABELS:
            if not text.startswith(label):
                continue
            remainder = text[len(label):]
            if remainder and re.match(r"^(?:\s+|[-–—:：])", remainder):
                return clean_remainder(remainder)
        split = re.match(r"^(?P<label>.+?)\s+[-–—]\s+(?P<dialogue>.+)$", text)
        if (
            split
            and _is_high_confidence_unbracketed_target_label(split.group("label"))
            and _source_has_corresponding_sound_label(
                source_text,
                split.group("label"),
            )
        ):
            return clean_remainder(split.group("dialogue"))
        if (
            _is_high_confidence_unbracketed_target_label(text)
            and _source_has_corresponding_sound_label(source_text, text)
        ):
            return ""
        return text

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
            cleaned = clean_remainder(cleaned)
        else:
            cleaned = clean_unbracketed(line)
        if cleaned:
            cleaned_lines.append(cleaned)
    return "\n".join(cleaned_lines).strip()


def dialogue_only_qa_source_text(source: str) -> str:
    """Return the dialogue-bearing source text under the sound-omission policy."""
    if not isinstance(source, str) or not source.strip():
        return ""
    if _is_sound_description(source):
        return ""
    dialogue_lines: list[str] = []
    for line in source.splitlines():
        if _is_sound_description_line(line):
            continue
        cleaned = clean_sound_description_translation_text(
            line,
            source_text=line,
        )
        if cleaned:
            dialogue_lines.append(cleaned)
    return "\n".join(dialogue_lines).strip()


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
        cleaned_translation = clean_sound_description_translation_text(
            translation,
            source_text=source,
        )
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


def _term_present(text: str, term: str) -> bool:
    normalized_text = re.sub(r"\s+", " ", _clean_text(text))
    normalized_term = re.sub(r"\s+", " ", _clean_text(term))
    if not normalized_text or not normalized_term:
        return False
    escaped = re.escape(normalized_term)
    ascii_token = r"A-Za-z0-9_"
    prefix = (
        rf"(?<![{ascii_token}])"
        if re.match(rf"[{ascii_token}]", normalized_term[0])
        else ""
    )
    suffix = (
        rf"(?![{ascii_token}])"
        if re.match(rf"[{ascii_token}]", normalized_term[-1])
        else ""
    )
    return (
        re.search(
            f"{prefix}{escaped}{suffix}",
            normalized_text,
            re.IGNORECASE,
        )
        is not None
    )


def _context_selected_terms(trace: Optional[dict]) -> list[tuple[str, str]]:
    if not isinstance(trace, dict):
        return []
    pairs: list[tuple[str, str]] = []
    seen = set()
    for hit in trace.get("kb_hits", []) or []:
        if not isinstance(hit, dict):
            continue
        if _clean_text(hit.get("scope")) not in {
            "curated_domain",
            "manual_terms",
            "project",
        }:
            continue
        source = _clean_text(hit.get("source"))
        target = _clean_text(hit.get("target"))
        key = (source.casefold(), re.sub(r"\s+", "", target).casefold())
        if not source or not target or key in seen:
            continue
        seen.add(key)
        pairs.append((source, target))
    return pairs


def _issue_counts(issues: list[QualityIssue]) -> dict:
    counts = {}
    for issue in issues:
        counts[issue.type] = counts.get(issue.type, 0) + 1
    return counts


def _majority_target_signature(observations: list[dict]) -> str:
    counts: dict[str, int] = {}
    order: list[str] = []
    for item in observations or []:
        if not isinstance(item, dict):
            continue
        signature = _clean_text(item.get("target_signature", ""))
        if not signature:
            continue
        if signature not in counts:
            order.append(signature)
            counts[signature] = 0
        counts[signature] += 1
    ranked = sorted(order, key=lambda value: (-counts[value], order.index(value)))
    if not ranked or counts[ranked[0]] < 2:
        return ""
    if len(ranked) > 1 and counts[ranked[0]] == counts[ranked[1]]:
        return ""
    return ranked[0]


_FAR_CATEGORY_BY_TYPE = {
    "missing_translation": "functional",
    "duplicate_id": "functional",
    "kb_term_missing": "functional",
    "manual_term_missing": "functional",
    "canonical_term_missing": "functional",
    "core_term_inconsistent": "functional",
    "semantic_mismatch": "functional",
    "semantic_uncertain": "functional",
    "semantic_qa_failed": "functional",
    "scientific_term_inconsistent": "functional",
    "proper_name_inconsistent": "functional",
    "speaker_line_structure_mismatch": "functional",
    "context_term_missing": "functional",
    "translation_meta_contamination": "functional",
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


def _scientific_suffix_chunks(cjk_text: str, source: str = "") -> list[str]:
    chunks: set[str] = set()
    for end in range(len(cjk_text)):
        prefix = cjk_text[:end + 1]
        if not _ends_with_scientific_target_suffix(prefix):
            continue
        for length in range(2, min(10, end + 1) + 1):
            if length <= end + 1:
                chunks.add(cjk_text[end - length + 1:end + 1])
    return sorted(chunks, key=lambda chunk: _scientific_suffix_chunk_sort_key(chunk, source))


def _scientific_suffix_chunk_sort_key(chunk: str, source: str = "") -> tuple[int, int, int, int, str]:
    noise = 1 if chunk and chunk[0] in _SCIENTIFIC_CHUNK_PREFIX_NOISE and len(chunk) > 2 else 0
    limit = _scientific_target_length_limit(source) if source else 10
    over_limit = 1 if len(chunk) > limit else 0
    too_short = 1 if len(chunk) < 3 else 0
    return noise, over_limit, too_short, -min(len(chunk), limit), chunk


def _scientific_target_signature(translation: str, source: str, shared_anchor: str = "") -> str:
    cjk_text = _cjk_compact_text(translation)
    if not cjk_text:
        return _compact_subtitle_text(translation)
    if shared_anchor and shared_anchor in cjk_text:
        signature = _scientific_signature_from_anchor(cjk_text, shared_anchor, source)
        if signature:
            return signature
    chunks = _scientific_suffix_chunks(cjk_text, source)
    if chunks:
        return chunks[0]
    limit = _scientific_target_length_limit(source)
    return cjk_text[:limit]


def _scientific_term_consistency_issues(
    source_by_id: dict[str, str],
    translation_by_id: dict[str, str],
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for source, observations in _scientific_observations(source_by_id, translation_by_id).items():
        if len(observations) < 2:
            continue
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
        expected = _majority_target_signature(observations)
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
                expected=expected if expected and item.get("target_signature") != expected else "",
            ))
    return issues


def _scientific_observations(
    source_by_id: dict[str, str],
    translation_by_id: dict[str, str],
) -> dict[str, list[dict]]:
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
    return {
        canonical_source.get(key, key): observations
        for key, observations in observations_by_source.items()
    }


def _rank_scientific_canonical_signature(signatures: list[str]) -> str:
    counts: dict[str, int] = {}
    for signature in signatures:
        if not signature:
            continue
        counts[signature] = counts.get(signature, 0) + 1
    ranked = sorted(
        counts,
        key=lambda item: (
            -counts[item],
            0 if _ends_with_scientific_target_suffix(item) else 1,
            len(item),
            item,
        ),
    )
    if len(ranked) < 2:
        return ""
    winner = ranked[0]
    runner_up = ranked[1]
    if counts[winner] < 2 or counts[winner] == counts[runner_up]:
        return ""
    if len(winner) < 2 or not _ends_with_scientific_target_suffix(winner):
        return ""
    return winner


def normalize_scientific_term_translations(blocks: Iterable) -> list[dict]:
    """Normalize minority auto-detected scientific term variants by majority."""
    active_blocks = [
        block for block in (blocks or [])
        if not getattr(block, "filtered", False)
        and isinstance(getattr(block, "index", None), int)
    ]
    if not active_blocks:
        return []

    source_by_id = {
        str(getattr(block, "index")): getattr(block, "text", "")
        for block in active_blocks
    }
    translation_by_id = {
        str(getattr(block, "index")): getattr(block, "translation", "")
        for block in active_blocks
    }
    by_id = {str(getattr(block, "index")): block for block in active_blocks}
    applied: list[dict] = []

    for source, observations in _scientific_observations(source_by_id, translation_by_id).items():
        if len(observations) < 3:
            continue
        cjk_translations = [
            _cjk_compact_text(item["translation"])
            for item in observations
            if _cjk_compact_text(item["translation"])
        ]
        shared_anchor = _common_scientific_anchor(cjk_translations)
        signatures = []
        for item in observations:
            signature = _scientific_target_signature(
                item["translation"],
                source,
                shared_anchor,
            )
            item["target_signature"] = signature
            signatures.append(signature)
        canonical = _rank_scientific_canonical_signature(signatures)
        if not canonical:
            continue

        for item in observations:
            signature = item.get("target_signature", "")
            if not signature or signature == canonical or signature.startswith(canonical):
                continue
            if not _ends_with_scientific_target_suffix(signature):
                continue
            block_id = str(item.get("block_id", "")).strip()
            block = by_id.get(block_id)
            if block is None:
                continue
            current = getattr(block, "translation", "")
            if not isinstance(current, str) or signature not in current:
                continue
            updated = current.replace(signature, canonical, 1)
            if updated == current:
                continue
            block.translation = updated
            applied.append({
                "id": getattr(block, "index", None),
                "source": source,
                "from": signature,
                "to": canonical,
                "reason": "scientific_term_majority_variant",
            })
    return applied


def normalize_curated_domain_term_translations(
    blocks: Iterable,
    *,
    project_kb: Optional[ProjectKb] = None,
) -> list[dict]:
    """Normalize safely identifiable curated domain-term variants."""
    applied: list[dict] = []
    for block in blocks or []:
        if getattr(block, "filtered", False):
            continue
        source = _clean_text(getattr(block, "text", ""))
        translation = _clean_text(getattr(block, "translation", ""))
        if not source or not translation:
            continue
        for match in find_domain_terms(source):
            if match_is_overridden_by_project_kb(match, project_kb):
                continue
            term = match.term
            if term.target_is_present(translation):
                continue
            signature = _scientific_target_signature(translation, term.source)
            if (
                not signature
                or signature == term.target
                or signature not in translation
                or not _ends_with_scientific_target_suffix(signature)
            ):
                continue
            updated = translation.replace(signature, term.target, 1)
            if updated == translation:
                continue
            block.translation = updated
            applied.append({
                "id": getattr(block, "index", None),
                "source": term.source,
                "from": signature,
                "to": term.target,
                "reason": "curated_domain_term_variant",
            })
            translation = updated
    return applied


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
    context_terms = _context_selected_terms(trace)
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
        sound_description = _is_sound_description(source)
        qa_source = dialogue_only_qa_source_text(source)

        if isinstance(block_id, int) and qa_source:
            block_key = str(block_id)
            source_by_id.setdefault(block_key, qa_source)
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

        speaker_contract = (
            classify_speaker_lines(qa_source)
            if source and translation and not sound_description
            else None
        )
        if (
            speaker_contract is not None
            and not preserves_speaker_line_structure(translation, speaker_contract)
        ):
            issues.append(QualityIssue(
                type="speaker_line_structure_mismatch",
                severity="error",
                block_id=block_id if isinstance(block_id, int) else None,
                message=(
                    "translation must preserve one line per source speaker "
                    "and retain its marker/label structure"
                ),
                source_text=source,
                translation=translation,
                expected=speaker_contract.expected_description(),
            ))

        if (
            not sound_description
            and
            chinese_target
            and translation
            and _translation_meta_contamination_match(translation)
        ):
            issues.append(QualityIssue(
                type="translation_meta_contamination",
                severity="error",
                block_id=block_id if isinstance(block_id, int) else None,
                message="target subtitle contains model reasoning or meta commentary",
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

        for term_source, term_target in kb_terms:
            if (
                not sound_description
                and _term_present(qa_source, term_source)
                and not _term_present(translation, term_target)
            ):
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
            if (
                not sound_description
                and _term_present(qa_source, term_source)
                and not _term_present(translation, term_target)
            ):
                issues.append(QualityIssue(
                    type="manual_term_missing",
                    severity="error",
                    block_id=block_id if isinstance(block_id, int) else None,
                    message=f"expected manual term {term_source} -> {term_target}",
                    source_text=source,
                    translation=translation,
                    expected=term_target,
                ))

        for term_source, term_target in context_terms:
            if (
                not sound_description
                and _term_present(qa_source, term_source)
                and not _term_present(translation, term_target)
            ):
                issues.append(QualityIssue(
                    type="context_term_missing",
                    severity="error",
                    block_id=block_id if isinstance(block_id, int) else None,
                    message=f"expected selected term {term_source} → {term_target}",
                    source_text=source,
                    translation=translation,
                    expected=term_target,
                ))

        if chinese_target and source and translation and not sound_description:
            issues.extend(_core_term_issues(
                qa_source,
                translation,
                block_id if isinstance(block_id, int) else None,
            ))
            for match in find_domain_terms(qa_source):
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
            observations = [
                observation for observation in item.get("observations", [])
                if isinstance(observation, dict)
            ]
            has_shared_anchor = any(
                _clean_text(observation.get("target_anchor", ""))
                for observation in observations
            )
            expected = _majority_target_signature(observations) if has_shared_anchor else ""
            for observation in observations:
                block_value = observation.get("block_id")
                block_id = int(block_value) if str(block_value).isdigit() else None
                issues.append(QualityIssue(
                    type="proper_name_inconsistent",
                    severity="warning",
                    block_id=block_id,
                    message=message,
                    source_text=item["source"],
                    translation=_clean_text(observation.get("translation", "")),
                    expected=(
                        expected
                        if expected and observation.get("target_signature") != expected
                        else ""
                    ),
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


def _subtitle_time_gap_seconds(previous, following) -> Optional[float]:
    previous_end = getattr(previous, "end", None)
    following_start = getattr(following, "start", None)
    if previous_end is None or following_start is None:
        return None
    try:
        gap = following_start - previous_end
        return float(gap.total_seconds()) if hasattr(gap, "total_seconds") else float(gap)
    except (TypeError, ValueError, OverflowError):
        return None


def _starts_new_speaker_cue(source: str) -> bool:
    return bool(
        _SINGLE_SPEAKER_START_RE.match(source)
        or _BRACKETED_SPEAKER_START_RE.match(source)
        or classify_speaker_lines(source) is not None
    )


def _cross_cue_semantic_continuation(previous, following) -> bool:
    previous_source = dialogue_only_qa_source_text(
        _clean_text(getattr(previous, "text", ""))
    )
    following_source = dialogue_only_qa_source_text(
        _clean_text(getattr(following, "text", ""))
    )
    if not previous_source or not following_source:
        return False

    gap_seconds = _subtitle_time_gap_seconds(previous, following)
    if gap_seconds is None:
        return False
    if gap_seconds < -0.5 or gap_seconds > 1.0:
        return False

    previous_line = previous_source.rstrip().splitlines()[-1]
    following_line = following_source.lstrip().splitlines()[0]
    following_lines = following_source.splitlines()
    first_dialogue_line = _DIALOGUE_DASH_PREFIX_RE.sub(
        "",
        following_line,
        count=1,
    )
    dual_speaker_first_line_continues = bool(
        len(following_lines) > 1
        and first_dialogue_line != following_line
        and _DUAL_SPEAKER_ON_CONTINUATION_RE.match(first_dialogue_line)
    )
    if (
        _starts_new_speaker_cue(following_source)
        and not dual_speaker_first_line_continues
    ):
        return False
    if _SEMANTIC_ELLIPSIS_RE.search(previous_line):
        return True
    if _SEMANTIC_TERMINAL_RE.search(previous_line):
        return False
    continuation_line = (
        first_dialogue_line
        if dual_speaker_first_line_continues
        else following_line
    )
    if _LOWERCASE_CONTINUATION_RE.match(continuation_line):
        return True
    return bool(
        _UPPERCASE_CONTINUATION_RE.match(continuation_line)
        and _INCOMPLETE_TRAILING_WORD_RE.search(previous_line)
    )


def _semantic_seed_positions_in_window(
    seed_positions: set[int],
    start: int,
    size: int,
) -> list[int]:
    """Return seeds in a fixed-width candidate group without scanning the component."""
    return [
        position
        for position in range(start, start + size)
        if position in seed_positions
    ]


def build_repair_items(blocks: Iterable, issues: list[QualityIssue]) -> list[dict]:
    failing_ids = {issue.block_id for issue in issues if isinstance(issue.block_id, int)}
    semantic_ids = {
        issue.block_id
        for issue in issues
        if (
            issue.type in {
                "semantic_mismatch",
                "semantic_uncertain",
                "semantic_qa_failed",
            }
            and isinstance(issue.block_id, int)
        )
    }
    reading_speed_by_id = {
        issue.block_id: issue
        for issue in issues
        if issue.type == "reading_speed_too_fast" and isinstance(issue.block_id, int)
    }
    timeline_blocks = list(blocks or [])
    active_timeline = [
        (timeline_position, block)
        for timeline_position, block in enumerate(timeline_blocks)
        if not getattr(block, "filtered", False)
    ]
    active_blocks = [block for _timeline_position, block in active_timeline]
    timeline_position_by_active_position = [
        timeline_position
        for timeline_position, _block in active_timeline
    ]
    semantic_seed_positions = {
        position
        for position, block in enumerate(active_blocks)
        if getattr(block, "index", None) in semantic_ids
    }
    continuation_edges = {
        position
        for position in range(len(active_blocks) - 1)
        if (
            timeline_position_by_active_position[position + 1]
            == timeline_position_by_active_position[position] + 1
            and _cross_cue_semantic_continuation(
                active_blocks[position],
                active_blocks[position + 1],
            )
        )
    }
    semantic_group_by_position: dict[int, list[int]] = {}
    semantic_seed_ids_by_position: dict[int, list[int]] = {}
    semantic_repair_positions = set(semantic_seed_positions)
    component_start = 0
    while component_start < len(active_blocks):
        component_end = component_start
        while component_end in continuation_edges:
            component_end += 1
        component_seed_positions = {
            position
            for position in range(component_start, component_end + 1)
            if position in semantic_seed_positions
        }
        ordered_seed_positions = sorted(component_seed_positions)
        partition_start = (0, component_start)

        def candidate_transitions(
            state: tuple[int, int],
        ) -> list[tuple[int, int, tuple[int, int]]]:
            seed_offset, first_available_position = state
            if seed_offset >= len(ordered_seed_positions):
                return []
            seed_position = ordered_seed_positions[seed_offset]
            transitions = []
            max_group_size = min(
                _MAX_SEMANTIC_GROUP_CUES,
                component_end - component_start + 1,
            )
            for group_size in range(max_group_size, 1, -1):
                earliest_start = max(
                    component_start,
                    first_available_position,
                    seed_position - group_size + 1,
                )
                latest_start = min(
                    seed_position,
                    component_end - group_size + 1,
                )
                def transition_priority(start: int) -> tuple:
                    window_seeds = _semantic_seed_positions_in_window(
                        component_seed_positions,
                        start,
                        group_size,
                    )
                    seed_count = len(window_seeds)
                    seed_center = sum(window_seeds) / max(1, seed_count)
                    return (
                        -seed_count,
                        abs(
                            2 * seed_center
                            - (2 * start + group_size - 1)
                        ),
                        -(
                            start + group_size - 1
                            - window_seeds[-1]
                        ),
                        start,
                    )

                group_starts = sorted(
                    range(earliest_start, latest_start + 1),
                    key=transition_priority,
                )
                for group_start in group_starts:
                    group_end = group_start + group_size - 1
                    next_seed_offset = seed_offset
                    while (
                        next_seed_offset < len(ordered_seed_positions)
                        and ordered_seed_positions[next_seed_offset] <= group_end
                    ):
                        next_seed_offset += 1
                    transitions.append((
                        group_start,
                        group_end,
                        (next_seed_offset, group_end + 1),
                    ))
            return transitions

        # Every transition advances the seed offset, so the reachable state
        # graph is acyclic and can be solved iteratively without recursion.
        # The fixed 2-3 cue group width also bounds transitions and frontier
        # variants per seed, keeping this linear in practice for long chains.
        reachable_states = {partition_start}
        pending_states = [partition_start]
        while pending_states:
            state = pending_states.pop()
            for _group_start, _group_end, next_state in (
                candidate_transitions(state)
            ):
                if next_state in reachable_states:
                    continue
                reachable_states.add(next_state)
                pending_states.append(next_state)

        partition_cost: dict[tuple[int, int], Optional[int]] = {}
        partition_choice: dict[
            tuple[int, int],
            Optional[tuple[int, int, tuple[int, int]]],
        ] = {}
        for state in sorted(reachable_states, reverse=True):
            seed_offset, _first_available_position = state
            if seed_offset >= len(ordered_seed_positions):
                partition_cost[state] = 0
                partition_choice[state] = None
                continue
            best_cost = None
            best_transition = None
            for transition in candidate_transitions(state):
                next_state = transition[2]
                suffix_cost = partition_cost.get(next_state)
                if suffix_cost is None:
                    continue
                candidate_cost = 1 + suffix_cost
                # Keep the first equal-cost transition: candidate order encodes
                # the established largest-group then centered/start tie-break.
                if best_cost is None or candidate_cost < best_cost:
                    best_cost = candidate_cost
                    best_transition = transition
            partition_cost[state] = best_cost
            partition_choice[state] = best_transition

        component_groups = []
        partition_state = partition_start
        while True:
            selected = partition_choice.get(partition_state)
            if selected is None:
                break
            group_start, group_end, partition_state = selected
            component_groups.append(list(range(group_start, group_end + 1)))
        for component_positions in component_groups:
            group_seed_positions = _semantic_seed_positions_in_window(
                component_seed_positions,
                component_positions[0],
                len(component_positions),
            )
            semantic_repair_positions.update(component_positions)
            group_ids = [
                block_id
                for block_id in (
                    getattr(active_blocks[item_position], "index", None)
                    for item_position in component_positions
                )
                if isinstance(block_id, int) and not isinstance(block_id, bool)
            ]
            if len(group_ids) <= 1:
                continue
            group_seed_ids = [
                getattr(active_blocks[item_position], "index", None)
                for item_position in group_seed_positions
            ]
            for item_position in component_positions:
                semantic_group_by_position[item_position] = group_ids
                semantic_seed_ids_by_position[item_position] = group_seed_ids
        component_start = component_end + 1

    repair_ids = set(failing_ids)
    repair_ids.update(
        getattr(active_blocks[position], "index", None)
        for position in semantic_repair_positions
    )

    def context_item(block) -> dict:
        return {
            "id": getattr(block, "index", None),
            "original": _clean_text(getattr(block, "text", "")),
            "draft": _clean_text(getattr(block, "translation", "")),
        }

    items = []
    for position, block in enumerate(active_blocks):
        block_id = getattr(block, "index", None)
        if block_id not in repair_ids:
            continue
        translation = _clean_text(getattr(block, "translation", ""))
        item = {
            "id": block_id,
            "original": _clean_text(getattr(block, "text", "")),
            "draft": translation,
            "preceding_context": (
                [context_item(active_blocks[position - 1])]
                if position > 0
                else []
            ),
            "following_context": (
                [context_item(active_blocks[position + 1])]
                if position + 1 < len(active_blocks)
                else []
            ),
        }
        if position in semantic_group_by_position:
            item["semantic_group_ids"] = semantic_group_by_position[position]
            item["semantic_seed_ids"] = semantic_seed_ids_by_position[position]
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
        if issue.type == "sound_description_translated":
            continue
        if (
            issue.type in _EXPECTED_REPAIRABLE_CONSISTENCY_TYPES
            and not _clean_text(issue.expected)
        ):
            continue
        repairable.append(issue)
    return repairable


def prioritized_repairable_quality_issues(
    issues: list[QualityIssue],
) -> list[QualityIssue]:
    """Repair blocking failures before spending a round on report-only warnings."""
    repairable = repairable_quality_issues(issues)
    blocking = [
        issue
        for issue in repairable
        if (
            _is_blocking_issue(issue)
            or getattr(issue, "type", "") == "semantic_uncertain"
        )
    ]
    return blocking or repairable


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
        "original 含多个说话人行时，每位说话人独占一行并保持原顺序和 -/–/— 或“姓名:”标记；"
        "不得合并说话人行，JSON 字符串中的换行写为 \\n。",
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
        parts.append(
            "行长超标时优先压缩成自然单行；确实过长才在语义边界换成两行，"
            "不要为了换行添加新信息。"
        )
    if "core_term_inconsistent" in issue_types:
        parts.append("核心术语不一致时必须使用 Issue 中 expected 指定的译法，并统一同一源术语。")
    if issue_types & {"semantic_mismatch", "semantic_uncertain"}:
        parts.append(
            "语义错位时必须抛弃 draft，严格按 original 重新翻译；"
            "不要沿用与原文无关的旧译文，不要合并相邻 id。"
        )
        parts.append(
            "preceding_context 和 following_context 只用于理解上下文，不得输出这些上下文 id；"
            "semantic_group_ids 相同的相邻失败项要连贯修复，但每个 id 必须分别输出且保持不变。"
        )
    if "scientific_term_inconsistent" in issue_types:
        parts.append("科学名不一致时必须使用 Issue 中 expected 指定的译名，只改必要的术语部分。")
    if "proper_name_inconsistent" in issue_types:
        parts.append("专名不一致时必须使用 Issue 中 expected 指定的译名，只改必要的专名部分，不要重写整句。")
    if issue_types & {
        "kb_term_missing",
        "manual_term_missing",
        "canonical_term_missing",
        "context_term_missing",
    }:
        parts.append("术语缺失时必须使用 Issue 中 expected 指定的译法；不要改写已审定或策展术语。")
    parts.append("")
    parts.append("待修复字幕:")
    for item in items:
        block_id = item.get("id")
        parts.append(json.dumps(item, ensure_ascii=False))
        for issue in by_id.get(block_id, []):
            expected = f" | expected: {issue.expected}" if _clean_text(issue.expected) else ""
            parts.append(f"  Issue: {issue.type} - {issue.message}{expected}")
    return "\n".join(parts)
