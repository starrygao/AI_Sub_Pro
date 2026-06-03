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


def test_kb_suggestions_endpoint_returns_project_suggestions(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_suggest"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Moonlit Case",
        "tmdb_id": 101,
        "cast": ["Maya Chen"],
        "overview": "Maya Chen visits the Moonlit Club.",
    })
    (pdir / "raw.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nMaya Chen enters the Moonlit Club.\n\n",
        encoding="utf-8",
    )

    response = client.get(f"/api/knowledge/projects/{pid}/suggestions")

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == pid
    assert any(item["source"] == "Maya Chen" for item in data["suggestions"])


def test_kb_accept_suggestions_persists_entries(tmp_project_dir, patched_kb_file):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_accept"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "moonlit",
        "show_title": "Moonlit Case",
        "tmdb_id": 101,
        "entries": [
            {"source": "Maya Chen", "target": "玛雅·陈", "category": "characters", "notes": "lead"}
        ],
    })

    assert response.status_code == 200
    saved = client.get("/api/knowledge/projects/moonlit").json()
    assert saved["characters"][0]["source"] == "Maya Chen"
    assert saved["characters"][0]["target"] == "玛雅·陈"


def test_kb_reject_suggestions_persists_project_decision(tmp_project_dir, patched_kb_file):
    import json

    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_reject"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/reject", json={
        "sources": ["Noisy Phrase", "Unused Name"]
    })

    assert response.status_code == 200
    data = json.loads((pdir / "kb_suggestion_decisions.json").read_text(encoding="utf-8"))
    assert data["rejected_sources"] == ["Noisy Phrase", "Unused Name"]


def test_kb_accept_suggestions_skips_duplicate_blank_target_and_invalid_category(
    tmp_project_dir,
    patched_kb_file,
):
    from app.main import app
    from app.utils.project_store import atomic_write_json

    client = TestClient(app)
    pid = "project_accept_robust"
    pdir = tmp_project_dir / pid
    atomic_write_json(pdir / "project.json", {"id": pid, "name": "Moonlit Case", "tmdb_id": 101})
    client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "moonlit",
        "show_title": "Moonlit Case",
        "tmdb_id": 101,
        "entries": [
            {"source": "Maya Chen", "target": "玛雅·陈", "category": "characters", "notes": "lead"}
        ],
    })

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/accept", json={
        "key": "moonlit",
        "show_title": "Moonlit Case",
        "tmdb_id": 101,
        "entries": [
            {"source": " maya chen ", "target": "重复", "category": "characters", "notes": ""},
            {"source": "Moonlit Club", "target": "", "category": "places", "notes": ""},
            {"source": "Ignored", "target": "忽略", "category": "unknown", "notes": ""},
            {"source": "Moonlit Club", "target": "月光俱乐部", "category": "places", "notes": ""},
        ],
    })

    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    saved = client.get("/api/knowledge/projects/moonlit").json()
    assert saved["characters"] == [{"source": "Maya Chen", "target": "玛雅·陈", "notes": "lead"}]
    assert saved["places"] == [{"source": "Moonlit Club", "target": "月光俱乐部", "notes": ""}]


def test_kb_suggestions_endpoint_returns_404_for_missing_project(patched_kb_file):
    from app.main import app

    client = TestClient(app)

    response = client.get("/api/knowledge/projects/missing_project/suggestions")

    assert response.status_code == 404
