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


def test_japanese_short_dialogue_and_names_are_not_filler():
    from app.utils.text import is_interjection
    for text in ('ミヤ', 'ママ', 'ママが', 'ママに', 'いいえ', 'まだまだ', 'しかし', 'はい'):
        assert not is_interjection(text, 'ja'), text


def test_distant_repeated_replies_remain_dialogue():
    from app.engines.filter import filter_subtitles
    blocks = [_block('ありがとうございます') for _ in range(3)]
    for index, block in enumerate(blocks):
        block.index = index + 1
        block.start = timedelta(seconds=index * 20)
        block.end = block.start + timedelta(seconds=2)
    filter_subtitles(blocks, language='ja')
    assert all(not block.filtered for block in blocks)


def test_separate_pairs_do_not_satisfy_local_repetition_threshold():
    from app.engines.filter import filter_subtitles
    blocks = [_block('Thank you very much') for _ in range(4)]
    for index, start in enumerate((0, 1, 20, 21)):
        blocks[index].index = index + 1
        blocks[index].start = timedelta(seconds=start)
        blocks[index].end = timedelta(seconds=start + 1)
    filter_subtitles(blocks, language='en')
    assert all(not block.filtered for block in blocks)


def test_short_text_merge_does_not_create_long_display_or_merge_overlap():
    from app.engines.filter import filter_subtitles
    for first_end, next_start, next_end in ((50, 50, 51), (7, 7, 9), (2, 1, 3)):
        a, b = _block('姉さん'), _block('学校で')
        a.end = timedelta(seconds=first_end)
        b.index = 2
        b.start, b.end = timedelta(seconds=next_start), timedelta(seconds=next_end)
        filter_subtitles([a, b], language='ja', filter_repetitive=False)
        assert not b.filtered
        assert a.text == '姉さん'
