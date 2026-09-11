from app.engines.providers.openai_compat import OpenAICompatProvider


def test_context_windows_use_exact_models_and_dated_snapshots():
    for model, expected in [('gpt-4.1', 1047576), ('gpt-4.1-2025-04-14', 1047576),
                            ('gpt-6-astra', 1050000), ('gpt-4.1-custom', 32000)]:
        provider = OpenAICompatProvider({'provider': 'openai', 'model': model, 'api_key': 'sk-test'})
        assert provider.context_window_tokens == expected


def test_gemini_context_window():
    provider = OpenAICompatProvider({'provider': 'gemini', 'model': 'gemini-3.8-flash', 'api_key': 'test'})
    assert provider.context_window_tokens == 1048576


def test_catalog_endpoint_distinguishes_missing_credentials_from_remote_listing():
    from unittest.mock import patch
    from app.main import app
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    client = TestClient(app)
    with patch('app.api.settings.Config.to_dict', return_value={'api_keys': {}}):
        fallback = client.get('/api/models/openai').json()
    assert fallback['source'] == 'fallback'
    assert fallback['reason'] == 'missing_key'
    assert fallback['capabilities']['gpt-4.1']['context_window_tokens'] == 1047576
    with patch('app.api.settings.Config.to_dict', return_value={'api_keys': {'openai':'test'}}), patch('openai.OpenAI') as sdk:
        sdk.return_value.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(id='custom-model')])
        remote = client.get('/api/models/openai').json()
    assert remote['source'] == 'remote'
    assert remote['models'] == ['custom-model']
    assert remote['capabilities']['custom-model']['context_window_tokens'] is None


def test_catalog_bootstrap_is_the_backend_catalog_and_loaded_before_ui():
    import json
    from pathlib import Path
    from app.main import app
    from fastapi.testclient import TestClient
    response = TestClient(app).get('/api/model-catalog.js')
    assert response.status_code == 200
    payload = json.loads(response.text.removeprefix('globalThis.AISUBPRO_MODEL_CATALOG = ').removesuffix(';'))
    assert payload['providers']['openai']['models']['gpt-4.1']['context_window_tokens'] == 1047576
    html = Path('app/static/index.html').read_text()
    assert html.index('/api/model-catalog.js') < html.index('/static/js/app.js')


def test_openai_effort_is_forwarded_only_when_supported():
    from unittest.mock import patch
    from types import SimpleNamespace
    from app.engines.translator import SubtitleTranslator
    cfg = SubtitleTranslator._build_provider_config('openai', 'gpt-6-astra', 'high', {'openai':'test'}, {})
    provider = OpenAICompatProvider(cfg)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='[{"id":1,"translation":"你好"}]'))])
    with patch.object(provider.client.chat.completions, 'create', return_value=response) as create:
        provider.translate_batch([{'id':1,'original':'hello'}], 'translate', retries=1)
    assert create.call_args.kwargs['reasoning_effort'] == 'high'
    assert 'temperature' not in create.call_args.kwargs


def test_context_budget_is_provider_specific_and_unknown_models_are_conservative():
    from app.engines.model_catalog import capabilities, context_window
    assert context_window('openai', 'gpt-5.6-sol') == 1050000
    assert context_window('codex_cli', 'gpt-5.6-sol') == 272000
    assert context_window('codex_cli', 'gpt-5.3-codex-spark') == 128000
    assert context_window('claude_cli', 'claude-haiku-4-5') == 200000
    assert capabilities('openai', 'not-gpt-4.1')['context_window_tokens'] is None
    assert context_window('openai', 'not-gpt-4.1') == 32000


def test_unsupported_effort_and_unknown_sampling_parameters_are_not_sent():
    from unittest.mock import patch
    from types import SimpleNamespace
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='[{"id":1,"translation":"你好"}]'))])
    for model in ('gpt-4.1', 'gpt-6-astra', 'custom-model'):
        provider = OpenAICompatProvider({'provider':'openai','model':model,'api_key':'test','effort':'ultra'})
        with patch.object(provider.client.chat.completions, 'create', return_value=response) as create:
            provider.translate_batch([{'id':1,'original':'hello'}], 'translate', retries=1)
        assert 'reasoning_effort' not in create.call_args.kwargs
        assert ('temperature' in create.call_args.kwargs) == (model == 'gpt-4.1')
