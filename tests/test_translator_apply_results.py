"""_apply_results — id matching, positional fallback, error field."""
from datetime import timedelta

from app.utils.srt import SubtitleBlock


def _make_translator():
    from app.engines.translator import SubtitleTranslator
    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
        },
        "api_keys": {"openai": "sk-test"},
    }
    return SubtitleTranslator(cfg)


def _blk(index, text):
    return SubtitleBlock(index=index, start=timedelta(0), end=timedelta(seconds=1), text=text)


def test_apply_results_matches_by_id_regardless_of_order():
    t = _make_translator()
    blocks = [_blk(11, "a"), _blk(12, "b")]
    t._apply_results(blocks, [{"id": 12, "translation": "乙"}, {"id": 11, "translation": "甲"}])
    assert blocks[0].translation == "甲"
    assert blocks[1].translation == "乙"


def test_apply_results_positional_fallback_when_ids_renumbered():
    """Model renumbered ids 1,2 instead of echoing 11,12 — must fall back to
    positional mapping rather than dropping the whole batch."""
    t = _make_translator()
    blocks = [_blk(11, "a"), _blk(12, "b")]
    t._apply_results(blocks, [{"id": 1, "translation": "甲"}, {"id": 2, "translation": "乙"}])
    assert blocks[0].translation == "甲"
    assert blocks[1].translation == "乙"


def test_apply_results_no_fallback_on_count_mismatch():
    """If counts differ, positional fallback is unsafe — leave unmatched blocks alone."""
    t = _make_translator()
    blocks = [_blk(11, "a"), _blk(12, "b")]
    t._apply_results(blocks, [{"id": 99, "translation": "甲"}])
    assert blocks[0].translation == ""
    assert blocks[1].translation == ""


def test_apply_results_records_error_field():
    t = _make_translator()
    blocks = [_blk(1, "a")]
    t._apply_results(blocks, [{"id": 1, "translation": "", "error": "boom"}])
    assert blocks[0].translation == ""
    assert blocks[0].translation_error == "boom"


def test_apply_results_rejects_non_string_translation():
    t = _make_translator()
    blocks = [_blk(1, "a")]
    t._apply_results(blocks, [{"id": 1, "translation": {"text": "bad"}}])
    assert blocks[0].translation == ""
    assert blocks[0].translation_error == "invalid translation type: dict"


def test_apply_results_empty_translation_clears_stale_text():
    t = _make_translator()
    blocks = [_blk(1, "a")]
    blocks[0].translation = "old"
    blocks[0].translation_error = "old error"
    t._apply_results(blocks, [{"id": 1, "translation": "", "error": ""}])
    assert blocks[0].translation == ""
    assert blocks[0].translation_error == ""
