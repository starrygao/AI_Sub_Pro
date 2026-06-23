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


def _isolate_kb(tmp_project_dir, monkeypatch):
    from app.engines import knowledge as kb_mod

    monkeypatch.setattr(kb_mod, "KB_FILE", tmp_project_dir / "knowledge.json")
    kb_mod._reset_singleton()
    try:
        import app.engines.translator as tmod
        monkeypatch.setattr(tmod, "_shared_kb", kb_mod.KnowledgeBase(), raising=False)
    except ImportError:
        pass


def _seed_subtitle_project(tmp_project_dir, pid="subkb01"):
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nOliver Wolf visits Hudson Oaks.\n\n",
        encoding="utf-8",
    )
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "Brilliant Minds S02E15 translation",
        "show_title": "Brilliant Minds",
        "video_path": None,
        "source_type": "subtitle",
        "status": "created",
        "selected_audio_track": 0,
        "audio_tracks": [],
        "target_language": "简体中文",
        "asr_skipped": True,
        "cast": [{"name": "Oliver Wolf"}],
    }), encoding="utf-8")
    return pid


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


def test_start_translate_generates_kb_suggestions_without_blocking_by_default(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    _isolate_kb(tmp_project_dir, monkeypatch)
    client = _client(tmp_project_dir, monkeypatch)
    _allow_translation(monkeypatch)
    pid = _seed_subtitle_project(tmp_project_dir)

    class DummyThread:
        def start(self):
            pass

    monkeypatch.setattr(translate_api, "try_register_task", lambda *args, **kwargs: DummyThread())

    r = client.post(f"/api/projects/{pid}/start-translate", json={"target_language": "English"})

    assert r.status_code == 200
    assert r.json()["status"] == "started"
    saved = json.loads((tmp_project_dir / pid / "kb_suggestions.json").read_text(encoding="utf-8"))
    sources = {item["source"] for item in saved["suggestions"]}
    assert {"Brilliant Minds", "Oliver Wolf"} <= sources


def test_start_translate_treats_kb_suggestions_as_soft_hints(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    _isolate_kb(tmp_project_dir, monkeypatch)
    client = _client(tmp_project_dir, monkeypatch)
    _allow_translation(monkeypatch)
    pid = _seed_subtitle_project(tmp_project_dir)
    monkeypatch.setattr(
        translate_api.Config,
        "to_dict",
        lambda: {"translation": {"require_kb_suggestion_review": True}},
    )

    class DummyThread:
        def start(self):
            pass

    monkeypatch.setattr(translate_api, "try_register_task", lambda *args, **kwargs: DummyThread())

    r = client.post(f"/api/projects/{pid}/start-translate", json={"target_language": "English"})

    assert r.status_code == 200
    assert r.json()["status"] == "started"
    saved = json.loads((tmp_project_dir / pid / "kb_suggestions.json").read_text(encoding="utf-8"))
    assert len(saved["suggestions"]) > 0


def test_start_translate_professional_mode_generates_suggestions_without_blocking(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    _isolate_kb(tmp_project_dir, monkeypatch)
    client = _client(tmp_project_dir, monkeypatch)
    _allow_translation(monkeypatch)
    pid = _seed_subtitle_project(tmp_project_dir)
    monkeypatch.setattr(
        translate_api.Config,
        "to_dict",
        lambda: {"translation": {"quality_mode": "professional"}},
    )

    class DummyThread:
        def start(self):
            pass

    monkeypatch.setattr(translate_api, "try_register_task", lambda *args, **kwargs: DummyThread())

    r = client.post(f"/api/projects/{pid}/start-translate", json={"target_language": "English"})

    assert r.status_code == 200
    assert r.json()["status"] == "started"
    saved = json.loads((tmp_project_dir / pid / "kb_suggestions.json").read_text(encoding="utf-8"))
    assert len(saved["suggestions"]) > 0


def test_start_translate_keeps_running_when_kb_suggestions_are_rejected(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    _isolate_kb(tmp_project_dir, monkeypatch)
    client = _client(tmp_project_dir, monkeypatch)
    _allow_translation(monkeypatch)
    pid = _seed_subtitle_project(tmp_project_dir, pid="subkb02")
    monkeypatch.setattr(
        translate_api.Config,
        "to_dict",
        lambda: {"translation": {"require_kb_suggestion_review": True}},
    )

    class DummyThread:
        def start(self):
            pass

    monkeypatch.setattr(translate_api, "try_register_task", lambda *args, **kwargs: DummyThread())
    first = client.post(f"/api/projects/{pid}/start-translate", json={"target_language": "English"})
    assert first.status_code == 200

    saved = json.loads((tmp_project_dir / pid / "kb_suggestions.json").read_text(encoding="utf-8"))
    sources = [item["source"] for item in saved["suggestions"]]
    (tmp_project_dir / pid / "kb_suggestion_decisions.json").write_text(
        json.dumps({"rejected_sources": sources}),
        encoding="utf-8",
    )

    r = client.post(f"/api/projects/{pid}/start-translate", json={"target_language": "English"})

    assert r.status_code == 200
    assert r.json()["status"] == "started"


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


def test_start_full_translate_only_dispatches_without_burn_and_persists_mode(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    client = _client(tmp_project_dir, monkeypatch)
    _allow_translation(monkeypatch)
    pid = _seed_project(tmp_project_dir)
    pfile = tmp_project_dir / pid / "project.json"
    launched = {}

    class DummyThread:
        def __init__(self, target=None, args=()):
            self.target = target
            self.args = args

        def start(self):
            launched["target"] = self.target
            launched["args"] = self.args

    monkeypatch.setattr(translate_api.threading, "Thread", lambda target, args=(), daemon=True: DummyThread(target, args))
    monkeypatch.setattr(translate_api, "try_register_task", lambda pid_, factory, **kwargs: factory())

    r = client.post(f"/api/projects/{pid}/start-full", json={
        "language": "ja",
        "target_language": "English",
        "workflow_mode": "translate_only",
    })

    assert r.status_code == 200
    assert r.json()["stage"] == "asr_translate"
    assert launched["target"] is translate_api._run_asr_translate_pipeline
    assert launched["args"] == (pid, 0, "ja", "English")
    saved = json.loads(pfile.read_text(encoding="utf-8"))
    assert saved["workflow_mode"] == "translate_only"
    assert saved["asr_language"] == "ja"
    assert saved["target_language"] == "English"


def test_start_full_dispatches_audio_and_subtitle_sources_to_supported_workflows(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    _allow_translation(monkeypatch)
    launched = {}

    class DummyThread:
        def __init__(self, target=None, args=()):
            self.target = target
            self.args = args

        def start(self):
            launched.setdefault("started", []).append((self.target, self.args))

    def fake_register(pid, factory, **kwargs):
        launched.setdefault("pids", []).append(pid)
        return factory()

    monkeypatch.setattr(translate_api, "try_register_task", fake_register)
    monkeypatch.setattr(translate_api.threading, "Thread", lambda target, args=(), daemon=True: DummyThread(target, args))
    client = _client(tmp_project_dir, monkeypatch)

    audio_pid = "audfull1"
    audio_dir = tmp_project_dir / audio_pid
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "original.mp3").write_bytes(b"audio")
    (audio_dir / "project.json").write_text(json.dumps({
        "id": audio_pid,
        "name": "audio.mp3",
        "video_path": str(audio_dir / "original.mp3"),
        "source_type": "audio",
        "status": "created",
        "selected_audio_track": 0,
        "audio_tracks": [{"index": 0, "codec": "mp3"}],
        "target_language": "简体中文",
    }), encoding="utf-8")

    r = client.post(
        f"/api/projects/{audio_pid}/start-full",
        json={"language": "en", "target_language": "English"},
    )

    assert r.status_code == 200
    assert r.json()["stage"] == "asr_translate"
    assert launched["started"][-1] == (translate_api._run_asr_translate_pipeline, (audio_pid, 0, "en", "English"))

    subtitle_pid = "subfull1"
    subtitle_dir = tmp_project_dir / subtitle_pid
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    (subtitle_dir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )
    (subtitle_dir / "project.json").write_text(json.dumps({
        "id": subtitle_pid,
        "name": "lecture.srt",
        "video_path": None,
        "source_type": "subtitle",
        "status": "created",
        "selected_audio_track": 0,
        "audio_tracks": [],
        "target_language": "简体中文",
        "asr_skipped": True,
    }), encoding="utf-8")

    r = client.post(
        f"/api/projects/{subtitle_pid}/start-full",
        json={"language": "en", "target_language": "Japanese"},
    )

    assert r.status_code == 200
    assert r.json()["stage"] == "translate"
    assert launched["started"][-1] == (translate_api._run_translate_pipeline, (subtitle_pid, "Japanese"))


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


def test_start_burn_rejects_projects_without_video_burn_stage(tmp_project_dir, monkeypatch):
    client = _client(tmp_project_dir, monkeypatch)

    for pid, source_type, video_path in (
        ("audnoburn", "audio", str(tmp_project_dir / "audnoburn" / "original.mp3")),
        ("subnoburn", "subtitle", None),
    ):
        pdir = tmp_project_dir / pid
        pdir.mkdir(parents=True, exist_ok=True)
        if video_path:
            (pdir / "original.mp3").write_bytes(b"audio")
        (pdir / "translated.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n你好\n\n",
            encoding="utf-8",
        )
        (pdir / "project.json").write_text(json.dumps({
            "id": pid,
            "name": pid,
            "video_path": video_path,
            "source_type": source_type,
            "status": "translated",
            "selected_audio_track": 0,
            "audio_tracks": [{"index": 0, "codec": "mp3"}] if source_type == "audio" else [],
            "target_language": "简体中文",
        }), encoding="utf-8")

        r = client.post(f"/api/projects/{pid}/burn")

        assert r.status_code == 400
        assert "burn" in r.json()["detail"].lower()


def test_resume_audio_project_with_translated_srt_does_not_launch_burn(tmp_project_dir, monkeypatch):
    from app.api import translate as translate_api

    _allow_translation(monkeypatch)
    launched = {}

    class DummyThread:
        def __init__(self, target=None, args=()):
            self.target = target
            self.args = args

        def start(self):
            launched["target"] = self.target
            launched["args"] = self.args

    def fake_register(pid, factory, **kwargs):
        launched["pid"] = pid
        return factory()

    monkeypatch.setattr(translate_api, "try_register_task", fake_register)
    monkeypatch.setattr(translate_api.threading, "Thread", lambda target, args, daemon: DummyThread(target, args))

    client = _client(tmp_project_dir, monkeypatch)
    pid = "audresume"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "original.mp3").write_bytes(b"audio")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n你好\n\n",
        encoding="utf-8",
    )
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "audio.mp3",
        "video_path": str(pdir / "original.mp3"),
        "source_type": "audio",
        "status": "translated",
        "selected_audio_track": 0,
        "audio_tracks": [{"index": 0, "codec": "mp3"}],
        "target_language": "简体中文",
    }), encoding="utf-8")

    r = client.post(f"/api/projects/{pid}/resume")

    assert r.status_code == 200
    assert r.json()["stage"] == "translate"
    assert launched["target"] is translate_api._run_translate_pipeline
    assert launched["args"] == (pid, "简体中文")


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
