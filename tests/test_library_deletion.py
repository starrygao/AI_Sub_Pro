from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from app.library.worker import LibraryWorker
from app.services import translation_tasks as tasks
from tests.test_library_control import action
from tests.test_library_hard_subtitles import setup


@pytest.mark.parametrize('state', ['waiting', 'ready', 'paused', 'cancelled', 'done', 'error', 'skipped', 'missing'])
def test_delete_removes_record_and_counts_but_preserves_media_and_scan_exclusion(setup, state):
    worker, video, client = setup
    subtitle = video.with_suffix('.srt'); subtitle.write_text('existing subtitles')
    worker.save(worker.store.get(video), state=state)
    assert 'delete' in client.get('/api/library/tasks').json()['items'][0]['available_actions']
    assert action(client, worker, video, 'delete')['state'] == 'deleted'
    worker.observe(video, {'show_title': 'Updated metadata'})
    restored = LibraryWorker(worker.config, video.parent.parent / 'state')
    restored.observe(video, {})
    assert restored.store.get(video)['state'] == 'deleted'
    for query in ('', '?view=processed', '?view=waiting', '?view=skipped', '?state=deleted'):
        response = client.get('/api/library/tasks' + query).json()
        assert response['items'] == [] and response['total'] == 0
        assert not any(response['view_counts'].values())
    assert restored.store.counts() == {}
    assert video.read_bytes() == b'video'
    assert subtitle.read_text() == 'existing subtitles'


def test_running_delete_waits_for_exit_and_stale_callbacks_cannot_restore_record(setup, monkeypatch):
    worker, video, client = setup
    worker.save(worker.store.get(video), state='translating', project_id='deadbeef')
    running = True
    monkeypatch.setattr(tasks, 'is_task_registered', lambda pid: running)
    cancel = Mock(); monkeypatch.setattr(tasks, 'cancel_task', cancel)
    stale = worker.store.get(video)
    assert action(client, worker, video, 'delete')['state'] == 'cancelling'
    cancel.assert_called_once_with('deadbeef')
    worker.finish()
    assert worker.store.get(video)['state'] == 'cancelling'
    assert client.get('/api/library/tasks').json()['items'][0]['available_actions'] == []
    running = False
    worker.finish()
    worker.save(stale, state='publishing', reason='late completion callback')
    assert worker.store.get(video)['state'] == 'deleted'
    assert client.get('/api/library/tasks').json()['items'] == []


def test_delete_during_extraction_waits_and_prevents_model_launch(setup, monkeypatch):
    worker, video, client = setup
    entered, release = Event(), Event()
    def prepare(row, info, sidecars):
        worker.save(row, state='translating', preparation_progress={'progress': 42})
        entered.set(); assert release.wait(3)
        worker.controls.check(str(video))
        pytest.fail('Deleted task must not launch a model')
    monkeypatch.setattr(worker, '_prepare', prepare)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(worker.prepare, worker.store.get(video), {}, [])
        assert entered.wait(3)
        try:
            assert action(client, worker, video, 'delete')['state'] == 'cancelling'
        finally:
            release.set()
        future.result(timeout=3)
    assert worker.store.get(video)['state'] == 'deleted'


def test_batch_delete_keeps_stale_and_missing_items_as_individual_failures(setup):
    worker, video, client = setup
    other = video.with_name('other.mkv'); other.write_bytes(b'other'); worker.observe(other, {})
    stale = worker.controls.revision(worker.store.get(other))
    other.write_bytes(b'replaced'); worker.observe(other, {})
    items = [{'path': str(video), 'revision': worker.controls.revision(worker.store.get(video))},
             {'path': str(other), 'revision': stale}, {'path': '/missing', 'revision': stale}]
    result = client.post('/api/library/tasks/control', json={'action': 'delete', 'items': items}).json()
    assert [r['ok'] for r in result['results']] == [True, False, False]
    assert worker.store.get(other)['state'] == 'waiting'
    assert client.get('/api/library/tasks').json()['total'] == 1


def test_deleted_video_can_be_explicitly_added_again_without_old_project(setup, monkeypatch):
    from app.library.selection import EmbySelection
    worker, video, client = setup
    worker.save(worker.store.get(video), state='done', project_id='deadbeef')
    action(client, worker, video, 'delete')
    item = {'Id': '1', 'Type': 'Movie', 'Name': 'Fixture', 'Path': str(video)}
    monkeypatch.setattr(worker.sources, 'emby', lambda *args, **kwargs: {'Items': [item]})
    selection = EmbySelection(worker)
    assert selection.describe(item)['selectable']
    assert selection.enqueue(['1'])['items'][0]['status'] == 'queued'
    row = worker.store.get(video)
    assert row['state'] == 'waiting' and row['manual_requested']
    assert not row.get('project_id') and not row.get('control_action')
    assert not selection.describe(item)['selectable']


@pytest.mark.parametrize('project_id', [None, 'deadbeef'])
def test_baseline_and_directory_changes_do_not_resurrect_deleted_records(setup, project_id):
    worker, video, client = setup
    worker.save(worker.store.get(video), state='done', project_id=project_id)
    action(client, worker, video, 'delete')
    worker.store.install_baseline([(str(video), worker.store.get(video)['fingerprint'])], worker.roots)
    worker.store.exclude_baseline_rows()
    worker.store.exclude_unstarted_outside_roots([])
    assert worker.store.get(video)['state'] == 'deleted'
