import threading
import json

import pytest

from app.services import translation_tasks as translate


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


def test_cancel_snapshot_cannot_signal_replacement_task_generation(
    tmp_project_dir,
    monkeypatch,
):
    from app.engines.scheduler import is_cancelled, reset_cancel
    from app.utils.project_store import atomic_write_json

    pid = "cancel-generation-aba"
    pdir = tmp_project_dir / pid
    pdir.mkdir()

    def write_processing_project():
        atomic_write_json(pdir / "project.json", {
            "id": pid,
            "name": "Generation ABA",
            "video_path": str(tmp_project_dir / "video.mp4"),
            "status": "processing",
            "pipeline_stage": "translate",
            "audio_tracks": [],
            "subtitle_tracks": [],
        })

    write_processing_project()
    monkeypatch.setattr(translate, "active_tasks", {})
    old_worker = threading.Thread(target=lambda: None)
    translate.try_register_task(
        pid,
        lambda: old_worker,
        reset_cancellation=True,
        launch_stage="translate",
    )

    request_entered = threading.Event()
    release_request = threading.Event()
    mark_entered = threading.Event()
    release_mark = threading.Event()
    replacement_done = threading.Event()
    real_request_cancel = translate.request_cancel
    real_mark_cancelled = translate._mark_project_cancelled

    def pause_before_cancel_signal(task_pid, **kwargs):
        request_entered.set()
        if not release_request.wait(timeout=5):
            raise RuntimeError("test timed out before cancel signal")
        real_request_cancel(task_pid, **kwargs)

    def pause_before_cancel_commit(*args, **kwargs):
        mark_entered.set()
        if not release_mark.wait(timeout=5):
            raise RuntimeError("test timed out before cancel commit")
        return real_mark_cancelled(*args, **kwargs)

    monkeypatch.setattr(
        translate,
        "request_cancel",
        pause_before_cancel_signal,
    )
    monkeypatch.setattr(
        translate,
        "_mark_project_cancelled",
        pause_before_cancel_commit,
    )
    cancel_result = {}
    new_worker = threading.Thread(target=lambda: None)

    def cancel_old_generation():
        cancel_result.update(translate.cancel_task(pid=pid))

    def replace_generation():
        translate.unregister_task(pid, task=old_worker)
        write_processing_project()
        translate.try_register_task(
            pid,
            lambda: new_worker,
            reset_cancellation=True,
            launch_stage="translate",
        )
        replacement_done.set()

    canceller = threading.Thread(target=cancel_old_generation)
    replacement = threading.Thread(target=replace_generation)
    canceller.start()
    assert request_entered.wait(timeout=5)
    replacement.start()
    try:
        replacement_done.wait(timeout=0.2)
        release_request.set()
        assert mark_entered.wait(timeout=5)
        assert replacement_done.wait(timeout=5)
    finally:
        release_mark.set()
        canceller.join(timeout=5)
        replacement.join(timeout=5)

    try:
        assert not canceller.is_alive()
        assert not replacement.is_alive()
        assert cancel_result["status"] == "no_task"
        assert translate.active_tasks[pid] is new_worker
        assert is_cancelled(pid) is False
        translate._check_cancel(pid)
    finally:
        translate.unregister_task(pid, task=new_worker)
        reset_cancel(pid)


def test_cancel_event_is_scoped_to_registered_task_generation(monkeypatch):
    from app.engines.scheduler import (
        is_cancelled,
        request_cancel,
        reset_cancel,
    )

    pid = "cancel-event-generation-scope"
    monkeypatch.setattr(translate, "active_tasks", {})
    old_worker = threading.Thread(target=lambda: None)
    translate.try_register_task(
        pid,
        lambda: old_worker,
        reset_cancellation=True,
        launch_stage="translate",
    )
    old_generation = translate._registered_task_snapshot(pid)[1]
    translate.unregister_task(pid, task=old_worker)

    new_worker = threading.Thread(target=lambda: translate._check_cancel(pid))
    translate.try_register_task(
        pid,
        lambda: new_worker,
        reset_cancellation=True,
        launch_stage="translate",
    )
    new_generation = translate._registered_task_snapshot(pid)[1]

    try:
        request_cancel(pid, generation=old_generation)

        assert is_cancelled(pid, generation=old_generation) is True
        assert is_cancelled(pid, generation=new_generation) is False
        new_worker.start()
        new_worker.join(timeout=5)
        assert not new_worker.is_alive()
    finally:
        translate.unregister_task(pid, task=new_worker)
        reset_cancel(pid)


def test_reset_of_old_generation_cannot_clear_new_generation_cancel(
    monkeypatch,
):
    from app.engines.scheduler import (
        is_cancelled,
        request_cancel,
        reset_cancel,
    )

    pid = "cancel-event-generation-reset"
    monkeypatch.setattr(translate, "active_tasks", {})
    old_worker = threading.Thread(target=lambda: None)
    translate.try_register_task(
        pid,
        lambda: old_worker,
        reset_cancellation=True,
    )
    old_generation = translate._registered_task_snapshot(pid)[1]
    translate.unregister_task(pid, task=old_worker)
    new_worker = threading.Thread(target=lambda: None)
    translate.try_register_task(
        pid,
        lambda: new_worker,
        reset_cancellation=True,
    )
    new_generation = translate._registered_task_snapshot(pid)[1]

    try:
        request_cancel(pid, generation=new_generation)
        reset_cancel(pid, generation=old_generation)

        assert is_cancelled(pid, generation=new_generation) is True
    finally:
        translate.unregister_task(pid, task=new_worker)
        reset_cancel(pid)


@pytest.mark.parametrize(
    "terminal_kind",
    [
        "translation_failed",
        "translation_incomplete",
        "burn_completed",
        "burn_unavailable",
        "burn_failed",
    ],
)
def test_cancel_wins_generation_bound_terminal_commit(
    tmp_project_dir,
    terminal_kind,
):
    """Catches a late failure terminal write overwriting an acknowledged cancel."""
    from app.engines.scheduler import request_cancel, reset_cancel
    from app.engines.workflow_state import load_workflow_state, start_stage
    from app.utils.project_store import atomic_write_json

    pid = f"cancel-terminal-{terminal_kind}"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Terminal race",
        "video_path": str(pdir / "video.mp4"),
        "status": "processing",
        "pipeline_stage": (
            "translate"
            if terminal_kind.startswith("translation_")
            else "burn"
        ),
        "audio_tracks": [],
        "subtitle_tracks": [],
    })
    stage = (
        "translate"
        if terminal_kind.startswith("translation_")
        else "burn"
    )
    start_stage(pid, stage)
    worker = threading.Thread(target=lambda: None)
    translate.try_register_task(
        pid,
        lambda: worker,
        reset_cancellation=True,
        launch_stage=stage,
    )
    generation = translate._registered_task_snapshot(pid)[1]
    request_cancel(pid, generation=generation)

    try:
        if terminal_kind == "translation_failed":
            terminal = translate._mark_translation_quality_failed(
                pid,
                "quality rejected",
                quality_policy="strict",
                quality_run_id="run",
                quality_content_hash="sha256:content",
                quality_source_generation_hash="sha256:source",
                quality_configuration_hash="sha256:configuration",
                expected_task_generation=generation,
            )
        elif terminal_kind == "translation_incomplete":
            terminal = translate._mark_translation_incomplete(
                pid,
                "translation incomplete",
                expected_task_generation=generation,
            )
        elif terminal_kind == "burn_completed":
            terminal = translate._mark_burn_completed(
                pid,
                str(pdir / "output.mp4"),
                "burn completed",
                expected_task_generation=generation,
            )
        elif terminal_kind == "burn_unavailable":
            terminal = translate._mark_burn_unavailable(
                pid,
                "delivery unavailable",
                expected_task_generation=generation,
            )
        else:
            terminal = translate._mark_burn_failed(
                pid,
                "burn failed",
                expected_task_generation=generation,
            )

        project = json.loads(
            (pdir / "project.json").read_text(encoding="utf-8")
        )
        assert terminal.cancel_won is True
        assert terminal.fields["status"] == "cancelled"
        assert project["status"] == "cancelled"
        assert project["pipeline_stage"] is None
        assert project["error"] is None
        assert load_workflow_state(pid)["stages"][stage]["status"] == "cancelled"
    finally:
        translate.unregister_task(pid, task=worker)
        reset_cancel(pid)


def test_stale_generation_cannot_commit_terminal_failure(tmp_project_dir):
    """Catches an old worker overwriting state owned by a replacement task."""
    from app.utils.project_store import atomic_write_json

    pid = "stale-terminal-generation"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Replacement",
        "video_path": str(pdir / "video.mp4"),
        "status": "processing",
        "pipeline_stage": "burn",
        "audio_tracks": [],
        "subtitle_tracks": [],
    })
    worker = threading.Thread(target=lambda: None)
    translate.try_register_task(
        pid,
        lambda: worker,
        reset_cancellation=True,
        launch_stage="burn",
    )

    try:
        with pytest.raises(translate.StaleTaskGeneration):
            translate._mark_burn_failed(
                pid,
                "old worker failed",
                expected_task_generation="replaced-generation",
            )
        project = json.loads(
            (pdir / "project.json").read_text(encoding="utf-8")
        )
        assert project["status"] == "processing"
        assert project["pipeline_stage"] == "burn"
    finally:
        translate.unregister_task(pid, task=worker)
