import subprocess
import signal
from unittest.mock import patch

import pytest


def test_codex_cli_models_include_gpt_5_6_family():
    from app.engines.providers.codex_cli import CODEX_CLI_MODELS

    assert CODEX_CLI_MODELS[:3] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]
    assert "gpt-5.6" not in CODEX_CLI_MODELS


def test_codex_cli_provider_cli_not_installed():
    from app.engines.providers.codex_cli import CodexCliProvider

    with patch.object(CodexCliProvider, "check_cli_available", return_value=False):
        p = CodexCliProvider({"model": "gpt-5.5"})
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys")

    assert result[0]["translation"] == ""
    assert "未安装" in result[0]["error"] or "not installed" in result[0]["error"].lower()


def test_codex_cli_provider_not_logged_in():
    from app.engines.providers.codex_cli import CodexCliProvider

    with patch.object(CodexCliProvider, "check_cli_available", return_value=True), \
         patch.object(CodexCliProvider, "check_logged_in", return_value=False):
        p = CodexCliProvider({"model": "gpt-5.5"})
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys")

    assert result[0]["translation"] == ""
    assert "登录" in result[0]["error"] or "login" in result[0]["error"].lower() or "auth" in result[0]["error"].lower()


def test_codex_cli_available_probe_treats_oserror_as_unavailable():
    import subprocess
    from app.engines.providers.codex_cli import CodexCliProvider

    with patch.object(subprocess, "run", side_effect=PermissionError("not executable")):
        assert CodexCliProvider.check_cli_available() is False


def test_codex_cli_provider_supports_full_document():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5"})

    assert p.supports_full_document_mode is True
    assert p.context_window_tokens >= 200_000
    assert p.full_document_max_items == 400


def test_codex_cli_provider_normalizes_bad_timeout():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5", "timeout_sec": "bad"})

    assert p.timeout_sec == 180


def test_codex_cli_provider_normalizes_non_object_and_non_string_model():
    from app.engines.providers.codex_cli import CodexCliProvider

    assert CodexCliProvider(["bad"]).model == "gpt-5.5"
    assert CodexCliProvider({"model": ["bad"]}).model == "gpt-5.5"


def test_codex_cli_provider_passes_explicit_effort_as_isolated_config(monkeypatch):
    from app.engines.providers import codex_cli as codex_mod
    from app.engines.providers.codex_cli import CodexCliProvider

    captured = {}

    class FakeProcess:
        pid = 12345
        returncode = 0

        def communicate(self, input=None, timeout=None):
            return ('[{"id":1,"translation":"ok"}]', "")

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr(codex_mod.subprocess, "Popen", fake_popen)
    provider = CodexCliProvider({"model": "gpt-5.6-sol", "effort": "ultra"})

    provider._invoke([{"id": 1, "original": "hi"}], "system")

    command = captured["cmd"]
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="ultra"'


def test_codex_cli_provider_omits_automatic_or_invalid_effort():
    from app.engines.providers.codex_cli import CodexCliProvider

    assert CodexCliProvider({"model": "gpt-5.6-sol", "effort": "auto"}).effort == "auto"
    assert CodexCliProvider({"model": "gpt-5.6-sol", "effort": "impossible"}).effort == "auto"
    assert CodexCliProvider({"model": "gpt-5.6-luna", "effort": "ultra"}).effort == "auto"
    assert CodexCliProvider({"model": "gpt-5.5", "effort": "max"}).effort == "auto"


def test_codex_cli_provider_parse_response():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5"})
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]
    text = '[{"id": 1, "translation": "甲"}, {"id": 2, "translation": "乙"}]'

    out = p._parse(text, items)

    assert len(out) == 2
    assert out[0]["translation"] == "甲"
    assert out[1]["translation"] == "乙"


def test_codex_cli_provider_parse_handles_markdown_wrap():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5"})
    items = [{"id": 1, "original": "a"}]
    text = '```json\n[{"id": 1, "translation": "甲"}]\n```'

    out = p._parse(text, items)

    assert out[0]["translation"] == "甲"


def test_codex_cli_provider_redacts_cli_error_secrets():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5"})
    raw_error = "codex failed api_key=secret123 Authorization: Bearer token123"
    with patch.object(CodexCliProvider, "check_cli_available", return_value=True), \
         patch.object(CodexCliProvider, "check_logged_in", return_value=True), \
         patch.object(p, "_invoke", side_effect=RuntimeError(raw_error)):
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys", retries=1)

    error = result[0]["error"]
    assert "secret123" not in error
    assert "token123" not in error
    assert "api_key=<redacted>" in error
    assert "Authorization: <redacted>" in error


def test_codex_cli_provider_kills_process_group_on_timeout(monkeypatch):
    from app.engines.providers import codex_cli as codex_mod
    from app.engines.providers.codex_cli import CodexCliProvider

    class FakeProcess:
        pid = 12345
        returncode = None

        def communicate(self, input=None, timeout=None):
            raise subprocess.TimeoutExpired(["codex"], timeout)

        def wait(self, timeout=None):
            self.returncode = -signal.SIGTERM

        def kill(self):
            self.returncode = -signal.SIGKILL

    killed = []
    fake_process = FakeProcess()

    def fake_popen(cmd, **kwargs):
        assert "--ignore-user-config" in cmd
        assert kwargs.get("start_new_session") is True
        return fake_process

    monkeypatch.setattr(codex_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        codex_mod.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("use Popen for cancellable invocation")),
    )
    monkeypatch.setattr(codex_mod.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    p = CodexCliProvider({"model": "gpt-5.5", "timeout_sec": 5})

    with pytest.raises(subprocess.TimeoutExpired):
        p._invoke([{"id": 1, "original": "hi"}], "sys")

    assert killed == [(12345, signal.SIGTERM)]
