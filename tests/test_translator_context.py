"""Bugfix B2 — context window lookahead must honor config, not hardcode 2."""
from datetime import timedelta

import pytest


def test_context_window_respects_config(monkeypatch):
    """With context_window=5, lookahead must be 5, not hardcoded 2."""
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 2,
            "context_window": 5,
            "target_language": "简体中文",
            "polish_provider": "",
            "polish_model": "",
        },
        "api_keys": {"openai": "sk-test"},
    }
    captured = []

    def fake_translate_batch(items, system_prompt, retries=3):
        captured.append({"items": list(items), "prompt": system_prompt})
        return [
            {"id": it["id"], "translation": f"t-{it['id']}", "error": ""}
            for it in items
        ]

    t = SubtitleTranslator(config)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)

    # 10 blocks; SubtitleBlock.start/end are timedeltas
    blocks = [
        SubtitleBlock(
            index=i,
            start=timedelta(seconds=i),
            end=timedelta(seconds=i + 1),
            text=f"line {i}",
        )
        for i in range(10)
    ]
    t.translate(blocks, target_lang="简体中文")

    # With batch_size=2, batches are: [0,1], [2,3], [4,5], [6,7], [8,9].
    # 2nd batch: batch_start=2, batch_end=4. With context_window=5,
    # ctx_end = min(10, 4+5) = 9 -> lookahead covers indices 4..8 inclusive.
    # The old code (batch_end + 2) would only cover indices 4..5 (lines 4,5).
    assert len(captured) >= 2, f"Expected at least 2 batches, got {len(captured)}"
    second = captured[1]
    prompt = second["prompt"]
    assert "line 7" in prompt or "line 8" in prompt, (
        f"Expected lookahead to include line 7/8 (context_window=5). "
        f"Prompt was: {prompt[:800]}"
    )


def test_translate_aborts_when_provider_returns_too_many_empty_results(monkeypatch):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 10,
            "context_window": 1,
            "target_language": "简体中文",
            "polish_provider": "",
            "polish_model": "",
            "missing_translation_retries": 0,
            "missing_translation_abort_min_blocks": 10,
            "missing_translation_abort_missing_pct": 50,
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = SubtitleTranslator(config)
    monkeypatch.setattr(
        t.primary,
        "translate_batch",
        lambda items, system_prompt, retries=3: [
            {"id": items[0]["id"], "translation": "只翻了一条", "error": ""}
        ],
    )
    blocks = [
        SubtitleBlock(
            index=i,
            start=timedelta(seconds=i),
            end=timedelta(seconds=i + 1),
            text=f"line {i}",
        )
        for i in range(10)
    ]

    with pytest.raises(RuntimeError, match="翻译服务返回大量空结果"):
        t.translate(blocks, target_lang="简体中文")


def test_translate_tolerates_malformed_meta_and_kb_data(monkeypatch):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 1,
            "context_window": 1,
            "target_language": "简体中文",
            "polish_provider": "",
            "polish_model": "",
        },
        "api_keys": {"openai": "sk-test"},
    }
    t = SubtitleTranslator(config)
    monkeypatch.setattr(
        t.primary,
        "translate_batch",
        lambda items, system_prompt, retries=3: [
            {"id": it["id"], "translation": "ok", "error": ""} for it in items
        ],
    )
    blocks = [
        SubtitleBlock(
            index=1,
            start=timedelta(seconds=0),
            end=timedelta(seconds=1),
            text="hello",
        )
    ]

    t.translate(blocks, target_lang="简体中文", meta_info=["bad"], kb_data=["bad"])
    polish_prompt = t._build_polish_prompt("简体中文", meta_info=["bad"], kb_data=["bad"])

    assert blocks[0].translation == "ok"
    assert "输出JSON数组" in polish_prompt


def test_batched_translate_retries_missing_result_ids(monkeypatch):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 3,
            "context_window": 1,
            "polish_provider": "",
            "missing_translation_retries": 2,
            "missing_translation_retry_batch_size": 1,
            "use_translation_memory": False,
            "use_phrase_library": False,
        },
        "api_keys": {"openai": "sk-test"},
    }
    calls = []

    def fake_translate_batch(items, system_prompt, retries=3):
        calls.append([item["id"] for item in items])
        if len(calls) == 1:
            return [
                {"id": 1, "translation": "一"},
                {"id": 3, "translation": "三"},
            ]
        assert "补翻要求" in system_prompt
        return [{"id": 2, "translation": "二"}]

    t = SubtitleTranslator(config)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)
    blocks = [
        SubtitleBlock(index=1, start=timedelta(seconds=1), end=timedelta(seconds=2), text="one"),
        SubtitleBlock(index=2, start=timedelta(seconds=2), end=timedelta(seconds=3), text="two"),
        SubtitleBlock(index=3, start=timedelta(seconds=3), end=timedelta(seconds=4), text="three"),
    ]

    t.translate(blocks, target_lang="简体中文")

    assert calls == [[1, 2, 3], [2]]
    assert [block.translation for block in blocks] == ["一", "二", "三"]
    assert [block.translation_error for block in blocks] == ["", "", ""]


def test_batched_translate_retries_empty_dialogue_translation(monkeypatch):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 2,
            "context_window": 1,
            "polish_provider": "",
            "missing_translation_retries": 1,
            "missing_translation_retry_batch_size": 5,
            "use_translation_memory": False,
            "use_phrase_library": False,
        },
        "api_keys": {"openai": "sk-test"},
    }
    calls = []

    def fake_translate_batch(items, system_prompt, retries=3):
        calls.append([item["id"] for item in items])
        if len(calls) == 1:
            return [
                {"id": 1, "translation": ""},
                {"id": 2, "translation": "二"},
            ]
        assert "补翻要求" in system_prompt
        return [{"id": 1, "translation": "一"}]

    t = SubtitleTranslator(config)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)
    blocks = [
        SubtitleBlock(index=1, start=timedelta(seconds=1), end=timedelta(seconds=2), text="one"),
        SubtitleBlock(index=2, start=timedelta(seconds=2), end=timedelta(seconds=3), text="two"),
    ]

    t.translate(blocks, target_lang="简体中文")

    assert calls == [[1, 2], [1]]
    assert [block.translation for block in blocks] == ["一", "二"]


def test_batched_translate_allows_empty_sound_description(monkeypatch):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 2,
            "context_window": 1,
            "polish_provider": "",
            "missing_translation_retries": 1,
            "missing_translation_retry_batch_size": 5,
            "use_translation_memory": False,
            "use_phrase_library": False,
        },
        "api_keys": {"openai": "sk-test"},
    }
    calls = []

    def fake_translate_batch(items, system_prompt, retries=3):
        calls.append([item["id"] for item in items])
        return [
            {"id": 1, "translation": ""},
            {"id": 2, "translation": "二"},
        ]

    t = SubtitleTranslator(config)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)
    blocks = [
        SubtitleBlock(index=1, start=timedelta(seconds=1), end=timedelta(seconds=2), text="[music]"),
        SubtitleBlock(index=2, start=timedelta(seconds=2), end=timedelta(seconds=3), text="two"),
    ]

    t.translate(blocks, target_lang="简体中文")

    assert calls == [[1, 2]]
    assert [block.translation for block in blocks] == ["", "二"]
    assert [block.translation_error for block in blocks] == ["", ""]
