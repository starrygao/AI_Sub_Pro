import threading
import json

import pytest

from app.api import translate


def test_try_register_task_rejects_duplicate(monkeypatch):
    monkeypatch.setattr(translate, "active_tasks", {})
    factory = lambda: threading.Thread(target=lambda: None)
    translate.try_register_task("p1", factory)
    with pytest.raises(translate.TaskAlreadyRunning):
        translate.try_register_task("p1", factory)


def test_unregister_allows_reregister(monkeypatch):
    monkeypatch.setattr(translate, "active_tasks", {})
    factory = lambda: threading.Thread(target=lambda: None)
    translate.try_register_task("p1", factory)
    translate.unregister_task("p1")
    translate.try_register_task("p1", factory)  # must not raise


def test_register_new_task_clears_stale_cancel(monkeypatch):
    from app.engines.scheduler import is_cancelled, request_cancel, reset_cancel

    monkeypatch.setattr(translate, "active_tasks", {})
    request_cancel("p-new")

    translate.try_register_task(
        "p-new",
        lambda: threading.Thread(target=lambda: None),
        reset_cancellation=True,
    )

    assert is_cancelled("p-new") is False
    translate.unregister_task("p-new")
    reset_cancel("p-new")


def test_start_failure_cleans_registration_marker_generation_and_cancel_event(
    tmp_project_dir,
    monkeypatch,
):
    from app.engines.scheduler import is_cancelled, request_cancel, reset_cancel
    from app.utils.project_store import atomic_write_json

    pid = "task-thread-start-failure"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    video_path = pdir / "video.mp4"
    video_path.write_bytes(b"video")
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Start failure",
        "video_path": str(video_path),
        "status": "asr_done",
        "source_type": "upload",
        "audio_tracks": [{"index": 0, "codec": "aac", "lang": "eng"}],
        "subtitle_tracks": [],
        "selected_audio_track": 0,
    })
    monkeypatch.setattr(translate, "active_tasks", {})

    def fail_start(thread):
        request_cancel(pid)
        raise RuntimeError("injected thread start failure")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    try:
        with pytest.raises(RuntimeError, match="thread start failure"):
            translate.start_asr(
                pid=pid,
                req=translate.ASRRequest(language="en"),
            )

        registered, generation, launch_stage = (
            translate._registered_task_snapshot(pid)
        )
        assert registered is False
        assert generation == ""
        assert launch_stage == ""
        assert is_cancelled(pid) is False
    finally:
        reset_cancel(pid)
        translate.unregister_task(pid)


def test_duplicate_register_does_not_clear_running_task_cancel(monkeypatch):
    from app.engines.scheduler import is_cancelled, request_cancel, reset_cancel

    monkeypatch.setattr(translate, "active_tasks", {"p1": object()})
    request_cancel("p1")

    with pytest.raises(translate.TaskAlreadyRunning):
        translate.try_register_task(
            "p1",
            lambda: threading.Thread(target=lambda: None),
            reset_cancellation=True,
        )

    assert is_cancelled("p1") is True
    reset_cancel("p1")


def test_concurrent_register_single_winner(monkeypatch):
    monkeypatch.setattr(translate, "active_tasks", {})
    barrier = threading.Barrier(10)
    results = []
    lock = threading.Lock()

    def attempt():
        barrier.wait()
        try:
            translate.try_register_task(
                "p1", lambda: threading.Thread(target=lambda: None)
            )
            outcome = "ok"
        except translate.TaskAlreadyRunning:
            outcome = "rejected"
        with lock:
            results.append(outcome)

    ts = [threading.Thread(target=attempt) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count("ok") == 1
    assert results.count("rejected") == 9


def test_asr_substep_keeps_registration_when_not_owner(tmp_path, monkeypatch):
    """As a full-pipeline sub-step (owns_registration=False) the ASR stage must
    NOT deregister the pid — otherwise a concurrent start could race in."""
    from app.utils import project_store
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(translate, "active_tasks", {})
    translate.active_tasks["px000001"] = object()  # pretend the full pipeline registered it
    # No project.json exists -> the stage fails fast and hits its finally block.
    translate._run_asr_pipeline("px000001", 0, "auto", owns_registration=False)
    assert "px000001" in translate.active_tasks


def test_asr_standalone_unregisters_when_owner(tmp_path, monkeypatch):
    """Run standalone (owns_registration=True), the ASR stage deregisters itself."""
    from app.utils import project_store
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(translate, "active_tasks", {})
    translate.active_tasks["px000001"] = object()
    translate._run_asr_pipeline("px000001", 0, "auto", owns_registration=True)
    assert "px000001" not in translate.active_tasks


def test_translate_worker_honors_cancel_requested_before_start(tmp_project_dir):
    from app.engines.scheduler import request_cancel, reset_cancel
    from app.utils.project_store import atomic_write_json

    pid = "cancel-before-start"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Cancel",
        "video_path": str(tmp_project_dir / "video.mp4"),
        "status": "asr_done",
        "audio_tracks": [],
        "subtitle_tracks": [],
        "duration": 1,
    })
    request_cancel(pid)

    try:
        translate._run_translate_pipeline(pid, "简体中文", owns_registration=False, burn_follows=False)
        data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
        assert data["status"] == "cancelled"
        assert data["error"] is None
        assert data["progress_msg"] == "已取消"
    finally:
        reset_cancel(pid)


def test_cancel_pipeline_stage_without_registered_task_sets_cancel_event(tmp_project_dir, monkeypatch):
    from fastapi.testclient import TestClient
    from app.engines.scheduler import is_cancelled, reset_cancel
    from app.utils.project_store import atomic_write_json
    from app.main import app

    monkeypatch.setattr(translate, "active_tasks", {})
    pid = "trailer-cancel"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Trailer",
        "video_path": None,
        "status": "created",
        "pipeline_stage": "download",
        "audio_tracks": [],
        "subtitle_tracks": [],
    })

    try:
        r = TestClient(app).post(f"/api/projects/{pid}/cancel")

        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        assert is_cancelled(pid) is True
        data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
        assert data["status"] == "cancelled"
        assert data["pipeline_stage"] is None
        assert data["error"] is None
    finally:
        reset_cancel(pid)


def test_stale_cancel_request_cannot_cancel_new_task_generation(
    tmp_project_dir,
    monkeypatch,
):
    from app.engines.scheduler import is_cancelled, reset_cancel
    from app.utils.project_store import atomic_write_json

    pid = "cancel-old-generation"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Generation race",
        "video_path": str(tmp_project_dir / "video.mp4"),
        "status": "processing",
        "pipeline_stage": "translate",
        "audio_tracks": [],
        "subtitle_tracks": [],
    })
    monkeypatch.setattr(translate, "active_tasks", {})
    old_worker = threading.Thread(target=lambda: None)
    translate.try_register_task(
        pid,
        lambda: old_worker,
        reset_cancellation=True,
        launch_stage="translate",
    )

    old_cancel_reached_commit = threading.Event()
    release_old_cancel = threading.Event()
    real_mark_cancelled = translate._mark_project_cancelled

    def pause_old_cancel(*args, **kwargs):
        old_cancel_reached_commit.set()
        if not release_old_cancel.wait(timeout=5):
            raise RuntimeError("test timed out before old cancel commit")
        return real_mark_cancelled(*args, **kwargs)

    monkeypatch.setattr(
        translate,
        "_mark_project_cancelled",
        pause_old_cancel,
    )
    cancel_result = {}

    def cancel_old_generation():
        cancel_result.update(translate.cancel_task(pid=pid))

    canceller = threading.Thread(target=cancel_old_generation)
    canceller.start()
    assert old_cancel_reached_commit.wait(timeout=5)

    translate.unregister_task(pid)
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Generation race",
        "video_path": str(tmp_project_dir / "video.mp4"),
        "status": "processing",
        "pipeline_stage": "translate",
        "audio_tracks": [],
        "subtitle_tracks": [],
    })
    new_worker = threading.Thread(target=lambda: None)
    translate.try_register_task(
        pid,
        lambda: new_worker,
        reset_cancellation=True,
        launch_stage="translate",
    )
    try:
        assert is_cancelled(pid) is False
    finally:
        release_old_cancel.set()
        canceller.join(timeout=5)

    try:
        assert not canceller.is_alive()
        assert cancel_result["status"] == "no_task"
        assert is_cancelled(pid) is False
        project = json.loads(
            (pdir / "project.json").read_text(encoding="utf-8")
        )
        assert project["status"] == "processing"
        assert project["pipeline_stage"] == "translate"
        assert translate.active_tasks[pid] is new_worker
    finally:
        translate.unregister_task(pid)
        reset_cancel(pid)
