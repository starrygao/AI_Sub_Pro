import copy

import pytest

from tests.test_project_export import _strict_quality_report
from app.utils.translation_quality_gate import validate_quality_report


def test_complete_translation_with_review_items_is_deliverable():
    from app.utils.translation_quality_gate import apply_advisory_delivery_policy
    report = _strict_quality_report('needs_review')
    original_issues = copy.deepcopy(report['issues'])
    apply_advisory_delivery_policy(report)
    result = validate_quality_report(report)
    assert result.valid and result.passed
    assert report['summary']['quality_gate']['verdict'] == 'passed_with_warnings'
    assert report['summary']['quality_gate']['review_recommended'] is True
    assert report['issues'] == original_issues
    assert '无需先审核' in result.message


def test_remaining_semantic_errors_are_delivered_with_explicit_warning():
    from app.utils.translation_quality_gate import apply_advisory_delivery_policy
    report = _strict_quality_report('failed')
    original_issues = copy.deepcopy(report['issues'])
    apply_advisory_delivery_policy(report)
    result = validate_quality_report(report)
    assert result.valid and result.passed
    assert '1 项错误' in result.message
    assert '质量报告' in result.message
    assert report['issues'] == original_issues
    assert report['summary']['error_count'] == 1
    assert report['issues'][0]['severity'] == 'error'


@pytest.mark.parametrize('issue_type', ['missing_translation', 'duplicate_id', 'non_positive_duration'])
def test_advisory_delivery_does_not_hide_incomplete_or_invalid_subtitles(issue_type):
    from app.utils.translation_quality_gate import apply_advisory_delivery_policy
    report = _strict_quality_report('failed')
    report['issues'][0]['type'] = issue_type
    apply_advisory_delivery_policy(report)
    assert not validate_quality_report(report).passed


def test_advisory_delivery_keeps_identity_and_count_checks():
    from app.utils.translation_quality_gate import apply_advisory_delivery_policy
    report = _strict_quality_report('needs_review')
    apply_advisory_delivery_policy(report)
    assert not validate_quality_report(report, expected_content_hash='wrong').valid
    report['summary']['error_count'] = 40
    assert not validate_quality_report(report).valid


def test_new_delivery_policy_keeps_errors_advisory():
    from app.utils.translation_quality_gate import apply_advisory_delivery_policy
    report = _strict_quality_report('failed')
    apply_advisory_delivery_policy(report)
    assert report['summary']['quality_gate']['passed']
    assert report['summary']['quality_gate']['review_recommended'] is True
    assert report['summary']['quality_gate']['delivery_policy_version'] == 3
    assert validate_quality_report(report).valid


def test_previously_delivered_advisory_certificate_remains_readable():
    report = _strict_quality_report('failed')
    report['status'] = 'ok'
    report['summary']['quality_gate'].update(verdict='passed_with_warnings', passed=True,
        delivery_mode='unattended_with_warnings', requires_human_review=False,
        review_recommended=True, next_action='deliver')
    assert validate_quality_report(report).valid
    assert validate_quality_report(report).passed


def test_versioned_report_cannot_claim_advisory_pass_with_confirmed_mismatch():
    report = _strict_quality_report('failed')
    report['status'] = 'ok'
    report['summary']['quality_gate'].update(verdict='passed_with_warnings', passed=True,
        delivery_mode='unattended_with_warnings', requires_human_review=False,
        review_recommended=True, next_action='deliver', delivery_policy_version=2)
    assert not validate_quality_report(report).valid
