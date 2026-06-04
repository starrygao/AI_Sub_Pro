import json


def test_phrase_library_imports_and_retrieves_by_language_pair(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    source = tmp_path / "phrases.json"
    source.write_text(json.dumps({
        "source": "unit-test",
        "license": "CC-BY",
        "phrases": [
            {
                "source_text": "Shoot your shot.",
                "target_text": "主动出击。",
                "source_language": "en",
                "target_language": "zh-CN",
                "quality": 0.9,
            },
            {
                "source_text": "Shoot your shot.",
                "target_text": "Passe à l'action.",
                "source_language": "en",
                "target_language": "fr",
                "quality": 0.9,
            },
        ],
    }), encoding="utf-8")

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    imported = library.import_json(source)

    assert imported == 2
    results = library.retrieve(
        "You should shoot your shot, Dr. Pierce.",
        source_language="en",
        target_language="zh-CN",
        limit=5,
    )
    assert len(results) == 1
    assert results[0].target_text == "主动出击。"
    assert results[0].source_name == "unit-test"
    assert results[0].license == "CC-BY"


def test_phrase_library_respects_limit_and_quality_order(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    library.add_phrase(
        source_text="That plan is way off.",
        target_text="这个计划太离谱了。",
        source_language="en",
        target_language="zh-CN",
        source_name="manual",
        license="local",
        quality=0.7,
    )
    library.add_phrase(
        source_text="That plan is way off.",
        target_text="这主意太不靠谱了。",
        source_language="en",
        target_language="zh-CN",
        source_name="manual",
        license="local",
        quality=0.95,
    )

    results = library.retrieve(
        "The plan is way off.",
        source_language="en",
        target_language="zh-CN",
        limit=1,
    )

    assert len(results) == 1
    assert results[0].target_text == "这主意太不靠谱了。"


def test_phrase_library_rejects_malformed_rows(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    source = tmp_path / "phrases.json"
    source.write_text(json.dumps({
        "source": "bad",
        "license": "unknown",
        "phrases": [
            {"source_text": "", "target_text": "空", "source_language": "en", "target_language": "zh-CN"},
            {"source_text": "Hello", "target_text": "", "source_language": "en", "target_language": "zh-CN"},
            {"source_text": "Hello", "target_text": "你好", "source_language": "en", "target_language": "zh-CN"},
        ],
    }), encoding="utf-8")

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")

    assert library.import_json(source) == 1
    assert len(library.retrieve("Hello", source_language="en", target_language="zh-CN")) == 1
