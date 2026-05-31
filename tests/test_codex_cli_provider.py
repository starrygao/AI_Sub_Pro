from unittest.mock import patch


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


def test_codex_cli_provider_normalizes_bad_timeout():
    from app.engines.providers.codex_cli import CodexCliProvider

    p = CodexCliProvider({"model": "gpt-5.5", "timeout_sec": "bad"})

    assert p.timeout_sec == 180


def test_codex_cli_provider_normalizes_non_object_and_non_string_model():
    from app.engines.providers.codex_cli import CodexCliProvider

    assert CodexCliProvider(["bad"]).model == "gpt-5.5"
    assert CodexCliProvider({"model": ["bad"]}).model == "gpt-5.5"


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
