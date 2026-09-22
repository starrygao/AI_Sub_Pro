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


def test_batched_translation_keeps_bounded_discourse_antecedent_across_batches(
    monkeypatch,
):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 1,
            "context_window": 1,
            "polish_provider": "",
            "missing_translation_retries": 0,
            "use_translation_memory": False,
            "use_phrase_library": False,
        },
        "api_keys": {"openai": "sk-test"},
    }
    calls = []
    translated = {
        84: "有你儿子做人质？",
        85: "我们的计划容易多了。",
        86: "我儿子？",
        87: "那男孩跑向了车站。",
    }

    def fake_translate_batch(items, system_prompt, retries=3):
        calls.append((list(items), system_prompt))
        return [
            {"id": item["id"], "translation": translated[item["id"]]}
            for item in items
        ]

    translator = SubtitleTranslator(config)
    monkeypatch.setattr(
        translator.primary,
        "translate_batch",
        fake_translate_batch,
    )
    blocks = [
        SubtitleBlock(
            index=84,
            start=timedelta(seconds=0),
            end=timedelta(seconds=1),
            text="[Luis]\nWith your boy here as leverage?",
        ),
        SubtitleBlock(
            index=85,
            start=timedelta(seconds=2),
            end=timedelta(seconds=3),
            text="Our plan just got a hell of a lot easier.",
        ),
        SubtitleBlock(
            index=86,
            start=timedelta(seconds=4),
            end=timedelta(seconds=5),
            text="My boy?",
        ),
        SubtitleBlock(
            index=87,
            start=timedelta(seconds=6),
            end=timedelta(seconds=7),
            text="That boy ran toward the station.",
        ),
    ]

    translator.translate(blocks, target_lang="简体中文")

    echo_items, echo_prompt = calls[2]
    assert echo_items[0]["id"] == 86
    assert len(echo_items[0]["discourse_links"]) == 1
    assert "局部话语链接" in echo_prompt
    assert "不是术语表" in echo_prompt
    assert "#84" in echo_prompt
    assert "With your boy here as leverage?" in echo_prompt
    assert "有你儿子做人质？" in echo_prompt
    assert "#85" in echo_prompt
    assert "只读" in echo_prompt

    unrelated_items, unrelated_prompt = calls[3]
    assert unrelated_items[0]["id"] == 87
    assert "discourse_links" not in unrelated_items[0]
    assert "局部话语链接" not in unrelated_prompt
    assert translator.last_quality_trace.kb_hits == []


def test_full_document_translation_shares_the_same_local_discourse_link(
    monkeypatch,
):
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 0,
            "context_window": 1,
            "polish_provider": "",
            "missing_translation_retries": 0,
            "use_translation_memory": False,
            "use_phrase_library": False,
        },
        "api_keys": {"openai": "sk-test"},
    }
    captured = {}

    def fake_translate_batch(items, system_prompt, retries=3):
        captured["items"] = list(items)
        captured["prompt"] = system_prompt
        return [
            {"id": item["id"], "translation": f"译文{item['id']}"}
            for item in items
        ]

    class FakeFullDocumentProvider:
        supports_full_document_mode = True
        context_window_tokens = 100_000
        full_document_max_items = None

        def translate_batch(self, items, system_prompt, retries=3):
            return fake_translate_batch(items, system_prompt, retries)

    translator = SubtitleTranslator(config)
    translator.primary = FakeFullDocumentProvider()
    blocks = [
        SubtitleBlock(
            index=84,
            start=timedelta(seconds=0),
            end=timedelta(seconds=1),
            text="With your boy here as leverage?",
        ),
        SubtitleBlock(
            index=85,
            start=timedelta(seconds=2),
            end=timedelta(seconds=3),
            text="The plan is easier.",
        ),
        SubtitleBlock(
            index=86,
            start=timedelta(seconds=4),
            end=timedelta(seconds=5),
            text="My boy?",
        ),
    ]

    translator.translate(blocks, target_lang="简体中文")

    item_by_id = {item["id"]: item for item in captured["items"]}
    assert item_by_id[84]["discourse_links"][0]["read_only_ids"] == [85]
    assert item_by_id[86]["discourse_links"][0]["read_only_ids"] == [85]
    assert "discourse_links" not in item_by_id[85]
    assert "局部话语链接" in captured["prompt"]


def test_full_document_fit_estimate_accounts_for_discourse_link_payload():
    from app.engines.translator import SubtitleTranslator
    from app.utils.srt import SubtitleBlock

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "batch_size": 0,
            "context_window": 1,
            "polish_provider": "",
        },
        "api_keys": {"openai": "sk-test"},
    }

    class SizedProvider:
        supports_full_document_mode = True
        full_document_max_items = None
        context_window_tokens = 4_000

    translator = SubtitleTranslator(config)
    translator.primary = SizedProvider()
    linked = [
        SubtitleBlock(
            index=84,
            start=timedelta(seconds=0),
            end=timedelta(seconds=1),
            text="With your boy here as leverage?",
        ),
        SubtitleBlock(
            index=85,
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text="The plan is easier.",
        ),
        SubtitleBlock(
            index=86,
            start=timedelta(seconds=2),
            end=timedelta(seconds=3),
            text="My boy?",
        ),
    ]
    unlinked = [
        SubtitleBlock(
            index=block.index,
            start=block.start,
            end=block.end,
            text=("No boy?" if block.index == 86 else block.text),
        )
        for block in linked
    ]

    distinguishing_window = None
    for context_window_tokens in range(2_400, 4_000):
        translator.primary.context_window_tokens = context_window_tokens
        if (
            translator._fits_full_doc(unlinked)
            and not translator._fits_full_doc(linked)
        ):
            distinguishing_window = context_window_tokens
            break

    assert distinguishing_window is not None


def test_batched_translate_retries_candidate_contract_contamination(monkeypatch):
    """A non-empty model meta-comment must not bypass the bounded retry path."""
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
                {
                    "id": 625,
                    "translation": (
                        "-[索尔玛丽]？不, original says this is a vocative "
                        "and the output needs exact speaker lines. Let's construct it."
                    ),
                },
                {"id": 626, "translation": "穿过那些门。"},
            ]
        assert "补翻要求" in system_prompt
        return [{
            "id": 625,
            "translation": "-索尔玛丽，我们找到了。\n-哦，谢天谢地！",
        }]

    translator = SubtitleTranslator(config)
    monkeypatch.setattr(translator.primary, "translate_batch", fake_translate_batch)
    blocks = [
        SubtitleBlock(
            index=625,
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text="-Solmari. We got it.\n-Oh, thank God!",
        ),
        SubtitleBlock(
            index=626,
            start=timedelta(seconds=2),
            end=timedelta(seconds=3),
            text="Through those doors.",
        ),
    ]

    translator.translate(blocks, target_lang="简体中文")

    assert calls == [[625, 626], [625]]
    assert [block.translation for block in blocks] == [
        "-索尔玛丽，我们找到了。\n-哦，谢天谢地！",
        "穿过那些门。",
    ]
    assert [block.translation_error for block in blocks] == ["", ""]


@pytest.mark.parametrize(
    ("source", "translation"),
    [
        ("Solmari found Hershel.", "索尔玛丽找到 Hershel 了。"),
        ("Use HTTP here.", "这里使用 HTTP。"),
        ("Hello.", "你好。"),
    ],
)
def test_candidate_contract_allows_entities_acronyms_and_normal_dialogue(
    source,
    translation,
):
    """Names, technical identifiers, and ordinary translations are not meta output."""
    from app.engines.translation_qa import translation_candidate_contract_error

    assert translation_candidate_contract_error(
        source,
        translation,
        target_language="简体中文",
    ) == ""


def test_candidate_contract_uses_dialogue_only_source_for_speaker_structure():
    from app.engines.translation_qa import translation_candidate_contract_error

    assert translation_candidate_contract_error(
        "-[Negan scoffing]\n-Maggie: Go.\n-Rick: No.",
        "-走。\n-不。",
        target_language="简体中文",
    ) == ""
    assert translation_candidate_contract_error(
        "[door slams]\n-Maggie: Go.\n-Rick: No.",
        "走。不。",
        target_language="简体中文",
    ) == "candidate_contract:speaker_structure"


@pytest.mark.parametrize(
    "translation",
    [
        "Translation: 你好。",
        "Here is the translation: 你好。",
        "译文：你好。",
    ],
)
def test_candidate_contract_blocks_short_canonical_meta_headers(translation):
    from app.engines.translation_qa import translation_candidate_contract_error

    assert translation_candidate_contract_error(
        "Hello.",
        translation,
        target_language="简体中文",
    ) == "candidate_contract:meta_contamination"


@pytest.mark.parametrize(
    "entity",
    ["Original Source Games", "Target Line Records"],
)
def test_candidate_contract_allows_exact_multiword_entities_from_source(entity):
    from app.engines.translation_qa import translation_candidate_contract_error

    assert translation_candidate_contract_error(
        f"Welcome to {entity}.",
        f"欢迎来到 {entity}。",
        target_language="简体中文",
    ) == ""


def test_batched_translate_allows_empty_sound_description(monkeypatch):
    """Pure sound cues stay local; only dialogue is sent once to the provider."""
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
            {"id": item["id"], "translation": "二"} for item in items
        ]

    t = SubtitleTranslator(config)
    monkeypatch.setattr(t.primary, "translate_batch", fake_translate_batch)
    blocks = [
        SubtitleBlock(index=1, start=timedelta(seconds=1), end=timedelta(seconds=2), text="[music]"),
        SubtitleBlock(index=2, start=timedelta(seconds=2), end=timedelta(seconds=3), text="two"),
    ]

    t.translate(blocks, target_lang="简体中文")

    assert calls == [[2]]
    assert [block.translation for block in blocks] == ["", "二"]
    assert [block.translation_error for block in blocks] == ["", ""]
