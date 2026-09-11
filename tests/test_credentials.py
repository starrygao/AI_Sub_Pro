import copy
import json

import pytest


class MemoryCredentialStore:
    def __init__(self): self.values = {}
    def get(self, key): return self.values.get(key)
    def set(self, key, value): self.values[key] = value
    def delete(self, key): self.values.pop(key, None)


@pytest.fixture(autouse=True)
def restore_config_state(monkeypatch):
    import app.config as cfg
    import app.api.settings as settings
    monkeypatch.setattr(settings, 'Config', cfg.Config)
    monkeypatch.setattr(cfg.Config, '_data', copy.deepcopy(cfg.DEFAULT_CONFIG))


def test_migration_removes_plaintext_only_after_verified_store(tmp_path, monkeypatch):
    import app.config as cfg
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'api_keys': {'openai': 'migration-fixture'}, 'tmdb': {'api_key': 'tmdb-fixture'}}))
    store = MemoryCredentialStore()
    monkeypatch.setattr(cfg, 'credential_store', lambda: store)
    monkeypatch.setattr(cfg, 'CONFIG_FILE', path)
    monkeypatch.setattr(cfg.Config, '_data', {})
    cfg.Config.load()
    disk = path.read_text()
    assert 'migration-fixture' not in disk and 'tmdb-fixture' not in disk
    cfg.Config._data = {}
    cfg.Config.load()
    assert cfg.Config.get('api_keys', 'openai') == 'migration-fixture'
    assert cfg.Config.get('tmdb', 'api_key') == 'tmdb-fixture'
    assert 'migration-fixture' not in json.dumps(cfg.Config.public_dict())
    assert cfg.Config.public_dict()['credentials_configured']['openai'] is True


def test_migration_failure_preserves_original_config(tmp_path, monkeypatch):
    import app.config as cfg
    from app.credentials import CredentialError
    class BrokenStore(MemoryCredentialStore):
        def set(self, key, value):
            raise CredentialError('Credential storage unavailable')
    path = tmp_path / 'config.json'
    original = json.dumps({'api_keys': {'openai': 'original-fixture'}})
    path.write_text(original)
    monkeypatch.setattr(cfg, 'CONFIG_FILE', path)
    monkeypatch.setattr(cfg, 'credential_store', lambda: BrokenStore())
    with pytest.raises(CredentialError):
        cfg.Config.load()
    assert path.read_text() == original


def test_public_api_preserves_blank_and_explicitly_clears_secret(tmp_path, monkeypatch):
    import app.config as cfg
    from app.api.settings import get_settings, update_settings
    monkeypatch.setattr(cfg, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(cfg.Config, '_data', copy.deepcopy(cfg.DEFAULT_CONFIG))
    cfg.Config.update({'api_keys': {'openai': 'api-fixture'}})
    assert get_settings()['api_keys']['openai'] == ''
    assert get_settings()['credentials_configured']['openai'] is True
    update_settings({'api_keys': {'openai': ''}, 'general': {'theme': 'light'}})
    assert cfg.Config.get('api_keys', 'openai') == 'api-fixture'
    update_settings({'clear_credentials': ['openai']})
    assert not get_settings()['credentials_configured']['openai']
    cfg.Config.load()
    assert cfg.Config.get('api_keys', 'openai') == ''


def test_failed_update_does_not_mutate_runtime_or_disk(tmp_path, monkeypatch):
    import app.config as cfg
    from app.credentials import CredentialError
    from app.utils import project_store
    path = tmp_path / 'config.json'
    monkeypatch.setattr(cfg, 'CONFIG_FILE', path)
    monkeypatch.setattr(cfg.Config, '_data', copy.deepcopy(cfg.DEFAULT_CONFIG))
    cfg.Config.update({'api_keys': {'openai': 'before-fixture'}})
    before = path.read_text()
    monkeypatch.setattr(project_store, 'atomic_write_json', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        cfg.Config.update({'api_keys': {'openai': 'after-fixture'}})
    assert cfg.Config.get('api_keys', 'openai') == 'before-fixture'
    assert path.read_text() == before


def test_post_commit_error_does_not_delete_referenced_credentials(tmp_path, monkeypatch):
    import app.config as cfg
    from app.utils import project_store
    path = tmp_path / 'config.json'
    monkeypatch.setattr(cfg, 'CONFIG_FILE', path)
    real_write = project_store.atomic_write_json
    def committed_then_error(path, data):
        real_write(path, data)
        raise OSError('directory sync interrupted')
    monkeypatch.setattr(project_store, 'atomic_write_json', committed_then_error)
    cfg.Config.update({'api_keys': {'openai': 'committed-fixture'}})
    monkeypatch.setattr(project_store, 'atomic_write_json', real_write)
    cfg.Config.load()
    assert cfg.Config.get('api_keys', 'openai') == 'committed-fixture'
    assert 'committed-fixture' not in path.read_text()
