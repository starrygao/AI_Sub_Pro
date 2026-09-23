"""Recovery must preserve reviewed output and let independent arrivals progress."""
import hashlib
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.library.worker import LibraryWorker


@pytest.fixture
def library(tmp_path, monkeypatch):
    from app.engines.providers.codex_cli import CodexCliProvider
    from app.library import worker as module
    media = tmp_path / 'media'
    media.mkdir()
    worker = LibraryWorker({'new_only': True, 'roots': [str(media)],
                            'allowed_roots': [str(media)], 'quiet_seconds': 0}, tmp_path / 'state')
    worker.establish_baseline()
    monkeypatch.setattr(CodexCliProvider, 'check_logged_in', lambda: True)
    monkeypatch.setattr(module.os, 'getloadavg', lambda: (0, 0, 0))
    monkeypatch.setattr(worker.sources, 'metadata', lambda path: {})
    monkeypatch.setattr(worker, 'refresh_readiness', lambda: None)
    return worker, media


@pytest.mark.parametrize('suffix', ['.srt', '.双语.zh-CN.srt'])
@pytest.mark.parametrize('user_edited', [False, True])
def test_repeated_replacement_retires_only_owned_old_subtitle(library, monkeypatch, user_edited, suffix):
    worker, media = library
    video = media / 'Episode.mkv'
    video.write_bytes(b'first version')
    worker.observe(video, {})
    subtitle = video.with_suffix(suffix)
    old_text = '1\n00:00:00,000 --> 00:00:01,000\n这是旧版视频的中文字幕。\nOld version.\n'
    subtitle.write_text(old_text)
    worker.save(worker.store.get(video), state='done', project_id='1234abcd',
                output_hash=hashlib.sha256(subtitle.read_bytes()).hexdigest(), output_path=str(subtitle))
    if user_edited:
        subtitle.write_text(old_text.replace('旧版', '用户改过'))
    for content in (b'replacement partially written', b'replacement finished with a different cut'):
        video.write_bytes(content)
        worker.observe(video, {})
    prepare = Mock()
    monkeypatch.setattr(worker, 'prepare', prepare)
    monkeypatch.setattr(worker, 'probe', lambda path: {'streams': [
        {'codec_type': 'audio', 'tags': {'language': 'eng'}}]})
    worker.process_one()
    if user_edited:
        assert subtitle.is_file() and '用户改过' in subtitle.read_text()
        assert worker.store.get(video)['state'] == 'skipped'
        prepare.assert_not_called()
    else:
        assert not subtitle.exists()
        backups = list((media / '.aisub-backups').glob('*.bak'))
        assert len(backups) == 1 and backups[0].read_text() == old_text
        prepare.assert_called_once()


def test_failed_tmdb_candidate_backs_off_without_starving_ready_arrival(library, monkeypatch):
    from app.library import worker as module
    worker, media = library
    clock = [datetime.now(timezone.utc).timestamp()]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    high, low = media / 'EmbyUnknown.mkv', media / 'MoviePilotEnglish.mkv'
    high.write_bytes(b'unknown language')
    low.write_bytes(b'known foreign language')
    worker.observe(high, {'date_created': datetime.now(timezone.utc).isoformat(), 'tmdb_id': 1})
    worker.observe(low, {'metadata_source': 'moviepilot', 'tmdb_id': 2})
    language = Mock(side_effect=RuntimeError('TMDB unavailable'))
    monkeypatch.setattr(worker.sources, 'original_language', language)
    probe = Mock(side_effect=lambda path: {'streams': [
        {'codec_type': 'audio', 'tags': {'language': 'und' if path == high else 'eng'}}]})
    monkeypatch.setattr(worker, 'probe', probe)
    prepare = Mock(side_effect=lambda row,info,sidecars:worker.save(row,state='translating',project_id='1234abcd'))
    monkeypatch.setattr(worker, 'prepare', prepare)
    worker.process_one()
    worker.process_one()
    assert language.call_count == 1
    prepare.assert_called_once()
    assert prepare.call_args.args[0]['path'] == str(low)
    assert worker.store.get(high)['state'] == 'waiting'
    clock[0] += 3601
    worker.process_one()
    assert language.call_count == 2  # Deferred files are retried, not silently abandoned.


def test_backoff_filter_does_not_fill_the_candidate_page_with_deferred_rows(library, monkeypatch):
    import time
    worker, media = library
    for i in range(101):
        worker.store.put({'path': str(media / f'blocked-{i}.mkv'), 'state': 'waiting', 'priority': 1,
                          'next_attempt_at': time.time() + 600, 'updated': i})
    video = media / 'Ready.mkv'
    video.write_bytes(b'english')
    worker.observe(video, {})
    prepare = Mock()
    monkeypatch.setattr(worker, 'prepare', prepare)
    monkeypatch.setattr(worker, 'probe', lambda path: {'streams': [
        {'codec_type': 'audio', 'tags': {'language': 'eng'}}]})
    worker.process_one()
    prepare.assert_called_once()
    assert prepare.call_args.args[0]['path'] == str(video)


def test_blocked_high_priority_page_rotates_to_ready_lower_priority_arrival(library, monkeypatch):
    worker, media = library
    blocked = {}
    for i in range(101):
        video = media / f'downloading-{i}.mkv'
        video.write_bytes(b'partial download')
        worker.observe(video, {'date_created': datetime.now(timezone.utc).isoformat()})
        blocked[str(video)] = 'qB：下载尚未完成'
    ready = media / 'MoviePilotReady.mkv'
    ready.write_bytes(b'completed arrival')
    worker.observe(ready, {'metadata_source': 'moviepilot'})
    worker.set_blockers(blocked)
    probe = Mock(return_value={'streams': [{'codec_type': 'audio', 'tags': {'language': 'eng'}}]})
    prepare = Mock()
    monkeypatch.setattr(worker, 'probe', probe)
    monkeypatch.setattr(worker, 'prepare', prepare)
    worker.process_one()
    worker.process_one()
    probe.assert_called_once_with(ready)
    prepare.assert_called_once()


def test_publish_retry_reuses_certified_project_without_model_work(library, tmp_project_dir, monkeypatch):
    from app import server
    from app.library import worker as module
    from app.services import translation_tasks as tasks
    from tests.test_project_export import _seed_hash_bound_strict_certification
    worker, media = library
    video = media / 'Episode.mkv'
    video.write_bytes(b'video unchanged')
    worker.observe(video, {})
    pid = _seed_hash_bound_strict_certification(tmp_project_dir, '1234abcd')
    worker.save(worker.store.get(video), state='translating', project_id=pid)
    monkeypatch.setattr(tasks, 'is_task_registered', lambda pid: False)
    monkeypatch.setattr(worker.sources, 'refresh_subtitles', lambda pid: None)
    publish = module.publish_sidecar
    monkeypatch.setattr(module, 'publish_sidecar', Mock(side_effect=PermissionError('temporary permission failure')))
    worker.finish()
    assert worker.store.get(video)['state'] == 'error'
    assert (tmp_project_dir / pid / 'bilingual.srt').is_file()
    monkeypatch.setattr(server, 'worker', worker)
    monkeypatch.setattr(module, 'publish_sidecar', publish)
    start = Mock(side_effect=AssertionError('Publication retry must not invoke the model'))
    monkeypatch.setattr(worker, 'prepare', start)
    server.library_retry(server.Retry(path=str(video)))
    worker.finish()
    assert worker.store.get(video)['state'] == 'done'
    assert worker.store.get(video)['project_id'] == pid
    assert video.with_suffix('.双语.zh-CN.srt').read_bytes() == (tmp_project_dir / pid / 'bilingual.srt').read_bytes()
    start.assert_not_called()


@pytest.mark.parametrize('change', ['source', 'artifact'])
def test_publish_retry_still_rejects_changed_source_or_invalid_artifact(library, tmp_project_dir, monkeypatch, change):
    from app import server
    from app.services import translation_tasks as tasks
    from tests.test_project_export import _seed_hash_bound_strict_certification
    worker, media = library
    video = media / 'Episode.mkv'
    video.write_bytes(b'original video')
    worker.observe(video, {})
    pid = _seed_hash_bound_strict_certification(tmp_project_dir, '1234abcd')
    worker.save(worker.store.get(video), state='error', project_id=pid, retry_stage='publish')
    if change == 'source':
        video.write_bytes(b'replaced video')
    else:
        (tmp_project_dir / pid / 'bilingual.srt').write_text('tampered output')
    monkeypatch.setattr(server, 'worker', worker)
    monkeypatch.setattr(tasks, 'is_task_registered', lambda pid: False)
    server.library_retry(server.Retry(path=str(video)))
    worker.finish()
    assert not video.with_suffix('.双语.zh-CN.srt').exists()
    assert worker.store.get(video)['state'] in {'changed', 'error'}
    if change == 'artifact':
        assert not worker.store.get(video).get('retry_stage')


def test_pending_emby_refresh_is_not_limited_to_latest_completed_tasks(library, monkeypatch):
    worker, media = library
    for i in range(51):
        worker.store.put({'path': str(media / f'{i}.mkv'), 'state': 'done', 'updated': i + 1,
                          'refresh_pending': i == 0, 'metadata': {'emby_id': str(i)}})
    for name in ('apply_storage_settings', 'finish', 'apply_pending_settings', 'discover', 'process_one'):
        monkeypatch.setattr(worker, name, lambda **kwargs: False)
    monkeypatch.setattr(worker.directories, 'apply', lambda: None)
    refresh = Mock()
    monkeypatch.setattr(worker.sources, 'refresh_subtitles', refresh)
    worker.tick()
    refresh.assert_called_once_with('0')
    assert not worker.store.get(media / '0.mkv')['refresh_pending']


def test_failed_emby_refresh_batch_rotates_to_remaining_pending_rows(library, monkeypatch):
    worker, media = library
    for i in range(60):
        worker.store.put({'path': str(media / f'{i}.mkv'), 'state': 'done', 'updated': i + 1,
                          'refresh_pending': True, 'metadata': {'emby_id': str(i)}})
    for name in ('apply_storage_settings', 'finish', 'apply_pending_settings', 'discover', 'process_one'):
        monkeypatch.setattr(worker, name, lambda **kwargs: False)
    monkeypatch.setattr(worker.directories, 'apply', lambda: None)
    refresh = Mock(side_effect=RuntimeError('Emby offline'))
    monkeypatch.setattr(worker.sources, 'refresh_subtitles', refresh)
    worker.tick()
    worker.tick()
    assert {call.args[0] for call in refresh.call_args_list} == {str(i) for i in range(60)}
