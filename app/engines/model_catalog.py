"""Shared, versioned model capabilities. Unknown IDs never inherit a short prefix."""
import copy
import json
import re
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'model_catalog.json').read_text())


def model_ids(provider: str) -> list[str]:
    return list(CATALOG['providers'].get(provider, {}).get('models', {}))


def capabilities(provider: str, model: str) -> dict:
    entries = CATALOG['providers'].get(provider, {}).get('models', {})
    model = model.strip() if isinstance(model, str) else ''
    if provider == 'codex_cli':
        from .codex_models import cached_capability
        dynamic = cached_capability(model)
        if dynamic is not None:
            return dynamic
    entry = entries.get(model)
    # Only documented date-style snapshots inherit their exact base model.
    if entry is None and provider == 'openai':
        base = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', model)
        entry = entries.get(base)
    if entry is not None:
        return copy.deepcopy(entry)
    return {'context_window_tokens': None, 'reasoning_efforts': [],
            'temperature': None, 'token_limit_parameter': None, 'source': None}


def context_window(provider: str, model: str) -> int:
    return capabilities(provider, model)['context_window_tokens'] or CATALOG['unknown_context_window_tokens']


def model_efforts(provider: str) -> dict[str, set[str]]:
    return {model: set(capabilities(provider, model)['reasoning_efforts']) for model in model_ids(provider)}


def catalog_response(provider: str, models: list[str], source: str, reason: str = '') -> dict:
    result = {'models': models, 'source': source, 'reason': reason,
              'verified_at': CATALOG['verified_at'],
              'capabilities': {model: capabilities(provider, model) for model in models}}
    if source != 'remote':
        result['fallback'] = True
    return result
