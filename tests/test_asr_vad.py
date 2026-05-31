"""Tests for Bugfix B4: vad_filter config must be honored (or warn if the
active whisper backend doesn't support it).

The two backends wired into app/engines/asr.py (mlx_whisper and openai
whisper) do not accept a `vad_filter` kwarg, so the expected behavior is
to log a warning when `vad_filter=True` is configured. If/when a backend
that supports VAD (e.g. faster-whisper) is added, these tests should be
updated to assert the kwarg is actually passed through.
"""
import logging
import sys
from types import SimpleNamespace

import pytest


def _reset_once_flag():
    """Reset the module-level _vad_warning_emitted flag so each test
    starts from a clean slate."""
    from app.engines import asr
    asr._vad_warning_emitted = False


def test_vad_filter_warning_when_unsupported(tmp_path, caplog, monkeypatch):
    """When vad_filter=True is configured but backend doesn't support VAD,
    a warning must be logged (not silently dropped)."""
    _reset_once_flag()

    # Create a dummy audio file so the existence check passes.
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    from app.engines import asr

    fake_mlx = SimpleNamespace(transcribe=lambda *a, **kw: {"segments": []})
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake_mlx)

    caplog.set_level(logging.WARNING, logger="app.engines.asr")

    asr.transcribe(
        str(audio),
        language="auto",
        model_size="small",
        vad_filter=True,
        beam_size=5,
    )

    messages = [rec.getMessage().lower() for rec in caplog.records]
    assert any("vad" in m for m in messages), (
        f"Expected a warning mentioning VAD, got: {messages}"
    )


def test_vad_filter_warning_not_emitted_when_disabled(tmp_path, caplog, monkeypatch):
    """When vad_filter=False, no VAD-related warning should be logged."""
    _reset_once_flag()

    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    from app.engines import asr

    fake_mlx = SimpleNamespace(transcribe=lambda *a, **kw: {"segments": []})
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake_mlx)

    caplog.set_level(logging.WARNING, logger="app.engines.asr")

    asr.transcribe(
        str(audio),
        language="auto",
        model_size="small",
        vad_filter=False,
        beam_size=5,
    )

    # Only the backend-failure warnings are expected; no VAD-specific one.
    vad_specific = [
        rec for rec in caplog.records
        if "vad" in rec.getMessage().lower()
        and "ignored" in rec.getMessage().lower()
    ]
    assert vad_specific == [], (
        f"Did not expect a VAD-unsupported warning when vad_filter=False, "
        f"got: {[r.getMessage() for r in vad_specific]}"
    )


def test_vad_filter_warning_is_emitted_only_once(tmp_path, caplog, monkeypatch):
    """The VAD-unsupported warning must not spam: only once per process."""
    _reset_once_flag()

    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    from app.engines import asr

    fake_mlx = SimpleNamespace(transcribe=lambda *a, **kw: {"segments": []})
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake_mlx)

    caplog.set_level(logging.WARNING, logger="app.engines.asr")

    for _ in range(3):
        asr.transcribe(
            str(audio),
            language="auto",
            model_size="small",
            vad_filter=True,
            beam_size=5,
        )

    vad_warnings = [
        rec for rec in caplog.records
        if "vad" in rec.getMessage().lower()
        and "ignored" in rec.getMessage().lower()
    ]
    assert len(vad_warnings) == 1, (
        f"Expected exactly one VAD warning across 3 calls, got "
        f"{len(vad_warnings)}: {[r.getMessage() for r in vad_warnings]}"
    )
