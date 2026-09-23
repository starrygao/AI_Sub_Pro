import json
from datetime import datetime, timezone

import pytest

from app.engines import codex_models

QUERY_MODELS = codex_models.query_models


@pytest.fixture(autouse=True)
def isolated_catalog(tmp_path, monkeypatch):
    path = tmp_path / 'models_cache.json'
    monkeypatch.setattr(codex_models, 'cache_path', lambda: path)
    monkeypatch.setattr(codex_models, '_live_capabilities', {})
    monkeypatch.setattr(codex_models, 'query_models', lambda: (_ for _ in ()).throw(OSError('offline')))
    return path


def test_fresh_cli_cache_lists_visible_models_and_provider_keeps_new_efforts(isolated_catalog, monkeypatch):
    from app.engines.providers.codex_cli import CodexCliProvider
    from app.engines.model_catalog import context_window
    from app.api.settings import list_models
    isolated_catalog.write_text(json.dumps({'fetched_at': datetime.now(timezone.utc).isoformat(), 'models': [
        {'slug': 'gpt-new-fixture', 'visibility': 'list', 'context_window': 272000,
         'supported_reasoning_levels': [{'effort': 'low'}, {'effort': 'ultra'}]},
        {'slug': 'hidden-fixture', 'visibility': 'hide'}]}))
    monkeypatch.setattr(codex_models, 'query_models', lambda: pytest.fail('fresh cache should not spawn CLI'))
    result = list_models('codex_cli')
    assert result['models'] == ['gpt-new-fixture']
    assert result['source'] == 'cache' and result['stale'] is False
    assert result['capabilities']['gpt-new-fixture']['reasoning_efforts'] == ['low', 'ultra']
    assert CodexCliProvider({'model': 'gpt-new-fixture', 'effort': 'ultra'}).effort == 'ultra'
    assert context_window('codex_cli', 'gpt-new-fixture') == 272000
    assert CodexCliProvider({'model': 'gpt-new-fixture', 'effort': 'high'}).effort == 'auto'


def test_force_refresh_picks_up_new_models_and_efforts_without_cache_write(monkeypatch):
    from app.api.settings import list_models
    from app.engines.providers.codex_cli import CodexCliProvider
    monkeypatch.setattr(codex_models, 'query_models', lambda: [
        {'model': 'brand-new-model', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]},
        {'model': 'hidden-fixture', 'hidden': True}])
    result = list_models('codex_cli', refresh=True)
    assert result['models'] == ['brand-new-model']
    assert result['source'] == 'remote' and not result.get('fallback')
    assert CodexCliProvider({'model': 'brand-new-model', 'effort': 'high'}).effort == 'high'


def test_unavailable_cli_uses_marked_stale_cache_then_builtin_fallback(isolated_catalog):
    isolated_catalog.write_text(json.dumps({'fetched_at': '2020-01-01T00:00:00Z', 'models': [
        {'slug': 'cached-fixture', 'visibility': 'list', 'supported_reasoning_levels': None}]}))
    result = codex_models.catalog()
    assert result['models'] == ['cached-fixture'] and result['stale']
    isolated_catalog.write_text('{broken')
    result = codex_models.catalog()
    assert result['source'] == 'fallback' and result['reason'] == 'cli_unavailable'
    assert 'gpt-6-astra' in result['models']


@pytest.mark.parametrize('timeout', [False, True])
def test_model_list_protocol_paginates_without_starting_turns_and_cleans_up(tmp_path, monkeypatch, timeout):
    import subprocess
    import sys
    import queue
    # Use the real protocol runner with an isolated JSONL peer, never the user's Codex.
    original_query = QUERY_MODELS
    script = tmp_path / 'peer.py'; log = tmp_path / 'requests.jsonl'
    script.write_text('''import sys,json,time
with open(sys.argv[1], 'w') as log:
 for line in sys.stdin:
  log.write(line);log.flush();m=json.loads(line)
  if m['method']=='initialize':r={}
  elif m['method']=='initialized':continue
  elif m['method']=='model/list':
   r={'data':[{'model':'second' if m['params']['cursor'] else 'first'}],'nextCursor':None if m['params']['cursor'] else 'more'}
  else:raise AssertionError(m['method'])
  print(json.dumps({'id':m['id'],'result':r}),flush=True)
''')
    real = subprocess.Popen; children = []
    def launch(cmd, **kwargs):
        assert cmd == ['codex', 'app-server', '--listen', 'stdio://']
        args = [sys.executable, '-c', 'import time;time.sleep(20)'] if timeout else [sys.executable, str(script), str(log)]
        process = real(args, **kwargs); children.append(process); return process
    monkeypatch.setattr(codex_models.subprocess, 'Popen', launch)
    if timeout:
        with pytest.raises((TimeoutError, queue.Empty)):
            original_query(timeout=.05)
    else:
        assert [x['model'] for x in original_query(timeout=5)] == ['first', 'second']
        methods = [json.loads(line)['method'] for line in log.read_text().splitlines()]
        assert methods == ['initialize', 'initialized', 'model/list', 'model/list']
    assert children[0].poll() is not None
