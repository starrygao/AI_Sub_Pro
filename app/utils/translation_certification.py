"""Authoritative validation for certified translation delivery artifacts."""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Optional

from app.utils.subtitle_generation import (
    subtitle_source_generation_snapshot,
)
from app.utils.translation_delivery import translation_delivery_is_invalid
from app.utils.translation_quality_gate import validate_quality_report
from app.utils.translation_configuration import translation_configuration_hash
from app.config import Config


_DELIVERY_ARTIFACTS = ("translated.srt", "bilingual.srt")


@dataclass(frozen=True)
class TranslationDeliveryValidation:
    expects_certification: bool
    valid: bool
    passed: bool
    message: str
    report: Optional[dict] = None
    source_artifact_name: str = ""
    source_artifact_bytes: Optional[bytes] = None
    delivery_artifact_bytes: dict[str, bytes] = field(default_factory=dict)


def project_expects_translation_certification(
    project: dict,
    project_path: Path,
) -> bool:
    report_path = Path(project_path) / "translation_qa_report.json"
    policy = project.get("translation_quality_policy")
    status = project.get("translation_quality_status")
    run_id = project.get("translation_quality_run_id")
    content_hash = project.get("translation_quality_content_hash")
    return (
        policy == "strict"
        or report_path.is_file()
        or isinstance(status, str) and bool(status.strip())
        or isinstance(run_id, str) and bool(run_id.strip())
        or isinstance(content_hash, str) and bool(content_hash.strip())
    )


def validate_translation_delivery(
    project: dict,
    project_path: Path,
    *,
    require_passed: bool = True,
) -> TranslationDeliveryValidation:
    """Validate one persisted QA certificate and its complete delivery set.

    Callers must hold the project's translation-delivery lock while using the
    result and consuming any certified artifacts.
    """
    project_path = Path(project_path)
    expects = project_expects_translation_certification(project, project_path)
    if translation_delivery_is_invalid(project_path):
        return TranslationDeliveryValidation(
            expects,
            False,
            False,
            "Translation delivery is incomplete; 翻译交付未完成，字幕文件暂不可用",
        )
    if not expects:
        return TranslationDeliveryValidation(False, True, False, "")

    policy = project.get("translation_quality_policy")
    quality_status = project.get("translation_quality_status")
    run_id = project.get("translation_quality_run_id")
    content_hash = project.get("translation_quality_content_hash")
    if (
        policy not in {"fast", "strict"}
        or quality_status not in {"passed", "failed", "needs_review"}
        or not isinstance(run_id, str)
        or not run_id.strip()
        or not isinstance(content_hash, str)
        or not content_hash.strip()
    ):
        return TranslationDeliveryValidation(
            True,
            False,
            False,
            "Translation quality certification identity is incomplete",
        )

    report_path = project_path / "translation_qa_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return TranslationDeliveryValidation(
            True,
            False,
            False,
            "Translation quality certification identity is unreadable",
        )
    decision = validate_quality_report(
        report,
        expected_run_id=run_id,
        expected_content_hash=content_hash,
        expected_policy=policy,
        expected_configuration_hash=project.get(
            "translation_quality_configuration_hash",
            "",
        ),
    )
    if not decision.valid:
        return TranslationDeliveryValidation(
            True, False, False, decision.message, report
        )

    report_verdict = report.get("summary", {}).get("quality_gate", {}).get("verdict")
    expected_status = {
        "passed": "passed",
        "passed_with_warnings": "passed",
        "failed": "failed",
        "needs_review": "needs_review",
    }.get(report_verdict)
    if quality_status != expected_status:
        return TranslationDeliveryValidation(
            True,
            False,
            False,
            "Translation quality certification status does not match its report",
            report,
        )
    project_source_hash = project.get(
        "translation_quality_source_generation_hash"
    )
    report_source_hash = report.get("source_generation_hash")
    (
        current_source_hash,
        source_artifact_name,
        source_artifact_bytes,
    ) = subtitle_source_generation_snapshot(project_path)
    if (
        not isinstance(project_source_hash, str)
        or not project_source_hash.strip()
        or not isinstance(report_source_hash, str)
        or not report_source_hash.strip()
        or not current_source_hash
        or report_source_hash != project_source_hash
        or current_source_hash != report_source_hash
    ):
        return TranslationDeliveryValidation(
            True,
            False,
            False,
            "Translation source generation identity does not match certification",
            report,
        )

    project_configuration_hash = project.get(
        "translation_quality_configuration_hash"
    )
    report_configuration_hash = report.get("configuration_hash")
    config = Config.to_dict()
    if (
        project.get('library_status') == 'done'
        and project.get('library_source_path')
        and project.get('library_delivery_run_id') == run_id
        and isinstance(project.get('library_delivery_config'), dict)
    ):
        config = project['library_delivery_config']
    current_configuration_hash = translation_configuration_hash(
        project,
        config=config,
        project_path=project_path,
    )
    if (
        not isinstance(project_configuration_hash, str)
        or not project_configuration_hash.strip()
        or not isinstance(report_configuration_hash, str)
        or not report_configuration_hash.strip()
        or report_configuration_hash != project_configuration_hash
        or current_configuration_hash != report_configuration_hash
    ):
        return TranslationDeliveryValidation(
            True,
            False,
            False,
            "Translation configuration identity does not match certification",
            report,
        )

    if require_passed and not decision.passed:
        return TranslationDeliveryValidation(
            True,
            False,
            False,
            f"Translation quality gate rejected delivery: {decision.message}",
            report,
        )

    if decision.passed:

        artifact_hashes = report.get("delivery_artifact_hashes")
        if not isinstance(artifact_hashes, dict):
            return TranslationDeliveryValidation(
                True,
                False,
                False,
                "Translation delivery artifact identity set is incomplete",
                report,
            )
        delivery_artifact_bytes = {}
        for artifact_name in _DELIVERY_ARTIFACTS:
            expected_hash = artifact_hashes.get(artifact_name)
            artifact_path = project_path / artifact_name
            artifact_bytes = (
                artifact_path.read_bytes()
                if artifact_path.is_file() and not artifact_path.is_symlink()
                else None
            )
            current_hash = (
                f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}"
                if artifact_bytes is not None
                else ""
            )
            if (
                not isinstance(expected_hash, str)
                or not expected_hash.strip()
                or current_hash != expected_hash
            ):
                return TranslationDeliveryValidation(
                    True,
                    False,
                    False,
                    "Translation delivery artifact identity does not match certification",
                    report,
                )
            delivery_artifact_bytes[artifact_name] = artifact_bytes

        return TranslationDeliveryValidation(
            True,
            True,
            decision.passed,
            decision.message,
            report,
            source_artifact_name,
            source_artifact_bytes,
            delivery_artifact_bytes,
        )

    return TranslationDeliveryValidation(
        True, True, decision.passed, decision.message, report
    )
