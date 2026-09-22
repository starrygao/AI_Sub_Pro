import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('prepare_signing', Path(__file__).parents[1] / 'tools/release/prepare_signing.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_explicit_identity_does_not_access_managed_credentials(monkeypatch):
    monkeypatch.setenv('AISUBPRO_CODESIGN_IDENTITY', 'CI identity')
    monkeypatch.setenv('AISUBPRO_CODESIGN_KEYCHAIN', '/ci/signing.keychain')
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: pytest.fail('unexpected unlock'))
    assert module.prepare() == ('CI identity', '/ci/signing.keychain')


def test_managed_unlock_is_scoped_and_failure_does_not_disclose_secret(tmp_path, monkeypatch):
    import json
    monkeypatch.delenv('AISUBPRO_CODESIGN_IDENTITY', raising=False)
    monkeypatch.setattr(module, 'PROJECT_ROOT', tmp_path)
    root = tmp_path / '.local-signing'
    root.mkdir(parents=True, mode=0o700)
    (root / 'identity.json').write_text(json.dumps({'identity':'fingerprint','keychain':'signing.keychain'}))
    secret = root / 'keychain-password'
    secret.write_text('synthetic-test-secret')
    secret.chmod(0o600)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='"/other.keychain"\n')
    monkeypatch.setattr(module.subprocess, 'run', run)
    assert module.prepare() == ('fingerprint', str(root / 'signing.keychain'))
    assert calls[1] == ['security', 'list-keychains', '-d', 'user', '-s', str(root / 'signing.keychain'), '/other.keychain']
    assert calls[2] == ['security', 'unlock-keychain', '-p', 'synthetic-test-secret', str(root / 'signing.keychain')]
    assert calls[3] == ['security', 'set-key-partition-list', '-S', 'apple-tool:,apple:',
                        '-s', '-k', 'synthetic-test-secret', str(root / 'signing.keychain')]
    monkeypatch.setattr(module.subprocess, 'run', lambda args, **k: SimpleNamespace(
        returncode=1 if args[1]=='unlock-keychain' else 0, stdout='"/other.keychain"\n'))
    with pytest.raises(RuntimeError, match='Cannot unlock') as error:
        module.prepare()
    assert 'synthetic-test-secret' not in str(error.value)
    secret.chmod(0o644)
    with pytest.raises(RuntimeError, match='only to its owner'):
        module.prepare()


def test_registration_replaces_only_duplicate_identity_and_preserves_other_keychains(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[1] == 'find-identity':
            return SimpleNamespace(returncode=0, stdout='fingerprint' if args[-1].startswith('/old/') else 'other-cert')
        return SimpleNamespace(returncode=0, stdout='"/old/stable.keychain" "login.keychain" "/other/stable.keychain"')
    monkeypatch.setattr(module.subprocess, 'run', run)
    module.register_managed_keychain(Path('/project/stable.keychain'), 'fingerprint')
    assert calls[-1] == ['security', 'list-keychains', '-d', 'user', '-s',
                         '/project/stable.keychain', 'login.keychain', '/other/stable.keychain']
