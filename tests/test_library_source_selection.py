"""Media-library source selection: no provider or model calls in these tests."""
import array
import json
import subprocess
import wave
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.library.worker import LibraryWorker


def candidate(tmp_path, monkeypatch, *, name='Episode.mkv', streams=None):
    from app.engines.providers.codex_cli import CodexCliProvider
    root = tmp_path / 'media'
    root.mkdir(exist_ok=True)
    video = root / name
    video.write_bytes(b'isolated media fixture')
    worker = LibraryWorker({'allowed_roots': [str(root)], 'quiet_seconds': 0}, tmp_path / 'state')
    worker.observe(video, {})
    monkeypatch.setattr(CodexCliProvider, 'check_logged_in', lambda: True)
    monkeypatch.setattr('os.getloadavg', lambda: (0, 0, 0))
    info = {'streams': streams or [
        {'index': 0, 'codec_type': 'video'},
        {'index': 1, 'codec_type': 'audio', 'tags': {'language': 'eng'}},
    ], 'format': {'duration': '120'}}
    monkeypatch.setattr(worker, 'probe', lambda path: info)
    monkeypatch.setattr(worker, 'refresh_readiness', lambda: None)
    monkeypatch.setattr(worker.sources, 'metadata', lambda path: {})
    return worker, video


def capture_project(worker, video, tmp_path, monkeypatch):
    from app.services import translation_tasks as tasks
    projects = tmp_path / 'projects'
    projects.mkdir(exist_ok=True)
    monkeypatch.setattr(tasks, 'PROJECTS_DIR', projects)
    translate, asr = Mock(), Mock()
    monkeypatch.setattr(tasks, 'start_translate', translate)
    monkeypatch.setattr(tasks, 'start_transcribe_translate', asr)
    worker.process_one()
    row = worker.store.get(video)
    project = json.loads((projects / row['project_id'] / 'project.json').read_text()) if row.get('project_id') else None
    return project, translate, asr


@pytest.mark.parametrize('tags', [
    {'language': 'chi'}, {'language': 'zho'}, {'language': 'zh-Hans'},
    {'language': 'zh-Hant'}, {'language': 'yue'}, {'title': '简体中文'},
    {'title': '繁體中文'}, {'LANGUAGE': 'ZH'},
])
@pytest.mark.parametrize('codec', ['subrip', 'hdmv_pgs_subtitle'])
def test_complete_chinese_text_and_graphic_tracks_skip_all_model_work(tmp_path, monkeypatch, tags, codec):
    worker, video = candidate(tmp_path, monkeypatch, streams=[
        {'index': 0, 'codec_type': 'video'},
        {'index': 1, 'codec_type': 'audio', 'tags': {'language': 'eng'}},
        {'index': 2, 'codec_type': 'subtitle', 'codec_name': codec, 'tags': tags},
    ])
    prepare = Mock()
    monkeypatch.setattr(worker, 'prepare', prepare)
    worker.process_one()
    assert worker.store.get(video)['state'] == 'skipped'
    prepare.assert_not_called()


@pytest.mark.parametrize('marker', ['Forced', 'Foreign', 'Commentary'])
def test_partial_chinese_track_title_is_not_a_complete_subtitle(tmp_path, monkeypatch, marker):
    worker, video = candidate(tmp_path, monkeypatch, streams=[
        {'index': 0, 'codec_type': 'video'},
        {'index': 1, 'codec_type': 'audio', 'tags': {'language': 'eng'}},
        {'index': 2, 'codec_type': 'subtitle', 'codec_name': 'subrip',
         'tags': {'language': 'chi', 'title': 'Chinese [' + marker + ']'}, 'disposition': {'forced': 0}},
    ])
    project, translate, asr = capture_project(worker, video, tmp_path, monkeypatch)
    assert project['library_subtitle_source'] == '语音识别'
    translate.assert_not_called()
    asr.assert_called_once()


@pytest.mark.parametrize('marker', ['forced', 'foreign', 'commentary'])
def test_partial_sidecar_never_replaces_full_dialogue_asr(tmp_path, monkeypatch, marker):
    worker, video = candidate(tmp_path, monkeypatch)
    video.with_suffix('.en.' + marker + '.srt').write_text(
        '1\n00:00:01,000 --> 00:00:02,000\nA single translated sign.\n')
    project, translate, asr = capture_project(worker, video, tmp_path, monkeypatch)
    assert project['library_subtitle_source'] == '语音识别'
    translate.assert_not_called()
    asr.assert_called_once()


@pytest.mark.parametrize('name', ['Chinese.Puzzle.mkv', 'Forced.Entry.mkv', 'Foreign.Correspondent.mkv'])
def test_movie_title_words_do_not_classify_english_sidecar(tmp_path, monkeypatch, name):
    worker, video = candidate(tmp_path, monkeypatch, name=name)
    subtitle = video.with_suffix('.en.srt')
    subtitle.write_text('1\n00:00:01,000 --> 00:00:02,000\nFull English dialogue.\n')
    project, translate, asr = capture_project(worker, video, tmp_path, monkeypatch)
    assert project is not None
    assert project['library_subtitle_source'] == str(subtitle)
    translate.assert_called_once()
    asr.assert_not_called()


@pytest.mark.parametrize('name', ['Forced.Entry.mkv', 'Foreign.Correspondent.mkv'])
def test_movie_title_words_do_not_hide_complete_chinese_sidecar(tmp_path, monkeypatch, name):
    worker, video = candidate(tmp_path, monkeypatch, name=name)
    video.with_suffix('.zh-Hant.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n這是完整的中文字幕。\n')
    prepare = Mock()
    monkeypatch.setattr(worker, 'prepare', prepare)
    worker.process_one()
    assert worker.store.get(video)['state'] == 'skipped'
    prepare.assert_not_called()


def test_second_readiness_failure_recovers_without_manual_retry(tmp_path, monkeypatch):
    worker, video = candidate(tmp_path, monkeypatch)
    prepare = Mock()
    monkeypatch.setattr(worker, 'prepare', prepare)
    monkeypatch.setattr(worker, 'refresh_readiness', Mock(side_effect=RuntimeError('temporary readiness timeout')))
    worker.process_one()
    assert worker.store.get(video)['state'] == 'waiting'
    assert '等待' in worker.store.get(video)['reason']
    prepare.assert_not_called()
    monkeypatch.setattr(worker, 'refresh_readiness', lambda: None)
    worker.observe(video, {})
    worker.process_one()
    prepare.assert_called_once()


@pytest.mark.parametrize(('tracks', 'expected'), [
    ([{'language': 'eng'}, {'language': 'chi'}], 0),
    ([{'language': 'chi'}, {'language': 'eng'}], 1),
    ([{'language': 'eng', 'title': 'Director Commentary'}, {'language': 'jpn'}], 1),
    ([{'language': 'und'}, {'language': 'eng'}], 1),
])
def test_asr_selects_audio_relative_dialogue_track(tmp_path, monkeypatch, tracks, expected):
    worker, video = candidate(tmp_path, monkeypatch, streams=[
        {'index': 0, 'codec_type': 'video'},
        *[{'index': index + 1, 'codec_type': 'audio', 'tags': tags} for index, tags in enumerate(tracks)],
    ])
    project, translate, asr = capture_project(worker, video, tmp_path, monkeypatch)
    assert project['selected_audio_track'] == expected
    asr.assert_called_once()


def test_original_dialogue_wins_over_foreign_dub_and_commentary(tmp_path, monkeypatch):
    worker, video = candidate(tmp_path, monkeypatch, streams=[
        {'index': 0, 'codec_type': 'video'},
        {'index': 1, 'codec_type': 'audio', 'tags': {'language': 'eng'}, 'disposition': {'default': 1}},
        {'index': 2, 'codec_type': 'audio', 'tags': {'language': 'jpn'}, 'disposition': {'original': 1}},
        {'index': 3, 'codec_type': 'audio', 'tags': {'language': 'jpn', 'title': 'Commentary'}, 'disposition': {'original': 1}},
    ])
    project, translate, asr = capture_project(worker, video, tmp_path, monkeypatch)
    assert project['selected_audio_track'] == 1
    asr.assert_called_once()


def test_english_commentary_does_not_turn_chinese_dialogue_into_a_translation_job(tmp_path, monkeypatch):
    worker, video = candidate(tmp_path, monkeypatch, streams=[
        {'index': 0, 'codec_type': 'video'},
        {'index': 1, 'codec_type': 'audio', 'tags': {'language': 'chi'}},
        {'index': 2, 'codec_type': 'audio', 'tags': {'language': 'eng', 'title': 'Director Commentary'}},
    ])
    prepare = Mock()
    monkeypatch.setattr(worker, 'prepare', prepare)
    worker.process_one()
    assert worker.store.get(video)['state'] == 'native_language'
    prepare.assert_not_called()


def test_complete_chinese_track_skips_even_when_english_output_name_is_taken(tmp_path, monkeypatch):
    worker, video = candidate(tmp_path, monkeypatch, streams=[
        {'index': 0, 'codec_type': 'video'},
        {'index': 1, 'codec_type': 'audio', 'tags': {'language': 'eng'}},
        {'index': 2, 'codec_type': 'subtitle', 'codec_name': 'hdmv_pgs_subtitle', 'tags': {'language': 'chi'}},
    ])
    sidecar = video.with_suffix('.srt')
    original = '1\n00:00:00,000 --> 00:00:01,000\nExisting English subtitle.\n'
    sidecar.write_text(original)
    prepare = Mock()
    monkeypatch.setattr(worker, 'prepare', prepare)
    worker.process_one()
    assert worker.store.get(video)['state'] == 'skipped'
    assert sidecar.read_text() == original
    prepare.assert_not_called()


def test_real_ffmpeg_dual_audio_extracts_selected_english_dialogue(tmp_path, monkeypatch):
    from app.services import translation_tasks as tasks
    from app.utils.media import get_ffmpeg_path, extract_audio
    root = tmp_path / 'media'
    root.mkdir()
    video = root / 'DualAudio.mkv'
    subprocess.run([
        get_ffmpeg_path(), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=64x64:d=1',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
        '-f', 'lavfi', '-i', 'sine=frequency=880:duration=1',
        '-map', '0:v:0', '-map', '1:a:0', '-map', '2:a:0', '-c:v', 'mpeg4', '-c:a', 'pcm_s16le',
        '-metadata:s:a:0', 'language=eng', '-metadata:s:a:1', 'language=chi', str(video),
    ], check=True)
    worker = LibraryWorker({'allowed_roots': [str(root)]}, tmp_path / 'state')
    worker.observe(video, {})
    projects = tmp_path / 'projects'
    projects.mkdir()
    monkeypatch.setattr(tasks, 'PROJECTS_DIR', projects)
    monkeypatch.setattr(tasks, 'start_transcribe_translate', Mock())
    monkeypatch.setattr(worker.sources, 'metadata', lambda path: {})
    worker.prepare(worker.store.get(video), worker.probe(video), [])
    row = worker.store.get(video)
    project = json.loads((projects / row['project_id'] / 'project.json').read_text())
    selected = tasks._resolve_audio_track(project, None)
    wav_path = tmp_path / 'selected.wav'
    assert extract_audio(str(video), str(wav_path), track_index=selected)
    with wave.open(str(wav_path)) as wav:
        rate = wav.getframerate()
        samples = array.array('h', wav.readframes(wav.getnframes()))
    crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
    measured_frequency = crossings / (len(samples) / rate)
    assert 425 < measured_frequency < 455


@pytest.mark.parametrize('partial', [False, True])
def test_real_chinese_subtitle_attachment_respects_full_vs_partial(tmp_path, monkeypatch, partial):
    from app.utils.media import get_ffmpeg_path
    from app.engines.providers.codex_cli import CodexCliProvider
    root = tmp_path / 'media'
    root.mkdir()
    subtitle = tmp_path / ('Episode.zh.foreign.srt' if partial else 'Episode.zh.srt')
    subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\n这是附件中的中文字幕。\n')
    video = root / 'Episode.mkv'
    subprocess.run([
        get_ffmpeg_path(), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=64x64:d=1',
        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-map', '0:v:0', '-map', '1:a:0',
        '-c:v', 'mpeg4', '-c:a', 'pcm_s16le', '-metadata:s:a:0', 'language=eng',
        '-attach', str(subtitle), '-metadata:s:t:0', 'mimetype=application/x-subrip',
        '-metadata:s:t:0', 'language=chi', str(video),
    ], check=True)
    worker = LibraryWorker({'allowed_roots': [str(root)], 'quiet_seconds': 0}, tmp_path / 'state')
    worker.observe(video, {})
    monkeypatch.setattr(CodexCliProvider, 'check_logged_in', lambda: True)
    monkeypatch.setattr('os.getloadavg', lambda: (0, 0, 0))
    monkeypatch.setattr(worker, 'refresh_readiness', lambda: None)
    prepare = Mock()
    monkeypatch.setattr(worker, 'prepare', prepare)
    worker.process_one()
    assert prepare.call_count == int(partial)
    if not partial:
        assert worker.store.get(video)['state'] == 'skipped'
        assert '附件' in worker.store.get(video)['reason']


def language_conflict(tmp_path, monkeypatch):
    from app.services import translation_tasks as tasks
    worker, video = candidate(tmp_path, monkeypatch, name='朱元璋.S01E25.mkv')
    worker.config['enabled'] = True
    worker.observe(video, {'tmdb_id': 42, 'tmdb_type': 'tv'})
    monkeypatch.setattr(worker.sources, 'original_language', Mock(return_value='zh'))
    audio_only = Mock()
    monkeypatch.setattr(tasks, 'start_asr', audio_only)
    monkeypatch.setattr(tasks, 'is_task_registered', lambda pid: False)
    project, translate, combined = capture_project(worker, video, tmp_path, monkeypatch)
    from app.utils import project_store
    monkeypatch.setattr(project_store, 'PROJECTS_DIR', tasks.PROJECTS_DIR)
    audio_only.assert_called_once()
    translate.assert_not_called()
    combined.assert_not_called()
    assert project['library_verify_audio_language'] is True
    assert project['asr_language'] == 'auto'
    return worker, video, project, translate, audio_only


def complete_language_verification(worker, video, project, language='zh', probability=0.99):
    from app.services import translation_tasks as tasks
    project.update(status='asr_done', asr_detected_language={
        'language': language, 'probability': probability,
        'audio_track': project['selected_audio_track'],
        'fingerprint': worker.store.get(video)['fingerprint'],
    })
    (tasks.PROJECTS_DIR / project['id'] / 'project.json').write_text(json.dumps(project))


def test_mislabeled_english_chinese_audio_is_stopped_before_translation(tmp_path, monkeypatch):
    worker, video, project, translate, _ = language_conflict(tmp_path, monkeypatch)
    complete_language_verification(worker, video, project)
    worker.finish()
    assert worker.store.get(video)['state'] == 'native_language'
    assert 'ASR' in worker.store.get(video)['reason']
    translate.assert_not_called()
    assert not video.with_suffix('.双语.zh-CN.srt').exists()


def test_real_foreign_dub_of_chinese_original_is_translated(tmp_path, monkeypatch):
    worker, video, project, translate, audio_only = language_conflict(tmp_path, monkeypatch)
    complete_language_verification(worker, video, project, 'en')
    worker.finish()
    translate.assert_called_once()
    audio_only.assert_called_once()
    assert worker.store.get(video)['state'] == 'translating'
    assert worker.store.get(video)['language_verification_pending'] is False


@pytest.mark.parametrize(('language', 'probability'), [('zh', None), ('zh', 0.5), ('', 0.99), ('zh', float('nan'))])
def test_uncertain_audio_evidence_neither_skips_nor_calls_translation(tmp_path, monkeypatch, language, probability):
    worker, video, project, translate, _ = language_conflict(tmp_path, monkeypatch)
    complete_language_verification(worker, video, project, language, probability)
    worker.finish()
    assert worker.store.get(video)['state'] == 'error'
    assert '核验' in worker.store.get(video)['reason']
    translate.assert_not_called()


@pytest.mark.parametrize('change', ['download', 'replacement', 'subtitle', 'target'])
def test_language_handoff_keeps_media_and_subtitle_safety_gates(tmp_path, monkeypatch, change):
    worker, video, project, translate, _ = language_conflict(tmp_path, monkeypatch)
    complete_language_verification(worker, video, project, 'en')
    if change == 'download':
        worker.set_blockers({str(video): '下载仍在校验'})
    elif change == 'replacement':
        video.write_bytes(b'replacement video')
    else:
        subtitle = video.with_suffix('.zh.srt' if change == 'subtitle' else '.双语.zh-CN.srt')
        subtitle.write_text('已有中文字幕')
    worker.finish()
    translate.assert_not_called()
    assert worker.store.get(video)['state'] != 'native_language'
    if change in {'subtitle', 'target'}:
        assert subtitle.read_text() == '已有中文字幕'
    if change == 'download':
        worker.set_blockers({})
        worker.finish()
        translate.assert_called_once()


def test_language_verification_survives_worker_restart(tmp_path, monkeypatch):
    worker, video, project, translate, _ = language_conflict(tmp_path, monkeypatch)
    complete_language_verification(worker, video, project)
    restored = LibraryWorker(worker.config, tmp_path / 'state')
    monkeypatch.setattr(restored, 'refresh_readiness', lambda: None)
    restored.finish()
    assert restored.store.get(video)['state'] == 'native_language'
    translate.assert_not_called()


@pytest.mark.parametrize('action', ['pause', 'cancel'])
def test_language_verification_honors_stop_and_resume(tmp_path, monkeypatch, action):
    from app.services import translation_tasks as tasks
    worker, video, project, translate, audio_only = language_conflict(tmp_path, monkeypatch)
    complete_language_verification(worker, video, project)
    row = worker.store.get(video)
    worker.controls.request(str(video), action, worker.controls.revision(row))
    worker.finish()
    assert worker.store.get(video)['state'] == ('paused' if action == 'pause' else 'cancelled')
    translate.assert_not_called()
    if action == 'pause':
        monkeypatch.setattr(tasks, '_resume_stage_for_project', lambda *args: 'translate')
        row = worker.store.get(video)
        worker.controls.request(str(video), 'resume', worker.controls.revision(row))
        worker.process_one()
        assert worker.store.get(video)['state'] == 'native_language'
        audio_only.assert_called_once()
        translate.assert_not_called()


def test_global_pause_holds_foreign_language_handoff(tmp_path, monkeypatch):
    worker, video, project, translate, _ = language_conflict(tmp_path, monkeypatch)
    complete_language_verification(worker, video, project, 'en')
    worker.store.set_setting('enabled', False)
    worker.finish()
    translate.assert_not_called()
    worker.store.set_setting('enabled', True)
    worker.finish()
    translate.assert_called_once()


pytestmark = pytest.mark.usefixtures("library_codex_config")


@pytest.mark.parametrize('field', ['fingerprint', 'audio_track'])
def test_language_evidence_from_other_media_or_track_cannot_skip(tmp_path, monkeypatch, field):
    from app.services import translation_tasks as tasks
    worker, video, project, translate, _ = language_conflict(tmp_path, monkeypatch)
    complete_language_verification(worker, video, project)
    project['asr_detected_language'][field] = {} if field == 'fingerprint' else 99
    (tasks.PROJECTS_DIR / project['id'] / 'project.json').write_text(json.dumps(project))
    worker.finish()
    assert worker.store.get(video)['state'] == 'error'
    translate.assert_not_called()
