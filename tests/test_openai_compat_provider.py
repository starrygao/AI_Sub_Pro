"""Tests for the extracted OpenAICompatProvider (Phase 2 / Task 2)."""
from unittest.mock import patch


def test_openai_compat_provider_basic_call():
    from app.engines.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider({"provider": "openai", "api_key": "sk-test", "model": "gpt-4o"})
    items = [{"id": 1, "original": "hello"}]

    class FakeResp:
        class C:
            class M:
                content = '[{"id": 1, "translation": "你好"}]'
            message = M()
        choices = [C()]

    with patch.object(p.client.chat.completions, "create", return_value=FakeResp()):
        result = p.translate_batch(items, "sys", retries=1)
    assert len(result) == 1
    assert result[0]["id"] == 1
    assert result[0]["translation"] == "你好"
    assert result[0]["error"] == ""


def test_translate_batch_fills_missing_ids_with_error():
    """A model that omits an input id must yield an explicit error entry for it,
    not silently drop the block."""
    from app.engines.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider({"provider": "openai", "api_key": "sk-test", "model": "gpt-4o"})
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}, {"id": 3, "original": "c"}]

    class FakeResp:
        class C:
            class M:
                # id 2 is omitted entirely; id 3 returned with empty translation
                content = '[{"id": 1, "translation": "甲"}, {"id": 3, "translation": ""}]'
            message = M()
        choices = [C()]

    with patch.object(p.client.chat.completions, "create", return_value=FakeResp()):
        result = p.translate_batch(items, "sys", retries=1)

    by_id = {r["id"]: r for r in result}
    assert set(by_id) == {1, 2, 3}              # one entry per input id, none dropped
    assert by_id[1]["translation"] == "甲" and by_id[1]["error"] == ""
    assert by_id[2]["translation"] == "" and by_id[2]["error"]   # absent -> error
    assert by_id[3]["translation"] == "" and by_id[3]["error"] == ""  # present-empty -> intentional


def test_translate_batch_rejects_non_string_translation():
    """Provider results must not pass non-string translations into SRT writing."""
    from app.engines.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider({"provider": "openai", "api_key": "sk-test", "model": "gpt-4o"})
    items = [{"id": 1, "original": "hello"}]

    class FakeResp:
        class C:
            class M:
                content = '[{"id": 1, "translation": {"text": "bad"}}]'
            message = M()
        choices = [C()]

    with patch.object(p.client.chat.completions, "create", return_value=FakeResp()):
        result = p.translate_batch(items, "sys", retries=1)

    assert result == [{"id": 1, "translation": "", "error": "invalid translation type: dict"}]


def test_translate_batch_rejects_missing_translation_key():
    from app.engines.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider({"provider": "openai", "api_key": "sk-test", "model": "gpt-4o"})
    items = [{"id": 1, "original": "hello"}]

    class FakeResp:
        class C:
            class M:
                content = '[{"id": 1}]'
            message = M()
        choices = [C()]

    with patch.object(p.client.chat.completions, "create", return_value=FakeResp()):
        result = p.translate_batch(items, "sys", retries=1)

    assert result == [{"id": 1, "translation": "", "error": "missing translation in model response"}]


def test_translate_batch_reports_non_string_response_content_as_parse_error():
    from app.engines.providers.openai_compat import OpenAICompatProvider

    p = OpenAICompatProvider({"provider": "openai", "api_key": "sk-test", "model": "gpt-4o"})
    items = [{"id": 1, "original": "hello"}]

    class FakeResp:
        class C:
            class M:
                content = {"bad": "shape"}
            message = M()
        choices = [C()]

    with patch.object(p.client.chat.completions, "create", return_value=FakeResp()):
        result = p.translate_batch(items, "sys", retries=1)

    assert result[0]["translation"] == ""
    assert "non-string response content: dict" in result[0]["error"]


def test_try_parse_json_returns_none_for_overlong_numbers():
    from app.engines.providers.openai_compat import _try_parse_json

    assert _try_parse_json('[{"id": ' + ("9" * 5000) + ', "translation": "x"}]') is None


def test_try_parse_json_returns_none_for_non_string_content():
    from app.engines.providers.openai_compat import _try_parse_json

    assert _try_parse_json({"bad": "shape"}) is None


def test_openai_compat_provider_rejects_non_string_model():
    import pytest
    from app.engines.providers.openai_compat import OpenAICompatProvider

    with pytest.raises(ValueError, match="model"):
        OpenAICompatProvider({"provider": ["bad"], "api_key": {"bad": "shape"}, "model": ["bad"]})

    with pytest.raises(ValueError, match="model"):
        OpenAICompatProvider({"provider": "openai", "api_key": "sk-test", "model": "  "})


def test_openai_compat_provider_strips_string_config_values():
    from app.engines.providers.openai_compat import OpenAICompatProvider

    p = OpenAICompatProvider({"provider": " openai ", "api_key": " sk-test ", "model": " gpt-4o "})

    assert p.provider_name == "openai"
    assert p.model == "gpt-4o"


def test_translate_batch_redacts_provider_error_secrets():
    from app.engines.providers.openai_compat import OpenAICompatProvider

    p = OpenAICompatProvider({"provider": "openai", "api_key": "sk-test", "model": "gpt-4o"})
    items = [{"id": 1, "original": "hello"}]
    raw_error = "GET https://api.test?api_key=secret123 failed with sk-live-secret-token and AIzaSyA1234567890abcdefghijklmnop"

    with patch.object(p.client.chat.completions, "create", side_effect=RuntimeError(raw_error)):
        result = p.translate_batch(items, "sys", retries=1)

    error = result[0]["error"]
    assert "secret123" not in error
    assert "sk-live-secret-token" not in error
    assert "AIzaSyA1234567890abcdefghijklmnop" not in error
    assert "api_key=<redacted>" in error
    assert "sk-<redacted>" in error
    assert "AIza<redacted>" in error


def test_openai_compat_provider_supports_full_document():
    from app.engines.providers.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider({"provider": "openai", "api_key": "sk-test", "model": "gpt-4o"})
    assert p.supports_full_document_mode is True
    assert p.context_window_tokens > 0


def test_translation_provider_alias_still_imports():
    """Backward-compat: legacy import path still works."""
    from app.engines.translator import TranslationProvider
    from app.engines.providers.openai_compat import OpenAICompatProvider
    assert TranslationProvider is OpenAICompatProvider


def test_translation_provider_alias_legacy_constructor():
    """Legacy constructor shape: (provider, api_key, model) as kwargs must still work."""
    from app.engines.translator import TranslationProvider
    p = TranslationProvider(provider="openai", api_key="sk-x", model="gpt-4o")
    # after the alias maps to OpenAICompatProvider(config_dict), this raises unless we provide a dual constructor
    assert p.model == "gpt-4o"
    assert p.provider_name == "openai"
