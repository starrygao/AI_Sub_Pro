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
        _make_block(4, "That car,", "那辆车，"),
    ]
    out = tmp_path / "translated.srt"

    write_srt(blocks, str(out), use_translation=True)

    text = out.read_text(encoding="utf-8")
    assert "你好" in text
    assert "再来" in text
    assert "那辆车，" in text
    assert "World" not in text
    assert "\n4\n" not in text


def test_translated_srt_collapses_short_translation_line_breaks(tmp_path):
    from app.utils.srt import write_mono_srt, write_srt

    blocks = [
        _make_block(1, "Short line", "我们现在就走\n别再回头"),
        _make_block(2, "English residue", "API\nreturns data"),
    ]
    translated = tmp_path / "translated.srt"
    mono = tmp_path / "mono.srt"

    write_srt(blocks, str(translated), use_translation=True)
    n = write_mono_srt(blocks, str(mono), use_translation=True)

    assert n == 2
    translated_text = translated.read_text(encoding="utf-8")
    mono_text = mono.read_text(encoding="utf-8")
    assert "我们现在就走别再回头" in translated_text
    assert "API returns data" in translated_text
    assert "我们现在就走\n别再回头" not in translated_text
    assert "我们现在就走别再回头" in mono_text


def test_translated_srt_collapses_short_structural_dialogue_line_breaks(tmp_path):
    from app.utils.srt import write_srt

    blocks = [
        _make_block(1, "Two speakers", "- 你看见了吗？\n- 看见了。"),
        _make_block(2, "Speaker labels", "玛丽：你来了？\n约翰：刚到。"),
        _make_block(3, "Long cue", "这是一条非常非常非常非常长的字幕\n它本来就不适合强行压成单行观看"),
    ]
    out = tmp_path / "translated.srt"

    write_srt(blocks, str(out), use_translation=True)

    text = out.read_text(encoding="utf-8")
    assert "- 你看见了吗？- 看见了。" in text
    assert "玛丽：你来了？约翰：刚到。" in text
    assert "这是一条非常非常非常非常长的字幕\n它本来就不适合强行压成单行观看" in text


def test_bilingual_srt_collapses_translation_only(tmp_path):
    from app.utils.srt import write_bilingual_srt

    blocks = [
        _make_block(1, "First source line\nSecond source line", "第一句译文\n第二句译文"),
    ]
    out = tmp_path / "bilingual.srt"

    write_bilingual_srt(blocks, str(out))

    text = out.read_text(encoding="utf-8")
    assert "第一句译文第二句译文\nFirst source line\nSecond source line" in text


def test_srt_writers_strip_music_decoration_symbols(tmp_path):
    from app.utils.srt import write_bilingual_srt, write_srt

    blocks = [
        _make_block(1, "- ♪ - [dialogue inaudible]", "♪\n[对话听不清]"),
        _make_block(2, "I love you", "🎵 爱不会迷路 🎶"),
    ]
    translated = tmp_path / "translated.srt"
    bilingual = tmp_path / "bilingual.srt"

    write_srt(blocks, str(translated), use_translation=True)
    write_bilingual_srt(blocks, str(bilingual))

    translated_text = translated.read_text(encoding="utf-8")
    bilingual_text = bilingual.read_text(encoding="utf-8")
    for symbol in "♪♫♬🎵🎶":
        assert symbol not in translated_text
        assert symbol not in bilingual_text
    assert "[对话听不清]" not in translated_text
    assert "爱不会迷路" in translated_text
    assert "[dialogue inaudible]" not in bilingual_text


def test_parse_srt_skips_non_positive_duration_blocks():
    from app.utils.srt import parse_srt

    blocks = parse_srt(
        "1\n00:00:02,000 --> 00:00:01,000\nbad\n\n"
        "2\n00:00:03,000 --> 00:00:03,000\nzero\n\n"
        "3\n00:00:04,000 --> 00:00:05,000\ngood\n"
    )

    assert [b.text for b in blocks] == ["good"]


def test_parse_srt_preserves_cue_line_breaks():
    from app.utils.srt import parse_srt

    blocks = parse_srt(
        "1\n"
        "00:00:00,000 --> 00:00:02,000\n"
        "第一行\n"
        "第二行\n"
    )

    assert blocks[0].text == "第一行\n第二行"


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


def test_fmt_time_rounds_milliseconds_without_truncating_float_artifacts():
    from app.utils.srt import SubtitleBlock, fmt_time, parse_time

    start = parse_time("00:04:17,758")
    end = parse_time("00:04:21,328")

    assert fmt_time(start) == "00:04:17,758"
    assert SubtitleBlock(index=1, start=start, end=end, text="Hello").to_dict()["start_ms"] == 257758


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


def test_parse_vtt_accepts_header_cue_ids_and_settings():
    from app.utils.srt import parse_vtt

    blocks = parse_vtt(
        """WEBVTT

intro
00:00:01.000 --> 00:00:02.500 align:start position:0%
Hello world

00:02.750 --> 00:03.000
Second cue

note1
00:00:04.000 --> 00:00:05.000
Cue id that begins with note
"""
    )

    assert len(blocks) == 3
    assert blocks[0].index == 1
    assert blocks[0].text == "Hello world"
    assert blocks[0].start.total_seconds() == 1
    assert blocks[0].end.total_seconds() == 2.5
    assert blocks[1].index == 2
    assert blocks[1].start.total_seconds() == 2.75
    assert blocks[2].text == "Cue id that begins with note"


def test_srt_to_vtt_preserves_multiline_text_and_uses_dot_milliseconds():
    from app.utils.srt import srt_to_vtt

    content = srt_to_vtt(
        "1\n"
        "00:00:01,000 --> 00:00:02,500\n"
        "你好\n"
        "Hello\n\n"
    )

    assert content.startswith("WEBVTT\n\n")
    assert "1\n" not in content
    assert "00:00:01.000 --> 00:00:02.500" in content
    assert "你好\nHello" in content


def test_parse_ass_accepts_format_dialogues_tags_and_commas():
    from app.utils.srt import parse_ass

    blocks = parse_ass(
        """[Script Info]
Title: Demo

[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,Arial,20

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.23,0:00:03.45,Default,,0,0,0,,{\\an8}Hello\\Nworld
Dialogue: 0,0:00:04.00,0:00:04.00,Default,,0,0,0,,zero duration
Dialogue: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,A line, with comma
"""
    )

    assert len(blocks) == 2
    assert blocks[0].index == 1
    assert blocks[0].text == "Hello world"
    assert blocks[0].start.total_seconds() == 1.23
    assert blocks[0].end.total_seconds() == 3.45
    assert blocks[1].text == "A line, with comma"


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
