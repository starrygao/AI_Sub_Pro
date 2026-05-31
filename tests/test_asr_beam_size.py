"""Tests for Bugfix B5: `beam_size` must be forwarded to mlx_whisper when
that backend can accept it (directly, via decode_options, or via a
**decode_options sink). If mlx_whisper has no way to accept beam_size,
a non-default configured value must produce a one-shot INFO log so users
aren't left wondering why their setting had no effect.
"""
import inspect
import logging

import pytest


def _reset_once_flags():
    """Reset module-level one-shot flags so tests start clean."""
    from app.engines import asr
    asr._mlx_beam_warning_emitted = False
    asr._vad_warning_emitted = False


def _mlx_accepts_beam_size() -> bool:
    """True iff mlx_whisper.transcribe can accept beam_size in some form."""
    try:
        import mlx_whisper
    except ImportError:
        return False
    try:
        params = inspect.signature(mlx_whisper.transcribe).parameters
    except (TypeError, ValueError):
        return False
    if "beam_size" in params or "decode_options" in params:
        return True
    return any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
    )


def test_mlx_beam_size_never_forwarded(tmp_path, monkeypatch):
    """mlx_whisper's DecodingTask raises NotImplementedError whenever
    options.beam_size is not None — even beam_size=1 trips it. Greedy
    decoding is selected by *omitting* beam_size. So `_transcribe_mlx`
    must never pass beam_size to mlx_whisper.transcribe, regardless of
    what the user configured."""
    try:
        import mlx_whisper
    except ImportError:
        pytest.skip("mlx_whisper not installed")

    _reset_once_flags()

    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    from app.engines import asr

    captured: dict = {}

    def fake_transcribe(audio_arg, *args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"segments": [], "language": "en"}

    monkeypatch.setattr(mlx_whisper, "transcribe", fake_transcribe)

    for bs in (1, 5, 7):
        captured.clear()
        asr._transcribe_mlx(
            str(audio),
            language="en",
            model_size="small",
            beam_size=bs,
            callback=None,
        )
        kwargs = captured.get("kwargs", {})
        assert "beam_size" not in kwargs, (
            f"beam_size must NOT be forwarded to mlx_whisper "
            f"(got kwargs={kwargs} for beam_size={bs})"
        )
        decode_options = kwargs.get("decode_options")
        if isinstance(decode_options, dict):
            assert "beam_size" not in decode_options, (
                f"beam_size must NOT appear nested in decode_options either "
                f"(got {decode_options} for beam_size={bs})"
            )


def test_mlx_beam_size_logs_info_when_ignored(tmp_path, caplog, monkeypatch):
    """If mlx_whisper has no way to accept beam_size AND user configured a
    non-default value, we emit a one-shot INFO log. Simulated by stubbing
    mlx_whisper.transcribe with a no-kwargs signature."""
    try:
        import mlx_whisper
    except ImportError:
        pytest.skip("mlx_whisper not installed")

    _reset_once_flags()

    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    # Stub transcribe with a signature that has no beam_size / decode_options
    # and no **kwargs sink, so the caller MUST take the log-warning branch.
    def no_kw_transcribe(audio_arg, path_or_hf_repo=None, verbose=False,
                        language=None):
        return {"segments": [], "language": "en"}

    monkeypatch.setattr(mlx_whisper, "transcribe", no_kw_transcribe)

    from app.engines import asr

    caplog.set_level(logging.INFO, logger="app.engines.asr")

    blocks = asr._transcribe_mlx(
        str(audio),
        language="en",
        model_size="small",
        beam_size=7,
        callback=None,
    )

    assert blocks == []
    beam_logs = [
        rec for rec in caplog.records
        if "beam_size" in rec.getMessage()
        and "mlx_whisper" in rec.getMessage()
    ]
    assert beam_logs, (
        "Expected an INFO log about mlx_whisper ignoring beam_size; "
        f"got records: {[r.getMessage() for r in caplog.records]}"
    )


def test_mlx_beam_size_info_log_emitted_only_once(tmp_path, caplog, monkeypatch):
    """The info log must not spam: only once per process regardless of how
    many transcribes happen with a non-default beam_size."""
    try:
        import mlx_whisper
    except ImportError:
        pytest.skip("mlx_whisper not installed")

    _reset_once_flags()

    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    def no_kw_transcribe(audio_arg, path_or_hf_repo=None, verbose=False,
                        language=None):
        return {"segments": [], "language": "en"}

    monkeypatch.setattr(mlx_whisper, "transcribe", no_kw_transcribe)

    from app.engines import asr

    caplog.set_level(logging.INFO, logger="app.engines.asr")

    for _ in range(3):
        asr._transcribe_mlx(
            str(audio),
            language="en",
            model_size="small",
            beam_size=7,
            callback=None,
        )

    beam_logs = [
        rec for rec in caplog.records
        if "beam_size" in rec.getMessage()
        and "mlx_whisper" in rec.getMessage()
    ]
    assert len(beam_logs) == 1, (
        f"Expected exactly one beam_size info log across 3 calls, got "
        f"{len(beam_logs)}: {[r.getMessage() for r in beam_logs]}"
    )


def test_mlx_beam_size_default_does_not_log(tmp_path, caplog, monkeypatch):
    """If beam_size matches the default (5) and mlx_whisper can't accept
    it anyway, stay silent — don't pester users who never touched this."""
    try:
        import mlx_whisper
    except ImportError:
        pytest.skip("mlx_whisper not installed")

    _reset_once_flags()

    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    def no_kw_transcribe(audio_arg, path_or_hf_repo=None, verbose=False,
                        language=None):
        return {"segments": [], "language": "en"}

    monkeypatch.setattr(mlx_whisper, "transcribe", no_kw_transcribe)

    from app.engines import asr

    caplog.set_level(logging.INFO, logger="app.engines.asr")

    asr._transcribe_mlx(
        str(audio),
        language="en",
        model_size="small",
        beam_size=asr._DEFAULT_BEAM_SIZE,
        callback=None,
    )

    beam_logs = [
        rec for rec in caplog.records
        if "beam_size" in rec.getMessage()
        and "mlx_whisper" in rec.getMessage()
    ]
    assert beam_logs == [], (
        f"Did not expect a beam_size info log at default value; got: "
        f"{[r.getMessage() for r in beam_logs]}"
    )
