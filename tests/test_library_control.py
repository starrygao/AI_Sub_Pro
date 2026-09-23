from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from app.services import translation_tasks as tasks
from tests.test_library_hard_subtitles import setup


def action(client,worker,video,verb):
    return client.post('/api/library/tasks/control',json={'action':verb,'items':[{'path':str(video),'revision':worker.controls.revision(worker.store.get(video))}]}).json()['results'][0]


def test_queued_pause_survives_restart_resume_rechecks_and_cancel_never_requeues(setup,monkeypatch):
    worker,video,client=setup
    assert action(client,worker,video,'pause')['state']=='paused'
    worker.observe(video,{'show_title':'test'})
    probe=Mock();monkeypatch.setattr(worker,'probe',probe)
    worker.inspect_candidate(worker.store.get(video));probe.assert_not_called()
    from app.library.worker import LibraryWorker
    assert LibraryWorker(worker.config,video.parent.parent/'state').store.get(video)['state']=='paused'
    assert action(client,worker,video,'resume')['state']=='waiting'
    assert action(client,worker,video,'cancel')['state']=='cancelled'
    worker.observe(video,{})
    assert worker.store.get(video)['state']=='cancelled'
    assert not action(client,worker,video,'resume')['ok']


def test_running_pause_waits_for_thread_exit_and_never_publishes(setup,monkeypatch):
    worker,video,client=setup
    worker.save(worker.store.get(video),state='translating',project_id='deadbeef')
    running=True
    monkeypatch.setattr(tasks,'is_task_registered',lambda pid:running)
    cancel=Mock();monkeypatch.setattr(tasks,'cancel_task',cancel)
    stale=worker.store.get(video)
    assert action(client,worker,video,'pause')['state']=='pausing'
    cancel.assert_called_once_with('deadbeef')
    worker.save(stale,state='translating',reason='stale callback')
    assert worker.store.get(video)['state']=='pausing'
    worker.finish();assert worker.store.get(video)['state']=='pausing'
    running=False;worker.finish()
    assert worker.store.get(video)['state']=='paused'
    assert action(client,worker,video,'resume')['state']=='waiting'
    assert worker.store.get(video)['resume_pending']


def test_pause_during_extraction_exits_before_model_launch(setup,monkeypatch):
    worker,video,client=setup
    entered,release=Event(),Event()
    def prepare(row,info,sidecars):
        worker.save(row,state='translating',preparation_progress={'progress':42})
        entered.set();assert release.wait(3)
        worker.controls.check(str(video))
        pytest.fail('Must not launch model after pause')
    monkeypatch.setattr(worker,'_prepare',prepare)
    with ThreadPoolExecutor() as pool:
        future=pool.submit(worker.prepare,worker.store.get(video),{},[])
        assert entered.wait(3)
        assert action(client,worker,video,'pause')['state']=='pausing'
        release.set();future.result(timeout=3)
    assert worker.store.get(video)['state']=='paused'
    assert worker.store.get(video)['preparation_progress']['progress']==42


def test_batch_partial_results_and_stale_record_guard(setup):
    worker,video,client=setup
    fp=worker.controls.revision(worker.store.get(video))
    payload={'action':'cancel','items':[{'path':str(video),'revision':fp},{'path':'/missing','revision':fp}]}
    result=client.post('/api/library/tasks/control',json=payload).json()['results']
    assert [r['ok'] for r in result]==[True,False]
    assert client.post('/api/library/tasks/control',json={'action':'pause','items':[]}).status_code==422
    video.write_bytes(b'replacement video');worker.observe(video,{})
    assert not client.post('/api/library/tasks/control',json=payload).json()['results'][0]['ok']
    assert worker.store.get(video)['state']=='waiting'


def test_pause_during_probe_cannot_be_overwritten(setup,monkeypatch):
    worker,video,client=setup
    def probe(path):
        assert action(client,worker,video,'pause')['state']=='paused'
        return {'streams':[{'codec_type':'audio','tags':{'language':'eng'}}]}
    monkeypatch.setattr(worker,'probe',probe)
    worker.inspect_candidate(worker.store.get(video))
    assert worker.store.get(video)['state']=='paused'


def test_resume_reuses_project_and_cannot_start_until_reinspection(setup,monkeypatch):
    worker,video,client=setup
    worker.save(worker.store.get(video),state='paused',project_id='deadbeef',control_action='pause')
    monkeypatch.setattr(tasks,'is_task_registered',lambda pid:False)
    launch=Mock();monkeypatch.setattr(tasks,'start_translate',launch)
    monkeypatch.setattr(tasks,'_load_project',lambda pid:{'workflow_mode':'translate_only'})
    monkeypatch.setattr(tasks,'_resume_stage_for_project',lambda pid,p:'translate')
    assert action(client,worker,video,'resume')['state']=='waiting'
    launch.assert_not_called()
    worker.prepare(worker.store.get(video),{},[])
    assert launch.call_args.args[0]=='deadbeef'
    assert worker.store.get(video)['project_id']=='deadbeef'
    assert worker.store.get(video)['state']=='translating'


def test_completed_translation_paused_before_publish_does_not_repeat_model(setup,monkeypatch):
    worker,video,client=setup
    worker.save(worker.store.get(video),state='publishing',project_id='deadbeef')
    monkeypatch.setattr(tasks,'is_task_registered',lambda pid:False)
    launch=Mock();monkeypatch.setattr(tasks,'start_translate',launch)
    monkeypatch.setattr(tasks,'_load_project',lambda pid:{'status':'translated','workflow_mode':'translate_only'})
    assert action(client,worker,video,'pause')['state']=='paused'
    assert action(client,worker,video,'resume')['state']=='waiting'
    worker.prepare(worker.store.get(video),{},[])
    assert worker.store.get(video)['state']=='publishing'
    launch.assert_not_called()


def test_task_actions_require_auth_and_reject_cross_origin(setup):
    from fastapi.testclient import TestClient
    from app import server
    worker,video,client=setup
    body={'action':'pause','items':[{'path':str(video),'revision':worker.controls.revision(worker.store.get(video))}]}
    assert TestClient(server.app).post('/api/library/tasks/control',json=body).status_code==401
    assert client.post('/api/library/tasks/control',json=body,headers={'Origin':'https://foreign.test'}).status_code==403
    assert worker.store.get(video)['state']=='waiting'


def test_real_registered_worker_observes_pause_and_exits_before_acknowledgement(setup,tmp_project_dir,monkeypatch):
    import threading
    from app.utils.project_store import atomic_write_json
    from app.engines.scheduler import is_cancelled
    worker,video,client=setup
    pid='deadcafe';folder=tmp_project_dir/pid;folder.mkdir()
    atomic_write_json(folder/'project.json',{'id':pid,'name':'fixture','status':'processing','pipeline_stage':'translate','video_path':str(video),'workflow_mode':'translate_only'})
    worker.save(worker.store.get(video),state='translating',project_id=pid)
    started,release=Event(),Event()
    def run():
        try:
            started.set();assert release.wait(3)
            generation=getattr(threading.current_thread(),'_aisubpro_task_generation')
            assert is_cancelled(pid,generation=generation)
        finally:tasks.unregister_task(pid)
    thread=tasks.try_register_task(pid,lambda:threading.Thread(target=run),reset_cancellation=True)
    thread.start();assert started.wait(3)
    try:
        assert action(client,worker,video,'pause')['state']=='pausing'
        assert tasks.is_task_registered(pid)
    finally:release.set();thread.join(3)
    assert not thread.is_alive()
    worker.finish();assert worker.store.get(video)['state']=='paused'


def test_browser_revision_round_trip_avoids_nanosecond_integer_precision_loss(setup):
    import json
    worker,video,client=setup
    row=client.get('/api/library/tasks').json()['items'][0]
    assert row['fingerprint'][3]>2**53
    # Browser JSON numbers cannot represent arbitrary nanosecond timestamps.
    browser=json.loads(json.dumps(row),parse_int=lambda value:int(float(value)))
    result=client.post('/api/library/tasks/control',json={'action':'pause','items':[{'path':browser['path'],'revision':browser['control_revision']}]}).json()
    assert result['results'][0]['state']=='paused'


def test_missing_project_reports_item_failure_instead_of_aborting_batch(setup,monkeypatch):
    from fastapi import HTTPException
    worker,video,client=setup
    worker.save(worker.store.get(video),state='translating',project_id='deadbeef')
    monkeypatch.setattr(tasks,'is_task_registered',lambda pid:True)
    monkeypatch.setattr(tasks,'cancel_task',Mock(side_effect=HTTPException(404,'Project not found')))
    result=action(client,worker,video,'pause')
    assert not result['ok'] and 'Project not found' in result['error']
    assert worker.store.get(video)['state']=='translating'
