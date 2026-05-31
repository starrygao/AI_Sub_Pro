"""Phase 2 — subprocess robustness: return codes checked, paths escaped,
large prompts passed via stdin."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---- check_ffmpeg: must inspect return codes -------------------------------

def test_check_ffmpeg_false_when_binary_broken():
    """ffmpeg present but exiting non-zero must NOT count as available."""
    from app.utils import media
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=1)):
        assert media.check_ffmpeg() is False


def test_check_ffmpeg_true_when_both_ok():
    from app.utils import media

    def fake_run(cmd, **kw):
        if "-filters" in cmd:
            return MagicMock(returncode=0, stdout=" .. subtitles        V->V       Render text subtitles\\n")
        return MagicMock(returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        assert media.check_ffmpeg() is True


def test_check_ffmpeg_false_when_subtitles_filter_missing():
    from app.utils import media

    def fake_run(cmd, **kw):
        if "-filters" in cmd:
            return MagicMock(returncode=0, stdout=" .. scale            V->V       Scale video\\n")
        return MagicMock(returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        assert media.check_ffmpeg() is False


# ---- burn_subtitles: fallback path must be escaped -------------------------

def test_burn_subtitles_fallback_uses_filter_safe_subtitle_copy(tmp_path):
    """Fallback burn should use a simple temp path, not the raw user filename."""
    from app.utils import media

    srt = tmp_path / "a'b.srt"  # single quote -> must be escaped for the filter
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")

    captured = {}

    class FailProc:
        returncode = 1

        def communicate(self):
            return (b"", b"boom")

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    with patch.object(media, "ffmpeg_supports_subtitle_burn", return_value=True), \
         patch.object(subprocess, "Popen", return_value=FailProc()), \
         patch.object(subprocess, "run", side_effect=fake_run):
        media.burn_subtitles("/fake/v.mp4", str(srt), str(tmp_path / "out.mp4"))

    cmd2 = captured["cmd"]
    vf = cmd2[cmd2.index("-vf") + 1]
    assert "aisubpro-subtitles-" in vf
    assert "track_0.srt" in vf
    assert str(srt) not in vf
    assert "'" in vf


def test_burn_subtitles_reports_when_ffmpeg_cannot_burn_subtitles(tmp_path):
    from app.utils import media

    srt = tmp_path / "caption.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    messages = []

    with patch.object(media, "ffmpeg_supports_subtitle_burn", return_value=False), \
         patch.object(subprocess, "Popen") as popen:
        ok = media.burn_subtitles("/fake/v.mp4", str(srt), str(tmp_path / "out.mp4"), callback=messages.append)

    assert ok is False
    assert not popen.called
    assert any("不支持 subtitles" in msg for msg in messages)


def test_burn_subtitles_with_real_ffmpeg_handles_spaces_and_quotes(tmp_path):
    """Smoke the actual ffmpeg subtitles filter against user-like filenames."""
    from app.utils import media

    if not media.check_ffmpeg():
        pytest.skip("ffmpeg/ffprobe unavailable")

    video = tmp_path / "input clip.mp4"
    srt = tmp_path / "director's cut.srt"
    output = tmp_path / "output subtitled.mp4"

    subprocess.run(
        [
            media.get_ffmpeg_path(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:d=1",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:00,800\nhello world\n",
        encoding="utf-8",
    )

    assert media.burn_subtitles(str(video), str(srt), str(output))
    assert output.exists()
    assert output.stat().st_size > 0


# ---- claude CLI: prompt via stdin, not argv --------------------------------

def test_claude_cli_invoke_passes_prompt_via_stdin():
    """Large prompts must go through stdin, not the command line (ARG_MAX)."""
    from app.engines.providers.claude_cli import ClaudeCliProvider

    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    big = "x" * 5000
    items = [{"id": 1, "original": big}]
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["input"] = kw.get("input")
        return MagicMock(
            returncode=0,
            stdout='{"result": "[{\\"id\\": 1, \\"translation\\": \\"y\\"}]"}',
            stderr="",
        )

    with patch.object(subprocess, "run", side_effect=fake_run):
        p._invoke(items, "SYSPROMPT")

    assert captured["input"] and "SYSPROMPT" in captured["input"]
    assert big in captured["input"]                       # payload is in stdin
    assert not any(big in str(a) for a in captured["cmd"])  # NOT on the command line


def test_codex_cli_invoke_passes_prompt_via_stdin_and_last_message_file(tmp_path):
    """Codex prompts must go through stdin and read the final answer from --output-last-message."""
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5"})
    big = "x" * 5000
    items = [{"id": 1, "original": big}]
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["input"] = kw.get("input")
        output_path = cmd[cmd.index("--output-last-message") + 1]
        Path(output_path).write_text('[{"id": 1, "translation": "y"}]', encoding="utf-8")
        return MagicMock(returncode=0, stdout="ignored progress output", stderr="")

    with patch.object(subprocess, "run", side_effect=fake_run):
        text = p._invoke(items, "SYSPROMPT")

    assert text == '[{"id": 1, "translation": "y"}]'
    assert captured["cmd"][:2] == ["codex", "exec"]
    assert "--output-last-message" in captured["cmd"]
    assert "--sandbox" in captured["cmd"]
    assert captured["input"] and "SYSPROMPT" in captured["input"]
    assert big in captured["input"]
    assert not any(big in str(a) for a in captured["cmd"])


# ---- demucs: non-zero exit must fall back to raw audio without crashing ----

def test_preprocess_audio_falls_back_when_demucs_fails(tmp_path, caplog):
    from app.engines import audio

    raw = tmp_path / "raw_audio.wav"

    def fake_extract_audio(video, out, **kw):
        with open(out, "wb") as f:
            f.write(b"\x00" * 4096)
        return True

    with patch.object(audio, "extract_audio", side_effect=fake_extract_audio), \
         patch.object(audio.shutil, "which", return_value="/usr/bin/demucs"), \
         patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stderr="demucs blew up")):
        result = audio.preprocess_audio("/fake/v.mp4", str(tmp_path))

    # Fell back to the raw extracted audio, did not raise.
    assert result == str(raw)
