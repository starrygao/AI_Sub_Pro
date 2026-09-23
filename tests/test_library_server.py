import base64
import hashlib
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app import server


def test_account_verification_and_authenticated_server_routes(monkeypatch,tmp_path):
    salt=b'fixture-salt-16b!'
    account={'algorithm':'PBKDF2WithHmacSHA256','iterations':600000,'salt':base64.b64encode(salt).decode(),
             'hash':base64.b64encode(hashlib.pbkdf2_hmac('sha256',b'fixture-password',salt,600000,32)).decode(),'username':'fixture'}
    monkeypatch.setattr(server.app.state,'server_account',account,raising=False)
    monkeypatch.setattr(server.app.state,'operator_token','fixture-token',raising=False)
    monkeypatch.setattr(server,'worker',SimpleNamespace(status=lambda:{'enabled':False}))
    from app.library.auth import Sessions,LoginAttempts
    monkeypatch.setattr(server.app.state,'sessions',Sessions(tmp_path/'sessions.sqlite3'),raising=False)
    monkeypatch.setattr(server,'login_attempts',LoginAttempts())
    client=TestClient(server.app)
    assert client.get('/healthz').status_code==200
    assert client.get('/api/library/status').status_code==401
    assert client.get('/api/library/status',auth=('fixture','wrong')).status_code==401
    assert client.get('/api/library/status',auth=('fixture','fixture-password')).status_code==401
    assert 'WWW-Authenticate' not in client.get('/api/library/status').headers
    assert client.get('/library',follow_redirects=False).headers['location'].startswith('/login?')
    assert client.get('/login').status_code==200
    assert client.get('/static/css/login.css').status_code==200
    for path, content_type in [('/favicon.ico', 'image/'), ('/static/favicon.ico?v=1', 'image/'),
                               ('/static/favicon.svg?v=1', 'image/svg+xml')]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith(content_type)
        assert response.content
    assert client.get('/static/library.html').status_code == 401
    assert client.get('/static/js/library.js').status_code == 401
    assert client.post('/api/auth/login',json={'username':'fixture','password':'wrong'}).status_code==401
    before=dict(account)
    response=client.post('/api/auth/login',json={'username':'fixture','password':'fixture-password'})
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=lax' in response.headers['set-cookie']
    assert account==before
    assert client.get('/api/library/status').json()=={'enabled':False}
    token=client.cookies.get('aisub_session')
    assert Sessions(tmp_path/'sessions.sqlite3').valid(token,account)
    assert client.post('/api/auth/logout').status_code==200
    assert not server.app.state.sessions.valid(token,account)
    assert client.get('/api/library/status').status_code==401
    headers={'X-AISub-Key':'fixture-token'}
    assert client.get('/api/library/status',headers=headers).status_code==200
    assert client.post('/api/library/control',headers={**headers,'Origin':'https://unrelated.example'},json={'enabled':True}).status_code==403
    assert client.get('/api/library/tasks?limit=201',headers=headers).status_code==400


def test_lists_separate_waiting_and_skipped_before_pagination(tmp_path,monkeypatch):
    from app.library.store import Store
    store=Store(tmp_path/'library.sqlite3')
    for i,state in enumerate(['done','error','waiting','native_language','waiting','skipped']):
        store.put({'path':f'/video/{i}.mkv','state':state,'updated':i})
    monkeypatch.setattr(server,'worker',SimpleNamespace(store=store,config={}))
    monkeypatch.setattr(server.app.state,'operator_token','fixture-token',raising=False)
    client=TestClient(server.app,headers={'X-AISub-Key':'fixture-token'})
    page=client.get('/api/library/tasks?view=processed&limit=1').json()
    assert [r['state'] for r in page['items']]==['error']
    assert page['total']==2
    assert page['view_counts']=={'processed':2,'waiting':2,'skipped':2}
    page=client.get('/api/library/tasks?view=processed&limit=1&offset=1').json()
    assert [r['state'] for r in page['items']]==['done']
    for view,states in [('waiting',{'waiting'}),('skipped',{'skipped','native_language'})]:
        page=client.get('/api/library/tasks?view='+view).json()
        assert {r['state'] for r in page['items']}==states
        assert page['total']==2
    assert client.get('/api/library/tasks?view=processed&state=waiting').json()['items']==[]
    assert len(client.get('/api/library/tasks').json()['items'])==6  # existing API clients retain all-view behavior
    assert client.get('/api/library/tasks?view=invalid').status_code==400


def test_session_expiry_tampering_and_account_change(tmp_path):
    import sqlite3
    from app.library.auth import Sessions
    path=tmp_path/'sessions.sqlite3';sessions=Sessions(path)
    account={'username':'fixture','hash':'one'}
    token=sessions.create(account)
    assert sessions.valid(token,account)
    assert not sessions.valid(token+'changed',account)
    assert not sessions.valid(token,{'username':'fixture','hash':'two'})
    assert path.stat().st_mode & 0o777==0o600
    with sqlite3.connect(path) as db:db.execute('UPDATE sessions SET expires=0')
    assert not sessions.valid(token,account)


def test_login_cross_site_and_attempt_limit(monkeypatch):
    from app.library.auth import LoginAttempts
    monkeypatch.setattr(server,'login_attempts',LoginAttempts())
    monkeypatch.setattr(server,'password_matches',lambda *args:False)
    monkeypatch.setattr(server.app.state,'server_account',{},raising=False)
    client=TestClient(server.app)
    body={'username':'fixture','password':'invalid'}
    assert client.post('/api/auth/login',json=body,headers={'Origin':'http://other.example'}).status_code==403
    for _ in range(10):assert client.post('/api/auth/login',json=body).status_code==401
    response=client.post('/api/auth/login',json=body)
    assert response.status_code==429 and response.headers['retry-after']=='60'


def test_task_list_distinguishes_missing_progress_from_recorded_zero(tmp_path, tmp_project_dir, monkeypatch):
    import json
    from app.library.store import Store
    store = Store(tmp_path / 'library.sqlite3')
    for pid in ['deadbeef', 'c0ffee42']:
        store.put({'path': '/video/' + pid + '.mkv', 'state': 'cancelled', 'updated': 1, 'project_id': pid})
    known = tmp_project_dir / 'deadbeef'; known.mkdir()
    (known / 'progress.json').write_text(json.dumps({'progress': 0, 'message': '尚未开始识别'}))
    monkeypatch.setattr(server, 'worker', SimpleNamespace(store=store, config={}))
    monkeypatch.setattr(server.app.state, 'operator_token', 'fixture-token', raising=False)
    client = TestClient(server.app, headers={'X-AISub-Key': 'fixture-token'})
    rows = {row['project_id']: row for row in client.get('/api/library/tasks?view=processed').json()['items']}
    assert rows['deadbeef']['progress']['progress'] == 0
    assert rows['c0ffee42']['progress'] is None
