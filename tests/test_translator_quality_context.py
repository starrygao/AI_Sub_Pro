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
