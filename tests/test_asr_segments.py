def test_segments_to_blocks_skips_non_positive_duration():
    from app.engines.asr import _segments_to_blocks

    blocks = _segments_to_blocks([
        {"start": 1.0, "end": 1.0, "text": "zero"},
        {"start": 2.0, "end": 1.5, "text": "negative"},
        {"start": 3.0, "end": 4.0, "text": "valid"},
    ])

    assert len(blocks) == 1
    assert blocks[0].text == "valid"
    assert blocks[0].index == 1


def test_segments_to_blocks_skips_bad_numeric_times():
    from app.engines.asr import _segments_to_blocks

    blocks = _segments_to_blocks([
        {"start": "bad", "end": 2.0, "text": "bad start"},
        {"start": 1.0, "end": "bad", "text": "bad end"},
        {"start": 1.0, "end": 2.0, "text": "valid"},
    ])

    assert [b.text for b in blocks] == ["valid"]


def test_segments_to_blocks_skips_non_finite_times():
    from app.engines.asr import _segments_to_blocks

    blocks = _segments_to_blocks([
        {"start": "nan", "end": 2.0, "text": "bad start"},
        {"start": 1.0, "end": "inf", "text": "bad end"},
        {"start": 1.0, "end": 2.0, "text": "valid"},
    ])

    assert [b.text for b in blocks] == ["valid"]


def test_segments_to_blocks_skips_overflowing_and_negative_times():
    from app.engines.asr import _segments_to_blocks

    blocks = _segments_to_blocks([
        {"start": 10**10000, "end": 2.0, "text": "huge start"},
        {"start": 1e18, "end": 1e18 + 1, "text": "finite overflow"},
        {"start": -1.0, "end": 2.0, "text": "negative start"},
        {"start": 1.0, "end": 2.0, "text": "valid"},
    ])

    assert [b.text for b in blocks] == ["valid"]


def test_word_timing_removes_long_silence_and_splits_utterances():
    from app.engines.asr import _segments_to_blocks
    blocks = _segments_to_blocks([{'start': 848.57, 'end': 899.69,
        'text': 'もう姉さんったら 学校でも大変で', 'words': [
            {'start': 848.57, 'end': 850.1, 'word': 'もう姉さんったら'},
            {'start': 898.69, 'end': 899.69, 'word': ' 学校でも大変で'},
        ]}])
    assert [b.text for b in blocks] == ['もう姉さんったら', '学校でも大変で']
    assert blocks[0].end.total_seconds() == 850.1
    assert blocks[1].start.total_seconds() == 898.69


def test_incomplete_or_invalid_word_alignment_never_drops_text():
    from app.engines.asr import _segments_to_blocks
    for words in ([{'start': 1, 'end': 2, 'word': 'Hello'}],
                  [{'start': 1, 'end': float('nan'), 'word': 'Hello world'}],
                  [{'start': 1, 'end': 20, 'word': 'Hello world'}]):
        blocks = _segments_to_blocks([{'start': 1, 'end': 4, 'text': 'Hello world', 'words': words}])
        assert len(blocks) == 1 and blocks[0].text == 'Hello world'
        assert blocks[0].end.total_seconds() == 4
