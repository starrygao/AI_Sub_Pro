import json
import sqlite3

import pytest
from fastapi.testclient import TestClient


class _ConnectionProxy:
    def __init__(
        self,
        conn,
        *,
        fail_memory_fts_create=False,
        fail_memory_fts_insert=False,
    ):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_fail_memory_fts_create", fail_memory_fts_create)
        object.__setattr__(self, "_fail_memory_fts_insert", fail_memory_fts_insert)

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
        if self._fail_memory_fts_create and "CREATE VIRTUAL TABLE" in sql and "translation_memory_fts" in sql:
            raise sqlite3.OperationalError("simulated memory FTS create failure")
        if self._fail_memory_fts_insert and "INSERT INTO translation_memory_fts(rowid" in sql:
            raise sqlite3.OperationalError("simulated memory FTS insert failure")
        return self._conn.execute(sql, *args, **kwargs)

    def executemany(self, sql, seq_of_parameters):
        return self._conn.executemany(sql, seq_of_parameters)


def _skip_without_fts5(tmp_path):
    from app.engines.retrieval_scoring import sqlite_supports_fts5

    if not sqlite_supports_fts5(tmp_path / "fts-probe.sqlite3"):
        pytest.skip("SQLite FTS5 is unavailable in this Python build")


def test_translation_memory_records_and_retrieves_similar_edits(tmp_path):
    from app.engines.translation_memory import TranslationMemoryStore

    store = TranslationMemoryStore(tmp_path / "memory.sqlite3")
    entry_id = store.record_edit(
        source_text="Hudson Oaks is giving resort vibes.",
        machine_translation="哈德森橡树很有度假村的感觉。",
        final_translation="哈德逊奥克斯有种度假村的感觉。",
        source_language="en",
        target_language="zh-CN",
        project_name="Brilliant Minds",
        tmdb_id=123,
    )

    assert entry_id is not None
    results = store.retrieve(
        "I need to go to Hudson Oaks.",
        source_language="en",
        target_language="zh-CN",
        limit=3,
    )

    assert len(results) == 1
    assert results[0].final_translation == "哈德逊奥克斯有种度假村的感觉。"
    assert results[0].project_name == "Brilliant Minds"
    assert store.last_retrieval_backend in {"fts5", "ngram"}


def test_translation_memory_rejects_empty_and_noop_edits(tmp_path):
    from app.engines.translation_memory import TranslationMemoryStore

    store = TranslationMemoryStore(tmp_path / "memory.sqlite3")

    assert store.record_edit(
        source_text="",
        machine_translation="旧",
        final_translation="新",
        source_language="en",
        target_language="zh-CN",
    ) is None
    assert store.record_edit(
        source_text="Hello",
        machine_translation="你好",
        final_translation="你好",
        source_language="en",
        target_language="zh-CN",
    ) is None
    assert store.retrieve("Hello", source_language="en", target_language="zh-CN") == []


def test_translation_memory_respects_language_pair_and_limit(tmp_path):
    from app.engines.translation_memory import TranslationMemoryStore

    store = TranslationMemoryStore(tmp_path / "memory.sqlite3")
    for i in range(5):
        store.record_edit(
            source_text=f"Take the shot now {i}",
            machine_translation=f"现在拍摄 {i}",
            final_translation=f"现在就出手 {i}",
            source_language="en",
            target_language="zh-CN",
        )
    store.record_edit(
        source_text="Take the shot now",
        machine_translation="Prends la photo",
        final_translation="Passe à l'action",
        source_language="en",
        target_language="fr",
    )

    results = store.retrieve(
        "Take your shot now",
        source_language="en",
        target_language="zh-CN",
        limit=2,
    )

    assert len(results) == 2
    assert all(item.target_language == "zh-CN" for item in results)


def test_translation_memory_reports_ngram_backend_and_increments_usage_count(tmp_path):
    from app.engines.translation_memory import TranslationMemoryStore

    store = TranslationMemoryStore(tmp_path / "memory.sqlite3")
    store.record_edit(
        source_text="Hudson Oaks is quiet.",
        machine_translation="哈德森橡树很安静。",
        final_translation="哈德逊奥克斯很安静。",
        source_language="en",
        target_language="zh-CN",
    )

    first = store.retrieve(
        "I need to go to Hudson Oaks.",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="ngram",
    )
    second = store.retrieve(
        "I need to go to Hudson Oaks.",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="ngram",
    )

    assert first[0].usage_count == 0
    assert second[0].usage_count >= 1
    assert store.last_retrieval_backend == "ngram"


def test_translation_memory_invalid_backend_falls_back_to_auto(tmp_path, monkeypatch):
    from app.engines import translation_memory as memory_module

    monkeypatch.setattr(memory_module, "sqlite_supports_fts5", lambda path: False)
    store = memory_module.TranslationMemoryStore(tmp_path / "memory.sqlite3")
    store.record_edit(
        source_text="Invalid backend still retrieves.",
        machine_translation="无效后端仍会检索。",
        final_translation="无效后端仍可检索。",
        source_language="en",
        target_language="zh-CN",
    )

    results = store.retrieve(
        "Invalid backend still retrieves.",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="not-a-backend",
    )

    assert results[0].final_translation == "无效后端仍可检索。"
    assert store.last_retrieval_backend == "ngram"


def test_translation_memory_auto_unions_fts_with_ngram_candidates(tmp_path):
    _skip_without_fts5(tmp_path)

    from app.engines.translation_memory import TranslationMemoryStore

    store = TranslationMemoryStore(tmp_path / "memory.sqlite3")
    store.record_edit(
        source_text="urgent now",
        machine_translation="形势有点急。",
        final_translation="现在很紧急。",
        source_language="en",
        target_language="zh-CN",
    )
    store.record_edit(
        source_text="urgent right now",
        machine_translation="情况很急。",
        final_translation="现在很紧急。",
        source_language="en",
        target_language="zh-CN",
    )
    store.record_edit(
        source_text="ちょっと待って",
        machine_translation="请等一下。",
        final_translation="等一下。",
        source_language="en",
        target_language="zh-CN",
    )

    ngram_results = store.retrieve(
        "urgent ちょっと待ってよ",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="ngram",
    )
    auto_results = store.retrieve(
        "urgent ちょっと待ってよ",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="auto",
    )

    assert ngram_results[0].final_translation == "等一下。"
    assert auto_results[0].final_translation == "等一下。"
    assert store.last_retrieval_backend == "fts5"


def test_translation_memory_forced_fts5_retrieves_when_available(tmp_path):
    _skip_without_fts5(tmp_path)

    from app.engines.translation_memory import TranslationMemoryStore

    store = TranslationMemoryStore(tmp_path / "memory.sqlite3")
    store.record_edit(
        source_text='urgent: ちょっと待って "now"',
        machine_translation="急着等一下。",
        final_translation="急一点，等一下。",
        source_language="en",
        target_language="zh-CN",
    )

    results = store.retrieve(
        'urgent!!! "quoted" ちょっと待って？',
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].final_translation == "急一点，等一下。"
    assert store.last_retrieval_backend == "fts5"


def test_translation_memory_auto_falls_back_to_ngram_when_fts_unavailable(tmp_path, monkeypatch):
    from app.engines import translation_memory as memory_module

    monkeypatch.setattr(memory_module, "sqlite_supports_fts5", lambda path: False)
    store = memory_module.TranslationMemoryStore(tmp_path / "memory.sqlite3")
    store.record_edit(
        source_text="Fallback scan phrase",
        machine_translation="回退扫描词条。",
        final_translation="回退扫描短语。",
        source_language="en",
        target_language="zh-CN",
    )

    results = store.retrieve(
        "Fallback scan phrase",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="auto",
    )

    assert results[0].final_translation == "回退扫描短语。"
    assert store.last_retrieval_backend == "ngram"


def test_translation_memory_fts_query_failure_falls_back_to_ngram(tmp_path, monkeypatch):
    _skip_without_fts5(tmp_path)

    from app.engines import translation_memory as memory_module

    store = memory_module.TranslationMemoryStore(tmp_path / "memory.sqlite3")
    store.record_edit(
        source_text="Query failure fallback",
        machine_translation="查询失败时回退。",
        final_translation="查询失败回退。",
        source_language="en",
        target_language="zh-CN",
    )
    monkeypatch.setattr(memory_module, "_fts_match_query", lambda value: '"unterminated')

    results = store.retrieve(
        "Query failure fallback",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="auto",
    )

    assert results[0].final_translation == "查询失败回退。"
    assert store.last_retrieval_backend == "ngram"


def test_translation_memory_recovers_when_fts_table_is_recreated_with_stale_sync_marker(tmp_path):
    _skip_without_fts5(tmp_path)

    from app.engines.translation_memory import TranslationMemoryStore

    db = tmp_path / "memory.sqlite3"
    first = TranslationMemoryStore(db)
    first.record_edit(
        source_text="Recovered stale sync memory",
        machine_translation="恢复过期同步记忆。",
        final_translation="恢复陈旧同步记忆。",
        source_language="en",
        target_language="zh-CN",
    )

    assert first.retrieve(
        "Recovered stale sync memory",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )[0].final_translation == "恢复陈旧同步记忆。"

    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT last_rowid FROM translation_memory_fts_sync WHERE name = ?",
            ("translation_memory_fts",),
        ).fetchone()[0] > 0
        conn.execute("DROP TABLE translation_memory_fts")

    second = TranslationMemoryStore(db)
    results = second.retrieve(
        "Recovered stale sync memory",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].final_translation == "恢复陈旧同步记忆。"
    assert second.last_retrieval_backend == "fts5"


def test_translation_memory_recovers_when_fts_rowid_coverage_is_inconsistent(tmp_path):
    _skip_without_fts5(tmp_path)

    from app.engines.translation_memory import TranslationMemoryStore

    db = tmp_path / "memory.sqlite3"
    first = TranslationMemoryStore(db)
    rows = [
        ("Coverage first memory", "覆盖第一条记忆。"),
        ("Coverage middle memory", "覆盖中间条记忆。"),
        ("Coverage final memory", "覆盖最后条记忆。"),
    ]
    inserted_ids = []
    for source_text, final_translation in rows:
        inserted_ids.append(
                first.record_edit(
                    source_text=source_text,
                    machine_translation=f"{final_translation}（机器）",
                    final_translation=final_translation,
                    source_language="en",
                    target_language="zh-CN",
            )
        )

    middle_id = inserted_ids[1]
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO translation_memory_fts(translation_memory_fts, rowid, source_text, final_translation)
            VALUES('delete', ?, ?, ?)
            """,
            (middle_id, "Coverage middle memory", "覆盖中间条记忆。"),
        )
        conn.execute(
            "INSERT INTO translation_memory_fts(rowid, source_text, final_translation) VALUES (?, ?, ?)",
            (999, "Coverage orphan memory", "覆盖孤立条记忆。"),
        )

    second = TranslationMemoryStore(db)
    results = second.retrieve(
        "Coverage middle memory",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].final_translation == "覆盖中间条记忆。"
    assert second.last_retrieval_backend == "fts5"


def test_translation_memory_fts_insert_failure_preserves_base_row(tmp_path, monkeypatch):
    from app.engines import translation_memory as memory_module

    db = tmp_path / "memory.sqlite3"
    real_connect = memory_module.sqlite3.connect

    def failing_connect(*args, **kwargs):
        return _ConnectionProxy(real_connect(*args, **kwargs), fail_memory_fts_insert=True)

    monkeypatch.setattr(memory_module.sqlite3, "connect", failing_connect)

    store = memory_module.TranslationMemoryStore(db)
    entry_id = store.record_edit(
        source_text="Insert failure still stores memory",
        machine_translation="插入失败仍写入原文。",
        final_translation="插入失败仍保存记忆。",
        source_language="en",
        target_language="zh-CN",
    )

    assert entry_id is not None
    with real_connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM translation_memory WHERE source_text = ?",
            ("Insert failure still stores memory",),
        ).fetchone()[0] == 1

    results = store.retrieve(
        "Insert failure still stores memory",
        source_language="en",
        target_language="zh-CN",
        limit=1,
        backend="fts5",
    )

    assert results[0].final_translation == "插入失败仍保存记忆。"
    assert store.last_retrieval_backend == "ngram"


@pytest.fixture
def client(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.utils import project_store

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    from app.main import app
    return TestClient(app)


def test_save_subtitles_records_user_translation_edit(client, tmp_project_dir):
    from app.engines.translation_memory import TranslationMemoryStore, default_memory_path

    pid = "memedit"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "Brilliant Minds S02E15",
        "video_path": "/fake/video.mkv",
        "status": "translated",
        "target_language": "简体中文",
        "original_language": "en",
        "tmdb_id": 123,
    }), encoding="utf-8")
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHudson Oaks is giving resort vibes.\n\n",
        encoding="utf-8",
    )
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n哈德森橡树很有度假村的感觉。\n\n",
        encoding="utf-8",
    )

    response = client.put(f"/api/projects/{pid}/subtitles", json={
        "blocks": [{
            "index": 1,
            "start": "00:00:00,000",
            "end": "00:00:02,000",
            "text": "Hudson Oaks is giving resort vibes.",
            "translation": "哈德逊奥克斯有种度假村的感觉。",
        }]
    })

    assert response.status_code == 200
    results = TranslationMemoryStore(default_memory_path()).retrieve(
        "Hudson Oaks feels like a resort.",
        source_language="en",
        target_language="zh-CN",
    )
    assert results[0].machine_translation == "哈德森橡树很有度假村的感觉。"
    assert results[0].final_translation == "哈德逊奥克斯有种度假村的感觉。"
