"""Tests for extract_subtitle: ASS/SSA → SRT normalization, subtitle-relative
indexing, and text-vs-image codec gating."""
import json
import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest


def test_uses_subtitle_relative_index(tmp_path):
    """extract_subtitle must use `-map 0:s:N` (subtitle-relative), not the
    absolute container stream index. Same convention as extract_audio."""
    from app.utils import media

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        # simulate ffmpeg writing a non-empty SRT
        out = cmd[cmd.index("-y") + 2:][-1]  # last positional arg
        # find the output_path argument: it's the last element
        with open(cmd[-1], "w") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
        return MagicMock(returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        out = tmp_path / "out.srt"
        ok = media.extract_subtitle("/fake/video.mkv", str(out), track_index=0)

    assert ok is True
    cmd = captured["cmd"]
    assert "-map" in cmd
    map_idx = cmd.index("-map")
    assert cmd[map_idx + 1] == "0:s:0", (
        f"expected subtitle-relative selector 0:s:0, got {cmd[map_idx + 1]}"
    )


def test_forces_srt_transcode(tmp_path):
    """ASS/SSA/MOV_TEXT inputs need `-c:s srt` + `-f srt` so the output
    is always parseable plain SRT regardless of source format."""
    from app.utils import media

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        with open(cmd[-1], "w") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
        return MagicMock(returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        out = tmp_path / "out.srt"
        media.extract_subtitle("/fake/video.mkv", str(out), track_index=2)

    cmd = captured["cmd"]
    assert "-c:s" in cmd and cmd[cmd.index("-c:s") + 1] == "srt"
    assert "-f" in cmd and cmd[cmd.index("-f") + 1] == "srt"


def test_returns_false_on_empty_output(tmp_path):
    """If ffmpeg succeeds but produces an empty file (e.g. PGS/DVD bitmap
    codec it couldn't transcode), return False so caller falls back to ASR."""
    from app.utils import media

    def fake_run(cmd, **kw):
        # ffmpeg "succeeds" but writes nothing
        open(cmd[-1], "w").close()
        return MagicMock(returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        out = tmp_path / "out.srt"
        ok = media.extract_subtitle("/fake/video.mkv", str(out), track_index=0)

    assert ok is False


def test_returns_false_on_ffmpeg_failure(tmp_path):
    """Non-zero ffmpeg exit must be swallowed and return False so the
    pipeline can fall back to ASR cleanly."""
    from app.utils import media

    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)

    with patch.object(subprocess, "run", side_effect=fake_run):
        out = tmp_path / "out.srt"
        ok = media.extract_subtitle("/fake/video.mkv", str(out), track_index=0)

    assert ok is False


def test_is_text_subtitle_codec():
    from app.utils.media import is_text_subtitle_codec

    # text-based: convertible
    assert is_text_subtitle_codec("subrip")
    assert is_text_subtitle_codec("ass")
    assert is_text_subtitle_codec("ssa")
    assert is_text_subtitle_codec("mov_text")
    assert is_text_subtitle_codec("webvtt")
    # case-insensitive
    assert is_text_subtitle_codec("ASS")
    # image-based: NOT convertible without OCR
    assert not is_text_subtitle_codec("hdmv_pgs_subtitle")
    assert not is_text_subtitle_codec("dvd_subtitle")
    assert not is_text_subtitle_codec("dvb_subtitle")
    # unknown / empty
    assert not is_text_subtitle_codec("")
    assert not is_text_subtitle_codec(None)


def test_get_tracks_tolerates_malformed_ffprobe_streams(monkeypatch):
    from app.utils import media

    payload = {
        "streams": [
            None,
            "bad",
            {
                "index": "not-an-index",
                "codec_name": None,
                "tags": "not-an-object",
                "channels": "2",
                "sample_rate": 48000,
            },
            {
                "index": 3,
                "codec_name": "aac",
                "tags": {"language": "eng", "title": "Main"},
                "channels": 2,
                "sample_rate": "48000",
            },
        ]
    }

    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(payload).encode("utf-8"),
    )

    assert media.get_tracks("/fake/video.mkv", "a") == [
        {
            "index": 0,
            "codec": "unknown",
            "lang": "und",
            "title": "",
            "channels": 0,
            "sample_rate": "",
        },
        {
            "index": 3,
            "codec": "aac",
            "lang": "eng",
            "title": "Main",
            "channels": 2,
            "sample_rate": "48000",
        },
    ]
