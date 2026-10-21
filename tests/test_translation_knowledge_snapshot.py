"""Knowledge edits affect future runs without changing certified delivery inputs."""
import copy
import json
import pytest
from tests.test_knowledge_api import patched_kb_file
from tests.test_project_export import client, _seed_hash_bound_strict_certification


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    import importlib
    from app.config import Config, DEFAULT_CONFIG
    monkeypatch.setattr(Config, '_data', copy.deepcopy(DEFAULT_CONFIG))
    # test_config reloads its module; import-time aliases elsewhere can otherwise
    # keep an older Config class during the full suite. Bind this fixture's users
    # to its isolated class as well as resetting the data.
    for name in ('app.services.translation_tasks', 'app.utils.translation_certification',
                 'app.library.settings', 'app.api.settings', 'app.api.projects'):
        monkeypatch.setattr(importlib.import_module(name), 'Config', Config)


def _completed(tmp_project_dir, pid='kb_complete'):
    _seed_hash_bound_strict_certification(tmp_project_dir, pid)
    path = tmp_project_dir / pid / 'project.json'
    project = json.loads(path.read_text())
    project.update(library_status='done', library_source_path='/video/movie.mkv')
    path.write_text(json.dumps(project))
    return pid


def _put_knowledge(client, target='爱丽丝'):
    response = client.put('/api/knowledge/projects/movie', json={
        'key': 'movie', 'show_title': 'movie',
        'characters': [{'source': 'Alice', 'target': target}],
    })
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('model_sealed', [False, True])
def test_completed_library_preview_survives_future_knowledge_edits(
    client, tmp_project_dir, patched_kb_file, model_sealed,
):
    from app.library.settings import seal_completed_delivery
    pid = _completed(tmp_project_dir)
    if model_sealed:
        assert seal_completed_delivery(pid)
        from app.config import Config
        Config._data['translation']['primary_model'] = 'new-global-default'
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 200
    original = (tmp_project_dir / pid / 'bilingual.srt').read_bytes()
    _put_knowledge(client)
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 200
    _put_knowledge(client, '艾丽丝')
    assert client.post(f'/api/projects/{pid}/export?format=bilingual').status_code == 200
    assert (tmp_project_dir / pid / 'bilingual.srt').read_bytes() == original


def test_ignoring_candidate_preserves_completed_delivery(client, tmp_project_dir, patched_kb_file):
    from app.engines.kb_suggestions import KbSuggestion, save_suggestions
    pid = 'kb_candidate'; pdir = tmp_project_dir / pid; pdir.mkdir()
    candidate = KbSuggestion(source='Alice', target='爱丽丝', category='characters')
    save_suggestions(pdir / 'kb_suggestions.json', [candidate])
    _completed(tmp_project_dir, pid)
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 200
    response = client.post(f'/api/knowledge/projects/{pid}/suggestions/{candidate.id}/status',
                           json={'status': 'rejected', 'target': '爱丽丝'})
    assert response.status_code == 200
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 200


def test_knowledge_edit_does_not_certify_invalid_historical_output(client, tmp_project_dir, patched_kb_file):
    pid = _completed(tmp_project_dir)
    (tmp_project_dir / pid / 'bilingual.srt').write_text('tampered')
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 409
    _put_knowledge(client)
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 409
    project = json.loads((tmp_project_dir / pid / 'project.json').read_text())
    assert 'translation_knowledge_context' not in project


@pytest.mark.parametrize('already_frozen', [False, True])
def test_legacy_review_migration_preserves_completed_delivery_identity(
    client, tmp_project_dir, patched_kb_file, already_frozen,
):
    from app.config import Config
    from app.library.settings import seal_completed_delivery
    from app.utils.translation_certification import validate_translation_delivery
    for field in ('provider', 'model', 'effort'):
        Config._data['translation'].pop(f'review_{field}')
    pid = _completed(tmp_project_dir, 'legacy_review')
    pdir = tmp_project_dir / pid
    if already_frozen:
        assert seal_completed_delivery(pid)
    before = json.loads((pdir / 'project.json').read_text())
    original_bytes = (pdir / 'bilingual.srt').read_bytes()
    Config.save()
    Config.load()
    project = json.loads((pdir / 'project.json').read_text())
    assert project['translation_quality_configuration_hash'] == before['translation_quality_configuration_hash']
    assert 'review_model' not in project['library_delivery_config']['translation']
    if already_frozen:
        assert project['library_delivery_config'] == before['library_delivery_config']
    assert validate_translation_delivery(project, pdir).valid
    Config.update({'translation': {'review_model': 'future-review-model', 'review_effort': 'high'}})
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 200
    assert (pdir / 'bilingual.srt').read_bytes() == original_bytes


def test_legacy_review_migration_never_certifies_invalid_historical_delivery(
    client, tmp_project_dir, patched_kb_file,
):
    from app.config import Config
    for field in ('provider', 'model', 'effort'):
        Config._data['translation'].pop(f'review_{field}')
    pid = _completed(tmp_project_dir, 'invalid_legacy_review')
    pdir = tmp_project_dir / pid
    (pdir / 'bilingual.srt').write_text('tampered')
    Config.save()
    Config.load()
    project = json.loads((pdir / 'project.json').read_text())
    assert 'library_delivery_config' not in project
    assert 'translation_knowledge_context' not in project
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 409


def test_running_translation_polish_and_qa_keep_context_until_next_run(
    client, tmp_project_dir, patched_kb_file, monkeypatch,
):
    from unittest.mock import Mock
    from app.config import Config
    from app.engines import translator
    from app.engines.kb_suggestions import load_suggestions
    from app.services import translation_tasks as tasks
    from app.utils.translation_certification import validate_translation_delivery
    _put_knowledge(client)
    pid = 'kb_running'; pdir = tmp_project_dir / pid; pdir.mkdir()
    (pdir / 'project.json').write_text(json.dumps({'id': pid, 'name': 'movie',
        'source_type': 'subtitle', 'status': 'asr_done', 'target_language': '简体中文'}))
    (pdir / 'raw.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\nHello Alice.\n\n'
                                 '2\n00:00:04,000 --> 00:00:07,000\nGoodbye Alice.\n')
    Config._data['translation'].update(primary_provider='codex_cli', primary_model='primary',
        polish_provider='codex_cli', polish_model='polish', full_doc_mode=False, batch_size=1,
        quality_mode='fast', semantic_qa=False, qa_auto_repair=False,
        use_translation_memory=False, use_phrase_library=False)
    calls = []; edited = False
    def factory(_name, config):
        provider = Mock(supports_full_document_mode=False, context_window_tokens=100000)
        def translate(items, prompt):
            nonlocal edited
            calls.append((config['model'], prompt))
            if not edited:
                edited = True
                _put_knowledge(client, '艾丽丝')
                candidate = load_suggestions(pdir / 'kb_suggestions.json')[0]
                response = client.post(f'/api/knowledge/projects/{pid}/suggestions/{candidate.id}/status',
                                       json={'status': 'rejected'})
                assert response.status_code == 200
            name = '艾丽丝' if 'Alice → 艾丽丝' in prompt else '爱丽丝'
            return [{'id': item['id'], 'translation': '你好，' + name + '。'} for item in items]
        provider.translate_batch.side_effect = translate
        return provider
    monkeypatch.setattr(translator, 'get_provider', factory)
    tasks._run_translate_pipeline(pid, '简体中文', burn_follows=False)
    project = json.loads((pdir / 'project.json').read_text())
    assert project['status'] == 'translated', project.get('error')
    assert validate_translation_delivery(project, pdir).valid
    assert [model for model, _ in calls] == ['primary', 'polish', 'primary', 'polish']
    assert all('Alice → 爱丽丝' in prompt and 'Alice → 艾丽丝' not in prompt for _, prompt in calls)
    old_context = project['translation_knowledge_context']
    calls.clear()
    tasks._run_translate_pipeline(pid, '简体中文', burn_follows=False)
    project = json.loads((pdir / 'project.json').read_text())
    assert project['status'] == 'translated', project.get('error')
    assert project['translation_knowledge_context']['run_id'] != old_context['run_id']
    assert validate_translation_delivery(project, pdir).valid
    assert calls and all('Alice → 艾丽丝' in prompt for _, prompt in calls)


@pytest.mark.parametrize('tamper', ['source', 'translation', 'report', 'metadata', 'snapshot', 'run'])
def test_frozen_knowledge_never_bypasses_delivery_or_identity_checks(
    client, tmp_project_dir, patched_kb_file, tamper,
):
    pid = _completed(tmp_project_dir); pdir = tmp_project_dir / pid
    _put_knowledge(client)
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 200
    if tamper == 'source':
        (pdir / 'raw.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nDifferent source\n')
    elif tamper == 'translation':
        (pdir / 'bilingual.srt').write_text('changed artifact')
    elif tamper == 'report':
        path = pdir / 'translation_qa_report.json'; data = json.loads(path.read_text())
        data['configuration_hash'] = 'sha256:tampered'; path.write_text(json.dumps(data))
    else:
        path = pdir / 'project.json'; data = json.loads(path.read_text())
        if tamper == 'metadata': data['tmdb_type'] = 'tv'
        if tamper == 'snapshot': data['translation_knowledge_context']['effective_kb']['selection'] = {'show_title': 'other'}
        if tamper == 'run': data['translation_knowledge_context']['run_id'] = 'other-run'
        path.write_text(json.dumps(data))
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 409


def test_legacy_bulk_knowledge_edit_preserves_old_delivery(client, tmp_project_dir, patched_kb_file):
    pid = _completed(tmp_project_dir)
    response = client.post('/api/knowledge', json={'movie': {'show_title': 'movie',
        'characters': [{'source': 'Alice', 'target': '爱丽丝'}]}})
    assert response.status_code == 200
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 200


def test_legacy_upgrade_does_not_block_on_a_delivery_reader(client, tmp_project_dir, patched_kb_file):
    import threading
    from app.utils.translation_delivery import translation_delivery_lock
    pid = _completed(tmp_project_dir)
    acquired = threading.Event(); release = threading.Event()
    def reader():
        with translation_delivery_lock(pid):
            acquired.set(); release.wait(5)
    thread = threading.Thread(target=reader); thread.start()
    try:
        assert acquired.wait(2)
        response = client.put('/api/knowledge/projects/movie', json={'key': 'movie', 'show_title': 'movie'})
        assert response.status_code == 409
        assert client.get('/api/knowledge').json() == {}
    finally:
        release.set(); thread.join(2)
    _put_knowledge(client)
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 200


def test_historical_snapshot_does_not_persist_provider_credentials(client, tmp_project_dir, patched_kb_file):
    from app.config import Config
    Config._data.setdefault('providers', {}).setdefault('codex_cli', {})['session_token'] = 'fixture-secret-never-persist'
    pid = _completed(tmp_project_dir)
    _put_knowledge(client)
    project_text = (tmp_project_dir / pid / 'project.json').read_text()
    assert 'fixture-secret-never-persist' not in project_text
    assert 'session_token' not in project_text
    assert client.get(f'/api/projects/{pid}/subtitles').status_code == 200
