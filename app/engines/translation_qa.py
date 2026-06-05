"""Deterministic subtitle translation QA and repair prompt helpers."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from app.evaluation.metrics import proper_name_consistency_score
from app.engines.kb_models import ProjectKb
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


def _is_chinese_target(target_language: str) -> bool:
    text = _clean_text(target_language).lower()
    return text in {
        "简体中文",
        "繁体中文",
        "繁體中文",
        "中文",
        "zh",
        "zh-cn",
        "zh-tw",
        "zh-hant",
        "chs",
        "cht",
        "zho",
        "cmn",
    }


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


def run_quality_checks(
    blocks: Iterable,
    *,
    project_kb: Optional[ProjectKb] = None,
    target_language: str = "简体中文",
    max_chars: int = 32,
    trace: Optional[dict] = None,
) -> TranslationQaReport:
    issues: list[QualityIssue] = []
    seen_ids = set()
    kb_terms = _kb_terms(project_kb)
    chinese_target = _is_chinese_target(target_language)
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

        if chinese_target and translation and _ENGLISH_RE.search(translation):
            issues.append(QualityIssue(
                type="english_residue",
                severity="warning",
                block_id=block_id if isinstance(block_id, int) else None,
                message="target subtitle still contains English text",
                source_text=source,
                translation=translation,
            ))

        compact_translation = re.sub(r"\s+", "", translation)
        if max_chars > 0 and len(compact_translation) > max_chars:
            issues.append(QualityIssue(
                type="line_too_long",
                severity="warning",
                block_id=block_id if isinstance(block_id, int) else None,
                message=f"translation length {len(compact_translation)} exceeds {max_chars}",
                source_text=source,
                translation=translation,
                expected=str(max_chars),
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
    parts.append("")
    parts.append("待修复字幕:")
    for item in items:
        block_id = item.get("id")
        parts.append(json.dumps(item, ensure_ascii=False))
        for issue in by_id.get(block_id, []):
            parts.append(f"  Issue: {issue.type} - {issue.message}")
    return "\n".join(parts)
