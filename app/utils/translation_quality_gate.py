"""Dependency-neutral validation for persisted translation quality certificates."""
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class TranslationQualityGateDecision:
    passed: bool
    message: str
    requires_human_review: bool = False
    valid: bool = True


def _invalid(message: str) -> TranslationQualityGateDecision:
    return TranslationQualityGateDecision(False, message, False, False)


def _valid_block_id_list(value) -> bool:
    return (
        isinstance(value, list)
        and all(
            isinstance(block_id, int)
            and not isinstance(block_id, bool)
            and block_id > 0
            for block_id in value
        )
        and len(value) == len(set(value))
    )


def _semantic_coverage_is_valid(trace: dict) -> bool:
    semantic = trace.get("semantic_qa")
    if not isinstance(semantic, dict):
        return False
    if semantic.get("enabled") is False:
        coverage_fields = {
            "requested_blocks",
            "checked_blocks",
            "failed_blocks",
            "skipped_blocks",
            "requested_block_ids",
            "checked_block_ids",
            "failed_block_ids",
            "skipped_block_ids",
            "coverage_complete",
        }
        return not any(field in semantic for field in coverage_fields)
    if semantic.get("enabled") is not True:
        return False

    count_to_ids = {
        "requested_blocks": "requested_block_ids",
        "checked_blocks": "checked_block_ids",
        "failed_blocks": "failed_block_ids",
        "skipped_blocks": "skipped_block_ids",
    }
    for count_field, ids_field in count_to_ids.items():
        count = semantic.get(count_field)
        ids = semantic.get(ids_field)
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            or not _valid_block_id_list(ids)
            or count != len(ids)
        ):
            return False

    requested = set(semantic["requested_block_ids"])
    checked = set(semantic["checked_block_ids"])
    failed = set(semantic["failed_block_ids"])
    skipped = set(semantic["skipped_block_ids"])
    if (
        checked & failed
        or checked & skipped
        or failed & skipped
        or requested != checked | failed | skipped
    ):
        return False
    expected_complete = not failed and not skipped and checked == requested
    return (
        isinstance(semantic.get("coverage_complete"), bool)
        and semantic["coverage_complete"] is expected_complete
    )


def validate_quality_report(
    report,
    *,
    expected_run_id: str = "",
    expected_content_hash: str = "",
    expected_policy: str = "",
    expected_configuration_hash: str = "",
) -> TranslationQualityGateDecision:
    if not isinstance(report, dict):
        return _invalid("翻译质量检查报告无效，已停止交付。")
    run_id = report.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return _invalid("翻译质量检查报告缺少运行身份，已停止交付。")
    if expected_run_id and run_id != expected_run_id:
        return _invalid("翻译质量检查报告已过期，已停止交付。")
    content_hash = report.get("content_hash")
    if not isinstance(content_hash, str) or not content_hash.strip():
        return _invalid("翻译质量检查报告缺少内容哈希，已停止交付。")
    if expected_content_hash and content_hash != expected_content_hash:
        return _invalid("翻译质量检查报告与当前字幕内容不匹配，已停止交付。")
    configuration_hash = report.get("configuration_hash")
    if expected_configuration_hash and (
        not isinstance(configuration_hash, str)
        or configuration_hash != expected_configuration_hash
    ):
        return _invalid(
            "翻译质量检查报告与当前翻译配置不匹配，已停止交付。"
        )

    issues = report.get("issues")
    summary = report.get("summary")
    unresolved_blocks = report.get("unresolved_blocks")
    trace = report.get("trace")
    observed_uncertain_ids = (
        trace.get("semantic_uncertain_observed_block_ids", [])
        if isinstance(trace, dict)
        else None
    )
    if (
        not isinstance(issues, list)
        or not isinstance(summary, dict)
        or not _valid_block_id_list(unresolved_blocks)
        or not isinstance(trace, dict)
        or not _valid_block_id_list(observed_uncertain_ids)
        or not _semantic_coverage_is_valid(trace)
    ):
        return _invalid("翻译质量检查报告无效或自相矛盾，已停止交付。")

    required_issue_fields = {
        "type",
        "severity",
        "block_id",
        "message",
        "source_text",
        "translation",
        "expected",
    }
    if any(
        not isinstance(issue, dict)
        or not required_issue_fields.issubset(issue)
        or not isinstance(issue.get("type"), str)
        or not issue["type"].strip()
        or issue.get("severity") not in {"warning", "error", "severe"}
        or not isinstance(issue.get("message"), str)
        or not issue["message"].strip()
        or not isinstance(issue.get("source_text"), str)
        or not isinstance(issue.get("translation"), str)
        or not isinstance(issue.get("expected"), str)
        or (
            issue.get("block_id") is not None
            and (
                not isinstance(issue.get("block_id"), int)
                or isinstance(issue.get("block_id"), bool)
                or issue["block_id"] <= 0
            )
        )
        for issue in issues
    ):
        return _invalid("翻译质量检查报告无效或自相矛盾，已停止交付。")

    gate = summary.get("quality_gate")
    if not isinstance(gate, dict):
        return _invalid("翻译质量检查报告无效或自相矛盾，已停止交付。")
    status = report.get("status")
    policy = gate.get("policy")
    verdict = gate.get("verdict")
    passed = gate.get("passed")
    requires_human_review = gate.get("requires_human_review")
    delivery_mode = gate.get("delivery_mode")
    next_action = gate.get("next_action")
    if (
        status not in {"ok", "failed", "needs_review"}
        or policy not in {"fast", "strict"}
        or verdict not in {"passed", "failed", "needs_review"}
        or not isinstance(passed, bool)
        or not isinstance(requires_human_review, bool)
    ):
        return _invalid("翻译质量检查报告无效或自相矛盾，已停止交付。")
    if expected_policy and policy != expected_policy:
        return _invalid("翻译质量检查报告策略不匹配，已停止交付。")
    if policy == "strict" and trace["semantic_qa"].get("enabled") is not True:
        return _invalid("翻译质量检查报告无效或自相矛盾，已停止交付。")

    if passed:
        gate_consistent = (
            status == "ok"
            and verdict == "passed"
            and requires_human_review is False
            and delivery_mode == "unattended"
            and next_action == "deliver"
        )
    elif requires_human_review:
        gate_consistent = (
            status == "needs_review"
            and verdict == "needs_review"
            and delivery_mode == "human_review"
            and next_action == "human_review"
        )
    else:
        gate_consistent = (
            status == "failed"
            and verdict == "failed"
            and delivery_mode == "unattended"
            and next_action == "auto_retry_or_stop"
        )

    actual_error_count = sum(
        1 for issue in issues if issue.get("severity") in {"error", "severe"}
    )
    actual_warning_count = sum(
        1 for issue in issues if issue.get("severity") == "warning"
    )
    counts_consistent = all(
        isinstance(summary.get(field), int)
        and not isinstance(summary.get(field), bool)
        and summary[field] == expected
        for field, expected in {
            "issue_count": len(issues),
            "error_count": actual_error_count,
            "warning_count": actual_warning_count,
            "unresolved_blocks": len(unresolved_blocks),
        }.items()
    )
    unresolved_consistent = (
        isinstance(gate.get("unresolved_blocks"), int)
        and not isinstance(gate.get("unresolved_blocks"), bool)
        and gate["unresolved_blocks"] == len(unresolved_blocks)
    )
    semantic_trace = trace["semantic_qa"]
    semantic_uncertainty_requires_review = (
        policy == "strict"
        and (
            bool(observed_uncertain_ids)
            or any(issue.get("type") == "semantic_uncertain" for issue in issues)
        )
    )
    incomplete_fast_semantics_requires_review = (
        policy == "fast"
        and semantic_trace.get("enabled") is True
        and semantic_trace.get("coverage_complete") is False
    )
    review_classification_consistent = (
        not semantic_uncertainty_requires_review
        or requires_human_review is True
    ) and (
        not incomplete_fast_semantics_requires_review
        or requires_human_review is True
    )
    coverage_allows_delivery = (
        semantic_trace.get("enabled") is False
        or semantic_trace.get("coverage_complete") is True
        or passed is False
    )
    passed_issue_consistent = not passed or (
        actual_error_count == 0
        and not any(
            issue.get("type") in {"semantic_uncertain", "semantic_qa_failed"}
            for issue in issues
        )
    )
    if not (
        gate_consistent
        and counts_consistent
        and unresolved_consistent
        and review_classification_consistent
        and coverage_allows_delivery
        and passed_issue_consistent
    ):
        return _invalid("翻译质量检查报告无效或自相矛盾，已停止交付。")

    conclusion = summary.get("conclusion")
    if not isinstance(conclusion, str) or not conclusion.strip():
        return _invalid("翻译质量检查报告无效或自相矛盾，已停止交付。")
    if passed:
        return TranslationQualityGateDecision(True, conclusion.strip(), False)
    return TranslationQualityGateDecision(
        False,
        f"翻译质量未达标：{conclusion.strip()} 已停止交付。",
        requires_human_review,
    )


def load_quality_report_decision(
    report_path: Path | None,
    *,
    expected_run_id: str = "",
    expected_content_hash: str = "",
    expected_policy: str = "",
    expected_configuration_hash: str = "",
) -> TranslationQualityGateDecision:
    if report_path is None:
        return _invalid("翻译质量检查未生成报告，已停止交付。")
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _invalid("翻译质量检查未生成报告，已停止交付。")
    except Exception:
        return _invalid("翻译质量检查报告无效，已停止交付。")
    return validate_quality_report(
        report,
        expected_run_id=expected_run_id,
        expected_content_hash=expected_content_hash,
        expected_policy=expected_policy,
        expected_configuration_hash=expected_configuration_hash,
    )
