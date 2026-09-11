import json

import pytest
from fastapi.testclient import TestClient


def _client(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.services import translation_tasks as translate_api
    from app.utils import project_store

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(translate_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(translate_api, "active_tasks", {})

    from app.main import app
    return TestClient(app)


@pytest.fixture
def client(tmp_project_dir, monkeypatch):
    return _client(tmp_project_dir, monkeypatch)


def test_import_audio_creates_asr_ready_project(client, tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api

    monkeypatch.setattr(
        projects_api,
        "get_tracks",
        lambda path, kind: [{"index": 0, "codec": "mp3", "lang": "eng"}] if kind == "a" else [],
    )
    monkeypatch.setattr(projects_api, "get_duration", lambda path: 42.2)

    r = client.post(
        "/api/projects/import-audio",
        data={"target_language": "简体中文", "original_language": "en"},
        files={"file": ("Interview Episode.mp3", b"audio bytes", "audio/mpeg")},
    )

    assert r.status_code == 200
    project = r.json()
    pid = project["id"]
    pdir = tmp_project_dir / pid
    saved = json.loads((pdir / "project.json").read_text(encoding="utf-8"))

    assert project["source_type"] == "audio"
    assert project["name"] == "Interview Episode.mp3"
    assert project["video_path"] == str(pdir / "original.mp3")
    assert project["audio_tracks"] == [{"index": 0, "codec": "mp3", "lang": "eng"}]
    assert project["subtitle_tracks"] == []
    assert project["duration"] == 42.2
    assert project["asr_language"] == "en"
    assert project["target_language"] == "简体中文"
    assert saved["source_type"] == "audio"
    assert (pdir / "original.mp3").read_bytes() == b"audio bytes"


def test_import_audio_rejects_non_audio_extension(client):
    r = client.post(
        "/api/projects/import-audio",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )

    assert r.status_code == 400
    assert "audio" in r.json()["detail"].lower()


def test_start_transcribe_translate_skips_burn_for_audio_project(tmp_project_dir, monkeypatch):
    from app.services import translation_tasks as translate_api
    from app.utils import project_store

    monkeypatch.setattr(translate_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(
        translate_api,
        "require_translation_ready",
        lambda: {"translation_ready": True, "translation_hint": "已配置"},
    )

    registered = {}

    class DummyThread:
        def __init__(self, target=None, args=()):
            self.target = target
            self.args = args

        def start(self):
            registered["target"] = self.target
            registered["args"] = self.args

    def fake_register(pid, factory, **kwargs):
        registered["pid"] = pid
        registered["reset_cancellation"] = kwargs.get("reset_cancellation")
        return factory()

    monkeypatch.setattr(translate_api, "try_register_task", fake_register)
    monkeypatch.setattr(translate_api.threading, "Thread", lambda target, args, daemon: DummyThread(target, args))

    client = _client(tmp_project_dir, monkeypatch)
    pid = "audflow1"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "original.mp3").write_bytes(b"audio")
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "audio.mp3",
        "video_path": str(pdir / "original.mp3"),
        "source_type": "audio",
        "status": "created",
        "selected_audio_track": 0,
        "audio_tracks": [{"index": 0, "codec": "mp3"}],
        "target_language": "简体中文",
    }), encoding="utf-8")

    r = client.post(
        f"/api/projects/{pid}/start-transcribe-translate",
        json={"language": "en", "target_language": "English"},
    )

    assert r.status_code == 200
    assert r.json()["stage"] == "asr_translate"
    assert registered["pid"] == pid
    assert registered["reset_cancellation"] is True
    assert registered["target"] is translate_api._run_asr_translate_pipeline
    assert registered["args"] == (pid, 0, "en", "English")
    saved = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert saved["asr_language"] == "en"
    assert saved["target_language"] == "English"
