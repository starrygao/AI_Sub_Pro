import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


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


@pytest.mark.parametrize('language', ['auto', 'en'])
@pytest.mark.parametrize('text', ['spoken dialogue', ''])
def test_language_evidence_only_reports_native_auto_detection(tmp_path, monkeypatch, language, text):
    from app.engines import asr
    audio = tmp_path / 'audio.wav'
    audio.write_bytes(b'audio')
    class Model:
        def __init__(self, *args, **kwargs):
            pass
        def transcribe(self, path, **kwargs):
            return [SimpleNamespace(start=1, end=2, text=text)], SimpleNamespace(
                language='zh', language_probability=0.97)
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    callback = Mock()
    asr.transcribe(str(audio), language=language, backend='faster_whisper', language_callback=callback)
    if language == 'auto' and text:
        callback.assert_called_once_with('zh', 0.97)
    else:
        callback.assert_not_called()


@pytest.mark.parametrize('report_language', [True, False])
def test_library_conflict_asr_forces_auto_and_persists_only_fresh_evidence(tmp_path, monkeypatch, report_language):
    import json
    from datetime import timedelta
    from app.services import translation_tasks as tasks
    from app.utils import project_store
    from app.utils.srt import SubtitleBlock
    pid = 'abcd1234'
    pdir = tmp_path / pid
    pdir.mkdir()
    fingerprint = {'size': 100, 'mtime_ns': 123}
    (pdir / 'project.json').write_text(json.dumps({
        'id': pid, 'name': 'test', 'video_path': '/fake/video.mkv', 'status': 'created',
        'selected_audio_track': 1, 'prefer_embedded_subtitle': True,
        'library_verify_audio_language': True, 'library_fingerprint': fingerprint,
        'asr_detected_language': {'language': 'zh', 'probability': 1},
    }))
    monkeypatch.setattr(tasks, 'PROJECTS_DIR', tmp_path)
    monkeypatch.setattr(project_store, 'PROJECTS_DIR', tmp_path)
    monkeypatch.setattr(tasks.Config, 'to_dict', lambda: {
        'asr': {'language': 'en', 'backend': 'faster_whisper', 'use_demucs': False},
        'translation': {},
    })
    monkeypatch.setattr(tasks, '_emit_progress', lambda *args, **kwargs: None)
    monkeypatch.setattr(tasks, '_check_cancel', lambda *args: None)
    monkeypatch.setattr('app.engines.audio.preprocess_audio', lambda *args, **kwargs: str(pdir / 'audio.wav'))
    translate = Mock(side_effect=AssertionError('ASR-only verification must not translate'))
    monkeypatch.setattr(tasks, '_run_translate_pipeline', translate)
    def transcribe(path, **kwargs):
        assert kwargs['language'] == 'auto'
        assert 'asr_detected_language' not in json.loads((pdir / 'project.json').read_text())
        if report_language:
            kwargs['language_callback']('zh', 0.98)
        return [SubtitleBlock(1, timedelta(), timedelta(seconds=2), '测试语音')]
    monkeypatch.setattr('app.engines.asr.transcribe', transcribe)
    monkeypatch.setattr('app.engines.filter.filter_subtitles', lambda blocks, **kwargs: blocks)
    monkeypatch.setattr('app.engines.filter.get_filter_stats', lambda blocks: {'active': 1, 'filtered': 0})
    tasks._run_asr_pipeline(pid, 1, 'en', owns_registration=False)
    project = json.loads((pdir / 'project.json').read_text())
    assert project['status'] == 'asr_done'
    if report_language:
        assert project['asr_detected_language'] == {
            'language': 'zh', 'probability': 0.98, 'audio_track': 1, 'fingerprint': fingerprint,
        }
    else:
        assert 'asr_detected_language' not in project
    translate.assert_not_called()


@pytest.mark.parametrize('probability', [0.98, 0.1])
@pytest.mark.parametrize('backend', ['mlx', 'openai'])
def test_whisper_backends_report_native_probe_confidence(tmp_path, monkeypatch, backend, probability):
    from app.engines import asr
    audio = tmp_path / 'audio.wav'
    audio.write_bytes(b'audio')
    segments = [{'start': 1, 'end': 2, 'text': 'speech'}]
    result = {'segments': segments, 'language': 'zh'}
    model = SimpleNamespace(
        dims=SimpleNamespace(n_mels=128), device='cpu',
        transcribe=lambda *args, **kwargs: result,
        detect_language=Mock(return_value=(None, {'zh': probability, 'en': 1 - probability})),
    )
    class Tensor:
        def astype(self, dtype):
            return self
        def to(self, device):
            return self
    tensor = Tensor()
    probe = Mock(return_value=tensor)
    monkeypatch.setattr(asr, '_language_probe_audio', probe)
    callback = Mock()
    if backend == 'mlx':
        core = SimpleNamespace(float16='float16', array=lambda value: value)
        monkeypatch.setitem(sys.modules, 'mlx', SimpleNamespace(core=core))
        monkeypatch.setitem(sys.modules, 'mlx.core', core)
        monkeypatch.setitem(sys.modules, 'mlx_whisper', SimpleNamespace(transcribe=lambda *args, **kwargs: result))
        monkeypatch.setitem(sys.modules, 'mlx_whisper.transcribe', SimpleNamespace(
            ModelHolder=SimpleNamespace(get_model=lambda *args: model)))
        monkeypatch.setitem(sys.modules, 'mlx_whisper.audio', SimpleNamespace(
            log_mel_spectrogram=lambda *args, **kwargs: tensor,
            pad_or_trim=lambda *args, **kwargs: tensor, N_FRAMES=3000, N_SAMPLES=480000))
        monkeypatch.setattr(asr, 'resolve_mlx_model_source', lambda size: {'source': 'download', 'path_or_repo': 'model'})
        blocks = asr._transcribe_mlx(str(audio), None, 'tiny', 5, None, language_callback=callback)
    else:
        monkeypatch.setitem(sys.modules, 'whisper', SimpleNamespace(
            load_model=lambda size: model, pad_or_trim=lambda audio: tensor,
            log_mel_spectrogram=lambda *args, **kwargs: tensor))
        blocks = asr._transcribe_openai(str(audio), None, 'tiny', 5, None, language_callback=callback)
    assert len(blocks) == 1
    probe.assert_called_once_with(str(audio), segments)
    model.detect_language.assert_called_once_with(tensor)
    callback.assert_called_once_with('zh', probability)
