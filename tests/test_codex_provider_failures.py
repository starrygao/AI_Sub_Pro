"""A failed Codex session must stop the task, not become missing subtitles."""
from datetime import timedelta
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def _failing_cli(monkeypatch, stderr):
    from app.engines.providers import codex_cli

    monkeypatch.setattr(codex_cli.CodexCliProvider, "check_cli_available", staticmethod(lambda: True))
    monkeypatch.setattr(codex_cli.CodexCliProvider, "check_logged_in", staticmethod(lambda: True))
    process = Mock(returncode=1)
    process.communicate.return_value = ("", stderr)
    invoke = Mock(return_value=process)
    monkeypatch.setattr(codex_cli.subprocess, "Popen", invoke)
    sleep = Mock()
    monkeypatch.setattr(codex_cli.time, "sleep", sleep)
    return invoke, sleep


@pytest.mark.parametrize("full_doc_mode", [False, True])
def test_expired_codex_login_stops_translation_before_missing_retries(
    monkeypatch, full_doc_mode,
):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    invoke, sleep = _failing_cli(
        monkeypatch,
        "2026-09-28T04:54:25Z ERROR codex_login::auth::manager: "
        "Failed to refresh token: 401 Unauthorized: "
        '{"error":{"code":"refresh_token_reused"}}',
    )
    translator = SubtitleTranslator({
        "translation": {
            "primary_provider": "codex_cli", "primary_model": "gpt-6-astra",
            "batch_size": 2, "full_doc_mode": full_doc_mode,
            "use_translation_memory": False, "use_phrase_library": False,
            "missing_translation_retries": 2,
        },
    })
    blocks = [SubtitleBlock(
        index=i, start=timedelta(seconds=i), end=timedelta(seconds=i + 1),
        text="What's wrong, Fry?",
    ) for i in range(1, 7)]

    with pytest.raises(RuntimeError, match="Codex CLI.*登录.*失效") as caught:
        translator.translate(blocks)

    assert "refresh_token_reused" in str(caught.value)
    assert "codex login" in str(caught.value)
    assert "大量空结果" not in str(caught.value)
    assert invoke.call_count == 1
    sleep.assert_not_called()
    assert not any(block.translation for block in blocks)


@pytest.mark.parametrize("diagnostic", [
    "ERROR: Your access token could not be refreshed because your refresh "
    "token was already used. Please log out and sign in again.",
    "ERROR: unexpected status 401 Unauthorized: Provided authentication token is expired.",
    'ERROR: Failed to refresh token: {"error":{"code":"refresh_token_invalidated"}}',
])
def test_codex_auth_error_is_detected_before_stderr_is_truncated(monkeypatch, diagnostic):
    from app.engines.providers.codex_cli import CodexCliProvider

    invoke, sleep = _failing_cli(
        monkeypatch,
        "startup diagnostics\n" * 50 + diagnostic,
    )

    with pytest.raises(RuntimeError, match="登录.*失效"):
        CodexCliProvider({}).translate_batch([{"id": 1, "original": "Hello"}], "sys")

    assert invoke.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("diagnostic", [
    "Error: timed out waiting for cloud config bundle after 15s",
    "ERROR codex_login::auth::manager: Failed to refresh token: error sending request",
])
def test_codex_network_failure_stops_after_provider_retry_budget(monkeypatch, diagnostic):
    from app.engines.providers.codex_cli import CodexCliProvider

    invoke, sleep = _failing_cli(
        monkeypatch, diagnostic,
    )

    with pytest.raises(RuntimeError, match="Codex CLI 调用失败") as caught:
        CodexCliProvider({}).translate_batch([{"id": 1, "original": "Hello"}], "sys")

    assert "登录已失效" not in str(caught.value)
    assert diagnostic[:60] in str(caught.value)
    assert invoke.call_count == 3
    assert sleep.call_count == 2


def test_codex_transient_network_failure_can_recover(monkeypatch):
    from app.engines.providers.codex_cli import CodexCliProvider

    invoke, sleep = _failing_cli(monkeypatch, "network unavailable")
    success = Mock(returncode=0)
    success.communicate.return_value = ('[{"id":1,"translation":"你好"}]', "")
    invoke.side_effect = [invoke.return_value, success]

    results = CodexCliProvider({}).translate_batch([{"id": 1, "original": "Hello"}], "sys")

    assert results == [{"id": 1, "translation": "你好", "error": ""}]
    assert invoke.call_count == 2
    sleep.assert_called_once()


@pytest.mark.parametrize('diagnostic', [
    'ERROR: stream disconnected before completion: error sending request',
    'Error: unexpected status 429 Too Many Requests: usage_limit_reached',
])
def test_codex_exit_reports_terminal_error_after_banner_and_before_trailing_warning(monkeypatch, caplog, diagnostic):
    from app.engines.providers.codex_cli import CodexCliProvider

    invoke, _ = _failing_cli(monkeypatch,
        '2026-09-29T00:46:25Z ERROR codex_models_manager: failed to refresh models\n'
        'OpenAI Codex v0.155.1\n--------\nworkdir: /app\nmodel: gpt-6-astra\n'
        'provider: openai\napproval: never\nsandbox: read-only\n'
        'user\n' + ('private-subtitle-content\n' * 30) +
        '\x1b[31m' + diagnostic + '\x1b[0m\n'
        'Warning: no last agent message; wrote empty content to /tmp/result.txt\n')

    with pytest.raises(RuntimeError) as caught:
        CodexCliProvider({}).translate_batch([{'id':1,'original':'Hello'}], 'sys', retries=1)

    for output in (str(caught.value), caplog.text):
        assert diagnostic.split(': ',1)[1] in output
        assert 'OpenAI Codex v' not in output
        assert 'workdir:' not in output
        assert 'failed to refresh models' not in output
        assert 'private-subtitle-content' not in output
        assert '\x1b' not in output
    assert invoke.call_count == 1


def test_codex_exit_diagnostic_redacts_secrets_and_does_not_echo_prompt_as_fallback(monkeypatch):
    from app.engines.providers.codex_cli import CodexCliProvider

    _failing_cli(monkeypatch, 'OpenAI Codex v0.155.1\nuser\nprivate-subtitle-content\n'
        'ERROR: connection refused; api_key=private-key Authorization: Bearer private-token\n')
    with pytest.raises(RuntimeError) as caught:
        CodexCliProvider({}).translate_batch([{'id':1,'original':'Hello'}], 'sys', retries=1)
    message=str(caught.value)
    assert 'connection refused' in message
    assert 'private-key' not in message and 'private-token' not in message
    _failing_cli(monkeypatch, 'OpenAI Codex v0.155.1\nuser\nprivate-subtitle-content\n')
    with pytest.raises(RuntimeError) as caught:
        CodexCliProvider({}).translate_batch([{'id':1,'original':'Hello'}], 'sys', retries=1)
    assert 'private-subtitle-content' not in str(caught.value)
    assert '退出码 1' in str(caught.value)


def test_codex_timeout_reports_duration_and_batch_size_without_dumping_command(monkeypatch, caplog):
    from app.engines.providers.codex_cli import CodexCliProvider

    invoke, sleep = _failing_cli(monkeypatch, "")
    invoke.return_value.communicate.side_effect = subprocess.TimeoutExpired(
        ["codex", "--ask-for-approval", "never", "exec", "private-command-value"],
        600,
        stderr=b"Authorization: Bearer private-token-value",
    )
    terminate = Mock()
    monkeypatch.setattr(CodexCliProvider, "_terminate_process_group", terminate)
    items = [{"id": i, "original": "Hello, Fry."} for i in range(1, 5)]

    with pytest.raises(RuntimeError) as caught:
        CodexCliProvider({"timeout_sec": 600}).translate_batch(items, "sys")

    message = str(caught.value)
    assert "超时" in message
    assert "600 秒" in message
    assert "4 条" in message
    assert "代理" in message
    assert "尝试 3 次" in message
    for output in (message, caplog.text):
        assert "--ask-for-approval" not in output
        assert "private-command-value" not in output
        assert "private-token-value" not in output
    assert invoke.call_count == terminate.call_count == 3
    assert sleep.call_count == 2


@pytest.mark.parametrize("stage", ["missing", "semantic", "targeted"])
def test_service_unavailability_stops_followup_model_passes(stage):
    from app.engines.providers.base import ProviderUnavailableError
    from app.engines.translation_qa import QualityIssue, TranslationQaReport
    from app.services import translation_tasks as tasks
    from app.utils.srt import SubtitleBlock

    failure = ProviderUnavailableError("Codex CLI 登录已失效，请重新运行 codex login")
    invoke = Mock(side_effect=failure)
    translator = SimpleNamespace(
        primary=SimpleNamespace(translate_batch=invoke), _build_prompt=Mock(return_value="sys"),
    )
    blocks = [SubtitleBlock(
        index=i, start=timedelta(seconds=i), end=timedelta(seconds=i + 1),
        text="Hello, Fry.", translation="" if stage == "missing" else "你好，弗莱。",
    ) for i in (1, 2)]
    cfg = {"translation": {
        "missing_translation_retries": 2, "missing_translation_retry_batch_size": 1,
        "semantic_qa": True, "semantic_qa_batch_size": 1,
    }}
    report = TranslationQaReport(status="needs_review", issues=[
        QualityIssue(type="semantic_uncertain", severity="warning", block_id=i,
                     message="meaning requires verification") for i in (1, 2)
    ])

    with pytest.raises(ProviderUnavailableError) as caught:
        if stage == "missing":
            tasks._retry_missing_translations_before_quality(
                cfg, translator, blocks, "简体中文", {}, None,
            )
        elif stage == "semantic":
            tasks._run_semantic_quality_checks(
                cfg, translator, blocks, "简体中文", strict_quality_gate=True,
            )
        else:
            tasks._run_targeted_semantic_verification(
                cfg, translator, blocks, "简体中文", {1, 2}, report, [],
                strict_quality_gate=True,
            )

    assert caught.value is failure
    assert invoke.call_count == 1


def test_service_unavailability_rolls_back_partial_repair_and_stops():
    from app.engines.providers.base import ProviderUnavailableError
    from app.engines.translation_qa import QualityIssue, TranslationQaReport
    from app.services.translation_tasks import _auto_repair_quality_issues
    from app.utils.srt import SubtitleBlock

    blocks = [SubtitleBlock(
        index=i, start=timedelta(seconds=i), end=timedelta(seconds=i + 1),
        text="Hello, Fry.", translation="原译。", translation_error="prior error",
    ) for i in (1, 2)]
    failure = ProviderUnavailableError("Codex CLI 登录已失效，请重新运行 codex login")
    invoke = Mock(side_effect=[[{"id": 1, "translation": "你好，弗莱。"}], failure])
    report = TranslationQaReport(status="needs_review", issues=[
        QualityIssue(type="semantic_mismatch", severity="error", block_id=block.index,
                     message="wrong meaning", source_text=block.text,
                     translation=block.translation) for block in blocks
    ])

    with pytest.raises(ProviderUnavailableError) as caught:
        _auto_repair_quality_issues(
            {"translation": {"qa_auto_repair": True, "qa_auto_repair_max_blocks": 1}},
            SimpleNamespace(primary=SimpleNamespace(translate_batch=invoke)),
            blocks, report, "简体中文", None,
        )

    assert caught.value is failure
    assert invoke.call_count == 2
    assert [(block.translation, block.translation_error) for block in blocks] == [
        ("原译。", "prior error"), ("原译。", "prior error"),
    ]


def test_codex_login_error_is_persisted_for_task_page(tmp_project_dir, monkeypatch):
    from app.services import translation_tasks as tasks

    invoke, _ = _failing_cli(
        monkeypatch, 'ERROR: Failed to refresh token: 401 Unauthorized: '
        '{"error":{"code":"refresh_token_reused"}}',
    )
    pid = "authfail"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "id": pid, "name": "Episode", "status": "asr_done",
        "video_path": "/fake/Episode.mkv",
    }))
    (pdir / "filtered.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello, Fry.\n\n")
    monkeypatch.setattr(tasks, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(tasks.Config, "to_dict", lambda: {"translation": {
        "primary_provider": "codex_cli", "primary_model": "gpt-6-astra",
        "use_translation_memory": False, "use_phrase_library": False,
    }})

    tasks._run_translate_pipeline(pid, "简体中文", burn_follows=False)

    project = json.loads((pdir / "project.json").read_text())
    assert project["status"] == "error"
    assert "refresh_token_reused" in project["error"]
    assert "codex login" in project["error"]
    assert "大量空结果" not in project["error"]
    assert invoke.call_count == 1
    assert not (pdir / "translated.srt").exists()
    assert not (pdir / "bilingual.srt").exists()
