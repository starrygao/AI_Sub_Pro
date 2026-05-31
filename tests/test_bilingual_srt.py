from datetime import timedelta

import pytest


def _make_block(idx, text, translation=""):
    from app.utils.srt import SubtitleBlock
    return SubtitleBlock(
        index=idx, start=timedelta(seconds=idx),
        end=timedelta(seconds=idx + 1), text=text, translation=translation,
    )


def test_write_mono_srt_translation_only(tmp_path):
    from app.utils.srt import write_mono_srt
    blocks = [_make_block(1, "Hello", "你好"), _make_block(2, "World", "世界")]
    out = tmp_path / "zh.srt"
    n = write_mono_srt(blocks, str(out), use_translation=True)
    assert n == 2
    text = out.read_text(encoding="utf-8")
    assert "你好" in text
    assert "世界" in text
    assert "Hello" not in text


def test_write_mono_srt_source_only(tmp_path):
    from app.utils.srt import write_mono_srt
    blocks = [_make_block(1, "Hello", "你好"), _make_block(2, "World", "世界")]
    out = tmp_path / "en.srt"
    n = write_mono_srt(blocks, str(out), use_translation=False)
    text = out.read_text(encoding="utf-8")
    assert "Hello" in text
    assert "World" in text
    assert "你好" not in text


def test_write_mono_srt_skips_filtered(tmp_path):
    from app.utils.srt import write_mono_srt
    b1 = _make_block(1, "keep", "保留")
    b2 = _make_block(2, "skip", "跳过")
    b2.filtered = True
    out = tmp_path / "zh.srt"
    n = write_mono_srt([b1, b2], str(out), use_translation=True)
    assert n == 1
    text = out.read_text(encoding="utf-8")
    assert "保留" in text
    assert "跳过" not in text


def test_write_mono_srt_skips_empty_translation(tmp_path):
    from app.utils.srt import write_mono_srt
    b1 = _make_block(1, "keep", "保留")
    b2 = _make_block(2, "no-trans", "")
    out = tmp_path / "zh.srt"
    n = write_mono_srt([b1, b2], str(out), use_translation=True)
    assert n == 1


def test_write_srt_translation_mode_skips_empty_translations(tmp_path):
    from app.utils.srt import write_srt
    blocks = [
        _make_block(1, "Hello", "你好"),
        _make_block(2, "World", ""),
        _make_block(3, "Again", "再来"),
    ]
    out = tmp_path / "translated.srt"

    write_srt(blocks, str(out), use_translation=True)

    text = out.read_text(encoding="utf-8")
    assert "你好" in text
    assert "再来" in text
    assert "World" not in text
    assert "\n3\n" not in text


def test_parse_srt_skips_non_positive_duration_blocks():
    from app.utils.srt import parse_srt

    blocks = parse_srt(
        "1\n00:00:02,000 --> 00:00:01,000\nbad\n\n"
        "2\n00:00:03,000 --> 00:00:03,000\nzero\n\n"
        "3\n00:00:04,000 --> 00:00:05,000\ngood\n"
    )

    assert [b.text for b in blocks] == ["good"]


def test_parse_srt_skips_out_of_range_time_fields():
    from app.utils.srt import parse_srt, parse_time, parse_time_strict

    blocks = parse_srt(
        "1\n00:99:00,000 --> 01:00:00,000\nbad minutes\n\n"
        "2\n00:00:60,000 --> 00:01:01,000\nbad seconds\n\n"
        "3\n00:00:00,000 --> 00:00:01,000\ngood\n"
    )

    assert [b.text for b in blocks] == ["good"]
    assert parse_time_strict("00:60:00,000") is None
    assert parse_time_strict("00:00:60,000") is None
    assert parse_time_strict("120:00:00,000") == timedelta(hours=120)
    assert parse_time_strict("999999999999999999999999999999:00:00,000") is None
    assert parse_time("00:60:00,000") == timedelta(0)


def test_srt_helpers_tolerate_malformed_inputs(tmp_path):
    from app.utils.srt import fmt_time, parse_srt, write_bilingual_srt, write_mono_srt, write_srt

    malformed = _make_block(1, 123, {"bad": "shape"})
    good = _make_block(2, "Hello", "你好")

    assert parse_srt(None) == []
    assert parse_srt(b"1\n00:00:00,000 --> 00:00:01,000\nHello\n")[0].text == "Hello"
    assert fmt_time({"bad": "shape"}) == "00:00:00,000"
    assert fmt_time(type("HugeTime", (), {"total_seconds": lambda self: 10**10000})()) == "00:00:00,000"

    mono_out = tmp_path / "mono.srt"
    assert write_mono_srt([malformed, good], str(mono_out), use_translation=True) == 1
    assert "你好" in mono_out.read_text(encoding="utf-8")

    translated_out = tmp_path / "translated.srt"
    write_srt([malformed, good], str(translated_out), use_translation=True)
    assert "你好" in translated_out.read_text(encoding="utf-8")

    bilingual_out = tmp_path / "bilingual.srt"
    write_bilingual_srt([malformed, good], str(bilingual_out))
    text = bilingual_out.read_text(encoding="utf-8")
    assert "Hello" in text
    assert "你好" in text
    assert "bad" not in text


def test_apply_offset_drops_blocks_collapsed_at_zero():
    from app.utils.srt import SubtitleBlock, apply_offset

    blocks = [
        SubtitleBlock(
            index=1,
            start=timedelta(milliseconds=100),
            end=timedelta(milliseconds=300),
            text="too early",
        ),
        SubtitleBlock(
            index=2,
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text="still visible",
        ),
    ]

    shifted = apply_offset(blocks, -500)

    assert [b.text for b in shifted] == ["still visible"]
    assert shifted[0].start == timedelta(milliseconds=500)
    assert shifted[0].end == timedelta(milliseconds=1500)


def test_compute_font_sizes_1080p():
    from app.utils.media import compute_font_sizes
    zh, en = compute_font_sizes(1080)
    assert zh >= 50
    assert en == int(zh * 0.7)


def test_compute_font_sizes_720p():
    from app.utils.media import compute_font_sizes
    zh, en = compute_font_sizes(720)
    assert 30 <= zh <= 50
    assert en == int(zh * 0.7)


def test_compute_font_sizes_min_floor():
    from app.utils.media import compute_font_sizes
    zh, en = compute_font_sizes(200)
    assert zh >= 18


@pytest.mark.parametrize("height", [
    None,
    "bad",
    float("inf"),
    pytest.param(10**10000, id="huge-int"),
    -720,
])
def test_compute_font_sizes_tolerates_malformed_heights(height):
    from app.utils.media import compute_font_sizes

    zh, en = compute_font_sizes(height)

    assert zh >= 18
    assert en >= 12
    assert zh <= 237


def test_resolve_font_zh_is_platform_appropriate():
    from app.utils.media import resolve_font
    import platform
    sys_ = platform.system()
    f = resolve_font("zh")
    if sys_ == "Darwin":
        assert f == "PingFang SC"
    elif sys_ == "Windows":
        assert f == "Microsoft YaHei"
    else:
        assert f == "DejaVu Sans"


def test_resolve_font_latin_default():
    from app.utils.media import resolve_font
    assert resolve_font("en") in ("Helvetica", "Arial", "DejaVu Sans")
    assert resolve_font("fr") in ("Helvetica", "Arial", "DejaVu Sans")
