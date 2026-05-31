import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def patched_kb_file(tmp_path, monkeypatch):
    import app.config as cfg
    import app.engines.knowledge as kb_mod

    kb_file = tmp_path / "knowledge.json"
    monkeypatch.setattr(cfg, "KB_FILE", kb_file, raising=False)
    monkeypatch.setattr(kb_mod, "KB_FILE", kb_file)
    monkeypatch.setattr(kb_mod, "LEGACY_KB", tmp_path / "legacy.json", raising=False)

    # Reset module-level singleton in knowledge module
    monkeypatch.setattr(kb_mod, "_singleton", None, raising=False)

    # Replace translator's shared KB with a fresh instance pointing at the patched file
    try:
        import app.engines.translator as tmod
        monkeypatch.setattr(tmod, "_shared_kb", kb_mod.KnowledgeBase(), raising=False)
    except ImportError:
        pass

    # Replace API module's local KB if it has one
    try:
        import app.api.knowledge as kbapi
        monkeypatch.setattr(kbapi, "_kb", kb_mod.KnowledgeBase(), raising=False)
    except Exception:
        pass

    return kb_file


def test_kb_list_projects_empty(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    r = client.get("/api/knowledge/projects")
    assert r.status_code == 200
    assert r.json() == {"projects": []}


def test_kb_clean_text_rejects_non_string_values():
    from app.api.knowledge import _clean_text

    assert _clean_text(123) == ""
    assert _clean_text(None) == ""
    assert _clean_text("  ok  ") == "ok"


def test_kb_create_and_get_project(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    payload = {
        "key": "elsbeth",
        "show_title": "Elsbeth",
        "tmdb_id": 1399,
        "characters": [{"source": "Elsbeth Tascioni", "target": "艾尔斯贝丝"}],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "sharp legal humor", "perspective": "", "rules": []},
    }
    r = client.put("/api/knowledge/projects/elsbeth", json=payload)
    assert r.status_code in (200, 201)

    r = client.get("/api/knowledge/projects/elsbeth")
    assert r.status_code == 200
    data = r.json()
    assert data["show_title"] == "Elsbeth"
    assert data["characters"][0]["source"] == "Elsbeth Tascioni"


def test_kb_put_rejects_body_key_mismatch(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/path-key", json={
        "key": "body-key",
        "show_title": "Mismatch",
        "characters": [],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })

    assert r.status_code == 400
    assert "key" in r.json()["detail"]


def test_kb_put_rejects_blank_key(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/%20%20", json={
        "key": "  ",
        "show_title": "Blank",
        "characters": [],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })

    assert r.status_code == 400
    assert "key" in r.json()["detail"]


def test_kb_put_rejects_non_positive_tmdb_id(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/show", json={
        "key": "show",
        "show_title": "Show",
        "tmdb_id": 0,
        "characters": [],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })

    assert r.status_code == 400
    assert "tmdb_id" in r.json()["detail"]


def test_kb_put_rejects_boolean_tmdb_id(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/show", json={
        "key": "show",
        "show_title": "Show",
        "tmdb_id": True,
        "characters": [],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })

    assert r.status_code == 422


def test_kb_put_drops_blank_terms_and_rules(patched_kb_file):
    from app.main import app
    client = TestClient(app)

    r = client.put("/api/knowledge/projects/clean", json={
        "key": "clean",
        "show_title": " Clean Show ",
        "characters": [
            {"source": "", "target": "", "notes": ""},
            {"source": "  Name  ", "target": "  名字  ", "notes": " lead "},
            {"source": "NoTarget", "target": "", "notes": ""},
        ],
        "places": [],
        "brands": [],
        "slang": [],
        "style_notes": {"tone": "  witty  ", "perspective": "", "rules": ["", " keep jokes "]},
    })

    assert r.status_code == 200
    data = client.get("/api/knowledge/projects/clean").json()
    assert data["show_title"] == "Clean Show"
    assert data["characters"] == [{"source": "Name", "target": "名字", "notes": "lead"}]
    assert data["style_notes"]["tone"] == "witty"
    assert data["style_notes"]["rules"] == ["keep jokes"]


def test_kb_list_projects_after_put(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    client.put("/api/knowledge/projects/x", json={
        "key": "x", "show_title": "X-Show", "tmdb_id": 42,
        "characters": [], "places": [], "brands": [], "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })
    r = client.get("/api/knowledge/projects")
    assert r.status_code == 200
    projects = r.json()["projects"]
    assert len(projects) == 1
    assert projects[0]["key"] == "x"
    assert projects[0]["show_title"] == "X-Show"
    assert projects[0]["tmdb_id"] == 42


def test_kb_delete_project(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    client.put("/api/knowledge/projects/temp", json={
        "key": "temp", "show_title": "Temp",
        "characters": [], "places": [], "brands": [], "slang": [],
        "style_notes": {"tone": "", "perspective": "", "rules": []},
    })
    r = client.delete("/api/knowledge/projects/temp")
    assert r.status_code == 200

    r = client.get("/api/knowledge/projects/temp")
    assert r.status_code == 404


def test_kb_get_nonexistent_returns_404(patched_kb_file):
    from app.main import app
    client = TestClient(app)
    r = client.get("/api/knowledge/projects/nonexistent")
    assert r.status_code == 404


def test_kb_saved_upserts_preserve_existing_projects(patched_kb_file):
    from app.engines.knowledge import KnowledgeBase
    from app.engines.kb_models import ProjectKb

    kb = KnowledgeBase()
    kb.load()
    kb.put_project("one", ProjectKb(show_title="One"))
    kb.put_project("two", ProjectKb(show_title="Two"))

    reloaded = KnowledgeBase()
    reloaded.load()
    assert reloaded.get_project("one").show_title == "One"
    assert reloaded.get_project("two").show_title == "Two"
