from unittest.mock import patch
import json
from datetime import timedelta

from fastapi.testclient import TestClient


def test_start_asr_initializes_workflow_state(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.api import translate as api_translate
    from app.utils import project_store
    from app.main import app

    pid = "asrstate1"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "created",
        "selected_audio_track": 0,
        "audio_tracks": [{"index": 0, "codec": "aac", "lang": "eng"}],
    }), encoding="utf-8")

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "active_tasks", {})

    class DummyThread:
        started = False

        def start(self):
            self.started = True

    dummy = DummyThread()
    monkeypatch.setattr(api_translate, "try_register_task", lambda *args, **kwargs: dummy)

    response = TestClient(app).post(f"/api/projects/{pid}/start-asr", json={})

    assert response.status_code == 200
    assert dummy.started is True
    state = json.loads((pdir / "workflow_state.json").read_text(encoding="utf-8"))
    assert set(state["stages"]) == {"asr"}
    assert state["stages"]["asr"]["status"] == "pending"


def test_retry_rejects_active_task(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.api import translate as api_translate
    from app.utils import project_store
    from app.main import app

    pid = "retrybusy"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "error",
        "pipeline_stage": None,
    }), encoding="utf-8")

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "is_task_registered", lambda task_pid: task_pid == pid)

    response = TestClient(app).post(f"/api/projects/{pid}/retry", json={"stage": "asr"})

    assert response.status_code == 409


def test_retry_blank_stage_falls_back_to_latest_failed(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.api import translate as api_translate
    from app.engines.workflow_state import fail_stage, reset_workflow
    from app.utils import project_store
    from app.main import app

    pid = "retryblank"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "error",
        "pipeline_stage": None,
        "target_language": "Japanese",
    }), encoding="utf-8")
    reset_workflow(pid, ["asr", "translate"])
    fail_stage(pid, "translate", RuntimeError("translator failed"))

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "active_tasks", {})
    monkeypatch.setattr(api_translate, "require_translation_ready", lambda: None)

    class DummyThread:
        started = False

        def start(self):
            self.started = True

    dummy = DummyThread()
    monkeypatch.setattr(api_translate, "try_register_task", lambda *args, **kwargs: dummy)

    response = TestClient(app).post(f"/api/projects/{pid}/retry", json={"stage": "   "})

    assert response.status_code == 200
    assert response.json()["stage"] == "translate"
    assert dummy.started is True


def test_resume_chooses_translate_when_filtered_srt_exists(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.api import translate as api_translate
    from app.utils import project_store
    from app.main import app

    pid = "resumetrans"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "error",
        "pipeline_stage": None,
        "target_language": "Japanese",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "active_tasks", {})
    monkeypatch.setattr(api_translate, "require_translation_ready", lambda: None)

    class DummyThread:
        started = False

        def start(self):
            self.started = True

    dummy = DummyThread()
    monkeypatch.setattr(api_translate, "try_register_task", lambda *args, **kwargs: dummy)

    response = TestClient(app).post(f"/api/projects/{pid}/resume")

    assert response.status_code == 200
    assert response.json()["stage"] == "translate"
    assert dummy.started is True


def test_resume_ignores_translated_srt_directory(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.api import translate as api_translate
    from app.utils import project_store
    from app.main import app

    pid = "resumedir"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "error",
        "pipeline_stage": None,
    }), encoding="utf-8")
    (pdir / "translated.srt").mkdir()

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "active_tasks", {})

    class DummyThread:
        started = False

        def start(self):
            self.started = True

    dummy = DummyThread()
    monkeypatch.setattr(api_translate, "try_register_task", lambda *args, **kwargs: dummy)

    response = TestClient(app).post(f"/api/projects/{pid}/resume")

    assert response.status_code == 200
    assert response.json()["stage"] == "asr"
    assert dummy.started is True


def test_resume_ignores_raw_srt_symlink_outside_project(tmp_project_dir, monkeypatch):
    from app.api import projects as projects_api
    from app.api import translate as api_translate
    from app.utils import project_store
    from app.main import app

    pid = "resumesymlink"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "error",
        "pipeline_stage": None,
        "target_language": "Japanese",
    }), encoding="utf-8")
    outside = tmp_project_dir.parent / "outside.srt"
    outside.write_text("1\n00:00:00,000 --> 00:00:01,000\nOutside\n\n", encoding="utf-8")
    (pdir / "raw.srt").symlink_to(outside)

    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(api_translate, "active_tasks", {})
    monkeypatch.setattr(api_translate, "require_translation_ready", lambda: None)

    class DummyThread:
        started = False

        def start(self):
            self.started = True

    dummy = DummyThread()
    monkeypatch.setattr(api_translate, "try_register_task", lambda *args, **kwargs: dummy)

    response = TestClient(app).post(f"/api/projects/{pid}/resume")

    assert response.status_code == 200
    assert response.json()["stage"] == "asr"
    assert dummy.started is True


def test_build_bilingual_tracks_skips_symlinked_generated_zh_output(tmp_project_dir, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "tracksymlink"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n你好\n\n",
        encoding="utf-8",
    )
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )
    outside = tmp_project_dir.parent / "outside-zh.srt"
    outside.write_text("keep me\n", encoding="utf-8")
    (pdir / "zh.srt").symlink_to(outside)

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    tracks = api_translate._build_bilingual_tracks(pid)

    assert outside.read_text(encoding="utf-8") == "keep me\n"
    track_paths = {track.path for track in tracks}
    assert str(pdir / "zh.srt") not in track_paths
    assert str(pdir / "en.srt") in track_paths
    assert (pdir / "en.srt").is_file()
    assert not (pdir / "en.srt").is_symlink()


def test_build_bilingual_tracks_generates_regular_project_local_tracks(tmp_project_dir, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "trackregular"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True)
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n你好\n\n",
        encoding="utf-8",
    )
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    tracks = api_translate._build_bilingual_tracks(pid)

    pdir_resolved = pdir.resolve()
    track_paths = [track.path for track in tracks]
    assert track_paths == [str(pdir / "zh.srt"), str(pdir / "en.srt")]
    for track_path in track_paths:
        path = pdir / (track_path.rsplit("/", 1)[-1])
        assert path.is_file()
        assert not path.is_symlink()
        assert path.resolve().is_relative_to(pdir_resolved)


def test_reset_workflow_for_action_preserves_retry_count(tmp_project_dir):
    from app.api import translate as api_translate
    from app.engines.workflow_state import fail_stage, load_workflow_state, reset_workflow

    pid = "retrykeep"
    reset_workflow(pid, ["translate"])
    fail_stage(pid, "translate", RuntimeError("first failure"))
    fail_stage(pid, "translate", RuntimeError("second failure"))

    api_translate._reset_workflow_for_action(pid, "translate")

    state = load_workflow_state(pid)
    stage = state["stages"]["translate"]
    assert stage["status"] == "pending"
    assert stage["started_at"] is None
    assert stage["finished_at"] is None
    assert stage["error_summary"] == ""
    assert stage["retry_count"] == 2


def test_emit_progress_routes_through_scheduler():
    """_emit_progress must delegate to scheduler.update_progress (single source of truth).

    Patch the local alias bound at import time, not the source symbol — translate.py does
    ``from app.engines.scheduler import update_progress as _scheduler_update_progress``
    so patching the origin doesn't rebind already-imported callers.
    """
    from app.api import translate as api_translate
    with patch.object(api_translate, "_scheduler_update_progress") as mock_update:
        api_translate._emit_progress("pidx", stage="asr", local_pct=10, msg="m")
    mock_update.assert_called_once_with("pidx", stage="asr", local_pct=10, msg="m")


def test_translate_module_reexports_scheduler_progress_store():
    """Compatibility import must still expose scheduler's progress_store."""
    from app.api.translate import progress_store as from_translate
    from app.engines.scheduler import progress_store as from_scheduler
    assert from_translate is from_scheduler


def test_translate_pipeline_ignores_malformed_filter_entries_per_block(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "trans001"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "tmdb_id": 123,
        "tmdb_type": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
    }), encoding="utf-8")
    (pdir / "raw.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nWorld\n\n",
        encoding="utf-8",
    )
    (pdir / "filter_state.json").write_text(json.dumps({
        "1": "bad-entry",
        "2": {"filtered": True, "reason": "music"},
    }), encoding="utf-8")

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    seen = {}

    class FakeTranslator:
        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            seen["meta_info"] = meta_info
            for block in blocks:
                if not block.filtered:
                    block.translation = f"zh-{block.index}"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"
    assert project["translated_srt"] == str(pdir / "translated.srt")
    assert project["bilingual_srt"] == str(pdir / "bilingual.srt")
    assert seen["meta_info"]["name"] == "movie"
    assert seen["meta_info"]["tmdb_id"] == 123
    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    assert "zh-1" in translated
    assert "zh-2" not in translated


def test_translate_pipeline_does_not_apply_stale_filter_state_to_filtered_srt(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "trans004"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nWorld\n\n",
        encoding="utf-8",
    )
    (pdir / "filter_state.json").write_text(json.dumps({
        "2": {"filtered": True, "reason": "old raw index"},
    }), encoding="utf-8")

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakeTranslator:
        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            for block in blocks:
                if not block.filtered:
                    block.translation = f"zh-{block.index}"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    assert "zh-1" in translated
    assert "zh-2" in translated


def test_translate_pipeline_tolerates_malformed_progress_callback_values(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "trans002"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakeTranslator:
        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            if callback:
                callback(float("inf"), {"bad": "shape"})
            blocks[0].translation = "你好"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"


def test_translate_pipeline_writes_quality_report(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transqa"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nAre you okay?\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "你好"
            blocks[1].translation = "Are you okay?"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"
    assert report["status"] == "ok"
    assert report["summary"]["by_type"]["english_residue"] == 1
    assert report["summary"]["quality_gate"]["passed"] is True
    assert (pdir / "translation_qa_report.md").exists()


def test_translate_pipeline_marks_contextual_background_speakers(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "contextspeaker"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nANNOUNCER: Welcome to trivia night.\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nNIKKI: I need air.\n\n"
        "3\n00:00:06,000 --> 00:00:08,000\nON TV: Breaking news.\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {"qa_auto_repair": False},
    })

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "欢迎来到问答之夜。"
            blocks[1].translation = "我需要透透气。"
            blocks[2].translation = "突发新闻。"
            return blocks

        def get_kb_usage_trace(self):
            return {"project": {}, "matches": []}

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    assert project["status"] == "translated"
    assert "【主持人】欢迎来到问答之夜。" in translated
    assert "我需要透透气。" in translated
    assert "【电视】突发新闻。" in translated
    marked = report["trace"]["deterministic_postprocess"]["contextual_speaker_marked_blocks"]
    assert [(item["id"], item["marker"]) for item in marked] == [
        (1, "【主持人】"),
        (3, "【电视】"),
    ]


def test_full_pipeline_stops_before_burn_when_quality_gate_fails(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "fullqagate"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "created",
        "target_language": "简体中文",
        "original_language": "en",
        "manual_terms": "Hello=你好",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {"qa_auto_repair": False},
    })
    monkeypatch.setattr(api_translate, "_ensure_kb_review_ready", lambda *args, **kwargs: None)

    def fake_asr(pid_, audio_track, language, owns_registration=True):
        api_translate.mutate_project(
            pid_,
            lambda p: p.update({"status": "asr_done", "error": None}),
            normalize=api_translate._apply_safe_defaults,
        )

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "Hello"
            return blocks

    burn_called = []
    monkeypatch.setattr(api_translate, "_run_asr_pipeline", fake_asr)
    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)
    monkeypatch.setattr(api_translate, "_run_burn_pipeline", lambda pid_: burn_called.append(pid_))

    api_translate._run_full_pipeline(pid, 0, "auto", "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    assert burn_called == []
    assert project["status"] == "error"
    assert "翻译质量未达标" in project["error"]
    assert project["translation_quality_status"] == "failed"
    assert "翻译质量未达标" in project["progress_msg"]
    assert api_translate._resume_stage_for_project(pid, project) == "translate"
    assert report["summary"]["quality_gate"]["passed"] is False
    assert report["summary"]["quality_gate"]["requires_human_review"] is False
    assert not (pdir / "translated.srt").exists()
    assert not (pdir / "bilingual.srt").exists()
    assert (pdir / "partial_translated.srt").exists()
    assert (pdir / "partial_bilingual.srt").exists()


def test_translate_done_message_ignores_blank_sound_descriptions(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transsound"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\n[ Dramatic music plays ]\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})
    progress_messages = []
    monkeypatch.setattr(
        api_translate,
        "_emit_progress",
        lambda pid, stage, pct, msg: progress_messages.append((stage, pct, msg)),
    )

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "你好"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    assert progress_messages[-1] == ("translate", 100, "翻译完成: 1 条")
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"
    assert project["progress"] == 100
    assert project["progress_msg"] == "翻译完成: 1 条"
    assert project["pipeline_stage"] is None


def test_translate_pipeline_marks_partial_translation_as_error(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transpartial"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
        "translated_srt": str(pdir / "translated.srt"),
        "bilingual_srt": str(pdir / "bilingual.srt"),
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nWorld\n\n",
        encoding="utf-8",
    )
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n旧译文\n\n",
        encoding="utf-8",
    )
    (pdir / "bilingual.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n旧译文\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "你好"
            return blocks

        def get_kb_usage_trace(self):
            return {"project": {}, "matches": []}

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    state = json.loads((pdir / "workflow_state.json").read_text(encoding="utf-8"))
    assert project["status"] == "error"
    assert project["translated_srt"] is None
    assert project["bilingual_srt"] is None
    assert "翻译未完成: 1/2 条成功，1 条缺失" in project["error"]
    assert state["stages"]["translate"]["status"] == "failed"
    assert not (pdir / "translated.srt").exists()
    assert not (pdir / "bilingual.srt").exists()
    assert (pdir / "partial_translated.srt").exists()
    assert (pdir / "partial_bilingual.srt").exists()
    assert (pdir / "translation_qa_report.json").exists()


def test_translate_pipeline_blocks_export_when_cleaned_translation_is_empty(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transexportempty"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello.\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {"qa_auto_repair": False},
    })

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "♪"
            return blocks

        def get_kb_usage_trace(self):
            return {"project": {}, "matches": []}

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "error"
    assert "翻译导出不完整" in project["error"]
    assert project["translated_srt"] is None
    assert project["bilingual_srt"] is None
    assert not (pdir / "translated.srt").exists()
    assert not (pdir / "bilingual.srt").exists()
    assert (pdir / "partial_translated.srt").exists()
    assert (pdir / "partial_bilingual.srt").exists()


def test_translate_pipeline_professional_semantic_mismatch_blocks_delivery(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transsemanticbad"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello.\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nBear, what does that mean?\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {
            "quality_mode": "professional",
            "qa_auto_repair": False,
            "semantic_qa": True,
            "semantic_qa_batch_size": 10,
        },
    })

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            assert "字幕语义质检员" in system_prompt
            return [
                {"id": 1, "translation": "OK"},
                {"id": 2, "translation": "MISMATCH: 译文与原文问题含义不对应"},
            ]

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "你好。"
            blocks[1].translation = "你车呢？"
            return blocks

        def get_kb_usage_trace(self):
            return {"project": {}, "matches": []}

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    assert project["status"] == "error"
    assert project["translation_quality_status"] == "failed"
    assert "翻译质量未达标" in project["error"]
    assert report["summary"]["by_type"]["semantic_mismatch"] == 1
    assert report["issues"][0]["severity"] == "error"
    assert report["summary"]["quality_gate"]["passed"] is False
    assert report["summary"]["quality_gate"]["requires_human_review"] is False
    assert not (pdir / "translated.srt").exists()
    assert not (pdir / "bilingual.srt").exists()
    assert (pdir / "partial_translated.srt").exists()


def test_professional_semantic_uncertainty_requires_human_review():
    from app.api.translate import (
        _finalize_quality_conclusion,
        _refresh_quality_report_issue_summary,
        _run_semantic_quality_checks,
    )
    from app.engines.translation_qa import TranslationQaReport

    blocks = [
        type("Block", (), {
            "index": 7,
            "text": "Maybe he left.",
            "translation": "也许他走了。",
            "filtered": False,
        })(),
    ]

    class Primary:
        def translate_batch(self, items, prompt):
            return [{"id": 7, "translation": "UNCERTAIN: 指代信息不足"}]

    translator = type("Translator", (), {"primary": Primary()})()
    issues, trace = _run_semantic_quality_checks(
        {
            "translation": {
                "quality_mode": "professional",
                "semantic_qa": True,
            },
        },
        translator,
        blocks,
        "简体中文",
        strict_quality_gate=True,
    )
    report = TranslationQaReport(status="ok", issues=issues, trace={"semantic_qa": trace})
    _refresh_quality_report_issue_summary(report)
    _finalize_quality_conclusion(
        report,
        [],
        False,
        strict_quality_gate=True,
    )

    assert trace["requested_block_ids"] == [7]
    assert trace["checked_block_ids"] == [7]
    assert trace["failed_block_ids"] == []
    assert trace["skipped_block_ids"] == []
    assert report.summary["quality_gate"]["passed"] is False
    assert report.summary["quality_gate"]["verdict"] == "needs_review"
    assert report.summary["quality_gate"]["requires_human_review"] is True
    assert report.summary["quality_gate"]["delivery_mode"] == "human_review"
    assert report.unresolved_blocks == [7]
    assert report.summary["quality_gate"]["unresolved_blocks"] == 1


def test_professional_semantic_provider_unavailable_fails_closed():
    from app.api.translate import _run_semantic_quality_checks

    blocks = [
        type("Block", (), {
            "index": 3,
            "text": "Hello.",
            "translation": "你好。",
            "filtered": False,
        })(),
    ]
    issues, trace = _run_semantic_quality_checks(
        {
            "translation": {
                "quality_mode": "professional",
                "semantic_qa": False,
            },
        },
        object(),
        blocks,
        "简体中文",
        strict_quality_gate=True,
    )

    assert [(issue.type, issue.severity, issue.block_id) for issue in issues] == [
        ("semantic_qa_failed", "error", 3),
    ]
    assert trace["requested_block_ids"] == [3]
    assert trace["checked_block_ids"] == []
    assert trace["failed_block_ids"] == []
    assert trace["skipped_block_ids"] == [3]
    assert trace["coverage_complete"] is False


def test_professional_semantic_batch_failure_tracks_failed_ids():
    from app.api.translate import _run_semantic_quality_checks

    blocks = [
        type("Block", (), {
            "index": block_id,
            "text": f"Source {block_id}",
            "translation": f"译文 {block_id}",
            "filtered": False,
        })()
        for block_id in (1, 2)
    ]

    class Primary:
        def translate_batch(self, items, prompt):
            raise RuntimeError("provider unavailable")

    translator = type("Translator", (), {"primary": Primary()})()
    issues, trace = _run_semantic_quality_checks(
        {"translation": {"quality_mode": "professional", "semantic_qa": True}},
        translator,
        blocks,
        "简体中文",
        strict_quality_gate=True,
    )

    assert {issue.block_id for issue in issues} == {1, 2}
    assert all(issue.type == "semantic_qa_failed" for issue in issues)
    assert trace["requested_block_ids"] == [1, 2]
    assert trace["checked_block_ids"] == []
    assert trace["failed_block_ids"] == [1, 2]
    assert trace["skipped_block_ids"] == []
    assert trace["coverage_complete"] is False


def test_professional_semantic_partial_coverage_fails_closed():
    from app.api.translate import _run_semantic_quality_checks

    blocks = [
        type("Block", (), {
            "index": block_id,
            "text": f"Source {block_id}",
            "translation": f"译文 {block_id}",
            "filtered": False,
        })()
        for block_id in (10, 11)
    ]

    class Primary:
        def translate_batch(self, items, prompt):
            return [{"id": 10, "translation": "OK"}]

    translator = type("Translator", (), {"primary": Primary()})()
    issues, trace = _run_semantic_quality_checks(
        {
            "translation": {
                "quality_mode": "professional",
                "semantic_qa": True,
                "semantic_qa_max_blocks": 1,
            },
        },
        translator,
        blocks,
        "简体中文",
        strict_quality_gate=True,
    )

    assert [(issue.type, issue.severity, issue.block_id) for issue in issues] == [
        ("semantic_qa_failed", "error", 11),
    ]
    assert trace["requested_block_ids"] == [10, 11]
    assert trace["checked_block_ids"] == [10]
    assert trace["failed_block_ids"] == []
    assert trace["skipped_block_ids"] == [11]
    assert trace["coverage_complete"] is False


def test_quality_gate_rejects_stale_or_hash_mismatched_report(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "staleqareport"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    report = {
        "run_id": "old-run",
        "content_hash": "sha256:old",
        "status": "ok",
        "issues": [],
        "summary": {
            "conclusion": "达标：自动检查通过。",
            "quality_gate": {"passed": True},
        },
    }
    (pdir / "translation_qa_report.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)

    passed, message = api_translate._translation_quality_gate_status(
        pid,
        expected_run_id="new-run",
        expected_content_hash="sha256:old",
    )
    assert passed is False
    assert "已过期" in message

    passed, message = api_translate._translation_quality_gate_status(
        pid,
        expected_run_id="old-run",
        expected_content_hash="sha256:new",
    )
    assert passed is False
    assert "内容不匹配" in message


def test_translation_start_invalidates_prior_certification(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "invalidateqa"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "translation_qa_report.json").write_text('{"status":"ok"}', encoding="utf-8")
    (pdir / "translation_qa_report.md").write_text("# old", encoding="utf-8")
    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)

    run_id = api_translate._begin_translation_quality_run(pid)

    assert isinstance(run_id, str) and run_id
    assert not (pdir / "translation_qa_report.json").exists()
    assert not (pdir / "translation_qa_report.md").exists()


def test_translate_pipeline_does_not_swallow_quality_report_persistence_failure(
    tmp_path,
    monkeypatch,
):
    from app.api import translate as api_translate
    from app.engines import translation_qa
    from app.utils import project_store

    pid = "qapersistfail"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello.\n\n",
        encoding="utf-8",
    )
    (pdir / "translation_qa_report.json").write_text(json.dumps({
        "run_id": "old-run",
        "content_hash": "sha256:old",
        "status": "ok",
        "issues": [],
        "summary": {"quality_gate": {"passed": True}},
    }), encoding="utf-8")

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {
            "quality_mode": "fast",
            "qa_auto_repair": False,
            "semantic_qa": False,
        },
    })

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            pass

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "你好。"
            return blocks

        def get_kb_usage_trace(self):
            return {"project": {}, "matches": []}

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)
    monkeypatch.setattr(
        translation_qa,
        "save_quality_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "error"
    assert "translation QA report failed" in project["error"]
    assert not (pdir / "translation_qa_report.json").exists()
    assert not (pdir / "translated.srt").exists()


def test_translate_pipeline_final_retry_repairs_missing_translation(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transfinalretry"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nWorld\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {
            "missing_translation_retries": 2,
            "missing_translation_retry_batch_size": 5,
        }
    })
    progress_messages = []
    monkeypatch.setattr(
        api_translate,
        "_emit_progress",
        lambda pid, stage, pct, msg: progress_messages.append((stage, pct, msg)),
    )

    class FakePrimary:
        def __init__(self):
            self.calls = []

        def translate_batch(self, items, system_prompt):
            self.calls.append([item["id"] for item in items])
            assert [item["id"] for item in items] == [2]
            assert "最终补翻要求" in system_prompt
            return [{"id": 2, "translation": "世界"}]

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "你好"
            return blocks

        def _build_prompt(self, target_lang, meta_info, kb_data, context_before, context_after, items=None):
            assert items == [{"id": 2, "original": "World"}]
            assert context_before == [{"original": "Hello", "translated": "你好"}]
            return "retry prompt"

        def get_kb_usage_trace(self):
            return {"project": {}, "matches": []}

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    assert project["status"] == "translated"
    assert project["error"] is None
    assert "你好" in translated
    assert "世界" in translated
    assert not (pdir / "partial_translated.srt").exists()
    assert any("全片补翻缺失" in msg for _, _, msg in progress_messages)


def test_translate_pipeline_skips_final_retry_when_missing_count_is_catastrophic(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transfinalretryhuge"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nOne\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nTwo\n\n"
        "3\n00:00:04,000 --> 00:00:05,000\nThree\n\n"
        "4\n00:00:06,000 --> 00:00:07,000\nFour\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {
            "missing_translation_retries": 2,
            "missing_translation_retry_batch_size": 1,
            "missing_translation_retry_max_blocks": 2,
            "qa_auto_repair": False,
            "semantic_qa": False,
        }
    })
    progress_messages = []
    monkeypatch.setattr(
        api_translate,
        "_emit_progress",
        lambda pid, stage, pct, msg: progress_messages.append((stage, pct, msg)),
    )

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            raise AssertionError("catastrophic final retry should be skipped")

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "一"
            return blocks

        def _build_prompt(self, target_lang, meta_info, kb_data, context_before, context_after, items=None):
            return "retry prompt"

        def get_kb_usage_trace(self):
            return {"project": {}, "matches": []}

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    partial = (pdir / "partial_translated.srt").read_text(encoding="utf-8")
    assert project["status"] == "error"
    assert "翻译未完成" in project["error"]
    assert "一" in partial
    assert not (pdir / "translated.srt").exists()
    assert any("全片缺译过多" in msg for _, _, msg in progress_messages)


def test_translate_pipeline_retries_missing_created_after_quality_repair(tmp_path, monkeypatch):
    from pathlib import Path

    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transpostqaretry"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:02,000 --> 00:00:03,000\nWorld\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {
            "missing_translation_retries": 2,
            "missing_translation_retry_batch_size": 5,
        }
    })
    progress_messages = []
    monkeypatch.setattr(
        api_translate,
        "_emit_progress",
        lambda pid, stage, pct, msg: progress_messages.append((stage, pct, msg)),
    )

    persist_calls = []

    def fake_persist(
        pid,
        pdir,
        project,
        blocks,
        target_language,
        translator,
        cfg,
        progress_callback=None,
        *,
        quality_run_id="",
        strict_quality_gate=False,
    ):
        from app.engines.translation_qa import quality_content_hash

        persist_calls.append([block.translation for block in blocks])
        if len(persist_calls) == 1:
            blocks[1].translation = ""
        report = {
            "run_id": quality_run_id,
            "content_hash": quality_content_hash(blocks),
            "status": "ok",
            "issues": [],
            "summary": {"quality_gate": {"passed": True}},
        }
        root = Path(pdir)
        (root / "translation_qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        (root / "translation_qa_report.md").write_text("# Translation QA Report\n", encoding="utf-8")
        return []

    monkeypatch.setattr(api_translate, "_persist_translation_quality_report", fake_persist)

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            assert [item["id"] for item in items] == [2]
            assert "最终补翻要求" in system_prompt
            return [{"id": 2, "translation": "世界"}]

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "你好"
            blocks[1].translation = "世界"
            return blocks

        def _build_prompt(self, target_lang, meta_info, kb_data, context_before, context_after, items=None):
            assert items == [{"id": 2, "original": "World"}]
            return "retry prompt"

        def get_kb_usage_trace(self):
            return {"project": {}, "matches": []}

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"
    assert "你好" in translated
    assert "世界" in translated
    assert len(persist_calls) == 2
    assert any("全片补翻缺失" in msg for _, _, msg in progress_messages)


def test_translate_pipeline_can_auto_repair_quality_issues(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transrepair"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nAre you okay?\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            assert len(items) == 1
            assert {
                "id": items[0]["id"],
                "original": items[0]["original"],
                "draft": items[0]["draft"],
            } == {"id": 1, "original": "Are you okay?", "draft": "Are you okay?"}
            assert "Are you okay?" in system_prompt
            return [{"id": 1, "translation": "你还好吗？"}]

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "Are you okay?"
            return blocks

        def _apply_results(self, blocks, results):
            for block in blocks:
                for result in results:
                    if str(result.get("id")) == str(block.index):
                        block.translation = result.get("translation", "")

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    assert "你还好吗？" in translated
    assert report["status"] == "ok"
    assert report["repaired_blocks"] == [{"id": 1, "translation": "你还好吗？"}]
    assert report["summary"]["quality_gate"]["passed"] is True
    assert report["summary"]["conclusion"] == "达标：已自动重点返工 1 条并复检通过。"


def test_translate_pipeline_auto_repair_preserves_omitted_rows(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.engines.translator import SubtitleTranslator
    from app.utils import project_store

    pid = "transrepairpartial"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "\n".join([
            "1",
            "00:00:00,000 --> 00:00:01,000",
            "Are you okay?",
            "",
            "2",
            "00:00:01,000 --> 00:00:02,000",
            "Hello there.",
            "",
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {"qa_auto_repair": True},
    })
    attempted_batches = []

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            attempted_batches.append([item["id"] for item in items])
            if [item["id"] for item in items] == [1, 2]:
                return [{"id": 1, "translation": "你还好吗？"}]
            return []

    class FakeTranslator:
        last_quality_trace = None
        _apply_one = staticmethod(SubtitleTranslator._apply_one)

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "Are you okay?"
            blocks[1].translation = "Hello there."
            return blocks

        def _apply_results(self, blocks, results):
            SubtitleTranslator._apply_results(self, blocks, results)

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    assert attempted_batches == [[1, 2], [2]]
    assert project["status"] == "translated"
    assert "你还好吗？" in translated
    assert "Hello there." in translated
    assert not (pdir / "partial_translated.srt").exists()
    assert report["repaired_blocks"] == [{"id": 1, "translation": "你还好吗？"}]
    assert report["summary"]["quality_gate"]["passed"] is True


def test_translate_pipeline_does_not_auto_repair_scientific_terms_without_expected(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transscientificnorepair"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "Surviving Earth S01E01",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "\n".join([
            "1",
            "00:00:00,000 --> 00:00:04,000",
            "Novaraptor grazes nearby.",
            "",
            "2",
            "00:00:04,000 --> 00:00:08,000",
            "A young Novaraptor calls.",
            "",
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {"qa_auto_repair": True},
    })

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            raise AssertionError("scientific terms without expected should not auto-repair")

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "诺瓦盗龙在附近觅食。"
            blocks[1].translation = "幼年诺法猛禽在呼唤。"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    assert report["summary"]["by_type"]["scientific_term_inconsistent"] == 2
    assert report["repaired_blocks"] == []
    rounds = report["trace"]["auto_repair_rounds"]
    assert rounds[0]["candidate_blocks"] == 0
    assert rounds[0]["result"] == "no_repair_applied"


def test_translate_pipeline_normalizes_curated_scientific_terms_before_model_repair(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transscientificcuratedrepair"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "Surviving Earth S01E01",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "\n".join([
            "1",
            "00:00:00,000 --> 00:00:04,000",
            "Ischigualastia grazes nearby.",
            "",
            "2",
            "00:00:04,000 --> 00:00:08,000",
            "A young Ischigualastia calls.",
            "",
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {"qa_auto_repair": True},
    })

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            raise AssertionError("safe curated term variants should normalize before model repair")

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "伊斯基瓜拉斯兽在附近觅食。"
            blocks[1].translation = "幼年伊斯基瓜拉兽在呼唤。"
            return blocks

        def _apply_results(self, blocks, results):
            for block in blocks:
                for result in results:
                    if str(result.get("id")) == str(block.index):
                        block.translation = result.get("translation", "")

        def get_kb_usage_trace(self):
            return {"project": {}, "matches": []}

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    translated = (pdir / "translated.srt").read_text(encoding="utf-8")
    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    assert "幼年伊斯基瓜拉斯兽在呼唤。" in translated
    assert "canonical_term_missing" not in report["summary"]["by_type"]
    assert report["repaired_blocks"] == [{
        "id": 2,
        "source": "Ischigualastia",
        "from": "伊斯基瓜拉兽",
        "to": "伊斯基瓜拉斯兽",
        "reason": "curated_domain_term_variant",
    }]
    assert report["summary"]["quality_gate"]["passed"] is True


def test_translate_pipeline_does_not_auto_repair_inferred_proper_names(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transpropernamenorepair"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "\n".join([
            "1",
            "00:00:00,000 --> 00:00:04,000",
            "Hudson Oaks is quiet tonight.",
            "",
            "2",
            "00:00:04,000 --> 00:00:08,000",
            "I came from Hudson Oaks.",
            "",
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {"qa_auto_repair": True},
    })

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            raise AssertionError("inferred proper names should not auto-repair without approved target")

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            blocks[0].translation = "哈德逊奥克斯今晚很安静。"
            blocks[1].translation = "我从哈德逊橡树来。"
            return blocks

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    assert report["summary"]["by_type"]["proper_name_inconsistent"] == 2
    assert report["repaired_blocks"] == []
    rounds = report["trace"]["auto_repair_rounds"]
    assert rounds[0]["candidate_blocks"] == 0
    assert rounds[0]["result"] == "no_repair_applied"
    assert project["translation_quality_status"] == "passed"
    assert "需人工确认质量报告后再交付" not in project["progress_msg"]
    assert report["summary"]["quality_gate"]["passed"] is True
    assert report["summary"]["blocking_warning_count"] == 0


def test_quality_gate_does_not_block_expected_name_at_question_tail():
    from app.api.translate import _finalize_quality_conclusion
    from app.engines.translation_qa import QualityIssue, TranslationQaReport

    report = TranslationQaReport(
        status="ok",
        issues=[
            QualityIssue(
                type="proper_name_inconsistent",
                severity="warning",
                block_id=1494,
                message="inferred proper name One Wish Willow uses inconsistent target forms",
                source_text="What's a One Wish Willow?",
                translation="什么是一愿柳？",
                expected="一愿柳",
            )
        ],
        summary={},
        unresolved_blocks=[],
    )

    _finalize_quality_conclusion(report, [], False)

    assert report.summary["quality_gate"]["passed"] is True
    assert report.summary["blocking_warning_count"] == 0


def test_quality_gate_error_failure_is_unattended_not_human_review():
    from app.api.translate import _finalize_quality_conclusion
    from app.engines.translation_qa import QualityIssue, TranslationQaReport

    report = TranslationQaReport(
        status="needs_review",
        issues=[
            QualityIssue(
                type="missing_translation",
                severity="error",
                block_id=7,
                message="source subtitle has no translation",
                source_text="Long subtitle",
                translation="",
            )
        ],
        summary={},
        unresolved_blocks=[7],
    )

    _finalize_quality_conclusion(report, [{"id": 7}], True)

    gate = report.summary["quality_gate"]
    assert report.status == "failed"
    assert gate["verdict"] == "failed"
    assert gate["passed"] is False
    assert gate["requires_human_review"] is False
    assert gate["delivery_mode"] == "unattended"
    assert "人工" not in report.summary["conclusion"]
    assert "审核" not in report.summary["conclusion"]
    assert "自动交付未通过" in report.summary["conclusion"]


def test_quality_gate_warning_passes_with_report_only_notice():
    from app.api.translate import _finalize_quality_conclusion
    from app.engines.translation_qa import QualityIssue, TranslationQaReport

    report = TranslationQaReport(
        status="needs_review",
        issues=[
            QualityIssue(
                type="line_too_long",
                severity="warning",
                block_id=7,
                message="translation line exceeds 32",
                source_text="Long subtitle",
                translation="这是一条太长的字幕。",
            )
        ],
        summary={},
        unresolved_blocks=[7],
    )

    _finalize_quality_conclusion(report, [], True)

    gate = report.summary["quality_gate"]
    assert report.status == "ok"
    assert gate["verdict"] == "passed"
    assert gate["passed"] is True
    assert report.summary["blocking_warning_count"] == 0
    assert "非阻塞提醒" in report.summary["conclusion"]


def test_translate_pipeline_batches_auto_repair_and_records_trace(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "transrepaircap"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
        "target_language": "简体中文",
        "original_language": "en",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "\n".join([
            "1", "00:00:00,000 --> 00:00:01,000", "Line one.", "",
            "2", "00:00:01,000 --> 00:00:02,000", "Line two.", "",
            "3", "00:00:02,000 --> 00:00:03,000", "Line three.", "",
            "4", "00:00:03,000 --> 00:00:04,000", "Line four.", "",
            "5", "00:00:04,000 --> 00:00:05,000", "Line five.", "",
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "translation": {"qa_auto_repair": True, "qa_auto_repair_max_blocks": 2, "qa_auto_repair_rounds": 2},
    })
    attempted_batches = []

    class FakePrimary:
        def translate_batch(self, items, system_prompt):
            attempted_batches.append([item["id"] for item in items])
            assert len(items) <= 2
            return [
                {"id": item["id"], "translation": f"译文{item['id']}"}
                for item in items
            ]

    class FakeTranslator:
        last_quality_trace = None

        def __init__(self, cfg):
            self.primary = FakePrimary()

        def translate(self, blocks, target_lang, meta_info=None, kb_data=None, callback=None):
            return blocks

        def _apply_results(self, blocks, results):
            by_id = {str(result["id"]): result["translation"] for result in results}
            for block in blocks:
                translation = by_id.get(str(block.index))
                if translation:
                    block.translation = translation

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    report = json.loads((pdir / "translation_qa_report.json").read_text(encoding="utf-8"))
    rounds = report["trace"]["auto_repair_rounds"]
    assert attempted_batches == [[1, 2], [3, 4], [5]]
    assert project["status"] == "translated"
    assert rounds[0]["before_issue_count"] == 5
    assert rounds[0]["after_issue_count"] == 0
    assert rounds[0]["candidate_blocks"] == 5
    assert rounds[0]["max_blocks"] == 2
    assert rounds[0]["attempted_blocks"] == 5
    assert rounds[0]["skipped_blocks"] == 0
    assert rounds[0]["applied_blocks"] == 5
    assert rounds[0]["batches"] == [
        {"batch": 1, "attempted_blocks": 2, "applied_blocks": 2},
        {"batch": 2, "attempted_blocks": 2, "applied_blocks": 2},
        {"batch": 3, "attempted_blocks": 1, "applied_blocks": 1},
    ]
    assert rounds[0]["result"] == "improved"
    assert len(rounds) == 1
    assert report["repaired_blocks"] == [
        {"id": 1, "translation": "译文1"},
        {"id": 2, "translation": "译文2"},
        {"id": 3, "translation": "译文3"},
        {"id": 4, "translation": "译文4"},
        {"id": 5, "translation": "译文5"},
    ]
    assert report["summary"]["quality_gate"]["auto_repaired_blocks"] == 5
    assert report["summary"]["quality_gate"]["passed"] is True


def test_translate_pipeline_limits_auto_repair_rounds(tmp_path, monkeypatch):
    from app.api import translate as translate_api

    assert translate_api._repair_round_limit({"translation": {}}) == 3
    assert translate_api._repair_round_limit({"translation": {"qa_auto_repair_rounds": 0}}) == 3
    assert translate_api._repair_round_limit({"translation": {"qa_auto_repair_rounds": 1}}) == 3
    assert translate_api._repair_round_limit({"translation": {"qa_auto_repair_rounds": 3}}) == 3
    assert translate_api._repair_round_limit({"translation": {"qa_auto_repair_rounds": 4}}) == 4
    assert translate_api._repair_round_limit({"translation": {"qa_auto_repair_rounds": 99}}) == 4
    assert translate_api._repair_item_limit({"translation": {"qa_auto_repair_max_blocks": -1}}) == 0
    assert translate_api._repair_item_limit({"translation": {"qa_auto_repair_max_blocks": 2}}) == 2
    assert translate_api._repair_item_limit({"translation": {"qa_auto_repair_max_blocks": 99}}) == 50


def test_translate_pipeline_redacts_exception_details_in_project_error(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store

    pid = "trans003"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "asr_done",
    }), encoding="utf-8")
    (pdir / "filtered.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {"translation": {}})

    class FakeTranslator:
        def __init__(self, cfg):
            pass

        def translate(self, *args, **kwargs):
            raise RuntimeError("provider failed api_key=secret123 sk-live-secret-token")

    monkeypatch.setattr("app.engines.translator.SubtitleTranslator", FakeTranslator)

    api_translate._run_translate_pipeline(pid, "简体中文")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "error"
    assert "secret123" not in project["error"]
    assert "sk-live-secret-token" not in project["error"]
    assert "api_key=<redacted>" in project["error"]
    assert "sk-<redacted>" in project["error"]


def test_asr_pipeline_writes_filter_state_with_atomic_json(tmp_path, monkeypatch):
    from app.api import translate as api_translate
    from app.utils import project_store
    from app.utils.srt import SubtitleBlock

    pid = "asr001"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "movie",
        "video_path": "/fake/movie.mp4",
        "status": "created",
        "selected_audio_track": 0,
    }), encoding="utf-8")

    monkeypatch.setattr(api_translate, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(api_translate.Config, "to_dict", lambda: {
        "asr": {
            "language": "auto",
            "model_size": "tiny",
            "vad_filter": False,
            "beam_size": 1,
            "backend": "faster_whisper",
        },
        "translation": {},
    })
    monkeypatch.setattr(api_translate, "_emit_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_translate, "_check_cancel", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_translate, "_try_bypass_asr_with_embedded_subtitle", lambda *args, **kwargs: False)
    monkeypatch.setattr("app.engines.audio.preprocess_audio", lambda *args, **kwargs: str(pdir / "audio.wav"))

    captured_transcribe = {}

    def fake_transcribe(*args, **kwargs):
        captured_transcribe["kwargs"] = kwargs
        return [SubtitleBlock(
            index=1,
            start=timedelta(seconds=0),
            end=timedelta(seconds=1),
            text="noise",
        )]

    def fake_filter(blocks, **kwargs):
        blocks[0].filtered = True
        blocks[0].filter_reason = "ASR噪音"
        return blocks

    writes = []

    def fake_atomic_write_json(path, data):
        writes.append((path, data))

    monkeypatch.setattr("app.engines.asr.transcribe", fake_transcribe)
    monkeypatch.setattr("app.engines.filter.filter_subtitles", fake_filter)
    monkeypatch.setattr("app.engines.filter.get_filter_stats", lambda blocks: {"active": 0, "filtered": 1})
    monkeypatch.setattr(api_translate, "atomic_write_json", fake_atomic_write_json)

    api_translate._run_asr_pipeline(pid, audio_track=0, language="auto", owns_registration=False)

    assert writes == [
        (pdir / "filter_state.json", {"1": {"filtered": True, "reason": "ASR噪音"}})
    ]
    assert captured_transcribe["kwargs"]["backend"] == "faster_whisper"
