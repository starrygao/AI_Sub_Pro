import json

from fastapi.testclient import TestClient


def _client_with_projects_dir(tmp_project_dir, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg, "PROJECTS_DIR", tmp_project_dir)

    from app.main import app
    return TestClient(app)


def test_download_video_missing_project_returns_404(tmp_project_dir, monkeypatch):
    client = _client_with_projects_dir(tmp_project_dir, monkeypatch)

    r = client.get("/api/projects/miss1234/download-video")

    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


def test_download_video_without_output_returns_404(tmp_project_dir, monkeypatch):
    client = _client_with_projects_dir(tmp_project_dir, monkeypatch)
    pid = "abc12345"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "status": "translated",
        "output_video": None,
    }))

    r = client.get(f"/api/projects/{pid}/download-video")

    assert r.status_code == 404
    assert "No output video" in r.json()["detail"]


def test_download_video_returns_file_when_output_exists(tmp_project_dir, monkeypatch):
    client = _client_with_projects_dir(tmp_project_dir, monkeypatch)
    pid = "abc12345"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    output = pdir / "output.mp4"
    output.write_bytes(b"fake video")
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "status": "completed",
        "output_video": str(output),
    }))

    r = client.get(f"/api/projects/{pid}/download-video")

    assert r.status_code == 200
    assert r.content == b"fake video"
    assert "output.mp4" in r.headers["content-disposition"]


def test_download_video_resolves_relative_output_inside_project(tmp_project_dir, monkeypatch):
    client = _client_with_projects_dir(tmp_project_dir, monkeypatch)
    pid = "abc12345"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    output = pdir / "output.mp4"
    output.write_bytes(b"fake video")
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "status": "completed",
        "output_video": "output.mp4",
    }))

    r = client.get(f"/api/projects/{pid}/download-video")

    assert r.status_code == 200
    assert r.content == b"fake video"


def test_download_video_rejects_output_path_outside_project(tmp_project_dir, monkeypatch, tmp_path):
    client = _client_with_projects_dir(tmp_project_dir, monkeypatch)
    pid = "abc12345"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"not a project output")
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "status": "completed",
        "output_video": str(secret),
    }))

    r = client.get(f"/api/projects/{pid}/download-video")

    assert r.status_code == 404
    assert "No output video" in r.json()["detail"]


def test_download_video_rejects_symlinked_project_dir(tmp_project_dir, monkeypatch):
    client = _client_with_projects_dir(tmp_project_dir, monkeypatch)
    target = tmp_project_dir / "target01"
    target.mkdir()
    output = target / "output.mp4"
    output.write_bytes(b"fake video")
    (target / "project.json").write_text(json.dumps({
        "id": "linkproj",
        "name": "movie",
        "status": "completed",
        "output_video": "output.mp4",
    }))
    (tmp_project_dir / "linkproj").symlink_to(target, target_is_directory=True)

    r = client.get("/api/projects/linkproj/download-video")

    assert r.status_code == 400
    assert "Invalid project id" in r.json()["detail"]


def test_download_video_rejects_corrupt_project_json(tmp_project_dir, monkeypatch):
    client = _client_with_projects_dir(tmp_project_dir, monkeypatch)
    pid = "abc12345"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text("{not json", encoding="utf-8")

    r = client.get(f"/api/projects/{pid}/download-video")

    assert r.status_code == 400
    assert "Project file is invalid" in r.json()["detail"]


def test_download_video_rejects_non_object_project_json(tmp_project_dir, monkeypatch):
    client = _client_with_projects_dir(tmp_project_dir, monkeypatch)
    pid = "abc12345"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    r = client.get(f"/api/projects/{pid}/download-video")

    assert r.status_code == 400
    assert "Project file is invalid" in r.json()["detail"]
