def test_builtin_providers_registered():
    import app.engines.providers  # triggers registration
    from app.engines.providers.factory import list_providers

    names = list_providers()
    assert "openai" in names
    assert "deepseek" in names
    assert "gemini" in names
    assert "claude_cli" in names
    assert "codex_cli" in names


def test_get_openai_provider_via_factory():
    import app.engines.providers
    from app.engines.providers.factory import get_provider
    from app.engines.providers.openai_compat import OpenAICompatProvider

    p = get_provider("openai", {"provider": "openai", "api_key": "sk-x", "model": "gpt-4o"})
    assert isinstance(p, OpenAICompatProvider)


def test_get_claude_cli_provider_via_factory():
    import app.engines.providers
    from app.engines.providers.factory import get_provider
    from app.engines.providers.claude_cli import ClaudeCliProvider

    p = get_provider("claude_cli", {"model": "claude-opus-4-7"})
    assert isinstance(p, ClaudeCliProvider)


def test_get_codex_cli_provider_via_factory():
    import app.engines.providers
    from app.engines.providers.factory import get_provider
    from app.engines.providers.codex_cli import CodexCliProvider

    p = get_provider("codex_cli", {"model": "gpt-5.5"})
    assert isinstance(p, CodexCliProvider)
