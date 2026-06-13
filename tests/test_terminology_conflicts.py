def test_collect_terminology_conflicts_prefers_project_kb_target():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.terminology_conflicts import collect_terminology_conflicts

    kb = ProjectKb(slang=[TermEntry(source="Suminia", target="苏米尼亚兽")])
    trace = {
        "kb_hits": [
            {
                "source": "Suminia",
                "target": "苏美尼兽",
                "scope": "curated_domain",
            }
        ],
        "memory_hits": [
            {
                "source_text": "Suminia",
                "final_translation": "苏米尼亚兽",
                "score": 0.9,
            }
        ],
        "phrase_hits": [
            {
                "source_text": "Suminia",
                "target_text": "苏美尼兽",
                "pack_id": "ai-sub-pro.test",
            }
        ],
    }

    conflicts = collect_terminology_conflicts(project_kb=kb, trace=trace)

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["source"] == "Suminia"
    assert conflict["preferred_target"] == "苏米尼亚兽"
    assert conflict["preferred_scope"] == "project"
    assert {target["target"] for target in conflict["targets"]} == {"苏米尼亚兽", "苏美尼兽"}


def test_translator_trace_records_curated_phrase_conflicts(monkeypatch, tmp_path):
    from app.engines import translator as tmod
    from app.engines.knowledge import KnowledgeBase
    from app.engines.phrase_library import PhraseLibrary

    phrases = PhraseLibrary(tmp_path / "phrases.sqlite3")
    phrases.add_phrase(
        source_text="Suminia",
        target_text="苏米尼亚兽",
        source_language="en",
        target_language="zh-CN",
        source_name="unit-test",
        license="local",
        quality=0.95,
        tags=["science"],
    )
    monkeypatch.setattr(tmod, "PhraseLibrary", lambda: phrases)
    monkeypatch.setattr(tmod, "_shared_kb", KnowledgeBase(), raising=False)

    config = {
        "translation": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "polish_provider": "",
            "batch_size": 10,
            "context_window": 3,
            "use_translation_memory": False,
            "use_phrase_library": True,
        },
        "api_keys": {"openai": "sk-test"},
    }
    translator = tmod.SubtitleTranslator(config)
    translator._build_prompt(
        "简体中文",
        {"name": "Surviving Earth", "original_language": "en"},
        None,
        [],
        [],
        items=[{"id": 1, "original": "Suminia"}],
    )

    conflicts = translator.last_quality_trace.to_dict()["conflict_hits"]
    assert conflicts
    assert conflicts[0]["source"] == "Suminia"
    assert {target["target"] for target in conflicts[0]["targets"]} == {"苏美尼兽", "苏米尼亚兽"}
