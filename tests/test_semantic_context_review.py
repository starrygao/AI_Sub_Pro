from datetime import timedelta
from types import SimpleNamespace

from app.engines.translator import (
    SubtitleTranslator,
    _SUBTITLE_CONTEXT_TEXT_CHARS,
    _subtitle_context_window,
)
from app.services import translation_tasks as tasks
from app.utils.srt import SubtitleBlock


def _block(index, source, draft="", *, filtered=False):
    return SubtitleBlock(
        index=index,
        start=timedelta(seconds=index),
        end=timedelta(seconds=index + 1),
        text=source,
        translation=draft,
        filtered=filtered,
    )


def test_review_keeps_sound_evidence_without_promoting_it_to_targets():
    blocks = [
        _block(20, "[clinking]", filtered=True),
        _block(40, "Cheers!", "干杯！"),
        _block(80, "[gunshots]\nI got hit!", "我中枪了！"),
        _block(90, "Run!"),
        _block(99, "Visit this website", filtered=True),
    ]
    items = tasks._semantic_qa_requested_items(blocks)

    assert [item["id"] for item in items] == [40, 80]
    assert items[0]["preceding_context"] == [
        {"id": 20, "original": "[clinking]", "draft": ""}
    ]
    assert [row["id"] for row in items[0]["following_context"]] == [80, 90]
    assert items[1]["original"] == "I got hit!"
    assert items[1]["source_context"]["original"] == "[gunshots]\nI got hit!"
    assert blocks[0].filtered and blocks[0].translation == ""


def test_context_is_timeline_local_and_bounded_without_truncating_targets():
    large = "A" * (_SUBTITLE_CONTEXT_TEXT_CHARS + 200)
    blocks = [
        _block(index * 10, f"line {index}", f"第{index}句")
        for index in range(9)
    ]
    blocks[3].text = large
    blocks[3].translation = "字" * (_SUBTITLE_CONTEXT_TEXT_CHARS + 1)
    items = tasks._semantic_qa_requested_items(blocks)
    focus = items[4]

    assert [row["id"] for row in focus["preceding_context"]] == [10, 20, 30]
    assert [row["id"] for row in focus["following_context"]] == [50, 60, 70]
    excerpt = focus["preceding_context"][-1]
    assert excerpt["original"] == large[:_SUBTITLE_CONTEXT_TEXT_CHARS]
    assert excerpt["draft"] == "字" * _SUBTITLE_CONTEXT_TEXT_CHARS
    assert excerpt["original_truncated"] and excerpt["draft_truncated"]
    assert items[3]["original"] == large
    assert items[3]["draft"] == blocks[3].translation
    assert "preceding_context" not in excerpt


def test_batch_limit_does_not_remove_read_only_following_evidence():
    blocks = [
        _block(10, "Did she enter", "她参加了吗"),
        _block(11, "the contest?", "那个比赛？"),
        _block(12, "[applause]", filtered=True),
    ]
    selected = tasks._semantic_qa_items(
        blocks, {"translation": {"semantic_qa_max_blocks": 1}}
    )
    assert [item["id"] for item in selected] == [10]
    assert selected[0]["following_context"] == [
        {"id": 11, "original": "the contest?", "draft": "那个比赛？"},
        {"id": 12, "original": "[applause]", "draft": ""},
    ]


def test_targeted_group_preserves_raw_sound_evidence_and_read_only_scope():
    blocks = [
        _block(10, "[gunshots]", filtered=True),
        _block(11, "[groaning]\nI got hit", "我中枪了"),
        _block(12, "in the leg.", "伤在腿上。"),
        _block(13, "Stay down.", "趴下。"),
    ]
    items = tasks._targeted_semantic_items(
        blocks, {11, 12}, SimpleNamespace(issues=[]), [[11, 12]]
    )
    singles, groups = tasks._targeted_semantic_verification_units(items, {11, 12}, [[11, 12]])
    assert singles == []
    group = groups[0]
    assert group["group_ids"] == [11, 12]
    assert [row["id"] for row in group["group_context"]] == [10, 13]
    assert group["group_members"][0]["source_context"]["original"] == "[groaning]\nI got hit"
    assert group["group_members"][0]["original"] == "I got hit"
    assert [member["id"] for member in group["group_members"]] == [11, 12]


def test_full_document_avoids_redundant_context_but_batch_budget_includes_it():
    engine = SubtitleTranslator.__new__(SubtitleTranslator)
    engine.primary = SimpleNamespace(context_window_tokens=7000)
    engine.resume_existing = False
    blocks = [_block(index, "Please come back. " * 35) for index in range(10)]
    engine.context_window = 0
    assert engine._fits_full_doc(blocks)
    without_context = engine._fallback_batch_size(blocks)
    engine.context_window = 3
    assert engine._fits_full_doc(blocks)
    assert engine._fallback_batch_size(blocks) < without_context


def test_full_document_context_adds_only_omitted_sound_not_visible_dialogue():
    blocks = [
        _block(1, "To our new partnership."),
        _block(2, "[clinking]", filtered=True),
        _block(3, "Cheers!"),
        _block(4, "Come back tomorrow."),
    ]
    before, after = _subtitle_context_window(blocks, 2, sound_only=True)
    assert before == [{"id": 2, "original": "[clinking]", "draft": ""}]
    assert after == []


def test_zero_context_window_does_not_include_neighbor_ids():
    blocks = [_block(1, "The Doctor left."), _block(9, "He will return.")]
    assert _subtitle_context_window(blocks, 1, radius=0) == ([], [])


def test_translation_and_both_semantic_passes_use_independent_efforts(monkeypatch):
    import json
    from app.engines.providers.omp_cli import OmpCliProvider
    from app.engines.translation_qa import TranslationQaReport
    monkeypatch.setattr(OmpCliProvider, 'check_cli_available', staticmethod(lambda: True))
    monkeypatch.setattr(OmpCliProvider, 'check_logged_in', staticmethod(lambda model: True))

    def invoke(provider, items, prompt):
        if provider.effort == 'medium':
            return '[{"id": 502, "translation": "不。"}]'
        if provider.effort == 'xhigh' and provider.model == 'custom-provider/reviewer':
            return json.dumps([{
                'id': 502, 'translation': 'OK', 'verdict': 'OK', 'taxonomy': 'none',
                'source_evidence': 'No.', 'target_evidence': '不。',
            }], ensure_ascii=False)
        raise RuntimeError('wrong configured stage')

    monkeypatch.setattr(OmpCliProvider, '_invoke', invoke)
    config = {'translation': {
        'primary_provider': 'omp_cli', 'primary_model': 'custom-provider/translator', 'primary_effort': 'medium',
        'review_provider': 'omp_cli', 'review_model': 'custom-provider/reviewer', 'review_effort': 'xhigh',
        'quality_mode': 'professional', 'use_translation_memory': False, 'use_phrase_library': False,
    }}
    engine = SubtitleTranslator(config)
    blocks = engine.translate([_block(502, 'No.')])
    issues, trace = tasks._run_semantic_quality_checks(config, engine, blocks, '简体中文')
    assert not issues
    assert trace['coverage_complete']
    issues, verified, hashes, traces = tasks._run_targeted_semantic_verification(
        config, engine, blocks, '简体中文', {502}, TranslationQaReport(status='ok', issues=[]), [],
        strict_quality_gate=True,
    )
    assert not issues
    assert verified == {502}
    assert hashes == {502: tasks._semantic_block_content_hash(blocks[0])}
    assert len(traces) == 2 and all(item['coverage_complete'] for item in traces)


def test_missing_review_never_falls_back_to_working_primary():
    from unittest.mock import Mock
    from app.engines.translation_qa import TranslationQaReport
    primary = Mock()
    engine = SimpleNamespace(primary=primary)
    blocks = [_block(502, 'No.', '不。')]
    config = {'translation': {'quality_mode': 'professional'}}
    issues, trace = tasks._run_semantic_quality_checks(config, engine, blocks, '简体中文')
    assert [issue.type for issue in issues] == ['semantic_qa_failed']
    assert not trace['coverage_complete']
    issues, verified, hashes, traces = tasks._run_targeted_semantic_verification(
        config, engine, blocks, '简体中文', {502}, TranslationQaReport(status='ok', issues=[]), [],
        strict_quality_gate=True,
    )
    assert issues and all(issue.type == 'semantic_qa_failed' for issue in issues)
    assert verified == set() and hashes == {}
    primary.translate_batch.assert_not_called()


def test_review_initialization_failure_is_not_downgraded_to_primary(monkeypatch):
    import pytest
    from app.engines.providers.omp_cli import OmpCliProvider
    original = OmpCliProvider.__init__

    def initialize(provider, config):
        if config['model'] == 'custom-provider/broken-review':
            raise RuntimeError('review cannot initialize')
        original(provider, config)

    monkeypatch.setattr(OmpCliProvider, '__init__', initialize)
    with pytest.raises(RuntimeError, match='review cannot initialize'):
        SubtitleTranslator({'translation': {
            'primary_provider': 'omp_cli', 'primary_model': 'custom-provider/working-primary',
            'review_provider': 'omp_cli', 'review_model': 'custom-provider/broken-review',
        }})
