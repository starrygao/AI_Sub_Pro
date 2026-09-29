import json
import os
import subprocess
import sys

import pytest

from app.library.worker import LibraryWorker
from app.services import translation_tasks as tasks


@pytest.fixture
def worker(tmp_path, monkeypatch):
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.setenv(name, '')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:7890')
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:7890')
    monkeypatch.setenv('NO_PROXY', 'localhost,127.0.0.1,192.168.31.4')
    monkeypatch.setattr(tasks, 'active_tasks', {})
    return LibraryWorker({}, tmp_path / 'library')


def test_proxy_changes_wait_for_jobs_persist_and_reach_child_processes(worker):
    before = worker.proxy_settings.read()
    assert before['current']['proxy_url'] == 'http://127.0.0.1:7890'
    assert before['source'] == 'environment'
    worker.store.put({'path': '/video/test.mkv', 'state': 'translating', 'updated': 1})
    result = worker.proxy_settings.queue({'proxy_url': 'http://192.168.31.4:7893'})
    assert result['pending']
    assert result['desired']['proxy_url'] == 'http://192.168.31.4:7893'
    assert not worker.proxy_settings.apply()
    assert os.environ['HTTPS_PROXY'] == 'http://127.0.0.1:7890'
    row = worker.store.get('/video/test.mkv')
    row['state'] = 'publishing'; worker.store.put(row)
    assert not worker.proxy_settings.apply()
    row['state'] = 'done'; worker.store.put(row)
    tasks.active_tasks['deadbeef'] = object()
    assert not worker.proxy_settings.apply()
    tasks.active_tasks.clear()
    assert worker.proxy_settings.apply()
    inherited = json.loads(subprocess.check_output(
        [sys.executable, '-c', 'import os,json; print(json.dumps({k:os.getenv(k) for k in ("HTTP_PROXY","HTTPS_PROXY","NO_PROXY")}))'],
        text=True,
    ))
    assert inherited == {'HTTP_PROXY': 'http://192.168.31.4:7893', 'HTTPS_PROXY': 'http://192.168.31.4:7893',
                         'NO_PROXY': 'localhost,127.0.0.1,192.168.31.4'}
    os.environ['HTTPS_PROXY'] = 'http://old-container-default:7890'
    restarted = LibraryWorker({}, os.path.dirname(worker.store.path))
    assert restarted.proxy_settings.read()['current']['proxy_url'] == 'http://192.168.31.4:7893'
    assert os.environ['HTTPS_PROXY'] == 'http://192.168.31.4:7893'


def test_proxy_pending_survives_restart_and_can_be_cancelled(worker):
    worker.proxy_settings.queue({'proxy_url': 'http://new-proxy:7890'})
    restarted = LibraryWorker({}, os.path.dirname(worker.store.path))
    assert restarted.proxy_settings.read()['pending']
    assert os.environ['HTTPS_PROXY'] == 'http://127.0.0.1:7890'
    result = restarted.proxy_settings.queue({'proxy_url': 'http://127.0.0.1:7890'})
    assert not result['pending']


def test_disabling_proxy_clears_fallbacks_and_survives_restart(worker, monkeypatch):
    monkeypatch.setenv('ALL_PROXY', 'socks5://old-proxy:7891')
    monkeypatch.setenv('https_proxy', 'http://old-proxy:7890')
    worker.proxy_settings.queue({'proxy_url': ''})
    assert worker.proxy_settings.apply()
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        assert not os.environ.get(name)
    monkeypatch.setenv('HTTP_PROXY', 'http://container-default:7890')
    restarted = LibraryWorker({}, os.path.dirname(worker.store.path))
    assert restarted.proxy_settings.read()['current']['proxy_url'] == ''


def test_dashboard_is_separate_and_does_not_reconfigure_an_authenticated_inherited_proxy(worker, monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY', 'http://user:private-password@proxy.example:7890')
    dashboard = 'http://192.168.31.4:9097/ui/#/proxies'
    result = worker.proxy_settings.queue({'dashboard_url': dashboard})
    assert result['current']['dashboard_url'] == dashboard
    assert result['current']['proxy_url'] == 'http://proxy.example:7890'
    assert result['credentials_configured'] is True
    assert 'private-password' not in json.dumps(result)
    assert not result['pending']
    assert worker.store.setting('proxy_url') is None
    assert os.environ['HTTPS_PROXY'] == 'http://user:private-password@proxy.example:7890'


@pytest.mark.parametrize('patch', [
    {'proxy_url': 'http://192.168.31.4:9097/ui/#/proxies'},
    {'proxy_url': 'javascript:alert(1)'}, {'proxy_url': 'http://host:70000'},
    {'proxy_url': 'http://user:password@host:7890'}, {'proxy_url': 'http://host\n:7890'},
    {'proxy_url': 'http://host\\other:7890'}, {'dashboard_url': 'javascript:alert(1)'},
    {'dashboard_url': '//host/ui/'}, {'proxy_url': None}, {'other': 'value'},
])
def test_invalid_proxy_input_does_not_change_saved_settings(worker, patch):
    before = worker.proxy_settings.read()
    with pytest.raises(ValueError):
        worker.proxy_settings.queue(patch)
    assert worker.proxy_settings.read() == before


def test_proxy_endpoint_requires_auth_and_returns_validation_errors(worker, monkeypatch):
    from fastapi.testclient import TestClient
    from app import server
    monkeypatch.setattr(server, 'worker', worker)
    monkeypatch.setattr(server.app.state, 'operator_token', 'fixture-token', raising=False)
    client = TestClient(server.app)
    assert client.get('/api/library/proxy').status_code == 401
    client.headers['X-AISub-Key'] = 'fixture-token'
    assert client.get('/api/library/proxy').json()['source'] == 'environment'
    assert client.post('/api/library/proxy', json={'proxy_url': 'http://host/ui/'}).status_code == 400
    response = client.post('/api/library/proxy', json={'proxy_url': 'http://new-proxy:7890'})
    assert response.status_code == 200 and response.json()['pending']
    assert worker.wake.is_set()
