import json

import pytest
from fastapi.testclient import TestClient


def _client(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.utils import project_store

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    from app.main import app
    return TestClient(app)


@pytest.fixture
def client(tmp_project_dir, monkeypatch):
    return _client(tmp_project_dir, monkeypatch)


def test_import_subtitle_creates_translatable_project(client, tmp_project_dir):
    srt = (
        "1\n"
        "00:00:00,000 --> 00:00:01,200\n"
        "Hello world.\n\n"
        "2\n"
        "00:00:01,500 --> 00:00:03,000\n"
        "Machine learning lecture.\n\n"
    )

    r = client.post(
        "/api/projects/import-subtitle",
        data={"target_language": "English", "original_language": "en"},
        files={"file": ("Stanford.CS229.Lecture.srt", srt.encode("utf-8"), "application/x-subrip")},
    )

    assert r.status_code == 200
    project = r.json()
    pid = project["id"]
    pdir = tmp_project_dir / pid
    saved = json.loads((pdir / "project.json").read_text(encoding="utf-8"))

    assert project["source_type"] == "subtitle"
    assert project["video_path"] is None
    assert project["name"] == "Stanford.CS229.Lecture.srt"
    assert project["target_language"] == "English"
    assert project["original_language"] == "en"
    assert project["source_has_subtitles"] is True
    assert project["subtitle_source"] == "uploaded"
    assert project["asr_skipped"] is True
    assert saved["source_type"] == "subtitle"
    assert "Hello world." in (pdir / "raw.srt").read_text(encoding="utf-8")
    assert "Machine learning lecture." in (pdir / "filtered.srt").read_text(encoding="utf-8")

    subtitles = client.get(f"/api/projects/{pid}/subtitles")
    assert subtitles.status_code == 200
    assert subtitles.json()["source"] == "filtered.srt"
    assert len(subtitles.json()["blocks"]) == 2


def test_import_subtitle_accepts_webvtt_and_writes_editable_srt(client, tmp_project_dir):
    vtt = (
        "WEBVTT\n\n"
        "intro\n"
        "00:00:00.000 --> 00:00:01.200 align:start\n"
        "Hello VTT.\n\n"
        "00:00:01.500 --> 00:00:03.000\n"
        "Machine learning lecture.\n\n"
    )

    r = client.post(
        "/api/projects/import-subtitle",
        data={"target_language": "English", "original_language": "en"},
        files={"file": ("Stanford.CS229.Lecture.vtt", vtt.encode("utf-8"), "text/vtt")},
    )

    assert r.status_code == 200
    project = r.json()
    pid = project["id"]
    pdir = tmp_project_dir / pid
    raw = (pdir / "raw.srt").read_text(encoding="utf-8")

    assert project["source_type"] == "subtitle"
    assert project["name"] == "Stanford.CS229.Lecture.vtt"
    assert project["subtitle_source"] == "uploaded_vtt"
    assert "00:00:00,000 --> 00:00:01,200" in raw
    assert "Hello VTT." in raw

    subtitles = client.get(f"/api/projects/{pid}/subtitles")
    assert subtitles.status_code == 200
    assert len(subtitles.json()["blocks"]) == 2


def test_import_subtitle_accepts_ass_and_writes_editable_srt(client, tmp_project_dir):
    ass = (
        "[Script Info]\n"
        "Title: Lecture overlay\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.50,0:00:01.70,Default,,0,0,0,,{\\an8}Hello ASS.\\NNext line.\n"
        "Dialogue: 0,0:00:02.00,0:00:03.25,Default,,0,0,0,,Machine learning, lecture.\n"
    )

    r = client.post(
        "/api/projects/import-subtitle",
        data={"target_language": "English", "original_language": "en"},
        files={"file": ("Stanford.CS229.Lecture.ass", ass.encode("utf-8"), "text/x-ass")},
    )

    assert r.status_code == 200
    project = r.json()
    pid = project["id"]
    pdir = tmp_project_dir / pid
    raw = (pdir / "raw.srt").read_text(encoding="utf-8")

    assert project["source_type"] == "subtitle"
    assert project["name"] == "Stanford.CS229.Lecture.ass"
    assert project["subtitle_source"] == "uploaded_ass"
    assert "00:00:00,500 --> 00:00:01,700" in raw
    assert "Hello ASS. Next line." in raw
    assert "Machine learning, lecture." in raw

    subtitles = client.get(f"/api/projects/{pid}/subtitles")
    assert subtitles.status_code == 200
    assert len(subtitles.json()["blocks"]) == 2


def test_import_subtitle_rejects_non_srt_extension(client):
    r = client.post(
        "/api/projects/import-subtitle",
        files={"file": ("notes.txt", b"not a subtitle", "text/plain")},
    )

    assert r.status_code == 400
    assert "subtitle" in r.json()["detail"].lower()


def test_import_subtitle_rejects_empty_or_unparseable_srt(client):
    r = client.post(
        "/api/projects/import-subtitle",
        files={"file": ("empty.srt", b"not a valid subtitle", "application/x-subrip")},
    )

    assert r.status_code == 400
    assert "valid subtitle" in r.json()["detail"]


def test_start_translate_accepts_subtitle_only_project(tmp_project_dir, monkeypatch):
    from app.services import translation_tasks as translate_api
    from app.utils import project_store

    monkeypatch.setattr(translate_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(
        translate_api,
        "require_translation_ready",
        lambda: {"translation_ready": True, "translation_hint": "已配置"},
    )

    class DummyThread:
        def start(self):
            pass

    monkeypatch.setattr(translate_api, "try_register_task", lambda *args, **kwargs: DummyThread())
    client = _client(tmp_project_dir, monkeypatch)
    pid = "subonly1"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "lecture.srt",
        "video_path": None,
        "source_type": "subtitle",
        "status": "created",
        "target_language": "简体中文",
        "source_has_subtitles": True,
        "subtitle_source": "uploaded",
        "asr_skipped": True,
    }), encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/start-translate", json={"target_language": "English"})

    assert r.status_code == 200
    saved = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert saved["target_language"] == "English"
