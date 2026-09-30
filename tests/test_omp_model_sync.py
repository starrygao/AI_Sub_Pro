import json
import sys

import pytest

from app.engines import omp_models
from app.engines.model_catalog import capabilities, context_window
from app.engines.providers.omp_cli import OmpCliProvider


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch):
    monkeypatch.setattr(omp_models, '_cached', None)
    monkeypatch.setattr(omp_models, '_cached_at', 0.0)
    monkeypatch.setattr(omp_models, '_live_capabilities', {})


def test_dynamic_model_metadata_retains_selector_and_uses_conservative_unknowns(monkeypatch):
    monkeypatch.setattr(omp_models, 'query_models', lambda **kwargs: [
        {'provider': 'remote', 'id': 'future', 'selector': 'remote/future',
         'contextWindow': 654321, 'thinking': ['low', 'max', 'low']},
        {'provider': 'remote', 'id': 'unknown', 'contextWindow': True, 'thinking': None},
        {'provider': 'remote', 'id': 'image', 'kind': 'image', 'contextWindow': 999999},
        {'provider': 'remote', 'id': 'wrong', 'selector': 'different/wrong'},
    ])
    result = omp_models.catalog(force=True)
    assert result['models'] == ['remote/future', 'remote/unknown']
    assert context_window('omp_cli', 'remote/future') == 654321
    assert capabilities('omp_cli', 'remote/future')['reasoning_efforts'] == ['low', 'max']
    unknown = capabilities('omp_cli', 'remote/unknown')
    assert unknown['context_window_tokens'] is None
    assert unknown['reasoning_efforts'] == [] and unknown['temperature'] is None
    assert context_window('omp_cli', 'remote/future-preview') == 32000


def test_readiness_requires_selected_exact_model_in_fresh_authenticated_catalog(monkeypatch):
    rows = [{'provider': 'other', 'id': 'gpt-6-astra'}]
    monkeypatch.setattr(omp_models, 'query_models', lambda **kwargs: rows)
    omp_models.catalog(force=True)
    assert not OmpCliProvider.check_logged_in('openai-codex/gpt-6-astra')
    assert OmpCliProvider.check_logged_in('other/gpt-6-astra')
    rows.clear()
    assert not OmpCliProvider.check_logged_in('other/gpt-6-astra')
    assert not OmpCliProvider.check_logged_in('gpt-6-astra')


def test_metadata_outage_can_display_stale_models_but_cannot_pass_auth(monkeypatch):
    monkeypatch.setattr(omp_models, 'query_models', lambda **kwargs: [{'provider': 'remote', 'id': 'ready'}])
    omp_models.catalog(force=True)
    def unavailable(**kwargs):
        raise OSError('offline')
    monkeypatch.setattr(omp_models, 'query_models', unavailable)
    result = omp_models.catalog(force=True)
    assert result['models'] == ['remote/ready']
    assert result['source'] == 'cache' and result['stale'] and result['refresh_failed']
    assert not OmpCliProvider.check_logged_in('remote/ready')


def test_fresh_unauthenticated_catalog_does_not_substitute_bundled_model(monkeypatch):
    monkeypatch.setattr(omp_models, 'query_models', lambda **kwargs: [])
    result = omp_models.catalog(force=True)
    assert result['models'] == [] and result['source'] == 'remote'
    assert not OmpCliProvider.check_logged_in()


def test_unavailable_cli_marks_static_picker_fallback_without_auth(monkeypatch):
    def unavailable(**kwargs):
        raise OSError('not installed')
    monkeypatch.setattr(omp_models, 'query_models', unavailable)
    result = omp_models.catalog(force=True)
    assert result['models'] == ['openai-codex/gpt-6-astra']
    assert result['source'] == 'fallback' and result['reason'] == 'cli_unavailable'
    assert not OmpCliProvider.check_logged_in()


def test_manual_refresh_discovers_models_published_after_cli_cache_was_created(tmp_path, monkeypatch):
    from app.api.settings import list_models

    provider_catalog = tmp_path / 'provider.json'
    cli_cache = tmp_path / 'cache.json'
    cli = tmp_path / 'models_cli.py'
    cli.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "root = Path(os.environ['MODEL_TEST_DIR'])\n"
        "cache = root / 'cache.json'\n"
        "if 'refresh' in sys.argv or not cache.exists():\n"
        "    cache.write_text((root / 'provider.json').read_text())\n"
        "print(cache.read_text())\n"
    )
    monkeypatch.setenv('MODEL_TEST_DIR', str(tmp_path))
    real_run = omp_models.run_cli
    monkeypatch.setattr(
        omp_models, 'run_cli',
        lambda args, **kwargs: real_run([sys.executable, str(cli), *args[1:]], **kwargs),
    )
    old_model = {'provider': 'openai-codex', 'id': 'gpt-6-sol', 'contextWindow': 272000}
    new_model = {'provider': 'openai-codex', 'id': 'gpt-6.1-sol', 'contextWindow': 272000}
    provider_catalog.write_text(json.dumps({'models': [old_model]}))
    assert list_models('omp_cli')['models'] == ['openai-codex/gpt-6-sol']

    provider_catalog.write_text(json.dumps({'models': [old_model, new_model]}))
    assert list_models('omp_cli')['models'] == ['openai-codex/gpt-6-sol']
    refreshed = list_models('omp_cli', refresh=True)
    assert refreshed['models'] == ['openai-codex/gpt-6-sol', 'openai-codex/gpt-6.1-sol']
    assert json.loads(cli_cache.read_text())['models'] == [old_model, new_model]
    assert OmpCliProvider.check_logged_in('openai-codex/gpt-6.1-sol')
