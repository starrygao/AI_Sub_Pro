"""Tests for filename → metadata extraction. Covers Chinese / English titles,
movie vs episode detection, year extraction, and graceful degradation when
guessit can't parse anything useful."""
import pytest


def test_chinese_movie_with_year():
    """The exact case the user hit: 爱情抓马 (2026) - 1080p.mkv must parse
    to {title=爱情抓马, year=2026, type=movie}."""
    from app.engines.file_metadata import parse_filename
    out = parse_filename("爱情抓马 (2026) - 1080p.mkv")
    assert out["title"] == "爱情抓马"
    assert out["year"] == 2026
    assert out["type"] == "movie"


def test_english_movie_dot_separated():
    from app.engines.file_metadata import parse_filename
    out = parse_filename("The.Drama.2026.1080p.WEB-DL.x264-FOO.mkv")
    assert out["title"] == "The Drama"
    assert out["year"] == 2026
    assert out["type"] == "movie"


def test_english_tv_episode():
    from app.engines.file_metadata import parse_filename
    out = parse_filename("Black.Mirror.S05E01.1080p.WEB.H264-NTb.mkv")
    assert out["title"] == "Black Mirror"
    assert out["type"] == "tv"
    assert out["season"] == 5
    assert out["episode"] == 1


def test_chinese_tv_episode():
    from app.engines.file_metadata import parse_filename
    out = parse_filename("黑袍纠察队.S05E04.1080p.mkv")
    assert out["title"] == "黑袍纠察队"
    assert out["type"] == "tv"
    assert out["season"] == 5
    assert out["episode"] == 4


def test_full_path_uses_basename_only():
    """Directory components must not bleed into the title — guessit only
    sees the basename."""
    from app.engines.file_metadata import parse_filename
    out = parse_filename(
        "/Users/foo/Movies/Random Folder Name/The.Drama.2026.1080p.mkv"
    )
    assert out["title"] == "The Drama"
    assert out["year"] == 2026


def test_movie_without_year_still_gets_title():
    """Best-effort: a title without a year is still useful for fuzzy
    TMDB search."""
    from app.engines.file_metadata import parse_filename
    out = parse_filename("Inception.mkv")
    assert out is not None
    assert out["title"] == "Inception"
    assert out["year"] is None
    assert out["type"] == "movie"


def test_empty_or_garbage_returns_none():
    from app.engines.file_metadata import parse_filename
    assert parse_filename("") is None
    assert parse_filename("   ") is None
    assert parse_filename(None) is None
    assert parse_filename(["Movie.2026.mkv"]) is None


def test_coerce_int_rejects_boolean_values():
    from app.engines.file_metadata import _coerce_int

    assert _coerce_int(True) is None
    assert _coerce_int([False]) is None
    assert _coerce_int(float("inf")) is None


def test_tv_keys_only_present_for_tv():
    from app.engines.file_metadata import parse_filename
    movie = parse_filename("Inception.2010.1080p.mkv")
    assert "season" not in movie
    assert "episode" not in movie
    tv = parse_filename("Severance.S02E08.1080p.WEB-DL.mkv")
    assert tv["season"] == 2
    assert tv["episode"] == 8
