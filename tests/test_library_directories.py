from pathlib import Path
import threading

import pytest

from app.library.worker import LibraryWorker
from app.library.directories import DirectorySettings


def make_worker(tmp_path):
    media = tmp_path / 'media'; media.mkdir()
    first = media / 'first'; first.mkdir()
    worker = LibraryWorker({'new_only': True, 'roots': [str(first)], 'allowed_roots': [str(media)],
                            'host_path_maps': {str(media): '/vol2/media'}}, tmp_path / 'data')
    worker.establish_baseline()
    return worker, media, first


def test_adding_parent_preserves_new_arrivals_in_existing_root_and_excludes_old_siblings(tmp_path):
    worker, media, first = make_worker(tmp_path)
    new = first / 'new.mkv'; new.write_bytes(b'new')
    worker.observe(new, {})
    old = media / 'old.mkv'; old.write_bytes(b'old')
    settings = DirectorySettings(worker)
    settings.queue(['/vol2/media'])
    assert settings.read()['pending']
    assert settings.apply()
    assert worker.eligible_new_path(new)
    assert not worker.eligible_new_path(old)
    assert worker.store.get(new)['state'] == 'waiting'
    restored = LibraryWorker(worker.config, tmp_path / 'data')
    assert restored.roots == [str(media)]


def test_empty_roots_stop_discovery_and_do_not_delete_media_or_history(tmp_path, monkeypatch):
    worker, media, first = make_worker(tmp_path)
    new = first / 'new.mkv'; new.write_bytes(b'new'); worker.observe(new, {})
    worker.store.put({'path': str(first / 'done.mkv'), 'state': 'done', 'project_id': 'deadbeef', 'updated': 1})
    settings = DirectorySettings(worker); settings.queue([])
    assert settings.apply()
    monkeypatch.setattr(worker.sources, 'libraries', lambda: pytest.fail('Explicit empty list must not rediscover Emby roots'))
    worker.discover(); worker.establish_baseline()
    assert worker.roots == [] and not worker.eligible_new_path(new)
    assert new.exists() and worker.store.get(new) is None
    assert worker.store.counts() == {'done': 1}


def test_root_changes_wait_for_running_task_and_reject_unmounted_or_symlink_paths(tmp_path, monkeypatch):
    worker, media, first = make_worker(tmp_path)
    settings = DirectorySettings(worker)
    from app.services import translation_tasks
    monkeypatch.setattr(translation_tasks, 'active_tasks', {'deadbeef': object()})
    settings.queue([]); assert not settings.apply()
    assert worker.roots == [str(first)]
    outside = tmp_path / 'private'; outside.mkdir(); (media / 'escape').symlink_to(outside)
    for path in ['/vol1/private', '/vol2/media/escape', '/vol2/media/missing', '/vol2/media/../private']:
        with pytest.raises(ValueError): settings.queue([path])
    assert settings.read()['desired'] == []


def test_authenticated_directory_api_validates_paths_and_preserves_configuration(tmp_path, monkeypatch):
    from app import server
    from app.library.storage import StoragePaths
    from fastapi.testclient import TestClient
    worker, media, first = make_worker(tmp_path)
    worker.storage = StoragePaths(tmp_path / 'storage', '/vol2/aisub', tmp_path / 'links')
    worker.storage.initialize()
    monkeypatch.setattr(server, 'worker', worker)
    monkeypatch.setattr(server.app.state, 'operator_token', 'fixture-token', raising=False)
    client = TestClient(server.app, headers={'X-AISub-Key': 'fixture-token'})
    assert client.get('/api/library/directories').json()['watch']['current'] == ['/vol2/media/first']
    assert client.post('/api/library/directories/watch', json={'roots': ['/outside']}).status_code == 400
    assert client.post('/api/library/directories/watch', json={'roots': []}).json()['pending']
    desired = dict(worker.storage.state()['current'], data='/vol2/aisub/new-data')
    response = client.post('/api/library/directories/storage', json=desired)
    assert response.status_code == 200 and response.json()['pending']
    assert worker.storage.state()['current']['data'] == '/vol2/aisub/data'
    assert client.post('/api/library/directories/storage', json=desired, headers={'Origin': 'https://other.test'}).status_code == 403


@pytest.mark.parametrize('replacements', [('third',), ('first',), ('third', 'second')])
def test_newer_directory_save_or_cancel_survives_an_inflight_baseline(tmp_path, monkeypatch, replacements):
    from app import server
    from fastapi.testclient import TestClient
    worker, media, first = make_worker(tmp_path)
    for name in ['second', 'third']:
        folder = media / name; folder.mkdir()
        (folder / 'existing.mkv').write_bytes(b'existing')
    monkeypatch.setattr(server, 'worker', worker)
    monkeypatch.setattr(server.app.state, 'operator_token', 'fixture-token', raising=False)
    client = TestClient(server.app, headers={'X-AISub-Key': 'fixture-token'})
    entered, release = threading.Event(), threading.Event()
    filesystem = worker.filesystem

    def paused_scan(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        yield from filesystem(*args, **kwargs)

    monkeypatch.setattr(worker, 'filesystem', paused_scan)
    assert client.post('/api/library/directories/watch', json={'roots': ['/vol2/media/second']}).status_code == 200
    results = []
    thread = threading.Thread(target=lambda: results.append(worker.directories.apply()))
    thread.start()
    try:
        assert entered.wait(5)
        for name in replacements:
            saved = client.post('/api/library/directories/watch', json={'roots': ['/vol2/media/' + name]})
            assert saved.status_code == 200
            assert saved.json()['desired'] == ['/vol2/media/' + name]
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive()
    assert results == [False], 'An obsolete inventory must not commit or clear a newer request'
    state = client.get('/api/library/directories').json()['watch']
    assert state['current'] == ['/vol2/media/first']
    assert state['desired'] == ['/vol2/media/' + replacements[-1]]
    assert worker.store.setting('baseline')['count'] == 0
    should_apply = replacements[-1] != 'first'
    assert state['pending'] is should_apply
    assert worker.directories.apply() is should_apply
    assert worker.roots == [str(media / replacements[-1])]
    assert not worker.directories.read()['pending']
    restored = LibraryWorker(worker.config, tmp_path / 'data')
    assert restored.roots == worker.roots
