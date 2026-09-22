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


def test_remaining_semantic_errors_are_preserved_in_advisory_delivery():
    from app.utils.translation_quality_gate import apply_advisory_delivery_policy
    report = _strict_quality_report('failed')
    apply_advisory_delivery_policy(report)
    assert validate_quality_report(report).passed
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
