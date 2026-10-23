from datetime import datetime

from fastapi.testclient import TestClient
from app import server
from tests.test_library_hard_subtitles import setup


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


def test_overview_delivery_dates_and_auth(setup, monkeypatch):
    from app.library import overview
    worker, video, client = setup
    now = stamp('2026-03-10T12:00:00+00:00')
    monkeypatch.setattr(overview.time, 'time', lambda: now)
    samples = [
        ('done', stamp('2026-03-08T07:59:59+00:00')),
        ('done', stamp('2026-03-08T08:00:00+00:00')),
        ('done', stamp('2026-03-09T06:59:59+00:00')),
        ('done', stamp('2026-03-09T07:00:00+00:00')),
        ('done', stamp('2025-01-01T00:00:00+00:00')),
        ('done', None), ('done', 'not-a-date'), ('done', True),
        ('done', now + 100), ('deleted', now), ('cancelled', now),
    ]
    for i, (state, completed) in enumerate(samples):
        worker.store.put({'path': str(video) + str(i), 'state': state, 'updated': now,
                          'completed_at': completed})
    response = client.get('/api/library/overview?timezone=America/Los_Angeles')
    assert response.status_code == 200
    result = response.json()
    assert result['deliveries'] == {'timezone': 'America/Los_Angeles', 'total': 5, 'undated': 4,
        'days': [{'date': f'2026-03-{day:02}', 'count': count}
                 for day, count in zip(range(4, 11), [0, 0, 0, 1, 2, 1, 0])]}
    assert 'deleted' not in result['counts']
    assert TestClient(server.app).get('/api/library/overview').status_code == 401
    for zone in ('not-real', '../UTC'):
        assert client.get('/api/library/overview', params={'timezone': zone}).status_code == 400
    assert client.get('/api/library/overview').json()['deliveries']['timezone'] == 'UTC'


def test_cards_match_task_contract_queue_priority_and_public_models(setup, monkeypatch):
    worker, video, client = setup
    worker.config['host_path_maps'] = {str(video.parent): '/host/media'}
    monkeypatch.setattr('app.engines.scheduler.get_progress', lambda pid: {'progress': 63, 'stage': 'translate'})
    for i, (state, priority, updated) in enumerate([
            ('ready', 0, 1), ('ready', 5, 9), ('ready', 5, 2), ('ready', 5, 2),
            ('translating', 0, 4), ('publishing', 0, 5), ('pausing', 0, 6), ('cancelling', 0, 7),
            ('error', 0, 8), ('changed', 0, 9), ('missing', 0, 10), ('error', 0, 11)]):
        worker.store.put({'path': str(video.parent / f'{i:02}.mkv'), 'state': state, 'updated': updated,
                          'priority': priority, 'project_id': 'deadbeef', 'fingerprint': [1, 2],
                          'detection': {'secret': 'detection-credential'},
                          'poster_url': 'https://unsafe.example/image?secret=secret',
                          'metadata': {'emby_id': '123'}})
    fields = {f'{stage}_{field}': ('ultra' if field == 'effort' else 'fixture')
              for stage in ('primary', 'polish', 'review') for field in ('provider', 'model', 'effort')}
    current = {'current_provider': 'codex_cli', 'current_model': 'gpt-6-astra', 'current_effort': 'medium',
               'current_polish_effort': 'medium', 'current_review_effort': 'medium', 'pending': True, 'error': ''}
    monkeypatch.setattr(worker.model_settings, 'read', lambda: {
        'settings': {'translation': {**fields, 'api_key': 'model-credential'},
                     'providers': {'secret': 'provider-credential'}}, 'state': current})
    response = client.get('/api/library/overview')
    result = response.json()
    assert [row['path'].rsplit('/', 1)[-1] for row in result['queue']] == ['02.mkv', '03.mkv', '01.mkv']
    assert len(result['active']) == 3
    assert {row['state'] for row in result['active']} == {'publishing', 'pausing', 'cancelling'}
    assert result['attention']['counts'] == {'error': 2, 'changed': 1, 'missing': 1}
    assert len(result['attention']['items']) == 3
    listed = {row['path']: row for row in client.get('/api/library/tasks').json()['items']}
    for row in result['queue'] + result['active'] + result['attention']['items']:
        assert row == listed[row['path']]
        assert row['poster_url'].startswith('/api/library/artwork?')
        assert row['server_source_path'].startswith('/host/media/')
        assert row['available_actions']
        assert len(row['control_revision']) == 64
        assert row['progress'] == (None if row['state'] == 'ready' else {'progress': 63, 'stage': 'translate'})
    assert result['models']['desired'] == fields
    assert result['models']['current']['primary_effort'] == 'medium'
    assert result['models']['current']['polish_effort'] == 'medium'
    assert result['models']['pending'] is True
    for secret in ('detection-credential', 'model-credential', 'provider-credential', 'unsafe.example'):
        assert secret not in response.text


def test_fall_dst_counts_repeated_hour_and_empty_calendar(setup, monkeypatch):
    from app.library import overview
    worker, video, client = setup
    monkeypatch.setattr(overview.time, 'time', lambda: stamp('2026-11-02T12:00:00+00:00'))
    empty = client.get('/api/library/overview?timezone=America/Los_Angeles').json()
    assert len(empty['deliveries']['days']) == 7
    assert all(day['count'] == 0 for day in empty['deliveries']['days'])
    assert empty['active'] == empty['queue'] == empty['attention']['items'] == []
    for i, completed in enumerate(['2026-11-01T08:30:00+00:00', '2026-11-01T09:30:00+00:00',
                                   '2026-11-02T07:59:59+00:00', '2026-11-02T08:00:00+00:00']):
        worker.store.put({'path': str(video) + str(i), 'state': 'done', 'updated': 0,
                          'completed_at': stamp(completed)})
    delivery = client.get('/api/library/overview?timezone=America/Los_Angeles').json()['deliveries']
    assert delivery['days'][-2:] == [{'date': '2026-11-01', 'count': 3}, {'date': '2026-11-02', 'count': 1}]
