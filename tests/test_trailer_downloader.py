import pytest


def test_validate_youtube_url_accepts_youtube_com():
    from app.engines.trailer_downloader import _validate_youtube_url
    _validate_youtube_url("https://www.youtube.com/watch?v=abc")  # no raise


def test_validate_youtube_url_accepts_youtu_be():
    from app.engines.trailer_downloader import _validate_youtube_url
    _validate_youtube_url("https://youtu.be/abc")


def test_validate_youtube_url_rejects_other_domain():
    from app.engines.trailer_downloader import _validate_youtube_url
    with pytest.raises(ValueError, match="not a YouTube"):
        _validate_youtube_url("https://evil.example.com/abc")


def test_validate_youtube_url_rejects_non_http_scheme():
    from app.engines.trailer_downloader import _validate_youtube_url
    with pytest.raises(ValueError, match="http or https"):
        _validate_youtube_url("ftp://www.youtube.com/watch?v=abc")


def test_validate_youtube_url_rejects_non_string_value():
    from app.engines.trailer_downloader import _validate_youtube_url
    with pytest.raises(ValueError, match="non-empty string"):
        _validate_youtube_url(["https://youtu.be/abc"])


def test_validate_download_url_accepts_direct_video_file_url():
    from app.engines.trailer_downloader import _validate_download_url

    _validate_download_url("https://cdn.example.com/trailers/movie-preview.mp4?token=abc")


def test_validate_download_url_rejects_generic_web_page_url():
    from app.engines.trailer_downloader import _validate_download_url

    with pytest.raises(ValueError, match="YouTube link or direct video file URL"):
        _validate_download_url("https://example.com/watch/123")


def test_build_youtube_url_accepts_valid_key():
    from app.engines.trailer_downloader import build_youtube_url
    assert build_youtube_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_build_youtube_url_rejects_bad_key():
    from app.engines.trailer_downloader import build_youtube_url
    with pytest.raises(ValueError):
        build_youtube_url("not a key")
    with pytest.raises(ValueError):
        build_youtube_url(["dQw4w9WgXcQ"])


def test_download_progress_percent_tolerates_overflowing_numbers():
    from app.engines.trailer_downloader import _download_progress_percent

    assert _download_progress_percent(10**10000, 10**10000) == 0


def test_download_trailer_calls_ytdlp_with_expected_options(monkeypatch, tmp_path):
    from app.engines import trailer_downloader as td

    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def download(self, urls):
            captured["urls"] = urls
            out = tmp_path / "trailer.mp4"
            out.write_bytes(b"fake mp4")
            return 0

    monkeypatch.setattr(td.yt_dlp, "YoutubeDL", FakeYDL)

    out = td.download_trailer("https://www.youtube.com/watch?v=abc123", str(tmp_path / "trailer.mp4"))
    assert out.endswith("trailer.mp4")
    assert captured["urls"] == ["https://www.youtube.com/watch?v=abc123"]
    assert "format" in captured["opts"]
    assert captured["opts"]["outtmpl"] == str(tmp_path / "trailer.mp4")
    assert "1080" in captured["opts"]["format"] or "mp4" in captured["opts"]["format"]


def test_download_progress_hook_tolerates_malformed_numbers(monkeypatch, tmp_path):
    from app.engines import trailer_downloader as td

    captured = {}
    progress = []

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def download(self, urls):
            hook = captured["opts"]["progress_hooks"][0]
            hook({"status": "downloading", "downloaded_bytes": "bad", "total_bytes": "also-bad"})
            hook({"status": "downloading", "downloaded_bytes": 200, "total_bytes": 100})
            out = tmp_path / "trailer.mp4"
            out.write_bytes(b"fake mp4")
            return 0

    monkeypatch.setattr(td.yt_dlp, "YoutubeDL", FakeYDL)

    td.download_trailer(
        "https://www.youtube.com/watch?v=abc123",
        str(tmp_path / "trailer.mp4"),
        progress_callback=lambda pct, msg: progress.append((pct, msg)),
    )

    assert progress == [(0, "downloading"), (100, "downloading")]


def test_download_trailer_rejects_missing_output_after_ytdlp(monkeypatch, tmp_path):
    from app.engines import trailer_downloader as td

    class FakeYDL:
        def __init__(self, opts):
            pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def download(self, urls):
            return 0

    monkeypatch.setattr(td.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(td, "_detect_browser_for_cookies", lambda: None)

    with pytest.raises(RuntimeError, match="output file"):
        td.download_trailer("https://www.youtube.com/watch?v=abc123", str(tmp_path / "trailer.mp4"))


def test_download_trailer_rejects_non_youtube_url(tmp_path):
    from app.engines import trailer_downloader as td
    with pytest.raises(ValueError):
        td.download_trailer("https://vimeo.com/123", str(tmp_path / "out.mp4"))


def test_download_trailer_accepts_direct_video_file_url(monkeypatch, tmp_path):
    from app.engines import trailer_downloader as td

    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def download(self, urls):
            captured["urls"] = urls
            out = tmp_path / "direct.mp4"
            out.write_bytes(b"fake mp4")
            return 0

    monkeypatch.setattr(td.yt_dlp, "YoutubeDL", FakeYDL)

    out = td.download_trailer(
        "https://cdn.example.com/videos/direct.mp4",
        str(tmp_path / "direct.mp4"),
    )

    assert out.endswith("direct.mp4")
    assert captured["urls"] == ["https://cdn.example.com/videos/direct.mp4"]


def test_probe_video_info_uses_ytdlp_without_download_and_normalizes_metadata(monkeypatch):
    from app.engines import trailer_downloader as td

    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def extract_info(self, url, download=False):
            captured["url"] = url
            captured["download"] = download
            return {
                "title": "Lecture 1: Neural Networks",
                "uploader": "Course Channel",
                "channel": "Academic Videos",
                "duration": 3661.7,
                "language": "en",
                "webpage_url": "https://www.youtube.com/watch?v=abc123def45",
                "extractor_key": "Youtube",
                "description": "x" * 700,
                "subtitles": {
                    "en": [{"ext": "vtt"}],
                    "ja": [{"ext": "srt"}],
                },
                "automatic_captions": {
                    "ko": [{"ext": "vtt"}],
                },
            }

    monkeypatch.setattr(td.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(td, "_detect_browser_for_cookies", lambda: None)

    info = td.probe_video_info("https://www.youtube.com/watch?v=abc123def45")

    assert captured["url"] == "https://www.youtube.com/watch?v=abc123def45"
    assert captured["download"] is False
    assert captured["opts"]["skip_download"] is True
    assert info["title"] == "Lecture 1: Neural Networks"
    assert info["uploader"] == "Course Channel"
    assert info["channel"] == "Academic Videos"
    assert info["duration"] == 3661.7
    assert info["language"] == "en"
    assert info["source_type"] == "youtube"
    assert info["subtitle_languages"] == ["en", "ja"]
    assert info["automatic_caption_languages"] == ["ko"]
    assert info["has_subtitles"] is True
    assert len(info["description"]) <= 500
