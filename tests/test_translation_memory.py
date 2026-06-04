import json

import pytest
from fastapi.testclient import TestClient


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
