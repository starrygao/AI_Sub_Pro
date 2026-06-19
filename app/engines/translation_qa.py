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
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_REPEATED_CJK_RE = re.compile(r"([\u4e00-\u9fff])(?:[，,、\s]*\1){2,}")
_ASCII_PUNCT_RE = re.compile(r"[?!,;:]")
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


def _english_residue_match(translation: str, *, allow_technical_terms: bool = False):
    for match in _ENGLISH_RE.finditer(translation or ""):
        if allow_technical_terms and _is_allowed_technical_token(match.group(0)):
            continue
        return match
    return None


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

        sound_description = bool(_SOUND_RE.match(source))
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
        if effective_max_chars > 0 and any(
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

        if active_style_profile is not None and translation:
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

    status = "ok" if not issues else "needs_review"
    report = TranslationQaReport(
        status=status,
        issues=issues,
        summary={
            "issue_count": len(issues),
            "by_type": _issue_counts(issues),
            "far": _far_counts(issues),
            "style_profile": _style_profile_summary(active_style_profile),
        },
        unresolved_blocks=sorted({
            issue.block_id for issue in issues if isinstance(issue.block_id, int)
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
    items = []
    for block in blocks or []:
        block_id = getattr(block, "index", None)
        if block_id not in failing_ids:
            continue
        items.append({
            "id": block_id,
            "original": _clean_text(getattr(block, "text", "")),
            "draft": _clean_text(getattr(block, "translation", "")),
        })
    return items


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
    if "line_too_long" in issue_types:
        parts.append("行长超标时优先在语义边界换行或压缩，不要为了换行添加新信息。")
    if "proper_name_inconsistent" in issue_types:
        parts.append("专名不一致时统一同一英文专名的中文译法，不要改动无关句意。")
    if "core_term_inconsistent" in issue_types:
        parts.append("核心术语不一致时必须使用 Issue 中 expected 指定的译法，并统一同一源术语。")
    parts.append("")
    parts.append("待修复字幕:")
    for item in items:
        block_id = item.get("id")
        parts.append(json.dumps(item, ensure_ascii=False))
        for issue in by_id.get(block_id, []):
            parts.append(f"  Issue: {issue.type} - {issue.message}")
    return "\n".join(parts)
