from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from app import server
from app.library.worker import LibraryWorker


@pytest.fixture
def setup(tmp_path,monkeypatch):
    root=tmp_path/'media';root.mkdir();video=root/'episode.mkv';video.write_bytes(b'video')
    worker=LibraryWorker({'roots':[str(root)],'allowed_roots':[str(root)],'quiet_seconds':0},tmp_path/'state')
    worker.observe(video,{})
    monkeypatch.setattr(server,'worker',worker)
    monkeypatch.setattr(server.app.state,'operator_token','fixture-only',raising=False)
    client=TestClient(server.app,headers={'X-AISub-Key':'fixture-only'})
    return worker,video,client


def test_manual_mark_survives_scans_blocks_translation_and_can_be_undone(setup,monkeypatch):
    worker,video,client=setup
    assert client.post('/api/library/hard-subtitle',json={'path':str(video),'present':True}).status_code==200
    worker.observe(video,{'show_title':'Updated'})
    probe=Mock();monkeypatch.setattr(worker,'probe',probe)
    assert worker.inspect_candidate(worker.store.get(video)) is None
    probe.assert_not_called()
    row=worker.store.get(video)
    assert row['state']=='skipped' and row['manual_hard_subtitle']
    assert client.post('/api/library/retry',json={'path':str(video)}).status_code==409
    restored=LibraryWorker(worker.config,video.parent.parent/'state')
    assert restored.store.get(video)['manual_hard_subtitle']
    assert client.post('/api/library/hard-subtitle',json={'path':str(video),'present':False}).status_code==200
    assert worker.store.get(video)['state']=='waiting'
    assert not worker.store.get(video).get('manual_hard_subtitle')


def test_replaced_video_does_not_inherit_old_hard_subtitle_mark(setup):
    worker,video,client=setup
    assert client.post('/api/library/hard-subtitle',json={'path':str(video),'present':True}).status_code==200
    video.write_bytes(b'a different replacement')
    worker.observe(video,{})
    assert worker.store.get(video)['state']=='waiting'
    assert not worker.store.get(video).get('manual_hard_subtitle')


def test_mark_rejects_active_or_changed_file_and_requires_auth(setup):
    worker,video,client=setup
    assert TestClient(server.app).post('/api/library/hard-subtitle',json={'path':str(video),'present':True}).status_code==401
    worker.save(worker.store.get(video),state='translating',project_id='active')
    assert client.post('/api/library/hard-subtitle',json={'path':str(video),'present':True}).status_code==409
    worker.save(worker.store.get(video),state='waiting',project_id=None)
    video.write_bytes(b'changed')
    assert client.post('/api/library/hard-subtitle',json={'path':str(video),'present':True}).status_code==409


def test_detection_cannot_overwrite_concurrent_manual_mark(setup,monkeypatch):
    worker,video,client=setup
    entered,release=Event(),Event()
    def probe(path):
        entered.set();assert release.wait(3)
        return {'streams':[{'codec_type':'audio','tags':{'language':'eng'}}]}
    monkeypatch.setattr(worker,'probe',probe)
    with ThreadPoolExecutor(max_workers=2) as pool:
        inspection=pool.submit(worker.inspect_candidate,worker.store.get(video))
        assert entered.wait(3)
        marking=pool.submit(client.post,'/api/library/hard-subtitle',json={'path':str(video),'present':True})
        release.set();inspection.result(timeout=3)
        assert marking.result(timeout=3).status_code==200
    assert worker.store.get(video)['state']=='skipped'
    assert worker.inspect_candidate({'path':str(video),'state':'ready'}) is None
