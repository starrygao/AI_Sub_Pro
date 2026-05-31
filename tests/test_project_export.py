import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.utils import project_store

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    from app.main import app
    return TestClient(app)


def _seed_project(tmp_project_dir, pid="exp123"):
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n你好\n",
        encoding="utf-8",
    )
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "translated",
    }), encoding="utf-8")
    return pid


def test_export_rejects_unknown_format(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)

    r = client.post(f"/api/projects/{pid}/export?format=zip")

    assert r.status_code == 400
    assert "format" in r.json()["detail"]


def test_export_uses_project_id_when_name_is_missing(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    project.pop("name")
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/export?format=translated")

    assert r.status_code == 200
    assert r.json()["filename"] == f"{pid}.translated.srt"


def test_export_sanitizes_project_name_for_filename(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    project["name"] = "../bad\nmovie"
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/export?format=translated")

    assert r.status_code == 200
    filename = r.json()["filename"]
    assert filename == "bad_movie.translated.srt"
    assert "/" not in filename
    assert "\\" not in filename
    assert "\n" not in filename


def test_export_treats_srt_directories_as_unavailable(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "translated.srt").unlink()
    (pdir / "translated.srt").mkdir()

    r = client.post(f"/api/projects/{pid}/export?format=translated")

    assert r.status_code == 404
    assert "subtitle" in r.json()["detail"].lower()


def test_export_replaces_invalid_utf8_bytes(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "translated.srt").write_bytes(
        b"1\n00:00:00,000 --> 00:00:01,000\nhello \xff\n"
    )

    r = client.post(f"/api/projects/{pid}/export?format=translated")

    assert r.status_code == 200
    assert "hello" in r.json()["content"]
    assert "\ufffd" in r.json()["content"]


def test_export_original_prefers_filtered_editable_timeline(client, tmp_project_dir):
    pid = _seed_project(tmp_project_dir)
    pdir = tmp_project_dir / pid
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nRaw original\n\n",
        encoding="utf-8",
    )
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nFiltered editable\n\n",
        encoding="utf-8",
    )

    r = client.post(f"/api/projects/{pid}/export?format=original")

    assert r.status_code == 200
    assert "Filtered editable" in r.json()["content"]
    assert "Raw original" not in r.json()["content"]
