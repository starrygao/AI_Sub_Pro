import hashlib
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from app import server
from app.library.worker import LibraryWorker
from app.library import cleanup as module
from app.library.guard import fingerprint


NOW=time.time()+200000


@pytest.fixture
def setup(tmp_path,monkeypatch):
    worker=LibraryWorker({},tmp_path/'data')
    monkeypatch.setattr(module,'GIB',100)  # Small deterministic fixtures, same policy bounds.
    from app.services import translation_tasks as tasks
    monkeypatch.setattr(tasks,'active_tasks',{})
    return worker,worker.cleanup


def artifact(worker,pid,size,*,state='done',age=100000):
    root=Path(worker.store.path).parent
    folder=root/'projects'/pid;folder.mkdir(parents=True)
    audio=folder/'raw_audio.wav';audio.write_bytes(b'a'*size);os.utime(audio,(age,age))
    subtitle=folder/'bilingual.srt';subtitle.write_text('保留最终字幕')
    video=root/(pid+'.mkv');video.write_bytes(b'source video')
    worker.store.put({'path':str(video),'fingerprint':fingerprint(video),'state':state,'updated':1,'project_id':pid,
        'completed_at':age,'output_path':str(subtitle),'output_hash':hashlib.sha256(subtitle.read_bytes()).hexdigest()})
    return audio,subtitle


def test_threshold_cleanup_keeps_outputs_projects_failed_work_and_recent_files(setup,monkeypatch):
    worker,cleanup=setup
    old,subtitle=artifact(worker,'11111111',700)
    recent,_=artifact(worker,'22222222',100,age=NOW-1)
    failed,_=artifact(worker,'33333333',100,state='error')
    cleanup.configure(True,5)
    cleanup.tick(now=NOW)
    assert not old.exists()
    assert subtitle.read_text()=='保留最终字幕' and recent.exists() and failed.exists()
    assert len(worker.store.rows())==3
    assert cleanup.snapshot()['last_run']['freed_bytes']==700


def test_policy_minimum_and_api_auth(setup,monkeypatch):
    worker,cleanup=setup
    monkeypatch.setattr(server,'worker',worker)
    monkeypatch.setattr(server.app.state,'operator_token','fixture-only',raising=False)
    client=TestClient(server.app)
    assert client.get('/api/library/cleanup').status_code==401
    client.headers['X-AISub-Key']='fixture-only'
    for value in [0,1,4,-1,5.5,True,'5']:
        assert client.post('/api/library/cleanup',json={'enabled':True,'limit_gb':value}).status_code==422
    assert client.post('/api/library/cleanup',json={'enabled':True,'limit_gb':5}).status_code==200
    assert LibraryWorker({},Path(worker.store.path).parent).cleanup.policy()=={'enabled':True,'limit_gb':5}


def test_disabled_below_limit_and_active_task_do_not_delete(setup,monkeypatch):
    worker,cleanup=setup
    old,_=artifact(worker,'11111111',700)
    cleanup.tick(now=NOW);assert old.exists()
    cleanup.configure(True,10);cleanup.tick(now=NOW);assert old.exists()
    from app.services import translation_tasks as tasks
    monkeypatch.setattr(tasks,'active_tasks',{'running':object()})
    cleanup.configure(True,5);cleanup.tick(now=NOW);assert old.exists()
    assert cleanup.snapshot()['last_run']['status']=='busy'


def test_changed_published_subtitle_and_unregistered_project_are_preserved(setup):
    worker,cleanup=setup
    old,subtitle=artifact(worker,'11111111',700)
    subtitle.write_text('用户修订过的字幕')
    cleanup.configure(True,5);cleanup.tick(now=NOW)
    assert old.exists()
    assert cleanup.snapshot()['last_run']['status']=='protected_remaining'


def test_parent_symlink_swap_cannot_redirect_deletion(setup,tmp_path,monkeypatch):
    worker,cleanup=setup
    old,_=artifact(worker,'11111111',700)
    original=cleanup.inventory(NOW)
    folder=old.parent;retired=folder.with_name('retired');folder.rename(retired)
    outside=tmp_path/'outside';outside.mkdir();valuable=outside/'raw_audio.wav';valuable.write_bytes(b'keep')
    folder.symlink_to(outside,target_is_directory=True)
    monkeypatch.setattr(cleanup,'inventory',lambda now=None:original)
    cleanup.clean(NOW,5)
    assert valuable.read_bytes()==b'keep' and (retired/'raw_audio.wav').exists()


def test_file_changed_after_inventory_and_other_tmp_files_are_preserved(setup,monkeypatch):
    worker,cleanup=setup
    old,_=artifact(worker,'11111111',700)
    inventory=cleanup.inventory(NOW);old.write_bytes(b'changed')
    monkeypatch.setattr(cleanup,'inventory',lambda now=None:inventory)
    cleanup.clean(NOW,5);assert old.read_bytes()==b'changed'


def test_only_owned_old_temporary_files_are_cleanable(setup):
    worker,cleanup=setup
    root=Path(worker.store.path).parent/'temporary';root.mkdir()
    stale=root/'aisubpro-codex-old.txt';stale.write_bytes(b'x'*700);os.utime(stale,(100000,100000))
    keep=root/'private.txt';keep.write_bytes(b'important')
    link=root/'aisubpro-codex-link.txt';link.symlink_to(keep)
    cleanup.configure(True,5);cleanup.tick(now=NOW)
    assert not stale.exists() and keep.read_bytes()==b'important' and link.is_symlink()


def test_missing_source_video_prevents_removal_of_audio(setup):
    worker,cleanup=setup
    old,_=artifact(worker,'11111111',700)
    Path(worker.store.rows()[0]['path']).unlink()
    cleanup.configure(True,5);cleanup.tick(now=NOW)
    assert old.exists()


def test_recent_copy_with_old_mtime_is_still_protected(setup):
    worker,cleanup=setup
    old,_=artifact(worker,'11111111',700)
    cleanup.configure(True,5);cleanup.tick(now=time.time())
    assert old.exists()
    assert cleanup.snapshot()['last_run']['status']=='protected_remaining'


def test_pinned_unlink_rejects_parent_symlink_even_after_inventory(setup,tmp_path):
    worker,cleanup=setup
    old,_=artifact(worker,'11111111',700)
    candidate=cleanup.inventory(NOW)[1][0]
    folder=old.parent;folder.rename(folder.with_name('retired'))
    outside=tmp_path/'outside';outside.mkdir();valuable=outside/'raw_audio.wav';valuable.write_bytes(b'keep')
    folder.symlink_to(outside,target_is_directory=True)
    with pytest.raises(OSError):module.unlink_unchanged(candidate)
    assert valuable.read_bytes()==b'keep'


def test_cleanup_failure_is_recorded_without_blocking_worker(setup,monkeypatch):
    worker,cleanup=setup
    cleanup.configure(True,5)
    def fail(*args):raise OSError('inaccessible temporary directory')
    monkeypatch.setattr(cleanup,'clean',fail)
    cleanup.tick(now=NOW)
    assert cleanup.store.setting('cleanup_last_run')['status']=='error'
