def test_request_cancel_sets_flag():
    from app.engines.scheduler import request_cancel, is_cancelled, reset_cancel
    reset_cancel("pidc1")
    assert is_cancelled("pidc1") is False
    request_cancel("pidc1")
    assert is_cancelled("pidc1") is True


def test_is_cancelled_unknown_pid_is_false():
    from app.engines.scheduler import is_cancelled
    assert is_cancelled("never-existed-xxx") is False


def test_reset_cancel_clears_flag():
    from app.engines.scheduler import request_cancel, is_cancelled, reset_cancel
    request_cancel("pidc2")
    assert is_cancelled("pidc2") is True
    reset_cancel("pidc2")
    assert is_cancelled("pidc2") is False


def test_cancel_marks_workflow_stage_cancelled(tmp_project_dir, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from app.api import translate
    from app.engines.workflow_state import load_workflow_state, start_stage
    from app.main import app
    from app.utils.project_store import atomic_write_json

    monkeypatch.setattr(translate, "active_tasks", {})
    pid = "cancel-asr"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    atomic_write_json(pdir / "project.json", {
        "id": pid,
        "name": "Cancel ASR",
        "video_path": str(tmp_project_dir / "video.mp4"),
        "status": "processing",
        "pipeline_stage": "asr",
        "audio_tracks": [],
        "subtitle_tracks": [],
    })
    start_stage(pid, "asr", input_artifact="video.mp4")

    response = TestClient(app).post(f"/api/projects/{pid}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["pipeline_stage"] is None
    state = load_workflow_state(pid)
    assert state["stages"]["asr"]["status"] == "cancelled"
