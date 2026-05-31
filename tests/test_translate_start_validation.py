import json

from fastapi import HTTPException
from fastapi.testclient import TestClient


def _client(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.api import translate as translate_api
    from app.utils import project_store

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(translate_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(translate_api, "active_tasks", {})

    from app.main import app
    return TestClient(app)


def _seed_project(tmp_project_dir, pid="audio01"):
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "created",
        "selected_audio_track": 0,
        "audio_tracks": [{"index": 0, "codec": "aac", "lang": "eng"}],
    }), encoding="utf-8")
    return pid


def _allow_translation(monkeypatch):
    from app.api import translate as translate_api
    monkeypatch.setattr(
        translate_api,
        "require_translation_ready",
        lambda: {"translation_ready": True, "translation_hint": "已配置"},
    )


def test_start_asr_rejects_invalid_audio_track(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = _seed_project(tmp_project_dir)

    r = client.post(f"/api/projects/{pid}/start-asr", json={"audio_track": -1})

    assert r.status_code == 400
    assert "audio_track" in r.json()["detail"]


def test_start_asr_rejects_boolean_audio_track(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = _seed_project(tmp_project_dir)
    pfile = tmp_project_dir / pid / "project.json"
    data = json.loads(pfile.read_text(encoding="utf-8"))
    data["audio_tracks"].append({"index": 1, "codec": "aac", "lang": "jpn"})
    pfile.write_text(json.dumps(data), encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/start-asr", json={"audio_track": True})

    assert r.status_code == 422


def test_start_full_rejects_out_of_range_audio_track(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = _seed_project(tmp_project_dir)

    r = client.post(f"/api/projects/{pid}/start-full", json={"audio_track": 3})

    assert r.status_code == 400
    assert "audio_track" in r.json()["detail"]


def test_start_asr_rejects_blank_language(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = _seed_project(tmp_project_dir)

    r = client.post(f"/api/projects/{pid}/start-asr", json={"language": "   "})

    assert r.status_code == 400
    assert "language" in r.json()["detail"]


def test_start_translate_rejects_blank_target_language(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = _seed_project(tmp_project_dir)

    r = client.post(f"/api/projects/{pid}/start-translate", json={"target_language": "   "})

    assert r.status_code == 400
    assert "target_language" in r.json()["detail"]


def test_translation_dependent_starts_reject_missing_provider_before_launch(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    client = _client(tmp_project_dir, monkeypatch)

    def fail_ready():
        raise HTTPException(status_code=400, detail="请配置 OpenAI API 密钥")

    def fail_register(*args, **kwargs):
        raise AssertionError("task should not be registered when translation is not ready")

    monkeypatch.setattr(translate_api, "require_translation_ready", fail_ready)
    monkeypatch.setattr(translate_api, "try_register_task", fail_register)

    for pid, endpoint in (("miss01", "start-translate"), ("miss02", "start-full")):
        _seed_project(tmp_project_dir, pid=pid)
        r = client.post(f"/api/projects/{pid}/{endpoint}", json={"target_language": "English"})
        assert r.status_code == 400
        assert "OpenAI" in r.json()["detail"]

    assert translate_api.active_tasks == {}


def test_start_full_persists_requested_workflow_options_before_launch(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    client = _client(tmp_project_dir, monkeypatch)
    _allow_translation(monkeypatch)
    pid = _seed_project(tmp_project_dir)
    pfile = tmp_project_dir / pid / "project.json"
    project = json.loads(pfile.read_text(encoding="utf-8"))
    project["audio_tracks"].append({"index": 1, "codec": "aac", "lang": "jpn"})
    pfile.write_text(json.dumps(project), encoding="utf-8")

    class DummyThread:
        def start(self):
            pass

    monkeypatch.setattr(translate_api, "try_register_task", lambda *args, **kwargs: DummyThread())

    r = client.post(f"/api/projects/{pid}/start-full", json={
        "audio_track": 1,
        "language": "ja",
        "target_language": "English",
    })

    assert r.status_code == 200
    saved = json.loads(pfile.read_text(encoding="utf-8"))
    assert saved["selected_audio_track"] == 1
    assert saved["asr_language"] == "ja"
    assert saved["target_language"] == "English"


def test_start_translate_persists_requested_target_language_before_launch(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    client = _client(tmp_project_dir, monkeypatch)
    _allow_translation(monkeypatch)
    pid = _seed_project(tmp_project_dir)
    pfile = tmp_project_dir / pid / "project.json"

    class DummyThread:
        def start(self):
            pass

    monkeypatch.setattr(translate_api, "try_register_task", lambda *args, **kwargs: DummyThread())

    r = client.post(f"/api/projects/{pid}/start-translate", json={"target_language": "Japanese"})

    assert r.status_code == 200
    saved = json.loads(pfile.read_text(encoding="utf-8"))
    assert saved["target_language"] == "Japanese"


def test_start_asr_persists_requested_language_and_audio_track_before_launch(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    client = _client(tmp_project_dir, monkeypatch)
    pid = _seed_project(tmp_project_dir)
    pfile = tmp_project_dir / pid / "project.json"
    project = json.loads(pfile.read_text(encoding="utf-8"))
    project["audio_tracks"].append({"index": 1, "codec": "aac", "lang": "jpn"})
    pfile.write_text(json.dumps(project), encoding="utf-8")

    class DummyThread:
        def start(self):
            pass

    monkeypatch.setattr(translate_api, "try_register_task", lambda *args, **kwargs: DummyThread())

    r = client.post(f"/api/projects/{pid}/start-asr", json={"audio_track": 1, "language": "ja"})

    assert r.status_code == 200
    saved = json.loads(pfile.read_text(encoding="utf-8"))
    assert saved["selected_audio_track"] == 1
    assert saved["asr_language"] == "ja"


def test_manual_start_rejects_project_with_active_pipeline_stage(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = _seed_project(tmp_project_dir)
    pfile = tmp_project_dir / pid / "project.json"
    data = json.loads(pfile.read_text(encoding="utf-8"))
    data["pipeline_stage"] = "download"
    pfile.write_text(json.dumps(data), encoding="utf-8")

    for endpoint in ("start-asr", "start-translate", "start-full", "burn"):
        r = client.post(f"/api/projects/{pid}/{endpoint}", json={})
        assert r.status_code == 409
        assert "running" in r.json()["detail"]


def test_manual_start_rejects_project_with_processing_status(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = _seed_project(tmp_project_dir)
    pfile = tmp_project_dir / pid / "project.json"
    data = json.loads(pfile.read_text(encoding="utf-8"))
    data["status"] = "processing"
    pfile.write_text(json.dumps(data), encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/start-full", json={})

    assert r.status_code == 409
    assert "running" in r.json()["detail"]


def test_resolve_text_option_ignores_non_string_legacy_fallback():
    from app.api.translate import _resolve_text_option

    assert _resolve_text_option(None, ["bad"], "auto", "language") == "auto"
    assert _resolve_text_option(None, {"bad": "value"}, "简体中文", "target_language") == "简体中文"


def test_asr_runtime_config_coercion_rejects_dirty_values():
    from app.api.translate import _coerce_bool_option, _coerce_int_option, _coerce_str_option

    assert _coerce_bool_option("yes", True) is True
    assert _coerce_bool_option(False, True) is False
    assert _coerce_int_option(True, 5, minimum=1, maximum=20) == 5
    assert _coerce_int_option(float("inf"), 5, minimum=1, maximum=20) == 5
    assert _coerce_int_option(10 ** 1000, 5, minimum=1, maximum=20) == 5
    assert _coerce_int_option("30", 5, minimum=1, maximum=20) == 20
    assert _coerce_str_option(["bad"], "auto") == "auto"
    assert _coerce_str_option(" zh ", "auto") == "zh"


def test_start_asr_rejects_non_object_project_file(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = "badshape"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(json.dumps(["bad"]), encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/start-asr", json={})

    assert r.status_code == 400
    assert r.json()["detail"] == "Project file is invalid"


def test_start_asr_rejects_corrupt_project_file(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = "badjson"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text("{", encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/start-asr", json={})

    assert r.status_code == 400
    assert r.json()["detail"] == "Project file is invalid"


def test_start_asr_rejects_project_file_with_overlong_json_number(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)
    pid = "longnum"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(
        '{"id":"longnum","name":"bad","video_path":"/fake.mp4","status":"created","duration":'
        + ("1" * 5000)
        + "}",
        encoding="utf-8",
    )

    r = client.post(f"/api/projects/{pid}/start-asr", json={})

    assert r.status_code == 400
    assert r.json()["detail"] == "Project file is invalid"
