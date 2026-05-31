"""Phase 2 / Task 5 — SubtitleTranslator uses provider factory + full-doc mode."""
from unittest.mock import MagicMock
from datetime import timedelta


def test_translator_uses_factory_for_primary(monkeypatch):
    """SubtitleTranslator.__init__ must call get_provider() to build self.primary."""
    from app.engines import translator as tmod
    captured = {}

    def fake_get_provider(name, config):
        captured["name"] = name
        captured["config"] = config
        m = MagicMock()
        m.supports_full_document_mode = False
        m.context_window_tokens = 32000
        return m

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
            "target_language": "简体中文",
        },
        "api_keys": {"openai": "sk-test"},
    }
    tmod.SubtitleTranslator(cfg)

    assert captured["name"] == "openai"
    assert captured["config"]["model"] == "gpt-4o"
    assert captured["config"]["api_key"] == "sk-test"


def test_translator_strips_provider_model_and_key_config(monkeypatch):
    from app.engines import translator as tmod
    captured = {}

    def fake_get_provider(name, config):
        captured["name"] = name
        captured["config"] = config
        m = MagicMock()
        m.supports_full_document_mode = False
        m.context_window_tokens = 32000
        return m

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    tmod.SubtitleTranslator({
        "translation": {
            "primary_provider": " openai ",
            "primary_model": " gpt-4o ",
            "polish_provider": " ",
        },
        "api_keys": {"openai": " sk-test "},
    })

    assert captured["name"] == "openai"
    assert captured["config"]["model"] == "gpt-4o"
    assert captured["config"]["api_key"] == "sk-test"


def test_translator_factory_builds_claude_cli_config(monkeypatch):
    """For provider=claude_cli, config should have model + timeout but NO api_key."""
    from app.engines import translator as tmod
    captured = {}

    def fake_get_provider(name, config):
        captured["name"] = name
        captured["config"] = config
        m = MagicMock()
        m.supports_full_document_mode = True
        m.context_window_tokens = 1_000_000
        return m

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    cfg = {
        "translation": {
            "primary_provider": "claude_cli",
            "primary_model": "claude-opus-4-7",  # ignored in favor of providers.claude_cli.model
            "polish_provider": "",
            "batch_size": 0,
            "context_window": 3,
            "target_language": "简体中文",
            "full_doc_mode": True,
        },
        "api_keys": {},
        "providers": {"claude_cli": {"enabled": True, "model": "claude-sonnet-4-6", "timeout_sec": 240}},
    }
    tmod.SubtitleTranslator(cfg)

    assert captured["name"] == "claude_cli"
    assert captured["config"]["model"] == "claude-sonnet-4-6"  # from providers.claude_cli.model
    assert captured["config"]["timeout_sec"] == 240
    assert "api_key" not in captured["config"]


def test_translator_factory_builds_codex_cli_config(monkeypatch):
    """For provider=codex_cli, config should have model + timeout but NO api_key."""
    from app.engines import translator as tmod
    captured = {}

    def fake_get_provider(name, config):
        captured["name"] = name
        captured["config"] = config
        m = MagicMock()
        m.supports_full_document_mode = True
        m.context_window_tokens = 1_000_000
        return m

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    cfg = {
        "translation": {
            "primary_provider": "codex_cli",
            "primary_model": "gpt-5.5",
            "polish_provider": "",
            "batch_size": 0,
            "context_window": 3,
            "target_language": "简体中文",
            "full_doc_mode": True,
        },
        "api_keys": {"openai": "sk-" + "should-not-be-used"},
        "providers": {"codex_cli": {"enabled": True, "model": "gpt-5.4", "timeout_sec": 300}},
    }
    tmod.SubtitleTranslator(cfg)

    assert captured["name"] == "codex_cli"
    assert captured["config"]["model"] == "gpt-5.4"
    assert captured["config"]["timeout_sec"] == 300
    assert "api_key" not in captured["config"]


def test_translator_normalizes_malformed_legacy_numeric_config(monkeypatch):
    from app.engines import translator as tmod

    def fake_get_provider(name, config):
        m = MagicMock()
        m.supports_full_document_mode = False
        m.context_window_tokens = 32000
        return m

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    t = tmod.SubtitleTranslator({
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": "not-an-int",
            "context_window": "bad",
            "full_doc_mode": "false",
        },
        "api_keys": {"openai": "sk-test"},
    })

    assert t.batch_size == 10
    assert t.context_window == 3
    assert t.full_doc_mode is False


def test_translator_normalizes_malformed_config_sections_and_provider(monkeypatch):
    from app.engines import translator as tmod
    captured = {}

    def fake_get_provider(name, config):
        captured["name"] = name
        captured["config"] = config
        m = MagicMock()
        m.supports_full_document_mode = False
        m.context_window_tokens = 32000
        return m

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    tmod.SubtitleTranslator({
        "translation": {
            "primary_provider": "not-a-provider",
            "primary_model": ["bad"],
            "polish_provider": {"bad": "shape"},
        },
        "api_keys": {"openai": {"bad": "shape"}},
        "providers": {"claude_cli": "bad"},
    })

    assert captured["name"] == "openai"
    assert captured["config"]["model"] == "gpt-4o"
    assert captured["config"]["api_key"] == ""


def test_translator_normalizes_non_object_config_sections(monkeypatch):
    from app.engines import translator as tmod
    captured = {}

    def fake_get_provider(name, config):
        captured["name"] = name
        captured["config"] = config
        m = MagicMock()
        m.supports_full_document_mode = False
        m.context_window_tokens = 32000
        return m

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    tmod.SubtitleTranslator({
        "translation": ["bad"],
        "api_keys": ["bad"],
        "providers": ["bad"],
    })

    assert captured["name"] == "openai"
    assert captured["config"]["model"] == "gpt-4o"
    assert captured["config"]["api_key"] == ""


def test_translator_normalizes_non_finite_numeric_config(monkeypatch):
    from app.engines import translator as tmod

    def fake_get_provider(name, config):
        m = MagicMock()
        m.supports_full_document_mode = False
        m.context_window_tokens = 32000
        return m

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    t = tmod.SubtitleTranslator({
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": float("inf"),
            "context_window": float("nan"),
        },
        "api_keys": {"openai": "sk-test"},
    })

    assert t.batch_size == 10
    assert t.context_window == 3


def test_translator_normalizes_malformed_claude_timeout(monkeypatch):
    from app.engines import translator as tmod
    captured = {}

    def fake_get_provider(name, config):
        captured["config"] = config
        m = MagicMock()
        m.supports_full_document_mode = True
        m.context_window_tokens = 1_000_000
        return m

    monkeypatch.setattr("app.engines.translator.get_provider", fake_get_provider)

    tmod.SubtitleTranslator({
        "translation": {
            "primary_provider": "claude_cli",
            "primary_model": "claude-opus-4-7",
            "polish_provider": "",
        },
        "providers": {"claude_cli": {"model": "claude-opus-4-7", "timeout_sec": "bad"}},
    })

    assert captured["config"]["timeout_sec"] == 180


def test_full_doc_mode_sends_all_blocks_in_one_call(monkeypatch):
    """batch_size=0 + full_doc_mode=True + provider supports it -> one call, all blocks."""
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 0,
            "context_window": 3,
            "target_language": "简体中文",
            "full_doc_mode": True,
        },
        "api_keys": {"openai": "sk-test"},
    }
    captured = []

    def fake_translate_batch(items, system_prompt, retries=3):
        captured.append(len(items))
        return [{"id": it["id"], "translation": f"t-{it['id']}", "error": ""} for it in items]

    t = SubtitleTranslator(cfg)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)

    blocks = [SubtitleBlock(index=i, start=timedelta(seconds=i), end=timedelta(seconds=i+1), text=f"line {i}") for i in range(20)]
    t.translate(blocks, target_lang="简体中文")

    assert len(captured) == 1
    assert captured[0] == 20


def test_full_doc_falls_back_to_batched_if_too_large(monkeypatch):
    """Estimated tokens > 80% of context_window -> fall back to batched mode (multiple calls)."""
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-3.5-turbo",  # 16k context
            "polish_provider": "",
            "batch_size": 0,
            "context_window": 3,
            "target_language": "简体中文",
            "full_doc_mode": True,
        },
        "api_keys": {"openai": "sk-test"},
    }
    captured = []
    def fake_translate_batch(items, system_prompt, retries=3):
        captured.append(len(items))
        return [{"id": it["id"], "translation": "t", "error": ""} for it in items]

    t = SubtitleTranslator(cfg)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)

    # Force fallback: lots of text
    big_text = "x" * 50_000
    blocks = [SubtitleBlock(index=i, start=timedelta(seconds=i), end=timedelta(seconds=i+1), text=big_text) for i in range(5)]
    t.translate(blocks, target_lang="简体中文")

    # Fell back to batched -> multiple calls (batched path splits into chunks by batch_size fallback)
    assert len(captured) > 1, f"expected fallback to multiple batches, got {captured}"


def test_full_doc_ignores_non_finite_provider_context_window(monkeypatch):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 0,
            "context_window": 3,
            "full_doc_mode": True,
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = SubtitleTranslator(cfg)
    fake_primary = MagicMock()
    fake_primary.supports_full_document_mode = True
    fake_primary.context_window_tokens = float("inf")
    fake_primary.translate_batch = lambda items, system_prompt, retries=3: [
        {"id": it["id"], "translation": "ok", "error": ""} for it in items
    ]
    t.primary = fake_primary

    blocks = [SubtitleBlock(index=1, start=timedelta(0), end=timedelta(seconds=1), text="hello")]

    t.translate(blocks, target_lang="简体中文")

    assert blocks[0].translation == "ok"


def test_full_doc_polish_ignores_malformed_primary_translation(monkeypatch):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "openai",
            "polish_model": "gpt-4o",
            "batch_size": 0,
            "context_window": 3,
            "target_language": "简体中文",
            "full_doc_mode": True,
        },
        "api_keys": {"openai": "sk-test"},
    }

    t = SubtitleTranslator(cfg)
    monkeypatch.setattr(
        t.primary,
        "translate_batch",
        lambda items, system_prompt, retries=3: [
            {"id": 1, "translation": {"text": "bad"}, "error": ""},
            {"id": 2, "translation": "draft", "error": ""},
        ],
    )

    def fake_polish(items, system_prompt, retries=3):
        assert items == [{"id": 2, "original": "b", "draft": "draft"}]
        return [{"id": 2, "translation": "polished", "error": ""}]

    monkeypatch.setattr(t.polish, "translate_batch", fake_polish)

    blocks = [
        SubtitleBlock(index=1, start=timedelta(seconds=1), end=timedelta(seconds=2), text="a"),
        SubtitleBlock(index=2, start=timedelta(seconds=2), end=timedelta(seconds=3), text="b"),
    ]
    t.translate(blocks, target_lang="简体中文")

    assert blocks[0].translation == ""
    assert blocks[0].translation_error == "invalid translation type: dict"
    assert blocks[1].translation == "polished"
    assert blocks[1].translation_error == ""


def test_batched_polish_malformed_result_preserves_primary_draft(monkeypatch):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    cfg = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "openai",
            "polish_model": "gpt-4o",
            "batch_size": 10,
            "context_window": 3,
            "target_language": "简体中文",
            "full_doc_mode": False,
        },
        "api_keys": {"openai": "sk-test"},
    }

    t = SubtitleTranslator(cfg)
    monkeypatch.setattr(
        t.primary,
        "translate_batch",
        lambda items, system_prompt, retries=3: [
            {"id": 1, "translation": "draft", "error": ""},
        ],
    )
    monkeypatch.setattr(
        t.polish,
        "translate_batch",
        lambda items, system_prompt, retries=3: [
            {"id": 1, "translation": {"text": "bad"}, "error": ""},
        ],
    )

    blocks = [
        SubtitleBlock(index=1, start=timedelta(seconds=1), end=timedelta(seconds=2), text="a"),
    ]
    t.translate(blocks, target_lang="简体中文")

    assert blocks[0].translation == "draft"
    assert blocks[0].translation_error == ""
