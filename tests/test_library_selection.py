import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app import server
from app.library.worker import LibraryWorker
from app.library.selection import EmbySelection


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / 'media'; root.mkdir()
    video = root / 'old.mkv'; video.write_bytes(b'video')
    worker = LibraryWorker({'new_only': True, 'roots': [str(root)], 'allowed_roots': [str(tmp_path)],
                            'quiet_seconds': 0, 'path_maps': {'/emby': str(root)}}, tmp_path / 'state')
    worker.establish_baseline()
    item = {'Id': '1', 'Type': 'Movie', 'Name': 'Film', 'Path': '/emby/old.mkv', 'ProviderIds': {'Tmdb': '42'}}
    calls = []
    def emby(endpoint, **params):
        calls.append((endpoint, params))
        return {'Items': [dict(item)], 'TotalRecordCount': 1}
    monkeypatch.setattr(worker.sources, 'emby', emby)
    return worker, video, item, calls


def test_search_is_read_only_and_passes_pagination_and_type_filters(setup):
    worker, video, item, calls = setup
    result = EmbySelection(worker).search(' Film ', kind='movie', offset=30, limit=30)
    assert result['items'][0]['selectable']
    assert result['items'][0]['id'] == '1'
    assert calls[0][1]['SearchTerm'] == 'Film'
    assert calls[0][1]['IncludeItemTypes'] == 'Movie'
    assert calls[0][1]['StartIndex'] == 30
    assert worker.store.counts() == {}


def test_manual_old_video_survives_baseline_and_restart_without_enabling_automation(setup):
    worker, video, item, calls = setup
    worker.store.set_setting('enabled', False)
    result = EmbySelection(worker).enqueue(['1'])
    assert result['items'][0]['status'] == 'queued'
    row = worker.store.get(video)
    assert row['state'] == 'waiting' and row['manual_requested']
    assert row['metadata']['tmdb_id'] == 42
    assert not worker.store.setting('enabled')
    worker.establish_baseline()
    restarted = LibraryWorker(worker.config, os.path.dirname(worker.store.path))
    restarted.establish_baseline()
    assert restarted.store.get(video)['manual_requested']
    assert restarted.eligible_new_path(video, row['fingerprint'])


def test_explicit_emby_selection_reopens_history_exclusion_once(setup, monkeypatch):
    from app.library.guard import fingerprint
    worker, video, item, calls = setup
    worker.store.put({'path':str(video),'fingerprint':fingerprint(video),
                      'state':'historical','updated':1,'metadata':{}})
    monkeypatch.setattr(server,'worker',worker)
    monkeypatch.setattr(server.app.state,'operator_token','selection-test-token',raising=False)
    client=TestClient(server.app,headers={'X-AISub-Key':'selection-test-token'})
    result=client.get('/api/library/emby/search?q=Film').json()
    assert result['items'][0]['selectable']
    result=client.post('/api/library/emby/enqueue',json={'ids':['1']}).json()
    assert result['items'][0]['status']=='queued'
    row=worker.store.get(video)
    assert row['state']=='waiting' and row['manual_requested']
    assert worker.eligible_new_path(video,row['fingerprint'])
    assert client.post('/api/library/emby/enqueue',json={'ids':['1']}).json()['items'][0]['status']=='existing'
    assert worker.store.get(video)==row


def test_history_override_uses_current_emby_path_after_rename(setup):
    from app.library.guard import fingerprint
    worker,video,item,calls=setup
    worker.store.put({'path':str(video),'fingerprint':fingerprint(video),
                      'state':'historical','updated':1,'metadata':{}})
    renamed=video.with_name('renamed.mkv');video.rename(renamed);item['Path']=str(renamed)
    assert EmbySelection(worker).enqueue(['1'])['items'][0]['status']=='queued'
    row=worker.store.get(renamed)
    assert row and row['manual_requested']
    assert worker.store.get(video) is None
    assert worker.eligible_new_path(renamed,row['fingerprint'])


def test_history_row_with_project_is_not_offered_as_new_selection(setup):
    from app.library.guard import fingerprint
    worker,video,item,calls=setup
    worker.store.put({'path':str(video),'fingerprint':fingerprint(video),
                      'state':'historical','updated':1,'metadata':{},'project_id':'existing'})
    service=EmbySelection(worker)
    assert not service.search('Film')['items'][0]['selectable']
    assert service.enqueue(['1'])['items'][0]['status']=='existing'


def test_parallel_add_and_repeat_do_not_reset_a_task_or_stability_window(setup):
    worker, video, item, calls = setup
    service = EmbySelection(worker)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service.enqueue, [['1'], ['1']]))
    assert sorted(r['items'][0]['status'] for r in results) == ['existing', 'queued']
    row = worker.store.get(video); worker.save(row, state='translating', project_id='existing')
    before = worker.store.get(video)
    assert service.enqueue(['1', '1'])['items'][0]['status'] == 'existing'
    assert worker.store.get(video) == before


@pytest.mark.parametrize('kind,expected', [('embedded', 'skipped'), ('sidecar', 'skipped'),
    ('attachment', 'skipped'), ('chinese_audio', 'native_language'), ('foreign', 'ready'), ('downloading', 'waiting')])
def test_manual_selection_uses_existing_track_and_readiness_guards(setup, monkeypatch, kind, expected):
    from app.engines.providers.codex_cli import CodexCliProvider
    worker, video, item, calls = setup
    EmbySelection(worker).enqueue(['1'])
    streams = [{'codec_type': 'audio', 'tags': {'language': 'chi' if kind == 'chinese_audio' else 'eng'}}]
    if kind == 'embedded': streams.append({'codec_type': 'subtitle', 'tags': {'language': 'chi'}})
    if kind == 'attachment': streams.append({'codec_type': 'attachment', 'extradata_size': 1200, 'tags': {'filename': 'old.zh.srt', 'mimetype': 'application/x-subrip'}})
    if kind == 'sidecar': video.with_suffix('.zh.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n这是完整的中文字幕\n')
    if kind == 'downloading': worker.set_blockers({str(video): '下载尚未完成'})
    monkeypatch.setattr(CodexCliProvider, 'check_logged_in', lambda: True)
    monkeypatch.setattr(os, 'getloadavg', lambda: (0, 0, 0))
    monkeypatch.setattr(worker, 'probe', lambda p: {'streams': streams})
    monkeypatch.setattr(worker.sources, 'original_language', lambda metadata: 'en')
    monkeypatch.setattr(worker, 'refresh_readiness', lambda: None)
    prepare = Mock(); monkeypatch.setattr(worker, 'prepare', prepare)
    worker.process_one()
    assert worker.store.get(video)['state'] == expected
    assert prepare.call_count == (kind == 'foreign')


def test_manual_files_outside_watch_roots_remain_explicitly_selected(setup):
    worker, video, item, calls = setup
    outside = video.parent.parent / 'outside.mkv'; outside.write_bytes(b'outside')
    item['Path'] = str(outside)
    assert EmbySelection(worker).enqueue(['1'])['items'][0]['status'] == 'queued'
    worker.store.exclude_unstarted_outside_roots(worker.roots)
    row = worker.store.get(outside)
    assert worker.eligible_new_path(outside, row['fingerprint'])
    assert worker.store.get(outside)['manual_requested']
    worker.observe(outside, {})
    assert worker.store.get(outside)['manual_requested']


def test_missing_remote_and_directory_items_cannot_enter_queue(setup):
    worker, video, item, calls = setup
    for path in ['https://example.test/movie.mkv', str(video.parent), str(video.parent / 'missing.mkv'), '/etc/passwd']:
        item['Path'] = path
        assert EmbySelection(worker).enqueue(['1'])['items'][0]['status'] == 'unavailable'
    assert worker.store.counts() == {}


def test_episode_metadata_uses_series_identity_and_not_episode_tmdb(setup, monkeypatch):
    worker, video, item, calls = setup
    item.update(Type='Episode', SeriesId='series', ParentIndexNumber=0, IndexNumber=1, ProviderIds={'Tmdb': '999'})
    monkeypatch.setattr(worker.sources, 'item', lambda _: {'Name': 'Series', 'ProviderIds': {'Tmdb': '42'}})
    EmbySelection(worker).enqueue(['1'])
    assert worker.store.get(video)['metadata']['tmdb_id'] == 42
    assert worker.store.get(video)['metadata']['tmdb_type'] == 'tv'


def test_http_requires_auth_validates_ids_and_never_accepts_client_paths(setup, monkeypatch):
    worker, video, item, calls = setup
    monkeypatch.setattr(server, 'worker', worker)
    monkeypatch.setattr(server.app.state, 'operator_token', 'selection-test-token', raising=False)
    client = TestClient(server.app)
    assert client.get('/api/library/emby/search?q=Film').status_code == 401
    client.headers['X-AISub-Key'] = 'selection-test-token'
    assert client.get('/api/library/emby/search?q=Film').status_code == 200
    assert client.get('/api/library/emby/search?q=Film&limit=5000').status_code == 422
    assert client.post('/api/library/emby/enqueue', json={'ids': ['../escape']}).status_code == 422
    assert client.post('/api/library/emby/enqueue', json={'ids': ['1'], 'path': str(video)}).status_code == 422
    assert client.post('/api/library/emby/enqueue', json={'ids': ['1']}, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert worker.store.counts() == {}


def test_upstream_error_is_sanitized(setup, monkeypatch):
    worker, video, item, calls = setup
    monkeypatch.setattr(server, 'worker', worker)
    monkeypatch.setattr(server.app.state, 'operator_token', 'selection-test-token', raising=False)
    def fail(*a, **kw): raise httpx.ConnectError('secret-token', request=httpx.Request('GET', 'http://emby.test/?api_key=secret-token'))
    monkeypatch.setattr(worker.sources, 'emby', fail)
    r = TestClient(server.app, headers={'X-AISub-Key': 'selection-test-token'}).get('/api/library/emby/search?q=Film')
    assert r.status_code == 502 and 'secret-token' not in r.text


def test_manual_hardlink_duplicates_are_one_job(setup):
    worker, video, item, calls = setup
    service = EmbySelection(worker); service.enqueue(['1'])
    alias = video.parent / 'alias.mkv'; alias.hardlink_to(video)
    item.update(Id='2', Path=str(alias))
    assert service.enqueue(['2'])['items'][0]['status'] == 'existing'
    assert worker.store.counts() == {'waiting': 1}


def test_manual_replaced_waiting_file_restarts_stability_window(setup, monkeypatch):
    from app.engines.providers.codex_cli import CodexCliProvider
    from app.library.guard import fingerprint
    worker, video, item, calls = setup
    EmbySelection(worker).enqueue(['1'])
    video.write_bytes(b'newly replaced file')
    monkeypatch.setattr(CodexCliProvider, 'check_logged_in', lambda: True)
    monkeypatch.setattr(os, 'getloadavg', lambda: (0, 0, 0))
    prepare = Mock(); monkeypatch.setattr(worker, 'prepare', prepare)
    worker.process_one()
    row = worker.store.get(video)
    assert row['fingerprint'] == fingerprint(video) and row['manual_requested']
    prepare.assert_not_called()
    worker.establish_baseline()
    assert worker.store.get(video)['state'] == 'waiting'


def test_series_requires_explicit_episode_selection_and_paginates(setup, monkeypatch):
    worker, video, item, calls = setup
    def emby(endpoint, **params):
        calls.append((endpoint, params))
        if params.get('Ids') == 'series': return {'Items': [{'Id': 'series', 'Type': 'Series', 'Name': 'Show'}]}
        return {'Items': [{**item, 'Type': 'Episode', 'ParentIndexNumber': 0, 'IndexNumber': 1}], 'TotalRecordCount': 80}
    monkeypatch.setattr(worker.sources, 'emby', emby)
    result = EmbySelection(worker).episodes('series', offset=30, limit=30)
    assert result['series']['name'] == 'Show' and result['total'] == 80
    assert calls[-1][1]['ParentId'] == 'series' and calls[-1][1]['StartIndex'] == 30
    assert result['items'][0]['season'] == 0
    assert EmbySelection(worker).enqueue(['series'])['items'][0]['status'] == 'unavailable'
    assert worker.store.counts() == {}


def test_emby_zero_total_with_full_page_still_allows_next_page(setup, monkeypatch):
    worker, video, item, calls = setup
    monkeypatch.setattr(worker.sources, 'emby', lambda *a, **kw: {'Items': [item], 'TotalRecordCount': 0})
    result = EmbySelection(worker).search('Film', offset=1, limit=1)
    assert result['total'] >= 2 and result['has_more']


def test_outside_symlink_cannot_choose_an_unmounted_subtitle_output_folder(setup):
    worker, video, item, calls = setup
    worker.config['allowed_roots'] = [str(video.parent)]
    alias = video.parent.parent / 'outside-link.mkv'; alias.symlink_to(video)
    item['Path'] = str(alias)
    assert EmbySelection(worker).enqueue(['1'])['items'][0]['status'] == 'unavailable'
    assert worker.store.counts() == {}


pytestmark = pytest.mark.usefixtures("library_codex_config")
