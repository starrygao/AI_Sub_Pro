import copy
from pathlib import Path
import pytest
from fastapi import HTTPException
from app.config import Config, DEFAULT_CONFIG
from app.library.worker import LibraryWorker
from app.services import translation_tasks as tasks


@pytest.fixture
def worker(tmp_path, monkeypatch, tmp_project_dir):
    monkeypatch.setattr(Config, '_data', copy.deepcopy(DEFAULT_CONFIG))
    monkeypatch.setattr(tasks, 'active_tasks', {})
    return LibraryWorker({'enabled':True}, tmp_path/'library')


def test_model_edit_is_durable_and_waits_for_translation_and_publication(worker):
    original=Config.get('translation','primary_model')
    worker.store.put({'path':'/video/test.mkv','state':'translating','updated':1})
    result=worker.model_settings.queue({'translation':{'primary_model':'gpt-5.5','primary_effort':'high'}})
    assert result['state']['pending']
    assert result['settings']['translation']['primary_model']=='gpt-5.5'
    assert Config.get('translation','primary_model')==original
    assert not worker.apply_pending_settings()
    row=worker.store.get('/video/test.mkv');row['state']='publishing';worker.store.put(row)
    assert not worker.apply_pending_settings()
    # Pending choices survive worker recreation, including while automation is enabled.
    restored=LibraryWorker({'enabled':True}, Path(worker.store.path).parent)
    assert restored.model_settings.read()['settings']['translation']['primary_effort']=='high'
    row['state']='error';worker.store.put(row)
    assert restored.apply_pending_settings()
    assert Config.get('translation','primary_model')=='gpt-5.5'
    assert not restored.model_settings.read()['state']['pending']


def test_registered_task_blocks_apply_even_before_discovery_row_is_updated(worker,monkeypatch):
    worker.model_settings.queue({'translation':{'primary_model':'gpt-5.5'}})
    tasks.active_tasks['deadbeef']=object()
    assert not worker.apply_pending_settings()
    tasks.active_tasks.clear()
    assert worker.apply_pending_settings()


def test_polish_settings_are_independent_durable_and_wait_until_idle(worker):
    original = Config.get('translation', 'primary_model')
    tasks.active_tasks['deadbeef'] = object()
    polish = {'polish_provider': 'codex_cli', 'polish_model': 'gpt-5.5', 'polish_effort': 'high'}
    result = worker.model_settings.queue({'translation': polish})
    assert result['settings']['translation']['polish_model'] == 'gpt-5.5'
    assert result['state']['current_polish_provider'] == ''
    assert not worker.apply_pending_settings()
    restored = LibraryWorker({'enabled': True}, Path(worker.store.path).parent)
    assert restored.model_settings.read()['settings']['translation']['polish_effort'] == 'high'
    tasks.active_tasks.clear()
    assert restored.apply_pending_settings()
    assert Config.get('translation', 'primary_model') == original
    assert restored.model_settings.state()['current_polish_model'] == 'gpt-5.5'
    assert restored.model_settings.state()['current_polish_effort'] == 'high'
    restored.model_settings.queue({'translation': {'polish_provider': '', 'polish_model': '', 'polish_effort': 'auto'}})
    assert restored.apply_pending_settings()
    assert Config.get('translation', 'polish_provider') == ''
    with pytest.raises(HTTPException):
        restored.model_settings.queue({'translation': {'polish_provider': 'unknown-provider'}})


def test_pending_edits_merge_validate_and_can_be_reverted(worker):
    original=Config.get('translation','primary_model')
    worker.model_settings.queue({'translation':{'primary_model':'gpt-5.5'}})
    worker.model_settings.queue({'asr':{'beam_size':3}})
    assert worker.model_settings.read()['settings']['translation']['primary_model']=='gpt-5.5'
    for invalid in [{'translation':{'primary_effort':'wrong'}},{'asr':{'beam_size':0}},{'api_keys':{'openai':'never-store'}},{'translation':{'primary_provider':'unknown'}}]:
        with pytest.raises(HTTPException):worker.model_settings.queue(invalid)
    assert 'never-store' not in str(worker.store.setting('pending_model_settings',{}))
    worker.model_settings.queue({'translation':{'primary_model':original},'asr':{'beam_size':DEFAULT_CONFIG['asr']['beam_size']}})
    assert not worker.model_settings.read()['state']['pending']


def test_failed_save_keeps_pending_choices_and_prevents_next_start(worker,monkeypatch):
    worker.model_settings.queue({'translation':{'primary_model':'gpt-5.5'}})
    monkeypatch.setattr(Config,'update',lambda data:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):worker.apply_pending_settings()
    assert worker.model_settings.read()['state']['pending']


def test_pending_settings_apply_after_finish_before_next_task(worker,monkeypatch):
    events=[]
    monkeypatch.setattr(worker,'refresh_readiness',lambda:None)
    monkeypatch.setattr(worker,'finish',lambda:events.append('finish'))
    monkeypatch.setattr(worker,'apply_pending_settings',lambda:events.append('settings'))
    monkeypatch.setattr(worker,'discover',lambda:None)
    monkeypatch.setattr(worker,'process_one',lambda **kwargs:events.append('start'))
    from app.engines.providers.codex_cli import CodexCliProvider
    monkeypatch.setattr(CodexCliProvider,'check_logged_in',lambda:True)
    worker.tick()
    assert events==['finish','settings','start']


def test_authenticated_endpoint_accepts_edits_while_automatic_task_runs(worker, monkeypatch):
    from app import server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, 'worker', worker)
    monkeypatch.setattr(server.app.state, 'operator_token', 'fixture-token', raising=False)
    client=TestClient(server.app,headers={'X-AISub-Key':'fixture-token'})
    original=Config.get('translation','primary_model')
    worker.store.put({'path':'/video/running.mkv','state':'translating','updated':1})
    response=client.post('/api/library/settings',json={'translation':{'primary_model':'gpt-5.5'}})
    assert response.status_code==200 and response.json()['state']['pending']
    assert Config.get('translation','primary_model')==original
    assert worker.wake.is_set()
    assert client.get('/api/library/settings').json()['settings']['translation']['primary_model']=='gpt-5.5'
    assert client.post('/api/library/settings',json={'api_keys':{'openai':'secret'}}).status_code==400
    assert client.post('/api/library/settings',json={},headers={'Origin':'http://other.test'}).status_code==403


def test_primary_provider_switch_is_atomic_and_waits_for_running_task(worker):
    original = Config.get('translation', 'primary_provider')
    tasks.active_tasks['deadbeef'] = object()
    desired = {'primary_provider': 'claude_cli', 'primary_model': 'claude-opus-4-7', 'primary_effort': 'high'}
    result = worker.model_settings.queue({'translation': desired})
    assert result['state']['current_provider'] == original
    assert result['settings']['translation']['primary_provider'] == 'claude_cli'
    assert not worker.apply_pending_settings()
    assert Config.get('translation', 'primary_provider') == original
    restored = LibraryWorker({'enabled': True}, Path(worker.store.path).parent)
    tasks.active_tasks.clear()
    assert restored.apply_pending_settings()
    assert {key: Config.get('translation', key) for key in desired} == desired
    assert restored.model_settings.state()['current_provider'] == 'claude_cli'
