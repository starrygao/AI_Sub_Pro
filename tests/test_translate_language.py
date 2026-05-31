class _Block:
    def __init__(self, text, filtered=False):
        self.text = text
        self.filtered = filtered


def test_explicit_language_is_used():
    from app.api.translate import _resolve_filter_language
    assert _resolve_filter_language(lang="zh", original_language=None, blocks=[]) == "zh"


def test_auto_with_original_language_wins():
    from app.api.translate import _resolve_filter_language
    assert _resolve_filter_language(lang="auto", original_language="en", blocks=[]) == "en"


def test_auto_without_original_detects_chinese_from_blocks():
    from app.api.translate import _resolve_filter_language
    blocks = [_Block("你好世界"), _Block("今天天气真好"), _Block("再见")]
    assert _resolve_filter_language(lang="auto", original_language=None, blocks=blocks) == "zh"


def test_auto_without_original_detects_english_from_blocks():
    from app.api.translate import _resolve_filter_language
    blocks = [_Block("hello world"), _Block("good morning everyone")]
    assert _resolve_filter_language(lang="auto", original_language=None, blocks=blocks) == "en"


def test_auto_no_signal_falls_back_to_ja():
    from app.api.translate import _resolve_filter_language
    assert _resolve_filter_language(lang="auto", original_language=None, blocks=[]) == "ja"
