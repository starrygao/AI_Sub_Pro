from unittest.mock import patch


def test_claude_cli_provider_cli_not_installed():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    with patch.object(ClaudeCliProvider, "check_cli_available", return_value=False):
        p = ClaudeCliProvider({"model": "claude-opus-4-7"})
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys")
    assert result[0]["translation"] == ""
    assert "未安装" in result[0]["error"] or "not installed" in result[0]["error"].lower() or "not found" in result[0]["error"].lower()


def test_claude_cli_provider_not_logged_in():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    with patch.object(ClaudeCliProvider, "check_cli_available", return_value=True), \
         patch.object(ClaudeCliProvider, "check_logged_in", return_value=False):
        p = ClaudeCliProvider({"model": "claude-opus-4-7"})
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys")
    assert result[0]["translation"] == ""
    assert "登录" in result[0]["error"] or "login" in result[0]["error"].lower() or "auth" in result[0]["error"].lower()


def test_claude_cli_available_probe_treats_oserror_as_unavailable():
    import subprocess
    from app.engines.providers.claude_cli import ClaudeCliProvider

    with patch.object(subprocess, "run", side_effect=PermissionError("not executable")):
        assert ClaudeCliProvider.check_cli_available() is False


def test_claude_cli_provider_supports_full_document():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    assert p.supports_full_document_mode is True
    assert p.context_window_tokens >= 200_000


def test_claude_cli_provider_normalizes_bad_timeout():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7", "timeout_sec": "bad"})
    assert p.timeout_sec == 180


def test_claude_cli_provider_normalizes_non_finite_timeout():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7", "timeout_sec": float("inf")})
    assert p.timeout_sec == 180


def test_claude_cli_provider_normalizes_non_object_and_non_string_model():
    from app.engines.providers.claude_cli import ClaudeCliProvider

    assert ClaudeCliProvider(["bad"]).model == "claude-opus-4-7"
    assert ClaudeCliProvider({"model": ["bad"]}).model == "claude-opus-4-7"


def test_claude_cli_provider_parse_response():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]
    text = '[{"id": 1, "translation": "甲"}, {"id": 2, "translation": "乙"}]'
    out = p._parse(text, items)
    assert len(out) == 2
    assert out[0]["translation"] == "甲"
    assert out[1]["translation"] == "乙"


def test_claude_cli_provider_parse_handles_markdown_wrap():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    items = [{"id": 1, "original": "a"}]
    text = '```json\n[{"id": 1, "translation": "甲"}]\n```'
    out = p._parse(text, items)
    assert out[0]["translation"] == "甲"


def test_claude_cli_provider_parse_missing_id_returns_error_item():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]
    text = '[{"id": 1, "translation": "甲"}]'
    out = p._parse(text, items)
    assert out[0]["translation"] == "甲"
    assert out[1]["translation"] == ""
    assert out[1]["error"]  # non-empty error


def test_claude_cli_provider_parse_preserves_empty_translation():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    items = [{"id": 1, "original": "[music]"}]
    out = p._parse('[{"id": 1, "translation": ""}]', items)
    assert out == [{"id": 1, "translation": "", "error": ""}]


def test_claude_cli_provider_parse_rejects_non_string_translation():
    from app.engines.providers.claude_cli import ClaudeCliProvider
    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]
    text = '[{"id": 1, "translation": {"text": "bad"}}, {"id": 2}]'
    out = p._parse(text, items)
    assert out[0] == {"id": 1, "translation": "", "error": "invalid translation type: dict"}
    assert out[1] == {"id": 2, "translation": "", "error": "missing translation in model response"}


def test_claude_cli_provider_redacts_cli_error_secrets():
    from app.engines.providers.claude_cli import ClaudeCliProvider

    p = ClaudeCliProvider({"model": "claude-opus-4-7"})
    raw_error = "claude failed api_key=secret123 Authorization: Bearer token123"
    with patch.object(ClaudeCliProvider, "check_cli_available", return_value=True), \
         patch.object(ClaudeCliProvider, "check_logged_in", return_value=True), \
         patch.object(p, "_invoke", side_effect=RuntimeError(raw_error)):
        result = p.translate_batch([{"id": 1, "original": "hi"}], "sys", retries=1)

    error = result[0]["error"]
    assert "secret123" not in error
    assert "token123" not in error
    assert "api_key=<redacted>" in error
    assert "Authorization: <redacted>" in error
