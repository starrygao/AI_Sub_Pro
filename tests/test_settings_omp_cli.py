"""OMP settings preserve choices and gate every selected model's credentials."""
import copy
import json

import pytest
from fastapi.testclient import TestClient


def test_omp_requires_both_selected_model_providers(monkeypatch):
    from app.engines.providers.omp_cli import OmpCliProvider
    from app.services.provider_readiness import _translation_readiness

    monkeypatch.setattr(OmpCliProvider, "check_cli_available", lambda: True)
    monkeypatch.setattr(
        OmpCliProvider, "check_logged_in",
        lambda model: model == "openai-codex/gpt-6-astra",
    )
    config = {"translation": {
        "primary_provider": "omp_cli", "primary_model": "openai-codex/gpt-6-astra",
        "polish_provider": "omp_cli", "polish_model": "anthropic/claude-sonnet-4-6",
    }}
    assert _translation_readiness(config)["translation_ready"] is False
    config["translation"]["polish_provider"] = ""
    assert _translation_readiness(config)["translation_ready"] is True


def test_empty_omp_polish_model_inherits_primary_for_readiness(monkeypatch):
    from app.engines import omp_models
    from app.engines.providers.omp_cli import OmpCliProvider
    from app.engines.translator import SubtitleTranslator
    from app.services.provider_readiness import _translation_readiness

    rows = [{"provider": "custom-provider", "id": "my-model"}]
    monkeypatch.setattr(omp_models, "_live_capabilities", {})
    monkeypatch.setattr(omp_models, "query_models", lambda: rows)
    monkeypatch.setattr(OmpCliProvider, "check_cli_available", lambda: True)
    config = {"translation": {
        "primary_provider": "omp_cli", "primary_model": "custom-provider/my-model",
        "polish_provider": "omp_cli", "polish_model": "",
    }}
    translator = SubtitleTranslator(config)
    assert translator.primary.model == translator.polish.model == "custom-provider/my-model"
    assert _translation_readiness(config)["translation_ready"] is True

    rows.clear()
    assert _translation_readiness(config)["translation_ready"] is False


def test_omp_status_rejects_unavailable_selected_model(monkeypatch):
    from app.engines.providers.omp_cli import OmpCliProvider
    from app.main import app

    monkeypatch.setattr(OmpCliProvider, "check_cli_available", lambda: True)
    monkeypatch.setattr(
        OmpCliProvider, "check_logged_in",
        lambda model: model == "openai-codex/gpt-6-astra",
    )
    client = TestClient(app)
    response = client.get("/api/settings/omp-cli/status", params={"model": "anthropic/unavailable"})
    assert response.status_code == 200
    assert response.json()["installed"] is True
    assert response.json()["logged_in"] is False
    assert response.json()["hint"]


def test_cli_choice_and_custom_model_survive_settings_roundtrip(tmp_path, monkeypatch):
    import app.config as cfg
    from app.api import settings
    from app.main import app

    monkeypatch.setattr(cfg, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cfg.Config, "_data", copy.deepcopy(cfg.DEFAULT_CONFIG))
    monkeypatch.setattr(settings, "Config", cfg.Config)
    client = TestClient(app)
    selected = {
        "primary_provider": "omp_cli", "primary_model": "custom-provider/my-model",
        "primary_effort": "minimal", "polish_provider": "codex_cli",
        "polish_model": "gpt-5.5", "polish_effort": "high",
        "review_provider": "omp_cli", "review_model": "another-provider/review-custom",
        "review_effort": "xhigh",
    }
    response = client.post("/api/settings", json={
        "translation": selected, "providers": {"omp_cli": {"timeout_sec": 600}},
    })
    assert response.status_code == 200
    cfg.Config.load()
    restored = client.get("/api/settings").json()
    assert {key: restored["translation"][key] for key in selected} == selected
    assert restored["providers"]["omp_cli"]["timeout_sec"] == 600

    invalid = client.post("/api/settings", json={"providers": {"omp_cli": {"timeout_sec": 0}}})
    assert invalid.status_code == 400
    assert json.loads(cfg.CONFIG_FILE.read_text())["providers"]["omp_cli"]["timeout_sec"] == 600


def test_adding_omp_support_does_not_change_existing_configuration_identity(tmp_path, monkeypatch):
    import app.config as cfg
    from app.utils.translation_configuration import translation_configuration_hash

    config = copy.deepcopy(cfg.DEFAULT_CONFIG)
    config["translation"].update(primary_provider="codex_cli", primary_model="gpt-5.5", primary_effort="auto")
    config["providers"].pop("omp_cli", None)
    project = {"name": "Existing subtitle", "target_language": "简体中文"}
    before = translation_configuration_hash(project, config=config, effective_kb={}, candidate_terms=[])
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(cfg, "CONFIG_FILE", path)
    monkeypatch.setattr(cfg.Config, "_data", {})
    loaded = cfg.Config.load()
    after = translation_configuration_hash(project, config=loaded, effective_kb={}, candidate_terms=[])
    assert after == before


@pytest.mark.parametrize(('policy', 'semantic_qa', 'strict_gate', 'expected_ready'), [
    ('fast', False, False, True),
    ('fast', True, False, False),
    ('professional', False, False, False),
    ('fast', False, True, False),
])
def test_review_omp_model_credentials_are_required_only_when_semantic_review_runs(
    monkeypatch, policy, semantic_qa, strict_gate, expected_ready,
):
    from app.engines.providers.omp_cli import OmpCliProvider
    from app.services.provider_readiness import _translation_readiness
    monkeypatch.setattr(OmpCliProvider, 'check_cli_available', lambda: True)
    monkeypatch.setattr(OmpCliProvider, 'check_logged_in', lambda model: model == 'primary-service/model')
    config = {'translation': {
        'primary_provider': 'omp_cli', 'primary_model': 'primary-service/model',
        'review_provider': 'omp_cli', 'review_model': 'review-service/model',
        'quality_mode': policy, 'semantic_qa': semantic_qa,
    }}
    readiness = _translation_readiness(config, strict_quality_gate=strict_gate)
    assert readiness['translation_ready'] is expected_ready
    if not expected_ready:
        assert readiness['translation_hint']


def test_review_api_credentials_block_translation_until_configured():
    from app.services.provider_readiness import _translation_readiness
    config = {'translation': {
        'primary_provider': 'openai', 'review_provider': 'deepseek',
        'review_model': 'custom-review', 'semantic_qa': True,
    }, 'api_keys': {'openai': 'primary-key'}}
    readiness = _translation_readiness(config)
    assert not readiness['translation_ready']
    assert readiness['translation_provider'] == 'deepseek'
    assert '质量复核' in readiness['translation_hint']
    config['api_keys']['deepseek'] = 'review-key'
    assert _translation_readiness(config)['translation_ready']
