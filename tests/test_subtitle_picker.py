"""Tests for _pick_subtitle_track: lang-priority subtitle picker that decides
which embedded track will bypass ASR."""
import pytest


def _track(codec, lang="und", title=""):
    return {"index": 0, "codec": codec, "lang": lang, "title": title,
            "channels": 0, "sample_rate": ""}


def test_no_subtitles_returns_none():
    from app.api.projects import _pick_subtitle_track
    assert _pick_subtitle_track([], "简体中文") is None


def test_only_image_codecs_returns_none():
    """PGS/DVD bitmap subtitles can't be transcoded to SRT — must return
    None so the pipeline falls back to ASR."""
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("hdmv_pgs_subtitle", "eng"),
        _track("dvd_subtitle", "chi"),
    ]
    assert _pick_subtitle_track(tracks, "简体中文") is None


def test_prefers_english_when_present():
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("subrip", "fra"),
        _track("subrip", "eng"),
        _track("subrip", "spa"),
    ]
    assert _pick_subtitle_track(tracks, "简体中文") == 1


def test_does_not_prefer_english_when_english_is_target_language():
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("subrip", "eng"),
        _track("subrip", "chi"),
    ]

    assert _pick_subtitle_track(tracks, "English") == 1


def test_skips_target_language_when_other_available():
    """If user is translating TO 简体中文, don't pick a Chinese subtitle —
    pick the source-language one to translate from."""
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("subrip", "chi"),  # target language
        _track("subrip", "fra"),  # source candidate
    ]
    assert _pick_subtitle_track(tracks, "简体中文") == 1


@pytest.mark.parametrize("target_language,target_lang_code", [
    ("繁体中文", "cht"),
    ("Japanese", "jpn"),
])
def test_skips_target_language_aliases_used_by_frontend(target_language, target_lang_code):
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("subrip", target_lang_code),
        _track("subrip", "fra"),
    ]

    assert _pick_subtitle_track(tracks, target_language) == 1


def test_image_codec_skipped_text_picked():
    """Mixed bitmap + text: pick the text one even if bitmap is first."""
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("hdmv_pgs_subtitle", "eng"),  # image, must skip
        _track("ass", "jpn"),                 # text, picked
    ]
    assert _pick_subtitle_track(tracks, "简体中文") == 1


def test_falls_back_to_first_text_track():
    """No English, only target-language available — still pick it (better
    than ASR). User can manually disable via prefer_embedded_subtitle."""
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("subrip", "chi"),
    ]
    assert _pick_subtitle_track(tracks, "简体中文") == 0


def test_und_language_treated_as_first_text():
    """Tracks with und/empty lang are valid candidates if English isn't
    present. Don't accidentally promote them above english."""
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("subrip", "und"),
        _track("subrip", "eng"),
    ]
    assert _pick_subtitle_track(tracks, "简体中文") == 1


def test_english_iso639_2_code():
    """ffprobe sometimes reports `eng` (ISO 639-2) instead of `en`."""
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("subrip", "fra"),
        _track("ass", "eng"),
    ]
    assert _pick_subtitle_track(tracks, "简体中文") == 1


def test_returned_index_addresses_unfiltered_subtitle_list():
    """Contract: returned index is 0-based across ALL subtitle streams
    (not text-only). Frontend describeSubtitleTrack relies on this to
    index project.subtitle_tracks directly without pre-filtering."""
    from app.api.projects import _pick_subtitle_track
    tracks = [
        _track("hdmv_pgs_subtitle", "eng"),   # idx 0 — image, skipped
        _track("subrip", "eng"),              # idx 1 — text, picked
    ]
    idx = _pick_subtitle_track(tracks, "简体中文")
    assert idx == 1
    assert tracks[idx]["codec"] == "subrip", \
        "tracks[idx] must address the picked SRT track, not undefined"
