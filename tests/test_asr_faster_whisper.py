import sys
from types import SimpleNamespace


def test_faster_whisper_backend_passes_vad_and_beam(tmp_path, monkeypatch):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    captured = {}

    class FakeWhisperModel:
        def __init__(self, model_size, **kwargs):
            captured["model_size"] = model_size
            captured["init_kwargs"] = kwargs

        def transcribe(self, audio_path, **kwargs):
            captured["audio_path"] = audio_path
            captured["transcribe_kwargs"] = kwargs
            return [
                SimpleNamespace(start=0.25, end=1.5, text=" hello ")
            ], SimpleNamespace(language="en")

    fake_module = SimpleNamespace(WhisperModel=FakeWhisperModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    from app.engines import asr

    blocks = asr._transcribe_faster_whisper(
        str(audio),
        language="en",
        model_size="large-v3-turbo",
        vad_filter=True,
        beam_size=7,
        callback=None,
    )

    assert captured["model_size"] == "large-v3-turbo"
    assert captured["init_kwargs"] == {"device": "auto", "compute_type": "auto"}
    assert captured["audio_path"] == str(audio)
    assert captured["transcribe_kwargs"] == {
        "language": "en",
        "vad_filter": True,
        "beam_size": 7,
        "word_timestamps": True,
    }
    assert len(blocks) == 1
    assert blocks[0].text == "hello"


def test_transcribe_tries_faster_whisper_before_openai(tmp_path, monkeypatch):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    from app.engines import asr

    calls = []

    def fail_mlx(*args, **kwargs):
        calls.append("mlx")
        raise ImportError("mlx unavailable")

    def succeed_faster(*args, **kwargs):
        calls.append("faster")
        return []

    def openai_should_not_run(*args, **kwargs):
        raise AssertionError("openai-whisper fallback should not run after faster-whisper succeeds")

    monkeypatch.setattr(asr, "_transcribe_mlx", fail_mlx)
    monkeypatch.setattr(asr, "_transcribe_faster_whisper", succeed_faster)
    monkeypatch.setattr(asr, "_transcribe_openai", openai_should_not_run)

    assert asr.transcribe(str(audio), vad_filter=True) == []
    assert calls == ["mlx", "faster"]


def test_transcribe_explicit_faster_whisper_skips_other_backends(tmp_path, monkeypatch):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    from app.engines import asr

    calls = []

    def mlx_should_not_run(*args, **kwargs):
        raise AssertionError("explicit faster_whisper backend should skip mlx_whisper")

    def succeed_faster(*args, **kwargs):
        calls.append("faster")
        return []

    def openai_should_not_run(*args, **kwargs):
        raise AssertionError("explicit faster_whisper backend should skip openai-whisper")

    monkeypatch.setattr(asr, "_transcribe_mlx", mlx_should_not_run)
    monkeypatch.setattr(asr, "_transcribe_faster_whisper", succeed_faster)
    monkeypatch.setattr(asr, "_transcribe_openai", openai_should_not_run)

    assert asr.transcribe(str(audio), backend="faster_whisper") == []
    assert calls == ["faster"]


def test_transcribe_explicit_backend_does_not_fallback_when_missing(tmp_path, monkeypatch):
    audio = tmp_path / "fake.wav"
    audio.write_bytes(b"\x00" * 32)

    from app.engines import asr

    def fail_faster(*args, **kwargs):
        raise ImportError("faster-whisper unavailable")

    def other_backend_should_not_run(*args, **kwargs):
        raise AssertionError("explicit backend failure should not fallback to another backend")

    monkeypatch.setattr(asr, "_transcribe_mlx", other_backend_should_not_run)
    monkeypatch.setattr(asr, "_transcribe_faster_whisper", fail_faster)
    monkeypatch.setattr(asr, "_transcribe_openai", other_backend_should_not_run)

    try:
        asr.transcribe(str(audio), backend="faster_whisper")
    except RuntimeError as exc:
        assert "faster_whisper ImportError" in str(exc)
    else:
        raise AssertionError("expected explicit missing backend to fail")
