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


def test_phrase_pack_import_is_idempotent(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    source = tmp_path / "pack.json"
    source.write_text(json.dumps({
        "id": "unit.en-zh.pack",
        "version": 1,
        "source": "unit-pack",
        "license": "local",
        "source_language": "en",
        "target_language": "zh-CN",
        "tags": ["subtitle", "slang"],
        "phrases": [
            {
                "source_text": "Where's the after party?",
                "target_text": "续摊在哪？",
                "quality": 0.9,
            },
            {
                "source_text": "You got this.",
                "target_text": "你可以的。",
                "quality": 0.9,
            },
        ],
    }), encoding="utf-8")

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")

    assert library.import_pack(source) == 2
    assert library.import_pack(source) == 0

    results = library.retrieve(
        "Where is the after party?",
        source_language="en",
        target_language="zh-CN",
        limit=5,
    )
    assert len(results) == 1
    assert results[0].target_text == "续摊在哪？"
    assert results[0].pack_id == "unit.en-zh.pack"
    assert results[0].pack_version == 1
    assert results[0].tags == "subtitle,slang"


def test_phrase_pack_newer_version_adds_only_new_examples(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    source = tmp_path / "pack.json"
    source.write_text(json.dumps({
        "id": "unit.en-zh.pack",
        "version": 1,
        "source": "unit-pack",
        "license": "local",
        "source_language": "en",
        "target_language": "zh-CN",
        "phrases": [
            {
                "source_text": "Drop it.",
                "target_text": "别再说了。",
                "quality": 0.8,
            },
        ],
    }), encoding="utf-8")

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    assert library.import_pack(source) == 1

    source.write_text(json.dumps({
        "id": "unit.en-zh.pack",
        "version": 2,
        "source": "unit-pack",
        "license": "local",
        "source_language": "en",
        "target_language": "zh-CN",
        "phrases": [
            {
                "source_text": "Drop it.",
                "target_text": "别再说了。",
                "quality": 0.8,
            },
            {
                "source_text": "Read the room.",
                "target_text": "看点气氛行不行。",
                "quality": 0.9,
            },
        ],
    }), encoding="utf-8")

    assert library.import_pack(source) == 1
    assert library.import_pack(source) == 0
    assert len(library.retrieve("Drop it.", source_language="en", target_language="zh-CN")) == 1
    assert len(library.retrieve("Read the room.", source_language="en", target_language="zh-CN")) == 1


def test_phrase_library_boosts_preferred_tags(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    library.add_phrase(
        source_text="We need to run the scan.",
        target_text="我们需要跑起来。",
        source_language="en",
        target_language="zh-CN",
        source_name="sports",
        license="local",
        quality=0.95,
        tags=["sports"],
    )
    library.add_phrase(
        source_text="We need to run the scan.",
        target_text="我们需要做扫描。",
        source_language="en",
        target_language="zh-CN",
        source_name="medical",
        license="local",
        quality=0.8,
        tags=["medical"],
    )

    results = library.retrieve(
        "We need to run the scan.",
        source_language="en",
        target_language="zh-CN",
        preferred_tags={"medical"},
        limit=1,
    )

    assert len(results) == 1
    assert results[0].target_text == "我们需要做扫描。"


def test_bundled_phrase_packs_import_and_retrieve(tmp_path):
    from app.engines.phrase_library import (
        PhraseLibrary,
        bundled_phrase_pack_paths,
        import_bundled_phrase_packs,
    )

    pack_names = {path.name for path in bundled_phrase_pack_paths()}
    assert "en-zh.subtitle_colloquial_starter.v1.json" in pack_names
    assert "ja-zh.subtitle_colloquial_starter.v1.json" in pack_names
    assert "ko-zh.subtitle_colloquial_starter.v1.json" in pack_names
    assert "en-zh.domain_medical.v1.json" in pack_names
    assert "en-zh.domain_crime.v1.json" in pack_names
    assert "en-zh.domain_workplace.v1.json" in pack_names
    assert "es-zh.subtitle_colloquial_starter.v1.json" in pack_names
    assert "fr-zh.subtitle_colloquial_starter.v1.json" in pack_names
    assert "de-zh.subtitle_colloquial_starter.v1.json" in pack_names
    assert len(pack_names) == 12

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    imported = import_bundled_phrase_packs(library=library)

    assert imported["imported"] >= 600
    assert any(pack["file"] == "en-zh.subtitle_colloquial_starter.v1.json" for pack in imported["packs"])
    assert any(
        result.target_text == "续摊在哪？"
        for result in library.retrieve(
            "Where's the after party?",
            source_language="en",
            target_language="zh-CN",
        )
    )
    assert any(
        result.target_text == "等一下。"
        for result in library.retrieve("ちょっと待ってよ", source_language="ja", target_language="zh-CN")
    )
    assert any(
        result.target_text == "等一下。"
        for result in library.retrieve("잠깐만요", source_language="ko", target_language="zh-CN")
    )
    assert any(
        result.target_text == "等一下。"
        for result in library.retrieve("Espera un momento.", source_language="es", target_language="zh-CN")
    )
    assert any(
        result.target_text == "等一下。"
        for result in library.retrieve("Attends une seconde.", source_language="fr", target_language="zh-CN")
    )
    assert any(
        result.target_text == "等一下。"
        for result in library.retrieve("Warte kurz.", source_language="de", target_language="zh-CN")
    )
    assert any(
        result.target_text == "我们需要做 CT 扫描。"
        for result in library.retrieve(
            "We need to run a CT scan.",
            source_language="en",
            target_language="zh-CN",
            preferred_tags={"medical"},
        )
    )


def test_phrase_library_reports_retrieval_backend(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    library.add_phrase(
        source_text="Hudson Oaks is quiet.",
        target_text="哈德逊奥克斯很安静。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )

    results = library.retrieve(
        "I need to go to Hudson Oaks.",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="ngram",
    )

    assert results
    assert library.last_retrieval_backend == "ngram"


def test_phrase_library_auto_backend_preserves_existing_rows(tmp_path):
    from app.engines.phrase_library import PhraseLibrary

    db = tmp_path / "phrases.sqlite3"
    first = PhraseLibrary(db)
    first.add_phrase(
        source_text="We need to run the scan.",
        target_text="我们需要做扫描。",
        source_language="en",
        target_language="zh-CN",
        source_name="medical",
        license="local",
        quality=0.88,
        tags=["medical"],
    )

    second = PhraseLibrary(db)
    results = second.retrieve(
        "Can we run a scan?",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        preferred_tags={"medical"},
        backend="auto",
    )

    assert results[0].target_text == "我们需要做扫描。"
    assert second.last_retrieval_backend in {"fts5", "ngram"}
