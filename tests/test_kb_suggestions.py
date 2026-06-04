import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_project_dir, monkeypatch):
    from app.api import knowledge as knowledge_api
    from app.api import projects as projects_api
    from app.utils import project_store

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(knowledge_api, "PROJECTS_DIR", tmp_project_dir, raising=False)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    from app.main import app
    return TestClient(app)


def test_extract_suggestions_finds_places_and_people():
    from app.engines.kb_suggestions import extract_kb_suggestions

    project = {
        "name": "Brilliant Minds S02E15",
        "show_title": "Brilliant Minds",
        "cast": ["Dr. Pierce", "Oliver Wolf"],
    }
    blocks = [
        {"index": 1, "text": "Hudson Oaks is giving resort vibes."},
        {"index": 2, "text": "I need to go to Hudson Oaks to save Sofia."},
        {"index": 3, "text": "Shoot your shot, Dr. Pierce."},
        {"index": 4, "text": "The patient is waiting."},
    ]

    suggestions = extract_kb_suggestions(project, blocks)
    by_source = {s.source: s for s in suggestions}

    assert by_source["Hudson Oaks"].type == "place"
    assert by_source["Hudson Oaks"].target == "哈德逊奥克斯"
    assert by_source["Dr. Pierce"].type in {"person", "character"}
    assert "The" not in by_source
    assert "I" not in by_source


def test_extract_suggestions_marks_existing_collisions():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.kb_suggestions import extract_kb_suggestions

    existing = ProjectKb(
        places=[TermEntry(source="Hudson Oaks", target="哈德森橡树")]
    )

    suggestions = extract_kb_suggestions(
        {"name": "Show"},
        [{"index": 1, "text": "We are going to Hudson Oaks."}],
        existing_kb=existing,
    )

    hudson = next(s for s in suggestions if s.source == "Hudson Oaks")
    assert hudson.collision == "source_exists"
    assert hudson.status == "pending"


def test_suggestions_round_trip_and_status_updates(tmp_path):
    from app.engines.kb_suggestions import (
        KbSuggestion,
        load_suggestions,
        save_suggestions,
        update_suggestion_status,
    )

    path = tmp_path / "kb_suggestions.json"
    save_suggestions(path, [
        KbSuggestion(
            id="place:hudson-oaks",
            type="place",
            source="Hudson Oaks",
            target="哈德逊奥克斯",
            confidence=0.8,
            evidence=["subtitle:1"],
        )
    ])

    loaded = load_suggestions(path)
    assert loaded[0].source == "Hudson Oaks"
    assert loaded[0].status == "pending"

    updated = update_suggestion_status(path, "place:hudson-oaks", "accepted")
    assert updated.status == "accepted"
    assert json.loads(path.read_text(encoding="utf-8"))["suggestions"][0]["status"] == "accepted"


def test_project_suggestion_api_generates_and_updates(client, tmp_project_dir):
    pid = "suggest1"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "Brilliant Minds S02E15",
        "status": "asr_done",
        "video_path": "/fake/video.mkv",
        "show_title": "Brilliant Minds",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHudson Oaks is quiet.\n\n",
        encoding="utf-8",
    )

    response = client.post(f"/api/knowledge/projects/{pid}/suggestions/generate")
    assert response.status_code == 200
    body = response.json()
    assert any(item["source"] == "Hudson Oaks" for item in body["suggestions"])

    suggestion_id = next(item["id"] for item in body["suggestions"] if item["source"] == "Hudson Oaks")
    response = client.post(
        f"/api/knowledge/projects/{pid}/suggestions/{suggestion_id}/status",
        json={"status": "rejected"},
    )
    assert response.status_code == 200
    assert response.json()["suggestion"]["status"] == "rejected"
