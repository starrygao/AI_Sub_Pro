import json
import os
import subprocess
import sys
from contextlib import nullcontext
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


def mock_cli_result(monkeypatch, stdout='', stderr='', returncode=1):
    monkeypatch.setattr(OmpCliProvider, 'check_cli_available', staticmethod(lambda: True))
    monkeypatch.setattr(OmpCliProvider, 'check_logged_in', staticmethod(lambda model: True))
    monkeypatch.setattr(omp_models, 'isolated_cli',
                        lambda: nullcontext(('/isolated', '/overlay.json', {})))
    run = Mock(return_value=subprocess.CompletedProcess(['omp'], returncode, stdout, stderr))
    monkeypatch.setattr(omp_models, 'run_cli', run)
    return run


@pytest.mark.parametrize('output', [
    json.dumps({'type': 'error', 'error': '503 upstream unavailable'}),
    json.dumps({'type': 'aborted', 'message': '503 upstream unavailable'}),
    stream(assistant('', 'error', errorMessage='503 upstream unavailable')),
    stream(assistant('partial', 'aborted', errorMessage='503 upstream unavailable')),
])
def test_nonzero_exit_preserves_structured_service_error(monkeypatch, caplog, output):
    run = mock_cli_result(monkeypatch, output, 'ERROR: less useful stderr failure')
    with pytest.raises(ProviderUnavailableError) as caught:
        OmpCliProvider({}).translate_batch([{'id': 1}], 'sys', retries=1)
    for diagnostic in (str(caught.value), caplog.text):
        assert '503 upstream unavailable' in diagnostic
        assert '退出码 1' in diagnostic
        assert 'less useful stderr failure' not in diagnostic
        assert '未返回可识别的错误详情' not in diagnostic
    assert run.call_count == 1


@pytest.mark.parametrize('output', [
    json.dumps({'type': 'error', 'error': {
        'message': '503 capacity exhausted; Bearer private-bearer',
        'token': 'private-envelope-token',
        'prompt': 'private-prompt',
        'request': {'content': 'private-subtitle'},
    }}),
    stream(assistant('private-subtitle', 'error', errorMessage=(
        '503 capacity exhausted; {"api_key": "private-key", "access_token": "private-access", '
        '"password": "private-password"} prompt=private-prompt\nprivate-subtitle'
    ))),
])
@pytest.mark.parametrize('returncode', [0, 1])
def test_structured_service_error_redacts_sensitive_fields(monkeypatch, caplog, output, returncode):
    mock_cli_result(monkeypatch, output, returncode=returncode)
    with pytest.raises(ProviderUnavailableError) as caught:
        OmpCliProvider({}).translate_batch(
            [{'id': 1, 'original': 'private-subtitle'}], 'private-prompt', retries=1,
        )
    for diagnostic in (str(caught.value), caplog.text):
        assert '503 capacity exhausted' in diagnostic
        assert 'private-' not in diagnostic


@pytest.mark.parametrize('prefix', [
    '[omp] Error:',
    'omp: Error:',
    '[2026-10-14T12:00:00Z] [ERROR]',
    '2026-10-14T12:00:00Z [provider] FATAL:',
])
def test_prefixed_stderr_error_is_useful_and_redacted(monkeypatch, caplog, prefix):
    stderr = (
        'OMP banner\nprivate-subtitle\n'
        f'\x1b[31m{prefix} upstream connection refused; api_key=private-key '
        'Authorization: Bearer private-token; token=private-query; '
        'prompt=private-prompt\x1b[0m\n'
        'Warning: no final assistant message\n'
    )
    mock_cli_result(monkeypatch, stderr=stderr)
    with pytest.raises(ProviderUnavailableError) as caught:
        OmpCliProvider({}).translate_batch([{'id': 1}], 'sys', retries=1)
    for diagnostic in (str(caught.value), caplog.text):
        assert 'upstream connection refused' in diagnostic
        assert '退出码 1' in diagnostic
        assert 'private-' not in diagnostic
        assert 'OMP banner' not in diagnostic
        assert '\x1b' not in diagnostic


def test_terminal_stderr_error_wins_over_background_error_logs(monkeypatch):
    mock_cli_result(monkeypatch, stderr=(
        '[models] ERROR: background refresh failed\n'
        'Error: terminal connection refused\n'
        '[cleanup] ERROR: secondary cleanup failed\n'
    ))
    with pytest.raises(ProviderUnavailableError) as caught:
        OmpCliProvider({}).translate_batch([{'id': 1}], 'sys', retries=1)
    assert 'terminal connection refused' in str(caught.value)
    assert 'background' not in str(caught.value)
    assert 'cleanup' not in str(caught.value)


@pytest.mark.parametrize('model', [
    'openai-codex/aisubpro-diagnostic-nonexistent-model',
    'private-selector?token=private-token&prompt=private-prompt',
])
def test_missing_model_stderr_reports_safe_cause_without_help_or_selector(monkeypatch, caplog, model):
    mock_cli_result(monkeypatch, stderr=(
        f'Model "{model}" not found\n'
        'Run `omp models find <pattern>` to search, or `omp models` to list all.\n'
        'private-subtitle\n'
    ))
    with pytest.raises(ProviderUnavailableError) as caught:
        OmpCliProvider({}).translate_batch([{'id': 1}], 'sys', retries=1)
    for diagnostic in (str(caught.value), caplog.text):
        assert 'Model not found' in diagnostic
        assert '退出码 1' in diagnostic
        assert '未返回可识别的错误详情' not in diagnostic
        assert model not in diagnostic
        assert 'private-' not in diagnostic
        assert 'omp models' not in diagnostic


@pytest.mark.parametrize('stderr', [
    '',
    'OMP banner\nprivate-subtitle\nWarning: no last message',
    'user says an error occurred in private-subtitle',
    'user says Model "private-selector" not found',
    'Model "private-selector" not found in private-subtitle',
])
@pytest.mark.parametrize('stdout', [
    '',
    'private malformed stdout',
    json.dumps({'type': 'message_end', 'message': assistant('private-partial')}),
    stream(assistant('[{"id":1,"translation":"private-final"}]')),
])
def test_nonzero_exit_without_error_details_uses_safe_fallback(monkeypatch, caplog, stdout, stderr):
    mock_cli_result(monkeypatch, stdout, stderr)
    with pytest.raises(ProviderUnavailableError) as caught:
        OmpCliProvider({}).translate_batch([{'id': 1}], 'sys', retries=1)
    for diagnostic in (str(caught.value), caplog.text):
        assert '退出码 1' in diagnostic
        assert '未返回可识别的错误详情' in diagnostic
        assert 'private' not in diagnostic


@pytest.mark.parametrize('stdout,stderr', [
    (json.dumps({'type': 'error', 'error': '401 Unauthorized Bearer private-token'}), ''),
    (stream(assistant('', 'error', errorMessage='invalid_api_key private-key')), ''),
    ('', '[omp] Error: refresh_token_expired private-token'),
])
def test_nonzero_authentication_failure_is_not_retried(monkeypatch, caplog, stdout, stderr):
    run = mock_cli_result(monkeypatch, stdout, stderr)
    sleep = Mock()
    monkeypatch.setattr('app.engines.providers.omp_cli.time.sleep', sleep)
    with pytest.raises(ProviderUnavailableError, match='认证失败') as caught:
        OmpCliProvider({}).translate_batch([{'id': 1}], 'sys', retries=3)
    assert 'private-' not in str(caught.value) + caplog.text
    assert run.call_count == 1
    sleep.assert_not_called()


def test_successful_cli_still_uses_terminal_answer_and_validates_ids(monkeypatch):
    output = stream(assistant('[{"id":"009","translation":"你好"}]'))
    mock_cli_result(monkeypatch, output, '[omp] ERROR: nonfatal startup warning', returncode=0)
    provider = OmpCliProvider({})
    assert provider.translate_batch([{'id': '009'}], 'sys', retries=1) == [
        {'id': '009', 'translation': '你好', 'error': ''},
    ]
    result = provider.translate_batch([{'id': '010'}], 'sys', retries=1)
    assert result[0]['translation'] == ''
    assert 'unexpected id' in result[0]['error']
