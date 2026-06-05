import json
import sqlite3

import pytest


class _ConnectionProxy:
    def __init__(
        self,
        conn,
        *,
        statements=None,
        calls=None,
        fail_phrase_fts_create=False,
        fail_phrase_fts_insert=False,
    ):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_statements", statements)
        object.__setattr__(self, "_calls", calls)
        object.__setattr__(self, "_fail_phrase_fts_create", fail_phrase_fts_create)
        object.__setattr__(self, "_fail_phrase_fts_insert", fail_phrase_fts_insert)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        if name == "row_factory":
            setattr(self._conn, name, value)
            return
        object.__setattr__(self, name, value)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self._conn.__exit__(exc_type, exc, traceback)

    def execute(self, sql, *args, **kwargs):
        if self._statements is not None:
            self._statements.append(sql)
        if self._calls is not None:
            self._calls.append((sql, args, kwargs))
        if self._fail_phrase_fts_create and "CREATE VIRTUAL TABLE" in sql and "phrase_examples_fts" in sql:
            raise sqlite3.OperationalError("simulated phrase FTS create failure")
        if self._fail_phrase_fts_insert and "INSERT INTO phrase_examples_fts(rowid" in sql:
            raise sqlite3.OperationalError("simulated phrase FTS insert failure")
        return self._conn.execute(sql, *args, **kwargs)


def _skip_without_fts5(tmp_path):
    from app.engines.retrieval_scoring import sqlite_supports_fts5

    if not sqlite_supports_fts5(tmp_path / "fts-probe.sqlite3"):
        pytest.skip("SQLite FTS5 is unavailable in this Python build")


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


def test_phrase_library_forced_fts5_retrieves_when_available(tmp_path):
    _skip_without_fts5(tmp_path)

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
        "Hudson Oaks",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].target_text == "哈德逊奥克斯很安静。"
    assert library.last_retrieval_backend == "fts5"


def test_phrase_library_fts_rows_stay_synced_after_insert_and_reopen(tmp_path):
    _skip_without_fts5(tmp_path)

    from app.engines.phrase_library import PhraseLibrary

    db = tmp_path / "phrases.sqlite3"
    first = PhraseLibrary(db)
    first.add_phrase(
        source_text="Fresh sync marker",
        target_text="新的同步标记。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )

    assert first.retrieve(
        "Fresh sync",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )[0].target_text == "新的同步标记。"

    second = PhraseLibrary(db)
    results = second.retrieve(
        "Fresh sync",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].target_text == "新的同步标记。"
    assert second.last_retrieval_backend == "fts5"


def test_phrase_library_recovers_when_fts_table_is_recreated_with_stale_sync_marker(tmp_path):
    _skip_without_fts5(tmp_path)

    from app.engines.phrase_library import PhraseLibrary

    db = tmp_path / "phrases.sqlite3"
    first = PhraseLibrary(db)
    first.add_phrase(
        source_text="Recovered stale sync phrase",
        target_text="恢复陈旧同步短语。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )

    assert first.retrieve(
        "Recovered stale sync",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )[0].target_text == "恢复陈旧同步短语。"

    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT last_rowid FROM phrase_examples_fts_sync WHERE name = ?",
            ("phrase_examples_fts",),
        ).fetchone()[0] > 0
        conn.execute("DROP TABLE phrase_examples_fts")

    second = PhraseLibrary(db)
    results = second.retrieve(
        "Recovered stale sync",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].target_text == "恢复陈旧同步短语。"
    assert second.last_retrieval_backend == "fts5"


def test_phrase_library_fts_match_query_handles_quotes_punctuation_and_non_ascii(tmp_path):
    _skip_without_fts5(tmp_path)

    from app.engines.phrase_library import PhraseLibrary

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    library.add_phrase(
        source_text='urgent: ちょっと待って "now"',
        target_text="急ぎです、等一下。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )

    results = library.retrieve(
        'urgent!!! "quoted" ちょっと待って？',
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].target_text == "急ぎです、等一下。"
    assert library.last_retrieval_backend == "fts5"


def test_phrase_library_forced_fts5_retrieves_accented_latin_queries(tmp_path):
    _skip_without_fts5(tmp_path)

    from app.engines.phrase_library import PhraseLibrary

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    library.add_phrase(
        source_text="Café Müller",
        target_text="穆勒咖啡馆。",
        source_language="de",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )
    library.add_phrase(
        source_text="¿Dónde está el médico?",
        target_text="医生在哪里？",
        source_language="es",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )

    exact_results = library.retrieve(
        "Café Müller",
        source_language="de",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )
    folded_results = library.retrieve(
        "Cafe Muller",
        source_language="de",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )
    spanish_results = library.retrieve(
        "Donde esta el medico",
        source_language="es",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert exact_results[0].target_text == "穆勒咖啡馆。"
    assert folded_results[0].target_text == "穆勒咖啡馆。"
    assert spanish_results[0].target_text == "医生在哪里？"
    assert library.last_retrieval_backend == "fts5"


def test_phrase_library_auto_unions_fts_with_legacy_ngram_candidates(tmp_path):
    _skip_without_fts5(tmp_path)

    from app.engines.phrase_library import PhraseLibrary

    library = PhraseLibrary(tmp_path / "phrases.sqlite3")
    library.add_phrase(
        source_text="urgent now",
        target_text="现在很紧急。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.2,
    )
    library.add_phrase(
        source_text="ちょっと待って",
        target_text="等一下。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.95,
    )

    ngram_results = library.retrieve(
        "urgent ちょっと待ってよ",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="ngram",
    )
    auto_results = library.retrieve(
        "urgent ちょっと待ってよ",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="auto",
    )

    assert ngram_results[0].target_text == "等一下。"
    assert auto_results[0].target_text == "等一下。"
    assert library.last_retrieval_backend == "fts5"


def test_phrase_library_fts_query_failure_falls_back_to_ngram(tmp_path, monkeypatch):
    _skip_without_fts5(tmp_path)

    from app.engines import phrase_library as phrase_module

    library = phrase_module.PhraseLibrary(tmp_path / "phrases.sqlite3")
    library.add_phrase(
        source_text="Fallback scan phrase",
        target_text="回退扫描短语。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )
    monkeypatch.setattr(phrase_module, "_fts_match_query", lambda value: '"unterminated')

    results = library.retrieve(
        "Fallback scan phrase",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="auto",
    )

    assert results[0].target_text == "回退扫描短语。"
    assert library.last_retrieval_backend == "ngram"


def test_phrase_library_fts_create_failure_falls_back_to_ngram(tmp_path, monkeypatch):
    from app.engines import phrase_library as phrase_module

    real_connect = phrase_module.sqlite3.connect

    def failing_connect(*args, **kwargs):
        return _ConnectionProxy(real_connect(*args, **kwargs), fail_phrase_fts_create=True)

    monkeypatch.setattr(phrase_module.sqlite3, "connect", failing_connect)

    library = phrase_module.PhraseLibrary(tmp_path / "phrases.sqlite3")
    library.add_phrase(
        source_text="Create failure fallback",
        target_text="创建失败回退。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )

    results = library.retrieve(
        "Create failure fallback",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].target_text == "创建失败回退。"
    assert library.last_retrieval_backend == "ngram"


def test_phrase_library_fts_insert_failure_preserves_base_phrase_row(tmp_path, monkeypatch):
    from app.engines import phrase_library as phrase_module

    db = tmp_path / "phrases.sqlite3"
    real_connect = phrase_module.sqlite3.connect

    def failing_connect(*args, **kwargs):
        return _ConnectionProxy(real_connect(*args, **kwargs), fail_phrase_fts_insert=True)

    monkeypatch.setattr(phrase_module.sqlite3, "connect", failing_connect)

    library = phrase_module.PhraseLibrary(db)
    entry_id = library.add_phrase(
        source_text="Insert failure still stores phrase",
        target_text="插入失败仍保存短语。",
        source_language="en",
        target_language="zh-CN",
        source_name="unit",
        license="local",
        quality=0.9,
    )

    assert entry_id is not None
    with real_connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM phrase_examples WHERE source_text = ?",
            ("Insert failure still stores phrase",),
        ).fetchone()[0] == 1

    results = library.retrieve(
        "Insert failure still stores phrase",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].target_text == "插入失败仍保存短语。"
    assert library.last_retrieval_backend == "ngram"


def test_phrase_library_fts_schema_init_does_not_rebuild_on_reopen(tmp_path, monkeypatch):
    _skip_without_fts5(tmp_path)

    from app.engines import phrase_library as phrase_module

    db = tmp_path / "phrases.sqlite3"
    first = phrase_module.PhraseLibrary(db)
    for index in range(3):
        first.add_phrase(
            source_text=f"No rebuild marker {index}",
            target_text=f"不重建标记 {index}。",
            source_language="en",
            target_language="zh-CN",
            source_name="unit",
            license="local",
            quality=0.9,
        )

    with sqlite3.connect(db) as conn:
        seeded_ids = {
            row[0]
            for row in conn.execute(
                "SELECT id FROM phrase_examples WHERE source_text LIKE 'No rebuild marker %'"
            )
        }

    statements = []
    calls = []
    real_connect = phrase_module.sqlite3.connect

    def tracing_connect(*args, **kwargs):
        return _ConnectionProxy(real_connect(*args, **kwargs), statements=statements, calls=calls)

    monkeypatch.setattr(phrase_module.sqlite3, "connect", tracing_connect)

    phrase_module.PhraseLibrary(db)

    reinserted_rowids = {
        args[0][0]
        for sql, args, _kwargs in calls
        if "INSERT INTO phrase_examples_fts(rowid" in sql and args and args[0]
    }
    assert not any("rebuild" in statement.lower() for statement in statements)
    assert reinserted_rowids.isdisjoint(seeded_ids)
