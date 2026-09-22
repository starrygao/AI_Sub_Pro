"""Resolve the local release identity and unlock only its dedicated keychain.

The managed config and password live in the Git-ignored .local-signing directory.
Explicit CI signing
settings take precedence. Never create or replace identities during a build.
"""
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def register_managed_keychain(keychain, identity):
    result = subprocess.run(
        ['security', 'list-keychains', '-d', 'user'], capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise RuntimeError('Cannot read signing keychain search list')
    paths = shlex.split(result.stdout)
    retained = []
    for path in paths:
        if path == str(keychain):
            continue
        if Path(path).name == keychain.name:
            candidate = subprocess.run(
                ['security', 'find-identity', '-v', '-p', 'codesigning', path],
                capture_output=True, text=True, timeout=15,
            )
            if not candidate.returncode and identity in candidate.stdout:
                continue
        retained.append(path)
    desired = [str(keychain), *retained]
    if desired != paths:
        result = subprocess.run(
            ['security', 'list-keychains', '-d', 'user', '-s', *desired],
            capture_output=True, timeout=15,
        )
        if result.returncode:
            raise RuntimeError('Cannot register project signing keychain')

def prepare():
    explicit = os.environ.get('AISUBPRO_CODESIGN_IDENTITY', '').strip()
    if explicit:
        return explicit, os.environ.get('AISUBPRO_CODESIGN_KEYCHAIN', '')
    root = PROJECT_ROOT / '.local-signing'
    config = json.loads((root / 'identity.json').read_text())
    secret = root / 'keychain-password'
    if root.stat().st_mode & 0o077 or secret.stat().st_mode & 0o077:
        raise RuntimeError('Signing storage must be accessible only to its owner')
    keychain = Path(config['keychain'])
    if not keychain.is_absolute():
        keychain = root / keychain
    register_managed_keychain(keychain, config['identity'])
    password = secret.read_text()
    result = subprocess.run(
        ['security', 'unlock-keychain', '-p', password, str(keychain)],
        capture_output=True, timeout=15,
    )
    if result.returncode:
        raise RuntimeError('Cannot unlock dedicated signing keychain')
    # Unlocking does not authorize codesign to use an imported private key.
    # Scope this to signing keys in the project's dedicated keychain, never
    # the user's login keychain or an explicitly managed CI identity.
    try:
        result = subprocess.run(
            ['security', 'set-key-partition-list', '-S', 'apple-tool:,apple:',
             '-s', '-k', password, str(keychain)],
            capture_output=True, timeout=15,
        )
    except subprocess.SubprocessError:
        raise RuntimeError('Cannot authorize dedicated signing keychain') from None
    if result.returncode:
        raise RuntimeError('Cannot authorize dedicated signing keychain')
    return config['identity'], str(keychain)


if __name__ == '__main__':
    try:
        identity, keychain = prepare()
        if any('\n' in value for value in (identity, keychain)):
            raise ValueError('Invalid signing configuration')
        print(identity)
        print(keychain)
    except Exception:
        print('Signing setup unavailable; configure AISUBPRO_CODESIGN_IDENTITY or restore the local signing setup. No ad-hoc fallback.', file=sys.stderr)
        sys.exit(1)
