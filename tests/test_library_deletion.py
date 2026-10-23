from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock
from pathlib import Path

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


def project_files(worker,video):
    from app.library.cleanup import PROJECT_FILES
    folder=Path(worker.store.path).parent/'projects'/'deadbeef'
    names=[*PROJECT_FILES,'subtitles.srt','translation_checkpoint.json','project.json','custom.wav']
    files={}
    for name in names:
        path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name);files[name]=path
    video.with_suffix('.srt').write_text('published subtitles')
    worker.save(worker.store.get(video),state='done',project_id='deadbeef')
    return files


def delete_with_cleanup(worker,video,client,**options):
    return client.post('/api/library/tasks/control',json={'action':'delete',**options,'items':[
        {'path':str(video),'revision':worker.controls.revision(worker.store.get(video))}]})


@pytest.mark.parametrize('cleanup',[False,True])
def test_cleanup_is_opt_in_and_never_deletes_media_subtitles_or_checkpoints(setup,cleanup):
    from app.library.cleanup import PROJECT_FILES
    worker,video,client=setup;files=project_files(worker,video)
    options={'cleanup_files':True} if cleanup else {}
    result=delete_with_cleanup(worker,video,client,**options).json()['results'][0]
    assert result['ok'] and result['state']=='deleted'
    for name,path in files.items():assert path.exists()==(not cleanup or name not in PROJECT_FILES)
    assert video.read_bytes()==b'video' and video.with_suffix('.srt').read_text()=='published subtitles'


def test_cleanup_waits_for_exit_survives_callback_and_restart(setup,monkeypatch):
    worker,video,client=setup;files=project_files(worker,video)
    worker.save(worker.store.get(video),state='translating')
    running=True
    monkeypatch.setattr(tasks,'is_task_registered',lambda pid:running)
    monkeypatch.setattr(tasks,'cancel_task',Mock())
    stale=worker.store.get(video)
    result=delete_with_cleanup(worker,video,client,cleanup_files=True).json()['results'][0]
    assert result['ok'] and result['state']=='cancelling'
    worker.save(stale,state='publishing');worker.controls.settle()
    assert files['raw_audio.wav'].exists() and worker.store.get(video)['cleanup_files']
    restored=LibraryWorker(worker.config,Path(worker.store.path).parent)
    running=False;restored.controls.settle()
    assert restored.store.get(video)['state']=='deleted' and not files['raw_audio.wav'].exists()


def test_cleanup_defers_while_another_pipeline_owns_registry_lock(setup,monkeypatch):
    worker,video,client=setup;files=project_files(worker,video)
    idle=tasks.run_when_tasks_idle
    monkeypatch.setattr(tasks,'run_when_tasks_idle',lambda action:False)
    assert delete_with_cleanup(worker,video,client,cleanup_files=True).json()['results'][0]['state']=='cancelling'
    worker.controls.settle();assert files['raw_audio.wav'].exists()
    monkeypatch.setattr(tasks,'run_when_tasks_idle',idle)
    worker.controls.settle();assert not files['raw_audio.wav'].exists()


@pytest.mark.parametrize('unsafe',['file_link','directory_link','root_link','hard_link','invalid_id'])
def test_cleanup_rejects_unsafe_paths_and_keeps_task_visible_for_retry(setup,tmp_path,unsafe):
    import os
    worker,video,client=setup;files=project_files(worker,video)
    outside=tmp_path/'outside';outside.mkdir();sentinel=outside/'raw_audio.wav';sentinel.write_text('preserve')
    audio=files['raw_audio.wav'];root=audio.parent.parent
    if unsafe=='invalid_id':worker.save(worker.store.get(video),project_id='../outside')
    elif unsafe=='directory_link':audio.parent.rename(root/'saved');audio.parent.symlink_to(outside,target_is_directory=True)
    elif unsafe=='root_link':root.rename(root.with_name('saved-projects'));root.symlink_to(outside,target_is_directory=True)
    else:
        audio.unlink()
        if unsafe=='hard_link':os.link(sentinel,audio)
        else:audio.symlink_to(sentinel)
    result=delete_with_cleanup(worker,video,client,cleanup_files=True).json()['results'][0]
    assert not result['ok'] and result['state']=='error'
    row=client.get('/api/library/tasks?view=processed').json()['items'][0]
    assert row['delete_error'] and row['available_actions']==['delete']
    assert sentinel.read_text()=='preserve'
    # Retrying without cleanup still allows the user to remove the task safely.
    assert delete_with_cleanup(worker,video,client).json()['results'][0]['state']=='deleted'


def test_deferred_cleanup_failure_is_visible_and_can_be_retried(setup,monkeypatch):
    from app.library import cleanup
    worker,video,client=setup;files=project_files(worker,video)
    running=True
    monkeypatch.setattr(tasks,'is_task_registered',lambda pid:running)
    monkeypatch.setattr(tasks,'cancel_task',Mock())
    delete_with_cleanup(worker,video,client,cleanup_files=True)
    running=False
    with monkeypatch.context() as patch:
        patch.setattr(cleanup,'unlink_unchanged',Mock(side_effect=PermissionError('denied')))
        worker.controls.settle()
    assert worker.store.get(video)['state']=='error' and files['raw_audio.wav'].exists()
    assert delete_with_cleanup(worker,video,client,cleanup_files=True).json()['results'][0]['ok']
    assert not files['raw_audio.wav'].exists()


@pytest.mark.parametrize('options',[{'cleanup_files':'true'},{'action':'pause','cleanup_files':True}])
def test_cleanup_requires_boolean_and_delete_action(setup,options):
    worker,video,client=setup
    assert delete_with_cleanup(worker,video,client,**options).status_code==422
    assert worker.store.get(video)['state']=='waiting'


def test_processed_pagination_prioritizes_current_and_attention_before_history(setup):
    worker,video,client=setup
    for i in range(30):
        other=video.with_name(f'{i}.mkv');other.write_bytes(b'fixture');worker.observe(other,{})
        worker.save(worker.store.get(other),state='done')
    row=worker.store.get(video);row.update(state='translating',updated=1);worker.store.put(row)
    attention=worker.store.get(video.with_name('0.mkv'));attention.update(state='error',updated=2);worker.store.put(attention)
    items=client.get('/api/library/tasks?view=processed&limit=20').json()['items']
    assert [r['state'] for r in items[:2]]==['translating','error']
    assert len(items)==20 and len({r['path'] for r in items})==20
