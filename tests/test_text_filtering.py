from datetime import timedelta


def _block(text):
    from app.utils.srt import SubtitleBlock
    return SubtitleBlock(index=1, start=timedelta(0), end=timedelta(seconds=1), text=text)


def test_single_character_chinese_is_not_interjection():
    from app.utils.text import is_interjection

    assert is_interjection("我", "zh") is False
    assert is_interjection("是", "zh") is False


def test_single_letter_english_is_not_interjection():
    from app.utils.text import is_interjection

    assert is_interjection("I", "en") is False


def test_filter_subtitles_keeps_short_meaningful_chinese():
    from app.engines.filter import filter_subtitles

    blocks = [_block("我")]
    filter_subtitles(blocks, language="zh", filter_repetitive=False)

    assert blocks[0].filtered is False


def test_meaningful_short_words_are_not_interjections():
    from app.utils.text import is_interjection

    assert is_interjection("No", "en") is False
    assert is_interjection("yes", "en") is False
    assert is_interjection("だめ", "ja") is False
    assert is_interjection("やめて", "ja") is False


def test_pure_filler_sounds_still_filter():
    from app.utils.text import is_interjection

    assert is_interjection("uh", "en") is True
    assert is_interjection("あっ", "ja") is True
    assert is_interjection("アッ", "ja-JP") is True


def test_filter_subtitles_normalizes_dirty_filter_config():
    from app.engines.filter import filter_subtitles

    blocks = [_block("Repeat"), _block("Repeat"), _block("Repeat")]

    filter_subtitles(
        blocks,
        language=["bad"],
        filter_repetitive="yes",
        repetitive_threshold=float("inf"),
        filter_interjections="no",
    )

    assert blocks[0].filtered is False
    assert blocks[1].filtered is True
    assert blocks[1].filter_reason == "重复内容 (出现>=3次)"


def test_text_helpers_tolerate_non_string_inputs():
    from app.utils.text import clean_sdh, clean_for_translation, detect_language_hint, detect_repetitive, is_interjection

    assert clean_sdh({"bad": "shape"}) == ""
    assert clean_for_translation(["bad"]) == ""
    assert is_interjection({"bad": "shape"}, ["ja"]) is True
    assert detect_repetitive(["Repeat", None, " repeat "], threshold=2) == {"repeat"}
    assert detect_language_hint(["hello", None, {"bad": "shape"}]) == "en"
