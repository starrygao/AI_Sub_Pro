"""Tests for SubtitleTrack dataclass and ffmpeg filter chain builder."""


def test_subtitle_track_defaults():
    from app.utils.media import SubtitleTrack
    t = SubtitleTrack(path="/tmp/foo.srt")
    assert t.path == "/tmp/foo.srt"
    assert t.font_name == "Helvetica"
    assert t.font_size == 20
    assert t.primary_color == "&H00FFFFFF"
    assert t.outline_color == "&H00000000"
    assert t.outline_width == 1.5
    assert t.margin_v == 30
    assert t.alignment == 2


def test_subtitle_track_custom_values():
    from app.utils.media import SubtitleTrack
    t = SubtitleTrack(path="/a/b/zh.srt", font_name="PingFang SC", font_size=28, margin_v=70, outline_width=2.0)
    assert t.font_name == "PingFang SC"
    assert t.font_size == 28
    assert t.margin_v == 70
    assert t.outline_width == 2.0


def test_build_filter_chain_single_track():
    from app.utils.media import SubtitleTrack, build_filter_chain
    track = SubtitleTrack(path="/tmp/zh.srt", font_name="PingFang SC", font_size=28, margin_v=70, outline_width=2.0)
    out = build_filter_chain([track])
    assert "subtitles='/tmp/zh.srt'" in out
    assert "FontName=PingFang SC" in out
    assert "FontSize=28" in out
    assert "MarginV=70" in out
    assert "Outline=2.0" in out


def test_build_filter_chain_two_tracks_are_comma_joined():
    from app.utils.media import SubtitleTrack, build_filter_chain
    tracks = [
        SubtitleTrack(path="/tmp/zh.srt", font_name="PingFang SC", font_size=28, margin_v=70),
        SubtitleTrack(path="/tmp/en.srt", font_name="Helvetica", font_size=20, margin_v=30),
    ]
    out = build_filter_chain(tracks)
    assert out.count("subtitles=") == 2
    parts = out.split("subtitles=")
    assert "zh.srt" in parts[1]
    assert "en.srt" in parts[2]


def test_escape_ffmpeg_filter_path_handles_spaces_and_colons():
    from app.utils.media import _escape_ffmpeg_filter_path
    # Plain POSIX path (no colons) — unchanged
    assert _escape_ffmpeg_filter_path("/tmp/foo bar.srt") == "/tmp/foo bar.srt"
    # Colon in POSIX → escaped
    assert _escape_ffmpeg_filter_path("/tmp/a:b.srt") == "/tmp/a\\:b.srt"
    # Windows path: backslashes normalize to forward slash, drive-colon escaped
    assert _escape_ffmpeg_filter_path(r"C:\Users\foo\x.srt") == "C\\:/Users/foo/x.srt"
