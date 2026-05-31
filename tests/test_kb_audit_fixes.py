import json


def test_legacy_keywords_preserved_after_save_load_roundtrip(tmp_path, monkeypatch):
    """Regression: v1 keywords should persist across load→save→load cycle."""
    from app.engines import knowledge as kb_module

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(kb_module, "KB_FILE", kb_file)
    monkeypatch.setattr(kb_module, "LEGACY_KB", tmp_path / "legacy.json", raising=False)

    v1 = {
        "Elsbeth": {
            "keywords": ["law", "procedural", "humor"],
            "style": "sharp",
            "terms": {"Elsbeth": "艾"},
        }
    }
    kb_file.write_text(json.dumps(v1), encoding="utf-8")

    kb = kb_module.KnowledgeBase()
    kb.load()  # migrates + saves

    # Fresh instance reloads from disk
    kb2 = kb_module.KnowledgeBase()
    kb2.load()

    proj = kb2.get_project("Elsbeth")
    assert proj is not None
    assert "law" in proj.legacy_keywords
    assert "procedural" in proj.legacy_keywords
    assert "humor" in proj.legacy_keywords


def test_legacy_post_knowledge_invalidates_translator_kb(tmp_path, monkeypatch):
    """POST /api/knowledge (legacy route) must refresh translator._shared_kb."""
    from fastapi.testclient import TestClient
    from app.engines import knowledge as kb_module

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(kb_module, "KB_FILE", kb_file)
    monkeypatch.setattr(kb_module, "LEGACY_KB", tmp_path / "legacy.json", raising=False)
    monkeypatch.setattr(kb_module, "_singleton", None, raising=False)

    import app.engines.translator as tmod
    fresh_kb = kb_module.KnowledgeBase()
    monkeypatch.setattr(tmod, "_shared_kb", fresh_kb, raising=False)

    from app.main import app
    client = TestClient(app)

    # Post a new KB via legacy route
    payload = {
        "Elsbeth": {
            "show_title": "Elsbeth",
            "tmdb_id": 1399,
            "characters": [{"source": "Elsbeth", "target": "艾", "notes": ""}],
            "places": [], "brands": [], "slang": [],
            "style_notes": {"tone": "", "perspective": "", "rules": []},
        }
    }
    r = client.post("/api/knowledge", json=payload)
    assert r.status_code == 200

    # Translator's shared KB should now see "Elsbeth"
    proj = tmod._shared_kb.get_project("Elsbeth")
    assert proj is not None
    assert proj.show_title == "Elsbeth"
    assert proj.tmdb_id == 1399
