"""Phase 3 — pipeline correctness: per-project error logs, consistent
burn-failure status handling across both burn entry points."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ---- ASR error log lands per-project, never in the projects root ----------

def test_asr_error_log_written_to_project_dir(tmp_path):
    """When all ASR backends fail, the error log must be per-project,
    not stomping a shared PROJECTS_DIR/asr_error.log file."""
    from app.engines import asr

    audio = tmp_path / "raw_audio.wav"
    audio.write_bytes(b"\x00" * 4096)
    pdir = tmp_path / "proj_xyz"
    pdir.mkdir()

    def _boom_mlx(*a, **kw):
        raise ImportError("mlx not installed")

    def _boom_openai(*a, **kw):
        raise ImportError("whisper not installed")

    with patch.object(asr, "_transcribe_mlx", side_effect=_boom_mlx), \
         patch.object(asr, "_transcribe_openai", side_effect=_boom_openai):
        with pytest.raises(RuntimeError, match="No working ASR backend"):
            asr.transcribe(str(audio), error_log_dir=str(pdir))

    log_in_project = pdir / "asr_error.log"
    assert log_in_project.exists(), "asr_error.log must be inside the project dir"
    assert "mlx not installed" in log_in_project.read_text()


# ---- /start-burn endpoint: failure path must mirror _run_burn_pipeline -----

def _make_upload_project(tmp_project_dir, video_path="/fake/video.mp4"):
    """Build a minimal upload project on disk so the burn entry point can read it.

    The HTTP-layer create_project is an async FastAPI route, so for unit tests
    we write the project.json directly using the same shape _apply_safe_defaults
    expects.
    """
    from app.api.projects import _apply_safe_defaults

    pid = "abcdef01"
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    project = _apply_safe_defaults({
        "id": pid,
        "name": "t",
        "video_path": video_path,
        "status": "translated",
        "error": None,
        "source_type": "upload",
    })
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
    )
    return pid, pdir


def test_start_burn_failure_marks_status_translated_with_error(tmp_project_dir, monkeypatch):
    """When burn_subtitles returns False inside the /start-burn endpoint's
    background task, the project status must be set to 'translated' with an
    error note — matching the failure behavior of _run_burn_pipeline. Without
    this, the UI shows stale state and users don't know burn failed."""
    from app.api import translate as tr
    from app.api import projects as projects_api
    from app.utils import project_store

    monkeypatch.setattr(tr, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)

    pid, pdir = _make_upload_project(tmp_project_dir)

    # Force burn_subtitles to fail without actually shelling out.
    monkeypatch.setattr(tr, "burn_subtitles", lambda *a, **kw: False)

    # Bypass the HTTP layer and exercise the inner task body directly,
    # synchronously, so we can assert state without thread races.
    result = tr.start_burn(pid=pid)
    assert result["status"] == "started"

    # The task started a daemon thread; wait it out.
    with tr._tasks_lock:
        thread = tr.active_tasks.get(pid)
    if thread is not None:
        thread.join(timeout=5)

    proj = projects_api._load_project(pid)
    assert proj["status"] == "translated", \
        f"burn failure must leave status=translated (translation still usable), got {proj['status']!r}"
    assert proj.get("error") and "烧录" in proj["error"], \
        f"burn failure must record an error note, got {proj.get('error')!r}"


def test_translate_load_project_rejects_invalid_pid():
    """Defense in depth: _load_project should validate the pid before
    touching the filesystem, even when called internally. Routing through
    project_store.load_project gives us the same path-traversal guard the
    write-side already has via mutate_project."""
    from fastapi import HTTPException
    from app.api import translate as tr

    with pytest.raises(HTTPException) as exc_info:
        tr._load_project("../etc/passwd")
    assert exc_info.value.status_code == 400, \
        f"invalid pid must raise HTTP 400, got {exc_info.value.status_code}"
