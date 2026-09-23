"""Discover Codex picker models without starting a thread or a model turn."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone

_lock = threading.Lock()
_live_capabilities = {}


def cache_path():
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'models_cache.json'


def read_cache():
    try:
        data = json.loads(cache_path().read_text())
        if not isinstance(data, dict) or not isinstance(data.get('models'), list):
            return None
        return data
    except (OSError, ValueError):
        return None


def cached_capability(model):
    live = _live_capabilities.get((str(cache_path()), model))
    if live:
        return {**live, 'reasoning_efforts': list(live['reasoning_efforts'])}
    for item in (read_cache() or {}).get('models', []):
        if isinstance(item, dict) and item.get('slug') == model:
            context = item.get('context_window')
            return {'context_window_tokens': context if type(context) is int and context > 0 else None,
                    'reasoning_efforts': reasoning_levels(item.get('supported_reasoning_levels'), 'effort'),
                    'temperature': False, 'token_limit_parameter': None,
                    'source': 'Codex CLI model metadata'}
    return None


def reasoning_levels(items, key):
    return list(dict.fromkeys(item[key] for item in (items if isinstance(items, list) else [])
                             if isinstance(item, dict) and isinstance(item.get(key), str) and item[key]))


def query_models(timeout=15):
    """Use the documented stdio initialize/model/list protocol, with bounded waits."""
    messages = queue.Queue()
    process = subprocess.Popen(['codex', 'app-server', '--listen', 'stdio://'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding='utf-8', start_new_session=(os.name != 'nt'))
    def read():
        try:
            for line in process.stdout:
                try: messages.put(json.loads(line))
                except ValueError: continue
        finally: messages.put(None)
    reader = threading.Thread(target=read, daemon=True); reader.start()
    deadline = time.monotonic() + timeout
    def send(message):
        process.stdin.write(json.dumps(message) + '\n'); process.stdin.flush()
    def request(identifier, method, params):
        send({'id': identifier, 'method': method, 'params': params})
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError('Codex model list timed out')
            message = messages.get(timeout=remaining)
            if message is None: raise RuntimeError('Codex model list closed')
            if isinstance(message, dict) and message.get('id') == identifier:
                if 'error' in message: raise RuntimeError('Codex model list unavailable')
                return message['result']
    try:
        request(0, 'initialize', {'clientInfo': {'name': 'ai_sub_pro', 'version': '1.0'}})
        send({'method': 'initialized', 'params': {}})
        result = []; cursor = None; seen = set()
        for identifier in range(1, 21):
            page = request(identifier, 'model/list', {'limit': 100, 'includeHidden': False, 'cursor': cursor})
            result.extend(page['data'])
            cursor = page.get('nextCursor')
            if not cursor: return result
            if cursor in seen: raise ValueError('Repeated model list cursor')
            seen.add(cursor)
        raise ValueError('Model list exceeds page limit')
    finally:
        if os.name != 'nt':
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        elif process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        process.wait(timeout=5)
        reader.join(timeout=1)
        process.stdin.close(); process.stdout.close()


def catalog(force=False):
    from .model_catalog import catalog_response, model_ids
    with _lock:
        cached = read_cache()
        try:
            age = time.time() - datetime.fromisoformat(cached['fetched_at'].replace('Z', '+00:00')).timestamp()
        except (AttributeError, TypeError, KeyError, ValueError):
            age = float('inf')
        models = None
        attempted = force or not 0 <= age < 300
        if attempted:
            try: models = query_models()
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, queue.Empty, subprocess.TimeoutExpired):
                pass
        if models is not None:
            entries = {item['model']: item for item in models if isinstance(item, dict)
                       and isinstance(item.get('model'), str) and item['model'].strip() and not item.get('hidden')}
            if entries:
                result = catalog_response('codex_cli', list(entries), 'remote', 'codex_model_list')
                result['verified_at'] = datetime.now(timezone.utc).isoformat()
                for model, item in entries.items():
                    result['capabilities'][model]['reasoning_efforts'] = reasoning_levels(item.get('supportedReasoningEfforts'), 'reasoningEffort')
                    _live_capabilities[(str(cache_path()), model)] = result['capabilities'][model]
                return result
        if cached:
            ids = list(dict.fromkeys(item['slug'] for item in cached['models'] if isinstance(item, dict)
                and isinstance(item.get('slug'), str) and item['slug'].strip() and item.get('visibility') == 'list'))
            if ids:
                result = catalog_response('codex_cli', ids, 'cache', 'codex_cache')
                result['verified_at'] = cached.get('fetched_at')
                result['stale'] = not 0 <= age < 300
                result['refresh_failed'] = attempted
                return result
        return catalog_response('codex_cli', model_ids('codex_cli'), 'fallback', 'cli_unavailable')
