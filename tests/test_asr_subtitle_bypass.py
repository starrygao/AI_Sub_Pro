"""Tests for the embedded-subtitle ASR bypass: when a project has a
selected text-based subtitle track and prefer_embedded_subtitle=True,
_run_asr_pipeline must extract the subtitle (writing raw.srt +
filtered.srt) and skip ASR entirely."""
import os
from unittest.mock import patch, MagicMock

import pytest


SAMPLE_SRT = """1
00:00:01,000 --> 00:00:02,500
Hello world.

2
00:00:03,000 --> 00:00:04,500
Second line.
"""


def _make_project(tmp_path, *, sub_idx, prefer=True, video_exists=True):
    pid = "testpid1"
    pdir = tmp_path / pid
    pdir.mkdir()
    video = tmp_path / "movie.mkv"
    if video_exists:
        video.write_bytes(b"not really an mkv but exists")

    project = {
        "id": pid,
        "name": "movie.mkv",
        "video_path": str(video),
        "selected_subtitle_track": sub_idx,
        "prefer_embedded_subtitle": prefer,
        "status": "created",
    }
    return pid, str(pdir), project


def test_bypass_succeeds_when_track_selected(tmp_path):
    """Happy path: subtitle extracts cleanly → raw.srt + filtered.srt
    written, ASR skipped."""
    from app.api import translate

    pid, pdir, project = _make_project(tmp_path, sub_idx=0)

    def fake_extract(video, output, track_index):
        with open(output, "w") as f:
            f.write(SAMPLE_SRT)
        return True

    with patch("app.utils.media.extract_subtitle", side_effect=fake_extract), \
         patch.object(translate, "_emit_progress"), \
         patch.object(translate, "mutate_project"):
        ok = translate._try_bypass_asr_with_embedded_subtitle(pid, project, pdir)

    assert ok is True
    assert os.path.exists(os.path.join(pdir, "raw.srt"))
    assert os.path.exists(os.path.join(pdir, "filtered.srt"))


def test_bypass_skipped_when_user_opts_out(tmp_path):
    """prefer_embedded_subtitle=False → return False without touching ffmpeg."""
    from app.api import translate

    pid, pdir, project = _make_project(tmp_path, sub_idx=0, prefer=False)

    extract_called = False

    def fake_extract(*a, **kw):
        nonlocal extract_called
        extract_called = True
        return True

    with patch("app.utils.media.extract_subtitle", side_effect=fake_extract), \
         patch.object(translate, "_emit_progress"):
        ok = translate._try_bypass_asr_with_embedded_subtitle(pid, project, pdir)

    assert ok is False
    assert not extract_called


def test_bypass_skipped_when_no_track_selected(tmp_path):
    from app.api import translate
    pid, pdir, project = _make_project(tmp_path, sub_idx=None)

    with patch.object(translate, "_emit_progress"):
        ok = translate._try_bypass_asr_with_embedded_subtitle(pid, project, pdir)
    assert ok is False


def test_bypass_falls_through_when_extraction_fails(tmp_path):
    """ffmpeg returns False (e.g. PGS bitmap codec) → return False so
    caller can fall back to ASR."""
    from app.api import translate

    pid, pdir, project = _make_project(tmp_path, sub_idx=0)

    with patch("app.utils.media.extract_subtitle", return_value=False), \
         patch.object(translate, "_emit_progress"):
        ok = translate._try_bypass_asr_with_embedded_subtitle(pid, project, pdir)

    assert ok is False


def test_bypass_falls_through_when_extracted_srt_is_empty(tmp_path):
    """ffmpeg returns True but the extracted SRT parses to 0 blocks
    (corrupt / empty stream) → fall back to ASR."""
    from app.api import translate

    pid, pdir, project = _make_project(tmp_path, sub_idx=0)

    def fake_extract(video, output, track_index):
        # Write a syntactically valid but empty SRT
        open(output, "w").close()
        return True

    with patch("app.utils.media.extract_subtitle", side_effect=fake_extract), \
         patch.object(translate, "_emit_progress"):
        ok = translate._try_bypass_asr_with_embedded_subtitle(pid, project, pdir)

    assert ok is False


def test_bypass_writes_both_raw_and_filtered_srt(tmp_path):
    """Translate pipeline reads filtered.srt first, then raw.srt — write
    both so the order in translate.py doesn't matter."""
    from app.api import translate

    pid, pdir, project = _make_project(tmp_path, sub_idx=2)

    def fake_extract(video, output, track_index):
        assert track_index == 2
        with open(output, "w") as f:
            f.write(SAMPLE_SRT)
        return True

    with patch("app.utils.media.extract_subtitle", side_effect=fake_extract), \
         patch.object(translate, "_emit_progress"), \
         patch.object(translate, "mutate_project"):
        translate._try_bypass_asr_with_embedded_subtitle(pid, project, pdir)

    raw = open(os.path.join(pdir, "raw.srt")).read()
    filtered = open(os.path.join(pdir, "filtered.srt")).read()
    assert raw == filtered
    assert "Hello world." in raw
