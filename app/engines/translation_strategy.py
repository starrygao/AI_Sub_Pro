"""Project-level translation strategy explanations."""
from __future__ import annotations

from typing import Any

from app.engines.content_profiles import ContentProfile, infer_content_profiles
from app.engines.project_metadata import (
    CONTENT_TYPE_LABELS,
    manual_term_pairs,
    normalize_project_metadata,
)


def _dict_section(config: dict, key: str) -> dict:
    value = config.get(key, {}) if isinstance(config, dict) else {}
    return value if isinstance(value, dict) else {}


def _bool_setting(section: dict, key: str, default: bool = False) -> bool:
    value = section.get(key) if isinstance(section, dict) else None
    return value if isinstance(value, bool) else default


def _choice_setting(section: dict, key: str, allowed: set[str], default: str) -> str:
    value = section.get(key) if isinstance(section, dict) else None
    if isinstance(value, str):
        cleaned = value.strip().casefold()
        if cleaned in allowed:
            return cleaned
    return default


def _int_setting(section: dict, key: str, default: int, *, min_value: int, max_value: int) -> int:
    value = section.get(key) if isinstance(section, dict) else None
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(min_value, min(max_value, parsed))


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _profile_to_dict(profile: ContentProfile) -> dict:
    return {
        "id": profile.id,
        "label": profile.label,
        "rules": list(profile.rules),
        "signals": list(profile.signals),
        "example_count": len(profile.examples),
    }


def _source_context(project: dict) -> dict:
    return {
        "title": _clean_text(project.get("source_title") or project.get("show_title") or project.get("name")),
        "uploader": _clean_text(project.get("source_uploader")),
        "channel": _clean_text(project.get("source_channel")),
        "source_language": _clean_text(project.get("source_language") or project.get("original_language")),
        "subtitle_source": _clean_text(project.get("subtitle_source")),
        "native_subtitle_language": _clean_text(project.get("native_subtitle_language")),
        "source_has_subtitles": bool(project.get("source_has_subtitles")),
    }


def _recommendations(
    *,
    project: dict,
    content_type: str,
    profiles: list[ContentProfile],
    manual_terms: list[tuple[str, str]],
    qa: dict,
    quality_mode: dict,
) -> list[dict]:
    recommendations: list[dict] = []
    if not quality_mode.get("professional"):
        recommendations.append({
            "id": "professional_mode_available",
            "severity": "info",
            "message": "当前为快速自动模式；专业辅助可自动生成知识库候选并启用质量报告。",
        })
    if content_type == "auto" and not profiles:
        recommendations.append({
            "id": "choose_content_type",
            "severity": "info",
            "message": "自动模式尚未识别明确场景；建议手动选择电影、剧集、访谈、学术或技术教程。",
        })
    if not manual_terms:
        recommendations.append({
            "id": "add_terms",
            "severity": "info",
            "message": "建议补充关键人名、机构、术语或固定译法，下一次翻译会作为高优先级约束。",
        })
    if bool(project.get("source_has_subtitles")) or _clean_text(project.get("native_subtitle_language")):
        recommendations.append({
            "id": "native_subtitles",
            "severity": "success",
            "message": "已检测到原生字幕上下文；翻译会优先利用字幕文本，减少 ASR 误差。",
        })
    if any(profile.id == "legal_adult" for profile in profiles):
        recommendations.append({
            "id": "legal_adult_scope",
            "severity": "warning",
            "message": "成人内容策略仅用于合法成年自愿语境；不会外溢到普通项目。",
        })
    if not qa.get("auto_repair"):
        recommendations.append({
            "id": "qa_auto_repair_optional",
            "severity": "info",
            "message": "翻译后自动修复未开启；仍会生成确定性质量报告，可在设置中开启窄范围修复。",
        })
    return recommendations


def _summary(profiles: list[ContentProfile], content_type_label: str, manual_terms_count: int) -> str:
    if profiles:
        labels = "、".join(profile.label for profile in profiles[:3])
        suffix = "等" if len(profiles) > 3 else ""
        return f"已启用 {len(profiles)} 个内容策略：{labels}{suffix}。"
    if manual_terms_count:
        return f"未命中特定内容策略，但会应用 {manual_terms_count} 条手动术语。"
    if content_type_label and content_type_label != "auto":
        return f"已记录项目内容类型：{content_type_label}。"
    return "尚未识别明确内容策略；可手动选择类型并补充术语。"


def _quality_mode_summary(translation_cfg: dict) -> dict:
    mode = _choice_setting(translation_cfg, "quality_mode", {"fast", "professional"}, "fast")
    professional = mode == "professional"
    requires_kb_review = _bool_setting(
        translation_cfg,
        "require_kb_suggestion_review",
        False,
    )
    if professional:
        return {
            "id": "professional",
            "label": "专业辅助",
            "professional": True,
            "requires_kb_review": requires_kb_review,
            "quality_gate": True,
            "summary": "自动使用已审定知识库、翻译记忆、短语库和质量报告；未审定候选只作为软提示，显式开启审校门槛时阻塞翻译。",
        }
    return {
        "id": "fast",
        "label": "快速自动",
        "professional": False,
        "requires_kb_review": requires_kb_review,
        "quality_gate": False,
        "summary": "自动生成知识库建议并继续翻译，适合快速产出可审校初稿。",
    }


def build_translation_strategy(project: dict, config: dict | None = None) -> dict:
    """Explain which translation aids will apply to one project.

    This is intentionally deterministic and model-free. The translator still
    owns the final prompt; this helper makes the same metadata visible to users
    and tests before they start a long translation job.
    """
    source_project = project if isinstance(project, dict) else {}
    meta = normalize_project_metadata(source_project)
    content_type = meta.get("content_type", "auto")
    content_type_label = CONTENT_TYPE_LABELS.get(content_type, content_type)
    profiles = infer_content_profiles({**source_project, **meta})
    manual_terms = manual_term_pairs(source_project)
    translation_cfg = _dict_section(config or {}, "translation")
    retrieval = {
        "translation_memory": _bool_setting(translation_cfg, "use_translation_memory", True),
        "phrase_library": _bool_setting(translation_cfg, "use_phrase_library", True),
        "max_memory_examples": _int_setting(
            translation_cfg,
            "max_memory_examples",
            6,
            min_value=0,
            max_value=20,
        ),
        "max_phrase_examples": _int_setting(
            translation_cfg,
            "max_phrase_examples",
            6,
            min_value=0,
            max_value=20,
        ),
    }
    qa = {
        "auto_repair": _bool_setting(translation_cfg, "qa_auto_repair", True),
        "auto_repair_rounds": _int_setting(
            translation_cfg,
            "qa_auto_repair_rounds",
            2,
            min_value=0,
            max_value=2,
        ),
    }
    quality_mode = _quality_mode_summary(translation_cfg)
    profile_dicts = [_profile_to_dict(profile) for profile in profiles]
    status = "ready" if profiles or manual_terms or content_type != "auto" else "needs_context"
    terms = [{"source": source, "target": target} for source, target in manual_terms]
    return {
        "project_id": _clean_text(source_project.get("id")),
        "status": status,
        "content_type": content_type,
        "content_type_label": content_type_label,
        "metadata_source": meta.get("metadata_source", ""),
        "academic_field": meta.get("academic_field", ""),
        "summary": _summary(profiles, content_type_label, len(terms)),
        "active_profiles": profile_dicts,
        "manual_terms": terms,
        "manual_terms_count": len(terms),
        "retrieval": retrieval,
        "qa": qa,
        "quality_mode": quality_mode,
        "source": _source_context(source_project),
        "recommendations": _recommendations(
            project=source_project,
            content_type=content_type,
            profiles=profiles,
            manual_terms=manual_terms,
            qa=qa,
            quality_mode=quality_mode,
        ),
    }
