def _translator_config():
    return {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
            "use_translation_memory": True,
            "use_phrase_library": True,
        },
        "api_keys": {"openai": "sk-test"},
    }


def test_build_prompt_orders_memory_kb_and_phrase_examples(monkeypatch, tmp_path):
    from app.engines import translator as tmod
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.knowledge import KnowledgeBase
    from app.engines.phrase_library import PhraseLibrary
    from app.engines.translation_memory import TranslationMemoryStore

    memory = TranslationMemoryStore(tmp_path / "memory.sqlite3")
    memory.record_edit(
        source_text="Hudson Oaks is giving resort vibes.",
        machine_translation="哈德森橡树很有度假村的感觉。",
        final_translation="哈德逊奥克斯有种度假村的感觉。",
        source_language="en",
        target_language="zh-CN",
    )
    phrases = PhraseLibrary(tmp_path / "phrases.sqlite3")
    phrases.add_phrase(
        source_text="Shoot your shot.",
        target_text="主动出击。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit-test",
        license="local",
        quality=0.9,
    )
    monkeypatch.setattr(tmod, "TranslationMemoryStore", lambda: memory)
    monkeypatch.setattr(tmod, "PhraseLibrary", lambda: phrases)

    kb = KnowledgeBase()
    kb.set_project("brilliant", ProjectKb(
        show_title="Brilliant Minds",
        places=[TermEntry(source="Hudson Oaks", target="哈德逊奥克斯")],
    ))
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    translator = tmod.SubtitleTranslator(_translator_config())
    prompt = translator._build_prompt(
        "简体中文",
        {"name": "Brilliant Minds S02E15", "original_language": "en"},
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "Hudson Oaks is giving resort vibes."},
            {"id": 2, "original": "Shoot your shot, Dr. Pierce."},
        ],
    )

    memory_pos = prompt.index("User correction memory")
    kb_pos = prompt.index("Use EXACTLY these translations")
    phrase_pos = prompt.index("Subtitle phrase examples")
    assert memory_pos < kb_pos < phrase_pos
    assert "哈德逊奥克斯有种度假村的感觉" in prompt
    assert "主动出击" in prompt
    assert translator.last_quality_trace.memory_hits
    assert translator.last_quality_trace.phrase_hits


def test_build_prompt_skips_quality_context_when_disabled(monkeypatch, tmp_path):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)
    config = _translator_config()
    config["translation"]["use_translation_memory"] = False
    config["translation"]["use_phrase_library"] = False

    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {"name": "Random"},
        None,
        [],
        [],
        items=[{"id": 1, "original": "Hello"}],
    )

    assert "User correction memory" not in prompt
    assert "Subtitle phrase examples" not in prompt


def test_build_prompt_respects_retrieval_example_limits_and_backends(monkeypatch):
    from types import SimpleNamespace

    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    class DummyMemoryStore:
        def __init__(self):
            self.calls = []

        def retrieve(
            self,
            source_text,
            *,
            source_language,
            target_language,
            limit,
            backend,
        ):
            self.calls.append({
                "source_text": source_text,
                "source_language": source_language,
                "target_language": target_language,
                "limit": limit,
                "backend": backend,
            })
            return [
                SimpleNamespace(
                    source_text=f"Need backup now. #{i}",
                    machine_translation=f"现在需要备份。#{i}",
                    final_translation=f"现在立刻支援。#{i}",
                    project_name="Dummy",
                    score=1.0 - i * 0.01,
                )
                for i in range(1, 6)
            ]

    class DummyPhraseLibrary:
        def __init__(self):
            self.calls = []

        def retrieve(
            self,
            source_text,
            *,
            source_language,
            target_language,
            limit,
            preferred_tags,
            backend,
        ):
            self.calls.append({
                "source_text": source_text,
                "source_language": source_language,
                "target_language": target_language,
                "limit": limit,
                "preferred_tags": preferred_tags,
                "backend": backend,
            })
            return [
                SimpleNamespace(
                    source_text=f"Need backup now. #{i}",
                    target_text=f"马上叫增援。#{i}",
                    source_name="dummy-pack",
                    license="local",
                    pack_id="dummy-pack.v1",
                    tags="crime",
                    score=0.95 - i * 0.01,
                )
                for i in range(1, 7)
            ]

    memory = DummyMemoryStore()
    phrases = DummyPhraseLibrary()
    monkeypatch.setattr(tmod, "TranslationMemoryStore", lambda: memory)
    monkeypatch.setattr(tmod, "PhraseLibrary", lambda: phrases)
    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)

    config = _translator_config()
    config["translation"]["memory_retrieval_backend"] = "ngram"
    config["translation"]["phrase_retrieval_backend"] = "fts5"
    config["translation"]["max_memory_examples"] = 3
    config["translation"]["max_phrase_examples"] = 4

    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {
            "name": "Police Case",
            "original_language": "en",
            "plot": "A detective works a crime scene.",
        },
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "Need backup now."},
            {"id": 2, "original": "Make it count."},
        ],
    )

    assert memory.calls == [{
        "source_text": "Need backup now.",
        "source_language": "en",
        "target_language": "zh-CN",
        "limit": 3,
        "backend": "ngram",
    }]
    assert phrases.calls == [{
        "source_text": "Need backup now.",
        "source_language": "en",
        "target_language": "zh-CN",
        "limit": 4,
        "preferred_tags": {"crime"},
        "backend": "fts5",
    }]
    assert prompt.count("User-approved translation:") == 3
    assert "现在立刻支援。#1" in prompt
    assert "现在立刻支援。#3" in prompt
    assert "现在立刻支援。#4" not in prompt
    assert prompt.count("(source: dummy-pack, license: local, tags: crime)") == 4
    assert "马上叫增援。#1" in prompt
    assert "马上叫增援。#4" in prompt
    assert "马上叫增援。#5" not in prompt


def test_build_prompt_skips_store_construction_when_retrieval_caps_are_zero(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    class FailingMemoryStore:
        def __init__(self):
            raise AssertionError("TranslationMemoryStore should not be constructed")

    class FailingPhraseLibrary:
        def __init__(self):
            raise AssertionError("PhraseLibrary should not be constructed")

    monkeypatch.setattr(tmod, "TranslationMemoryStore", FailingMemoryStore)
    monkeypatch.setattr(tmod, "PhraseLibrary", FailingPhraseLibrary)
    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)

    config = _translator_config()
    config["translation"]["max_memory_examples"] = 0
    config["translation"]["max_phrase_examples"] = 0

    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {"name": "Random", "original_language": "en"},
        None,
        [],
        [],
        items=[{"id": 1, "original": "Need backup now."}],
    )

    assert "User correction memory" not in prompt
    assert "Subtitle phrase examples" not in prompt
    assert translator.last_quality_trace.memory_hits == []
    assert translator.last_quality_trace.phrase_hits == []


def test_build_prompt_sanitizes_invalid_retrieval_backends_to_auto(monkeypatch):
    from types import SimpleNamespace

    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    calls = {"memory": [], "phrase": []}

    class DummyMemoryStore:
        def retrieve(self, source_text, *, source_language, target_language, limit, backend):
            calls["memory"].append(backend)
            return [
                SimpleNamespace(
                    source_text=source_text,
                    machine_translation="旧译文",
                    final_translation="新译文",
                    project_name="Dummy",
                    score=0.9,
                )
            ]

    class DummyPhraseLibrary:
        def retrieve(
            self,
            source_text,
            *,
            source_language,
            target_language,
            limit,
            preferred_tags,
            backend,
        ):
            calls["phrase"].append(backend)
            return [
                SimpleNamespace(
                    source_text=source_text,
                    target_text="自然表达",
                    source_name="dummy",
                    license="local",
                    pack_id="dummy-pack.v1",
                    tags="",
                    score=0.8,
                )
            ]

    monkeypatch.setattr(tmod, "TranslationMemoryStore", DummyMemoryStore)
    monkeypatch.setattr(tmod, "PhraseLibrary", DummyPhraseLibrary)
    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)

    config = _translator_config()
    config["translation"]["memory_retrieval_backend"] = "bad-backend"
    config["translation"]["phrase_retrieval_backend"] = "also-bad"

    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {"name": "Random", "original_language": "en"},
        None,
        [],
        [],
        items=[{"id": 1, "original": "Need backup now."}],
    )

    assert calls["memory"] == ["auto"]
    assert calls["phrase"] == ["auto"]
    assert "新译文" in prompt
    assert "自然表达" in prompt


def test_build_prompt_uses_bundled_phrase_pack_examples(monkeypatch, tmp_path):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.phrase_library import PhraseLibrary, import_bundled_phrase_packs

    phrases = PhraseLibrary(tmp_path / "phrases.sqlite3")
    imported = import_bundled_phrase_packs(library=phrases)
    assert imported["imported"] >= 1

    monkeypatch.setattr(tmod, "PhraseLibrary", lambda: phrases)
    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)
    config = _translator_config()
    config["translation"]["use_translation_memory"] = False

    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {"name": "Party Scene", "original_language": "en"},
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "Where's the after party?"},
        ],
    )

    assert "Subtitle phrase examples" in prompt
    assert "续摊在哪" in prompt
    assert "tags:" in prompt
    assert translator.last_quality_trace.phrase_hits
    assert translator.last_quality_trace.phrase_hits[0]["pack_id"].startswith("ai-sub-pro.")


def test_build_prompt_prefers_domain_phrase_pack_from_metadata(monkeypatch, tmp_path):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.phrase_library import PhraseLibrary, import_bundled_phrase_packs

    phrases = PhraseLibrary(tmp_path / "phrases.sqlite3")
    imported = import_bundled_phrase_packs(library=phrases)
    assert imported["imported"] >= 600

    monkeypatch.setattr(tmod, "PhraseLibrary", lambda: phrases)
    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)
    config = _translator_config()
    config["translation"]["use_translation_memory"] = False

    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {
            "name": "Hospital Case S01E01",
            "original_language": "en",
            "plot": "A doctor and her team treat a patient in a hospital.",
        },
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "We need to run a CT scan."},
        ],
    )

    assert "我们需要做 CT 扫描" in prompt
    assert "tags: medical" in prompt
    assert translator.last_quality_trace.phrase_hits
    assert translator.last_quality_trace.phrase_hits[0]["pack_id"] == "ai-sub-pro.en-zh.domain_medical"


def test_build_prompt_injects_curated_domain_terms_below_project_kb(monkeypatch, tmp_path):
    from app.engines import translator as tmod
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.knowledge import KnowledgeBase
    from app.engines.phrase_library import PhraseLibrary

    phrases = PhraseLibrary(tmp_path / "phrases.sqlite3")
    phrases.add_phrase(
        source_text="head for the sand",
        target_text="朝沙地去",
        source_language="en",
        target_language="zh-CN",
        source_name="unit-test",
        license="local",
        quality=0.9,
    )
    monkeypatch.setattr(tmod, "PhraseLibrary", lambda: phrases)

    kb = KnowledgeBase()
    kb.set_project("surviving", ProjectKb(
        show_title="Surviving Earth",
        slang=[TermEntry(source="Pangaea", target="盘古大陆")],
    ))
    monkeypatch.setattr(tmod, "_shared_kb", kb, raising=False)

    config = _translator_config()
    config["translation"]["use_translation_memory"] = False
    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {"name": "Surviving Earth S01E01", "original_language": "en"},
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "These little climbers are Suminia."},
            {"id": 2, "original": "called proto-Pterosaurs, head for the sand."},
        ],
    )

    kb_pos = prompt.index("Use EXACTLY these translations")
    domain_pos = prompt.index("Curated domain terminology")
    phrase_pos = prompt.index("Subtitle phrase examples")
    assert kb_pos < domain_pos < phrase_pos
    assert "Suminia → 苏美尼兽" in prompt
    assert "proto-Pterosaurs → 原翼龙类" in prompt
    assert translator.last_quality_trace.kb_hits
    assert translator.last_quality_trace.kb_hits[0]["scope"] == "curated_domain"


def test_build_prompt_injects_auto_scientific_terms_for_consistency(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)

    config = _translator_config()
    config["translation"]["use_translation_memory"] = False
    config["translation"]["use_phrase_library"] = False
    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {"name": "Surviving Earth S01E02", "original_language": "en"},
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "The Ischigualastia keeps moving."},
            {"id": 2, "original": "Without the Dicroidium, food is scarce."},
        ],
    )

    assert "Auto-detected terminology" in prompt
    assert "Ischigualastia" in prompt
    assert "Dicroidium" in prompt
    assert "preserve the standard source form" in prompt
    scopes = {
        hit.get("scope")
        for hit in translator.last_quality_trace.kb_hits
        if isinstance(hit, dict)
    }
    assert "auto_scientific_term" in scopes


def test_build_prompt_does_not_inject_auto_scientific_terms_for_technical_tutorial(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)

    config = _translator_config()
    config["translation"]["use_translation_memory"] = False
    config["translation"]["use_phrase_library"] = False
    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {
            "name": "Browser Automation Tutorial",
            "original_language": "en",
            "tags": ["tutorial", "programming"],
        },
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "Chromium renders the page while Selenium drives the browser."},
        ],
    )

    assert "Auto-detected terminology" not in prompt
    scopes = {
        hit.get("scope")
        for hit in translator.last_quality_trace.kb_hits
        if isinstance(hit, dict)
    }
    assert "auto_scientific_term" not in scopes


def test_translate_accumulates_quality_trace_across_batches(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.utils.srt import SubtitleBlock
    from datetime import timedelta

    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)
    config = _translator_config()
    config["translation"]["batch_size"] = 1
    config["translation"]["use_translation_memory"] = False
    config["translation"]["use_phrase_library"] = False
    translator = tmod.SubtitleTranslator(config)
    monkeypatch.setattr(
        translator.primary,
        "translate_batch",
        lambda items, system_prompt, retries=3: [
            {"id": item["id"], "translation": f"译文{item['id']}"}
            for item in items
        ],
    )
    blocks = [
        SubtitleBlock(
            index=1,
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text="These little climbers are Suminia.",
        ),
        SubtitleBlock(
            index=2,
            start=timedelta(seconds=2),
            end=timedelta(seconds=3),
            text="Called proto-Pterosaurs, head for the sand.",
        ),
    ]

    translator.translate(
        blocks,
        target_lang="简体中文",
        meta_info={"name": "Surviving Earth", "original_language": "en"},
    )

    sources = {
        hit.get("source")
        for hit in translator.last_quality_trace.kb_hits
        if isinstance(hit, dict)
    }
    assert {"Suminia", "proto-Pterosaurs"} <= sources


def test_build_prompt_injects_content_profiles_before_phrase_examples(monkeypatch, tmp_path):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.phrase_library import PhraseLibrary

    phrases = PhraseLibrary(tmp_path / "phrases.sqlite3")
    phrases.add_phrase(
        source_text="What happened?",
        target_text="怎么回事？",
        source_language="ko",
        target_language="zh-CN",
        source_name="unit-test",
        license="local",
        tags=["korean"],
        quality=0.9,
    )
    monkeypatch.setattr(tmod, "PhraseLibrary", lambda: phrases)
    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)

    config = _translator_config()
    config["translation"]["use_translation_memory"] = False
    translator = tmod.SubtitleTranslator(config)
    prompt = translator._build_prompt(
        "简体中文",
        {
            "name": "Korean Drama Cast Interview S01E01",
            "original_language": "ko",
            "tmdb_type": "tv",
            "tags": ["interview"],
        },
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "What happened?"},
        ],
    )

    profile_pos = prompt.index("Content profile guidance")
    phrase_pos = prompt.index("Subtitle phrase examples")
    assert profile_pos < phrase_pos
    assert "[Korean drama]" in prompt
    assert "[Interview]" in prompt
    assert "honorific" in prompt.lower()
    assert "filler" in prompt.lower()
    assert translator.last_quality_trace.profile_hits
    assert {hit["id"] for hit in translator.last_quality_trace.profile_hits} == {
        "korean_drama",
        "interview",
    }


def test_build_prompt_injects_subtitle_style_guidance(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)
    config = _translator_config()
    config["translation"]["use_translation_memory"] = False
    config["translation"]["use_phrase_library"] = False
    translator = tmod.SubtitleTranslator(config)

    prompt = translator._build_prompt(
        "简体中文",
        {"name": "Studio AV Release", "tags": ["adult"], "original_language": "en"},
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "Harder."},
        ],
    )

    assert "Subtitle style constraints" in prompt
    assert "16 Chinese characters per line" in prompt
    assert "reading speed at or below 9.0 characters per second" in prompt
    assert translator.last_quality_trace.style_hits
    assert translator.last_quality_trace.style_hits[0]["scope"] == "subtitle_style"


def test_build_prompt_injects_project_metadata_and_manual_terms(monkeypatch):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase

    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)
    config = _translator_config()
    config["translation"]["use_translation_memory"] = False
    config["translation"]["use_phrase_library"] = False
    translator = tmod.SubtitleTranslator(config)

    prompt = translator._build_prompt(
        "简体中文",
        {
            "name": "Stanford CS229 Lecture 04",
            "content_type": "academic_lecture",
            "academic_field": "machine learning",
            "content_notes": "Lecture about gradient descent and convexity.",
            "manual_terms": "gradient descent=梯度下降\nconvexity=凸性",
            "original_language": "en",
        },
        None,
        [],
        [],
        items=[
            {"id": 1, "original": "Gradient descent relies on convexity assumptions."},
        ],
    )

    assert "Project content metadata" in prompt
    assert "academic lecture" in prompt.lower()
    assert "machine learning" in prompt
    assert "gradient descent -> 梯度下降" in prompt
    assert "convexity -> 凸性" in prompt
    assert "Academic lecture / research talk" in prompt
    assert translator.last_quality_trace.kb_hits
    assert any(hit["scope"] == "manual_terms" for hit in translator.last_quality_trace.kb_hits)


def test_build_prompt_gates_legal_adult_phrase_examples(monkeypatch, tmp_path):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.phrase_library import PhraseLibrary, import_bundled_phrase_packs

    phrases = PhraseLibrary(tmp_path / "phrases.sqlite3")
    import_bundled_phrase_packs(library=phrases)
    monkeypatch.setattr(tmod, "PhraseLibrary", lambda: phrases)
    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)

    config = _translator_config()
    config["translation"]["use_translation_memory"] = False
    config["translation"]["max_phrase_examples"] = 6
    translator = tmod.SubtitleTranslator(config)

    plain_prompt = translator._build_prompt(
        "简体中文",
        {"name": "Airport Drama S01E01", "original_language": "en", "tmdb_type": "tv"},
        None,
        [],
        [],
        items=[{"id": 1, "original": "I'm coming."}],
    )
    plain_trace = translator.last_quality_trace.to_dict()

    assert "我要去了" not in plain_prompt
    assert all(
        hit["pack_id"] != "ai-sub-pro.en-zh.domain_legal_adult"
        for hit in plain_trace["phrase_hits"]
    )

    adult_prompt = translator._build_prompt(
        "简体中文",
        {"name": "Studio AV Release", "tags": ["adult"], "original_language": "en"},
        None,
        [],
        [],
        items=[{"id": 1, "original": "I'm coming."}],
    )
    adult_trace = translator.last_quality_trace.to_dict()

    assert "我要去了" in adult_prompt
    assert any(
        hit["pack_id"] == "ai-sub-pro.en-zh.domain_legal_adult"
        for hit in adult_trace["phrase_hits"]
    )
