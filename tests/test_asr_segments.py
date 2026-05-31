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
