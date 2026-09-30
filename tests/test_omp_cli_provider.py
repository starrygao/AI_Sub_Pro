import json
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from app.engines import omp_models
from app.engines.providers.base import ProviderUnavailableError
from app.engines.providers.omp_cli import OmpCliProvider


def assistant(text, reason='stop', **extra):
    return {'role': 'assistant', 'stopReason': reason,
            'content': [{'type': 'thinking', 'thinking': '[{"id":1,"translation":"not an answer"}]'},
                        {'type': 'text', 'text': text}], **extra}


def stream(*messages, **extra):
    return json.dumps({'type': 'agent_end', 'messages': list(messages), **extra})


def test_final_answer_excludes_echoes_thinking_and_earlier_messages():
    events = [
        {'type': 'message_end', 'message': {'role': 'user', 'content': 'private source'}},
        {'type': 'message_update', 'message': assistant('unfinished')},
        {'type': 'agent_end', 'isTerminal': False, 'messages': [assistant('intermediate')]},
        {'type': 'agent_end', 'messages': [assistant('earlier'), assistant('[{"id":9,"translation":"你好"}]')]},
    ]
    answer = OmpCliProvider._extract_answer('\n'.join(json.dumps(event) for event in events))
    assert json.loads(answer) == [{'id': 9, 'translation': '你好'}]


@pytest.mark.parametrize('output', [
    stream(assistant('partial'), isTerminal=False),
    stream(assistant('partial'), yielded=False),
    stream(assistant('partial', 'length')),
    stream(assistant('partial', 'aborted')),
    stream(assistant('', 'error', errorMessage='upstream unavailable')),
    stream(assistant('')),
    stream({'role': 'user', 'content': 'source echo'}),
    json.dumps({'type': 'message_end', 'message': assistant('not terminal')}),
    'plain text is not a protocol',
])
def test_incomplete_or_failed_stream_never_becomes_translation(output):
    with pytest.raises((RuntimeError, ValueError)):
        OmpCliProvider._extract_answer(output)


def test_zero_exit_auth_error_is_provider_unavailable_without_credential_leak():
    output = stream(assistant('', 'error', errorMessage='401 Unauthorized Bearer private-token'))
    with pytest.raises(ProviderUnavailableError, match='认证失败') as error:
        OmpCliProvider._extract_answer(output)
    assert 'private-token' not in str(error.value)


def test_id_reconciliation_preserves_request_order_and_semantic_fields():
    items = [{'id': 81}, {'id': '009'}]
    output = json.dumps([
        {'id': '009', 'translation': '', 'verdict': 'accept', 'taxonomy': [], 'source_evidence': ['yes']},
        {'id': 81, 'translation': '你好'},
    ])
    assert OmpCliProvider._parse(output, items) == [
        {'id': 81, 'translation': '你好', 'error': ''},
        {'id': '009', 'translation': '', 'error': '', 'verdict': 'accept', 'taxonomy': [], 'source_evidence': ['yes']},
    ]


@pytest.mark.parametrize('rows,expected', [
    ([{'id': 3, 'translation': '错'}], 'unexpected id'),
    ([{'id': 1, 'translation': '甲'}, {'id': 1, 'translation': '乙'}], 'duplicate id'),
    ([{'id': 1, 'translation': '甲'}], 'missing in model response'),
])
def test_mismatched_ids_do_not_shift_translations(rows, expected):
    result = OmpCliProvider._parse(json.dumps(rows), [{'id': 1}, {'id': 2}])
    assert result[1]['id'] == 2 and result[1]['translation'] == ''
    assert expected in result[1]['error']


@pytest.mark.parametrize('answer', ['', '[]', '{}', 'private source echo'])
def test_invalid_final_payload_is_service_failure_not_blank_subtitles(monkeypatch, answer):
    monkeypatch.setattr(OmpCliProvider, 'check_cli_available', staticmethod(lambda: True))
    monkeypatch.setattr(OmpCliProvider, 'check_logged_in', staticmethod(lambda model: True))
    monkeypatch.setattr(OmpCliProvider, '_invoke', lambda *args: answer)
    with pytest.raises(ProviderUnavailableError) as error:
        OmpCliProvider({}).translate_batch([{'id': 1}], 'sys', retries=1)
    assert 'private source echo' not in str(error.value)


def test_timeout_does_not_leak_subtitle_prompt_and_stays_batch_failure(monkeypatch):
    monkeypatch.setattr(OmpCliProvider, 'check_cli_available', staticmethod(lambda: True))
    monkeypatch.setattr(OmpCliProvider, 'check_logged_in', staticmethod(lambda model: True))
    monkeypatch.setattr(OmpCliProvider, '_invoke', Mock(side_effect=subprocess.TimeoutExpired(['omp', 'private-source'], 30)))
    with pytest.raises(ProviderUnavailableError, match='30 秒') as error:
        OmpCliProvider({'timeout_sec': 30}).translate_batch([{'id': 1}], 'sys', retries=1)
    assert 'private-source' not in str(error.value)


@pytest.mark.skipif(os.name == 'nt', reason='POSIX process group cleanup')
def test_timeout_reaps_cli_process(tmp_path, monkeypatch):
    real_popen = subprocess.Popen
    processes = []
    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(omp_models.subprocess, 'Popen', launch)
    with pytest.raises(subprocess.TimeoutExpired):
        omp_models.run_cli([sys.executable, '-c', 'import time; time.sleep(30)'],
                           cwd=str(tmp_path), env=dict(os.environ), timeout=.1)
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed
