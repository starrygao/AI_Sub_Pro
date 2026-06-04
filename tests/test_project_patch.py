"""Tests for PATCH /api/projects/{pid}: whitelisted partial updates,
including the prefer_embedded_subtitle toggle and TMDB relink fields."""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_SUB_PRO_DATA_DIR", str(tmp_path))
    # Patch the loaded PROJECTS_DIR
    from app import config
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    (tmp_path / "projects").mkdir()
    # Re-import modules that captured PROJECTS_DIR at import time
    from app.api import projects
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path / "projects")
    # project_store binds PROJECTS_DIR at import time; patch its copy too
    from app.utils import project_store
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path / "projects")

    from app.main import app
    return TestClient(app)


def _make_project(client, name="movie.mkv"):
    """Create a minimal project on disk by writing project.json directly,
    bypassing the create_project endpoint (which requires a real video file)."""
    from app.api import projects
    pid = "abc12345"
    pdir = projects.PROJECTS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)
    project = {
        "id": pid,
        "name": name,
        "video_path": "/fake/movie.mkv",
        "status": "created",
        "selected_audio_track": 0,
        "selected_subtitle_track": 0,
        "prefer_embedded_subtitle": True,
        "subtitle_tracks": [{"index": 2, "codec": "subrip", "lang": "eng",
                             "title": "", "channels": 0, "sample_rate": ""},
                            {"index": 3, "codec": "ass", "lang": "jpn",
                             "title": "", "channels": 0, "sample_rate": ""}],
        "audio_tracks": [{"index": 0, "codec": "aac", "lang": "eng"}],
        "asr_language": "auto",
        "target_language": "简体中文",
    }
    (pdir / "project.json").write_text(json.dumps(project, ensure_ascii=False))
    return pid


def test_patch_prefer_embedded_subtitle_off(client):
    pid = _make_project(client)
    r = client.patch(f"/api/projects/{pid}",
                     json={"prefer_embedded_subtitle": False})
    assert r.status_code == 200
    assert r.json()["prefer_embedded_subtitle"] is False

    # Verify persisted
    g = client.get(f"/api/projects/{pid}")
    assert g.json()["prefer_embedded_subtitle"] is False


def test_workflow_state_endpoint_returns_project_state(client):
    from app.engines.workflow_state import load_workflow_state, start_stage

    pid = _make_project(client)
    start_stage(pid, "asr", input_artifact="movie.mkv")

    r = client.get(f"/api/projects/{pid}/workflow-state")

    assert r.status_code == 200
    assert r.json() == load_workflow_state(pid)


def test_workflow_log_endpoint_downloads_stage_log(client):
    from app.engines.workflow_state import append_stage_log

    pid = _make_project(client)
    append_stage_log(pid, "asr", "正在识别")

    r = client.get(f"/api/projects/{pid}/logs/asr")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert f'filename="{pid}-asr.log"' in r.headers["content-disposition"]
    assert "正在识别" in r.content.decode("utf-8")


def test_workflow_log_endpoint_rejects_invalid_stage(client):
    pid = _make_project(client)

    r = client.get(f"/api/projects/{pid}/logs/not-a-stage")

    assert r.status_code == 400
    assert "stage" in r.json()["detail"]


def test_workflow_log_endpoint_rejects_symlinked_log_directory(client, tmp_path):
    from app.api import projects

    pid = _make_project(client)
    outside = tmp_path / "outside-logs"
    outside.mkdir()
    outside_secret = "outside log content must not be exposed"
    (outside / "asr.log").write_text(outside_secret, encoding="utf-8")
    (projects.PROJECTS_DIR / pid / "workflow_logs").symlink_to(
        outside,
        target_is_directory=True,
    )

    r = client.get(f"/api/projects/{pid}/logs/asr")

    assert r.status_code == 400
    assert outside_secret not in r.text


def test_workflow_log_endpoint_returns_404_when_log_missing(client):
    pid = _make_project(client)

    r = client.get(f"/api/projects/{pid}/logs/asr")

    assert r.status_code == 404
    assert "log" in r.json()["detail"].lower()


def test_patch_selected_subtitle_track(client):
    pid = _make_project(client)
    r = client.patch(f"/api/projects/{pid}",
                     json={"selected_subtitle_track": 1})
    assert r.status_code == 200
    assert r.json()["selected_subtitle_track"] == 1


def test_patch_tmdb_relink(client):
    pid = _make_project(client)
    r = client.patch(f"/api/projects/{pid}", json={
        "tmdb_id": 12345,
        "tmdb_type": "movie",
        "season_number": None,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["tmdb_id"] == 12345
    assert body["tmdb_type"] == "movie"


def test_patch_rejects_invalid_tmdb_type(client):
    pid = _make_project(client)

    r = client.patch(f"/api/projects/{pid}", json={"tmdb_type": "book"})

    assert r.status_code == 400
    assert "tmdb_type" in r.json()["detail"]


def test_patch_rejects_non_positive_tmdb_id(client):
    pid = _make_project(client)

    r = client.patch(f"/api/projects/{pid}", json={"tmdb_id": 0})

    assert r.status_code == 400
    assert "tmdb_id" in r.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"tmdb_id": True},
    {"selected_subtitle_track": True},
])
def test_patch_rejects_boolean_integer_fields(client, payload):
    pid = _make_project(client)

    r = client.patch(f"/api/projects/{pid}", json=payload)

    assert r.status_code == 422


def test_patch_rejects_blank_name(client):
    pid = _make_project(client)

    r = client.patch(f"/api/projects/{pid}", json={"name": "   "})

    assert r.status_code == 400
    assert "name" in r.json()["detail"]


def test_patch_rejects_out_of_range_subtitle_track(client):
    pid = _make_project(client)

    r = client.patch(f"/api/projects/{pid}", json={"selected_subtitle_track": 9})

    assert r.status_code == 400
    assert "selected_subtitle_track" in r.json()["detail"]


def test_patch_rejects_negative_audio_track(client):
    pid = _make_project(client)

    r = client.patch(f"/api/projects/{pid}", json={"selected_audio_track": -1})

    assert r.status_code == 400
    assert "selected_audio_track" in r.json()["detail"]


def test_patch_clear_unlinks_tmdb(client):
    pid = _make_project(client)
    # First, link
    client.patch(f"/api/projects/{pid}", json={"tmdb_id": 999, "tmdb_type": "tv"})
    # Then, clear
    r = client.patch(f"/api/projects/{pid}",
                     json={"clear": ["tmdb_id", "tmdb_type"]})
    assert r.status_code == 200
    body = r.json()
    assert body["tmdb_id"] is None
    assert body["tmdb_type"] is None


def test_patch_clear_ignores_non_nullable_project_fields(client):
    pid = _make_project(client)

    r = client.patch(f"/api/projects/{pid}", json={"clear": ["name", "archived"]})

    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "movie.mkv"
    assert body["archived"] is False


def test_patch_rejects_unknown_field(client):
    """Unknown fields must be silently dropped (not raise) so the API stays
    forward-compatible with future frontend changes."""
    pid = _make_project(client)
    r = client.patch(f"/api/projects/{pid}",
                     json={"status": "completed",  # not in patchable whitelist
                           "name": "renamed.mkv"})
    assert r.status_code == 200
    body = r.json()
    # name is patchable, status is not
    assert body["name"] == "renamed.mkv"
    assert body["status"] == "created"  # untouched


def test_patch_archived(client):
    pid = _make_project(client)
    r = client.patch(f"/api/projects/{pid}", json={"archived": True})
    assert r.status_code == 200
    assert r.json()["archived"] is True


def test_patch_invalid_project_json_returns_stable_error(client):
    from app.api import projects

    pid = "badjson1"
    pdir = projects.PROJECTS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text('{"duration": ' + ("9" * 5000) + "}", encoding="utf-8")

    r = client.patch(f"/api/projects/{pid}", json={"name": "renamed.mkv"})

    assert r.status_code == 400
    assert r.json()["detail"] == "Project file is invalid"


def test_patch_sanitizes_legacy_non_finite_unknown_fields_before_saving(client):
    from app.api import projects

    pid = _make_project(client)
    pdir = projects.PROJECTS_DIR / pid
    data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    data["legacy_extra"] = float("nan")
    (pdir / "project.json").write_text(json.dumps(data), encoding="utf-8")

    r = client.patch(f"/api/projects/{pid}", json={"name": "renamed.mkv"})

    assert r.status_code == 200
    saved = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert saved["legacy_extra"] is None
    assert saved["name"] == "renamed.mkv"


def test_list_projects_hides_archived_by_default(client):
    pid1 = _make_project(client, name="active.mkv")

    from app.api import projects
    pid2 = "arch1234"
    pdir = projects.PROJECTS_DIR / pid2
    pdir.mkdir(parents=True, exist_ok=True)
    archived = {
        "id": pid2,
        "name": "archived.mkv",
        "video_path": "/fake/archived.mkv",
        "status": "completed",
        "progress": 100,
        "archived": True,
    }
    (pdir / "project.json").write_text(json.dumps(archived, ensure_ascii=False))

    r = client.get("/api/projects")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert pid1 in ids
    assert pid2 not in ids

    r = client.get("/api/projects?include_archived=true")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert {pid1, pid2}.issubset(ids)


def test_list_projects_skips_symlinked_project_dirs(client):
    pid = _make_project(client, name="active.mkv")

    from app.api import projects
    link = projects.PROJECTS_DIR / "linkproj"
    link.symlink_to(projects.PROJECTS_DIR / pid, target_is_directory=True)

    r = client.get("/api/projects")

    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert ids.count(pid) == 1


def test_delete_missing_project_returns_404(client):
    r = client.delete("/api/projects/missing1")

    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


@pytest.mark.parametrize("project_updates", [
    {"status": "processing"},
    {"status": "created", "pipeline_stage": "download"},
])
def test_delete_rejects_processing_or_pipeline_project(client, project_updates):
    from app.api import projects

    pid = _make_project(client)
    pdir = projects.PROJECTS_DIR / pid
    data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    data.update(project_updates)
    (pdir / "project.json").write_text(json.dumps(data), encoding="utf-8")

    r = client.delete(f"/api/projects/{pid}")

    assert r.status_code == 409
    assert pdir.exists()
    assert "cancel" in r.json()["detail"]


def test_delete_rejects_registered_task_even_if_status_is_stale(client, monkeypatch):
    from app.api import projects, translate

    pid = _make_project(client)
    pdir = projects.PROJECTS_DIR / pid
    monkeypatch.setattr(translate, "active_tasks", {pid: object()})

    r = client.delete(f"/api/projects/{pid}")

    assert r.status_code == 409
    assert pdir.exists()


def test_delete_does_not_remove_internal_uploads_dir(client):
    from app.api import projects

    uploads = projects.PROJECTS_DIR / "_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    sentinel = uploads / "kept.mp4"
    sentinel.write_bytes(b"x")

    r = client.delete("/api/projects/_uploads")

    assert r.status_code == 404
    assert sentinel.exists()


def test_reveal_ignores_output_path_outside_project(client, tmp_path, monkeypatch):
    pid = _make_project(client)
    from app.api import projects

    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")
    pdir = projects.PROJECTS_DIR / pid
    data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    data["output_video"] = str(outside)
    (pdir / "project.json").write_text(json.dumps(data), encoding="utf-8")

    launched = {}
    monkeypatch.setattr("subprocess.Popen", lambda cmd: launched.setdefault("cmd", cmd))

    r = client.post(f"/api/projects/{pid}/reveal")

    assert r.status_code == 200
    assert r.json()["path"] == str(pdir)
    assert str(outside) not in launched["cmd"]


def test_reveal_resolves_relative_output_inside_project(client, monkeypatch):
    pid = _make_project(client)
    from app.api import projects

    pdir = projects.PROJECTS_DIR / pid
    output = pdir / "output.mp4"
    output.write_bytes(b"x")
    data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    data["output_video"] = "output.mp4"
    (pdir / "project.json").write_text(json.dumps(data), encoding="utf-8")

    launched = {}
    monkeypatch.setattr("subprocess.Popen", lambda cmd: launched.setdefault("cmd", cmd))

    r = client.post(f"/api/projects/{pid}/reveal")

    assert r.status_code == 200
    assert r.json()["path"] == str(output.resolve())
    assert str(output.resolve()) in launched["cmd"]


def test_reveal_uses_single_select_argument_on_windows(client, monkeypatch):
    pid = _make_project(client)
    from app.api import projects

    pdir = projects.PROJECTS_DIR / pid
    output = pdir / "output.mp4"
    output.write_bytes(b"x")
    data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    data["output_video"] = "output.mp4"
    (pdir / "project.json").write_text(json.dumps(data), encoding="utf-8")

    launched = {}
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("subprocess.Popen", lambda cmd: launched.setdefault("cmd", cmd))

    r = client.post(f"/api/projects/{pid}/reveal")

    assert r.status_code == 200
    assert launched["cmd"] == ["explorer", f"/select,{output.resolve()}"]


def test_tmdb_project_search_redacts_api_key_from_error(client, monkeypatch):
    pid = _make_project(client)

    async def boom(*args, **kwargs):
        raise RuntimeError(
            "GET https://api.themoviedb.org/3/search/movie?"
            "api_key=tmdb-secret-token&query=foo failed"
        )

    monkeypatch.setattr("app.engines.tmdb.search_movie", boom)

    r = client.post(f"/api/projects/{pid}/tmdb-search", json={
        "query": "foo",
        "type": "movie",
    })

    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "tmdb-secret-token" not in detail
    assert "api_key=<redacted>" in detail


def test_tmdb_project_search_rejects_invalid_type(client):
    pid = _make_project(client)

    r = client.post(f"/api/projects/{pid}/tmdb-search", json={
        "query": "foo",
        "type": "book",
    })

    assert r.status_code == 400
    assert "type" in r.json()["detail"]


def test_tmdb_project_search_rejects_empty_query(client):
    pid = _make_project(client)

    r = client.post(f"/api/projects/{pid}/tmdb-search", json={
        "query": "  ",
        "type": "movie",
    })

    assert r.status_code == 400
    assert "query" in r.json()["detail"]


def test_tmdb_project_search_drops_malformed_candidates(client, monkeypatch):
    pid = _make_project(client)

    async def fake_search(*args, **kwargs):
        return [
            {"title": "No ID"},
            {"id": 42, "original_title": "Fallback Title", "release_date": "2026-01-01"},
        ]

    monkeypatch.setattr("app.engines.tmdb.search_movie", fake_search)

    r = client.post(f"/api/projects/{pid}/tmdb-search", json={
        "query": "foo",
        "type": "movie",
    })

    assert r.status_code == 200
    assert [c["tmdb_id"] for c in r.json()["candidates"]] == [42]
    assert r.json()["candidates"][0]["title"] == "Fallback Title"


def test_tmdb_project_search_sanitizes_non_finite_candidate_values(client, monkeypatch):
    pid = _make_project(client)

    async def fake_search(*args, **kwargs):
        return [{
            "id": 42,
            "title": "Odd",
            "release_date": "2026-01-01",
            "vote_average": float("nan"),
        }]

    monkeypatch.setattr("app.engines.tmdb.search_movie", fake_search)

    r = client.post(f"/api/projects/{pid}/tmdb-search", json={
        "query": "foo",
        "type": "movie",
    })

    assert r.status_code == 200
    assert r.json()["candidates"][0]["vote_average"] is None
    assert client.get(f"/api/projects/{pid}").json()["tmdb_candidates"][0]["vote_average"] is None
