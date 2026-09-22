import base64
import hashlib
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app import server


def test_account_verification_and_authenticated_server_routes(monkeypatch):
    salt=b'fixture-salt-16b!'
    account={'algorithm':'PBKDF2WithHmacSHA256','iterations':600000,'salt':base64.b64encode(salt).decode(),
             'hash':base64.b64encode(hashlib.pbkdf2_hmac('sha256',b'fixture-password',salt,600000,32)).decode(),'username':'fixture'}
    monkeypatch.setattr(server.app.state,'server_account',account,raising=False)
    monkeypatch.setattr(server.app.state,'operator_token','fixture-token',raising=False)
    monkeypatch.setattr(server,'worker',SimpleNamespace(status=lambda:{'enabled':False}))
    client=TestClient(server.app)
    assert client.get('/healthz').status_code==200
    assert client.get('/api/library/status').status_code==401
    assert client.get('/api/library/status',auth=('fixture','wrong')).status_code==401
    assert client.get('/api/library/status',auth=('fixture','fixture-password')).json()=={'enabled':False}
    headers={'X-AISub-Key':'fixture-token'}
    assert client.get('/api/library/status',headers=headers).status_code==200
    assert client.post('/api/library/control',headers={**headers,'Origin':'https://unrelated.example'},json={'enabled':True}).status_code==403
    assert client.get('/api/library/tasks?limit=201',headers=headers).status_code==400
