"""Bugfix B3 — translate_batch must surface errors instead of returning [] silently."""
from unittest.mock import patch


def test_translate_batch_exhausted_retries_returns_error_items():
    from app.engines.translator import TranslationProvider
    p = TranslationProvider(provider="openai", api_key="sk-x", model="gpt-4o")
    items = [{"id": 1, "original": "a"}, {"id": 2, "original": "b"}]

    with patch.object(p.client.chat.completions, "create", side_effect=RuntimeError("network down")):
        result = p.translate_batch(items, "sys", retries=2)

    assert len(result) == 2
    ids = {r["id"] for r in result}
    assert ids == {1, 2}
    for r in result:
        assert r["translation"] == ""
        assert "error" in r and r["error"]
        low = r["error"].lower()
        assert "network" in low or "runtimeerror" in low


def test_translate_batch_success_preserves_shape():
    """Regression: successful path still returns [{id, translation}] shape."""
    from app.engines.translator import TranslationProvider
    p = TranslationProvider(provider="openai", api_key="sk-x", model="gpt-4o")
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
