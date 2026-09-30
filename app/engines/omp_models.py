"""Credential-filtered OMP model discovery; never starts a model turn."""
import copy
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OMP_CLI_MODEL = 'openai-codex/gpt-6-astra'
_lock = threading.Lock()
_cached = None
_cached_at = 0.0
_live_capabilities = {}

# These are discovery sources, not inference providers. Keep the real auth store
# and models.yml available while excluding user/project coding instructions.
_DISCOVERY_SOURCES = [
    'native', 'omp-plugins', 'claude', 'agent-plugins', 'codex', 'agents',
    'claude-plugins', 'gemini', 'opencode', 'windsurf', 'cline',
    'github', 'vscode', 'agents-md', 'claude-md', 'mcp-json', 'ssh-json',
    'builtin-defaults',
]
_ISOLATION_CONFIG = {
    'disabledProviders': _DISCOVERY_SOURCES,
    'enabledProviders': [], 'enabledModels': [],
    'advisor': {'enabled': False}, 'memory': {'backend': 'off'},
    'autolearn': {'enabled': False, 'autoContinue': False},
    'compaction': {'enabled': False, 'asyncEnabled': False},
    'contextPromotion': {'enabled': False},
    'retry': {'enabled': False, 'modelFallback': False},
    'prewalk': {'enabled': False}, 'personality': 'none',
    'includeWorkspaceTree': False, 'extendedContext': False,
    'externalThinking': False, 'providers': {'cacheWarming': 'off'},
}


@contextmanager
def isolated_cli():
    """One-shot overlay, not a profile: OAuth remains owned/refreshed by OMP."""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(('PI_', 'OMP_')) and not (
            key in {'PI_CONFIG_DIR', 'PI_CODING_AGENT_DIR', 'PI_PROFILE', 'OMP_PROFILE'}
            or key.startswith(('OMP_AUTH_BROKER_', 'PI_PROXY', 'PI_CODEX_', 'PI_OPENAI_', 'PI_AI_'))
        ):
            env.pop(key)
    with tempfile.TemporaryDirectory(prefix='aisubpro-omp-') as cwd:
        overlay = Path(cwd) / 'config.json'
        # JSON is valid YAML; this file is private and contains no credentials.
        overlay.write_text(json.dumps(_ISOLATION_CONFIG), encoding='utf-8')
        yield cwd, str(overlay), env


def _terminate_process_group(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        # The leader may exit before its children; still kill the whole group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)


def run_cli(args, *, cwd, env, timeout, prompt=None):
    process = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace',
                               start_new_session=(os.name != 'nt'))
    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout)
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    except BaseException:
        _terminate_process_group(process)
        raise
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def query_models(timeout=20, *, refresh=False):
    """OMP's available catalog filters by resolvable auth, unlike its registry.

    This establishes local credential availability, not remote account validity.
    No tokens are requested, read by this process, or included in diagnostics.
    """
    with isolated_cli() as (cwd, overlay, env):
        result = run_cli(['omp', 'models', 'refresh' if refresh else 'ls',
                          '--json', '--no-extensions', '--config', overlay],
                         cwd=cwd, env=env, timeout=timeout)
    if result.returncode:
        raise RuntimeError('OMP model metadata unavailable')
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise ValueError('OMP returned invalid model metadata') from None
    if not isinstance(payload, dict) or not isinstance(payload.get('models'), list):
        raise ValueError('OMP returned invalid model metadata')
    return payload['models']


def model_entries(rows):
    entries = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('kind', 'chat') != 'chat':
            continue
        provider, model = row.get('provider'), row.get('id')
        if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
            continue
        selector = f'{provider}/{model}'
        if row.get('selector', selector) != selector:
            continue
        context = row.get('contextWindow')
        thinking = row.get('thinking')
        efforts = list(dict.fromkeys(value for value in (thinking if isinstance(thinking, list) else [])
                                     if isinstance(value, str) and value))
        entries[selector] = {
            'context_window_tokens': context if type(context) is int and context > 0 else None,
            'reasoning_efforts': efforts, 'temperature': None,
            'token_limit_parameter': None, 'source': 'OMP CLI model metadata',
        }
    return entries


def cached_capability(model):
    entry = _live_capabilities.get(model)
    return copy.deepcopy(entry) if entry is not None else None


def available_model(model):
    """Never infer authentication from cached or bundled model names."""
    entries = model_entries(query_models())
    _live_capabilities.update(entries)
    return model in entries


def catalog(force=False):
    from .model_catalog import catalog_response, model_ids
    global _cached, _cached_at
    with _lock:
        if not force and _cached is not None and time.monotonic() - _cached_at < 300:
            return copy.deepcopy(_cached)
        try:
            entries = model_entries(query_models(refresh=force))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            if _cached is not None:
                result = copy.deepcopy(_cached)
                result.update(source='cache', fallback=True, stale=True, refresh_failed=True)
                return result
            return catalog_response('omp_cli', model_ids('omp_cli'), 'fallback', 'cli_unavailable')
        _live_capabilities.clear()
        _live_capabilities.update(entries)
        result = catalog_response('omp_cli', list(entries), 'remote', 'omp_available_models')
        result['verified_at'] = datetime.now(timezone.utc).isoformat()
        _cached, _cached_at = copy.deepcopy(result), time.monotonic()
        return result
