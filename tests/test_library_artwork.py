import base64
import json
import threading
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from app import server
from app.library.sources import Sources, emby_metadata
from app.library.store import Store


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5S0AAAAASUVORK5CYII=')


def setup_artwork(tmp_path, monkeypatch, responder, metadata=None, project_id=None):
    source = Sources({'emby': {'url': 'http://emby.test', 'token': 'private-emby-token'}})
    source.client.close()
    source.client = httpx.Client(transport=httpx.MockTransport(responder))
    store = Store(tmp_path / 'library.sqlite3')
    row = {'path': '/video/Episode.mkv', 'state': 'done', 'updated': 1,
           'metadata': metadata if metadata is not None else {'emby_id': 'episode1'}}
    if project_id is not None:
        row['project_id'] = project_id
    store.put(row)
    monkeypatch.setattr(server, 'worker', SimpleNamespace(store=store, config={}, sources=source))
    monkeypatch.setattr(server.app.state, 'operator_token', 'fixture-token', raising=False)
    return TestClient(server.app, headers={'X-AISub-Key': 'fixture-token'}), source, row


def image_url(kind='poster', path='/video/Episode.mkv'):
    return '/api/library/artwork?' + urlencode({'path': path, 'kind': kind})


def test_emby_discovery_retains_series_artwork_already_present_in_metadata():
    series = {'Id': 'series1', 'Name': 'A Series', 'ImageTags': {'Primary': 'poster-tag'},
              'BackdropImageTags': ['backdrop-tag'], 'ProviderIds': {'Tmdb': '42'}}
    metadata = emby_metadata({'Id': 'episode1', 'Type': 'Episode', 'SeriesId': 'series1'}, lambda _: series)
    assert metadata['emby_artwork'] == {
        'poster': {'id': 'series1', 'tag': 'poster-tag'},
        'backdrop': {'id': 'series1', 'tag': 'backdrop-tag'},
    }


def test_list_supplies_authenticated_same_origin_links_without_upstream_calls(tmp_path, monkeypatch):
    calls = []
    client, source, row = setup_artwork(tmp_path, monkeypatch, lambda request: calls.append(request))
    items = client.get('/api/library/tasks').json()['items']
    assert items[0]['poster_url'] == image_url()
    assert items[0]['backdrop_url'] == image_url('backdrop')
    assert calls == []
    response = TestClient(server.app).get(image_url(), follow_redirects=False)
    assert response.status_code == 401 and 'location' not in response.headers
    assert calls == []


def test_legacy_episode_fetches_series_image_privately_and_reuses_cache(tmp_path, monkeypatch):
    calls = []
    def responder(request):
        calls.append(request)
        assert request.headers['x-emby-token'] == 'private-emby-token'
        if request.url.path == '/Items':
            item = ({'Id': 'episode1', 'Type': 'Episode', 'SeriesId': 'series1'}
                    if request.url.params['Ids'] == 'episode1' else
                    {'Id': 'series1', 'ImageTags': {'Primary': 'poster-tag'}, 'BackdropImageTags': ['backdrop-tag']})
            return httpx.Response(200, json={'Items': [item]})
        assert request.url.path == '/Items/series1/Images/Backdrop/0'
        assert request.url.params['MaxWidth'] == '1280'
        return httpx.Response(200, content=PNG, headers={'Content-Type': 'image/png'})
    client, source, row = setup_artwork(tmp_path, monkeypatch, responder)
    response = client.get(image_url('backdrop'))
    assert response.status_code == 200 and response.content == PNG
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert 'private-emby-token' not in str(response.headers)
    assert len(calls) == 3
    assert client.get(image_url('backdrop')).content == PNG
    assert len(calls) == 3
    assert source.emby_cache == {}, 'Artwork browsing must not grow the worker metadata cache per episode'


@pytest.mark.parametrize('path', ['/etc/passwd', 'http://169.254.169.254/latest/meta-data/', '/video/../secret'])
def test_artwork_only_uses_existing_ledger_records(tmp_path, monkeypatch, path):
    calls = []
    client, source, row = setup_artwork(tmp_path, monkeypatch, lambda request: calls.append(request))
    assert client.get(image_url(path=path)).status_code == 404
    assert calls == []


@pytest.mark.parametrize('upstream', [
    httpx.Response(302, headers={'Location': 'http://169.254.169.254/private'}),
    httpx.Response(200, content=b'<svg onload="alert(1)"></svg>', headers={'Content-Type': 'image/svg+xml'}),
    httpx.Response(200, content=b'<html>not an image</html>', headers={'Content-Type': 'image/png'}),
    httpx.Response(200, content=PNG, headers={'Content-Type': 'image/png', 'Content-Length': str(5*1024*1024)}),
    httpx.Response(200, stream=httpx.ByteStream(PNG+b'\0'*(4*1024*1024)), headers={'Content-Type': 'image/png'}),
])
def test_redirects_non_images_and_oversize_responses_fail_closed(tmp_path, monkeypatch, upstream):
    calls = []
    def responder(request):
        calls.append(request)
        return upstream
    meta = {'emby_id': 'series1', 'emby_artwork': {'poster': {'id': 'series1', 'tag': 'tag'}}}
    client, source, row = setup_artwork(tmp_path, monkeypatch, responder, metadata=meta)
    response = client.get(image_url(), follow_redirects=False)
    assert response.status_code == 404 and 'location' not in response.headers
    assert len(calls) == 1
    assert client.get(image_url()).status_code == 404
    assert len(calls) == 1, 'Missing/invalid images must have a short negative cache'


def test_existing_tmdb_project_poster_is_used_without_api_key_or_arbitrary_url(tmp_path, tmp_project_dir, monkeypatch):
    from app.library import artwork
    project = tmp_project_dir / 'deadbeef'; project.mkdir()
    (project / 'project.json').write_text(json.dumps({'id': 'deadbeef', 'poster_path': '/real-poster.jpg'}))
    calls = []
    def responder(request):
        calls.append(request)
        assert str(request.url) == 'https://image.tmdb.org/t/p/w500/real-poster.jpg'
        assert 'x-emby-token' not in request.headers and 'api_key' not in request.url.params
        return httpx.Response(200, content=PNG, headers={'Content-Type': 'image/png'})
    client, source, row = setup_artwork(tmp_path, monkeypatch, responder, metadata={}, project_id='deadbeef')
    monkeypatch.setattr(artwork, 'tmdb_image_client', lambda: httpx.Client(transport=httpx.MockTransport(responder)))
    item = client.get('/api/library/tasks').json()['items'][0]
    assert item['poster_url'] == image_url() and item['backdrop_url'] is None
    assert client.get(item['poster_url']).content == PNG
    assert len(calls) == 1


def test_malicious_emby_ids_and_project_paths_never_reach_upstream(tmp_path, monkeypatch):
    calls = []
    metadata = {'emby_id': '../../Sessions', 'emby_artwork': {'poster': {'id': '../Users', 'tag': 'x'}},
                'poster_path': 'http://169.254.169.254/secret'}
    client, source, row = setup_artwork(tmp_path, monkeypatch, lambda request: calls.append(request),
                                      metadata=metadata, project_id='../../private')
    assert client.get(image_url()).status_code == 404
    assert calls == []


@pytest.mark.parametrize(('byte_capacity', 'entry_capacity'), [(2, 20), (20, 2)])
def test_artwork_cache_is_bounded_by_bytes_and_entries(tmp_path, monkeypatch, byte_capacity, entry_capacity):
    calls = []
    def responder(request):
        calls.append(request)
        return httpx.Response(200, content=PNG, headers={'Content-Type': 'image/png'})
    client, source, row = setup_artwork(tmp_path, monkeypatch, responder)
    source.artwork.max_cache_bytes = len(PNG) * byte_capacity
    source.artwork.max_cache_entries = entry_capacity
    for index in range(4):
        entry = dict(row, metadata={'emby_artwork': {'poster': {'id': str(index), 'tag': 'one'}}})
        assert source.artwork.get(entry, 'poster').content == PNG
    assert source.artwork.cache_bytes <= len(PNG) * 2
    assert len(source.artwork.cache) <= 2
    first = dict(row, metadata={'emby_artwork': {'poster': {'id': '0', 'tag': 'one'}}})
    assert source.artwork.get(first, 'poster').content == PNG
    assert len(calls) == 5


def test_known_missing_images_return_empty_links_without_upstream_requests(tmp_path, monkeypatch):
    calls = []
    client, source, row = setup_artwork(tmp_path, monkeypatch, lambda request: calls.append(request),
                                      metadata={'emby_id': 'series1', 'emby_artwork': {}})
    item = client.get('/api/library/tasks').json()['items'][0]
    assert item['poster_url'] is None and item['backdrop_url'] is None
    assert client.get(image_url()).status_code == 404
    assert calls == []


def test_concurrent_requests_for_the_same_image_share_one_upstream_fetch(tmp_path, monkeypatch):
    entered, second_checked, release = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def responder(request):
        calls.append(request)
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, content=PNG, headers={'Content-Type': 'image/png'})
    metadata = {'emby_artwork': {'poster': {'id': 'series1', 'tag': 'tag'}}}
    client, source, row = setup_artwork(tmp_path, monkeypatch, responder, metadata=metadata)
    delegate = threading.Lock()
    class ObservedLock:
        def __enter__(self):
            delegate.acquire()
        def __exit__(self, *args):
            delegate.release()
            if threading.current_thread().name == 'artwork-second':
                second_checked.set()
    source.artwork.lock = ObservedLock()
    images = []
    first = threading.Thread(target=lambda: images.append(source.artwork.get(row, 'poster')))
    second = threading.Thread(name='artwork-second', target=lambda: images.append(source.artwork.get(row, 'poster')))
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert second_checked.wait(5)
    finally:
        release.set(); first.join(5)
        if second.ident is not None: second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert len(images) == 2 and all(image.content == PNG for image in images)
    assert len(calls) == 1
