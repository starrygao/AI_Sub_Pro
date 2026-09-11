"""Start the real packaged process twice against isolated legacy data.

Uses synthetic credentials only; performs no model/TMDB requests. All HTTP
requests bypass proxies and target a randomly allocated loopback port.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request
import uuid


def run_smoke(command, expected_version, catalog_path):
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='aisubpro-release-smoke-') as temp:
        root = Path(temp)
        cfg = root / 'config.json'
        secret = 'release-fixture-' + uuid.uuid4().hex
        cfg.write_text(json.dumps({'api_keys': {'openai': secret}, 'tmdb': {'api_key': secret},
                                   'translation': {'primary_model': 'saved-custom-model', 'polish_provider': ''}}))
        project = root / 'projects' / 'release-smoke'
        project.mkdir(parents=True)
        (project / 'project.json').write_text(json.dumps({'id': 'release-smoke', 'name': 'Release migration fixture', 'status': 'created'}))
        env = dict(os.environ, AI_SUB_PRO_DATA_DIR=temp, AISUBPRO_PORT=str(port), AISUBPRO_HEADLESS='1')
        process = None
        log = (root / 'startup.log').open('w')
        base = f'http://127.0.0.1:{port}'
        def request(path, body=None):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'})
            with http.open(req, timeout=2) as response:
                return response.read().decode()
        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=10)
                process = None
        def start():
            nonlocal process
            process = subprocess.Popen(command + ['--headless'], env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Packaged process exited during startup')
                try:
                    return json.loads(request('/api/settings'))
                except (OSError, ValueError):
                    time.sleep(0.2)
            raise RuntimeError('Packaged startup timed out')
        try:
            for _ in range(2):
                settings = start()
                assert settings['app_info']['version'] == expected_version
                assert settings['translation']['primary_model'] == 'saved-custom-model'
                assert settings['credentials_configured']['openai'] and settings['credentials_configured']['tmdb']
                assert secret not in json.dumps(settings) and secret not in cfg.read_text()
                assert json.loads(request('/api/projects/release-smoke'))['name'] == 'Release migration fixture'
                script = request('/api/model-catalog.js')
                actual = json.loads(script.removeprefix('globalThis.AISUBPRO_MODEL_CATALOG = ').removesuffix(';'))
                assert actual == json.loads(Path(catalog_path).read_text())
                assert 'AISubProModelSettings' in request('/static/js/model-settings.js')
                stop()
            start()
            request('/api/settings', {'clear_credentials': ['openai', 'tmdb']})
            assert not json.loads(request('/api/settings'))['credentials_configured']['openai']
            assert not json.loads(cfg.read_text()).get('_credential_refs')
            stop()
            assert not start()['credentials_configured']['tmdb']
            return {'version': expected_version, 'startup': 'passed', 'catalog': 'passed',
                    'legacy_data': 'passed', 'credential_migration': 'passed',
                    'credential_restart_read': 'passed', 'credential_clear': 'passed'}
        finally:
            # Cleanup is performed by the executable so it owns the Keychain ACL.
            if process is not None and process.poll() is None:
                try: request('/api/settings', {'clear_credentials': ['openai', 'tmdb']})
                except Exception: pass
            stop()
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--catalog', type=Path, default=Path('app/model_catalog.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.bundle) == bool(args.python): parser.error('Choose --bundle or --python')
    command = [str(args.bundle.resolve() / 'Contents/MacOS/AI Sub Pro')] if args.bundle else [str(args.python.absolute()), str(Path('app/main.py').resolve())]
    result = run_smoke(command, args.version, args.catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
