from unittest.mock import patch


def test_claude_cli_models_include_fable_5():
    from app.engines.providers.claude_cli import CLAUDE_CLI_MODELS, ClaudeCliProvider

    assert CLAUDE_CLI_MODELS[0] == "claude-fable-5"
    assert ClaudeCliProvider({"model": "claude-fable-5"}).model == "claude-fable-5"


def test_claude_cli_login_probe_honors_explicit_logged_out_json():
    from app.engines.providers.claude_cli import ClaudeCliProvider

    completed = type("Completed", (), {
        "returncode": 1,
        "stdout": '{"loggedIn": false, "authMethod": "none"}',
        "stderr": "",
    })()
    with patch("app.engines.providers.claude_cli.subprocess.run", return_value=completed):
        assert ClaudeCliProvider.check_logged_in() is False


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


def test_claude_cli_provider_passes_explicit_effort_to_cli():
    from app.engines.providers.claude_cli import ClaudeCliProvider

    completed = type("Completed", (), {
        "returncode": 0,
        "stdout": '{"result":"[]"}',
        "stderr": "",
    })()
    with patch("app.engines.providers.claude_cli.subprocess.run", return_value=completed) as run:
        provider = ClaudeCliProvider({"model": "claude-fable-5", "effort": "xhigh"})
        assert provider._invoke([], "system") == "[]"

    command = run.call_args.args[0]
    assert command[command.index("--effort") + 1] == "xhigh"


def test_claude_cli_provider_preserves_caller_declared_semantic_schema():
    """The Claude wrapper must keep all fields declared by targeted QA."""
    from app.engines.providers.claude_cli import ClaudeCliProvider

    completed = type("Completed", (), {
        "returncode": 0,
        "stdout": '{"result":"[]"}',
        "stderr": "",
    })()
    semantic_prompt = (
        "Each result must contain id, translation, verdict, taxonomy, "
        "source_evidence, and target_evidence."
    )
    with patch(
        "app.engines.providers.claude_cli.subprocess.run",
        return_value=completed,
    ) as run:
        ClaudeCliProvider({"model": "claude-opus-4-7"})._invoke(
            [{"id": 1, "original": "No.", "draft": "不。"}],
            semantic_prompt,
        )

    final_prompt = run.call_args.kwargs["input"]
    assert "source_evidence" in final_prompt
    assert "target_evidence" in final_prompt
    assert "follow the response contract declared above" in final_prompt.lower()
    assert "reply with ONLY a JSON array of {\"id\": N, \"translation\"" not in final_prompt


def test_claude_cli_provider_omits_automatic_or_invalid_effort():
    from app.engines.providers.claude_cli import ClaudeCliProvider

    assert ClaudeCliProvider({"model": "claude-fable-5", "effort": "auto"}).effort == "auto"
    assert ClaudeCliProvider({"model": "claude-fable-5", "effort": "ultra"}).effort == "auto"
    assert ClaudeCliProvider({"model": "claude-haiku-4-5", "effort": "high"}).effort == "auto"
    assert ClaudeCliProvider({"model": "claude-sonnet-4-6", "effort": "xhigh"}).effort == "auto"


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
