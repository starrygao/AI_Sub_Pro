import json

import pytest


def test_workflow_state_records_stage_lifecycle(tmp_project_dir):
    from app.engines.workflow_state import (
        fail_stage,
        finish_stage,
        load_workflow_state,
        reset_workflow,
        start_stage,
    )

    reset_workflow("wf1", ["asr", "translate", "burn"])
    start_stage("wf1", "asr", input_artifact="input.mp4")
    finish_stage("wf1", "asr", output_artifact="filtered.srt")
    start_stage("wf1", "translate", input_artifact="filtered.srt")
    fail_stage("wf1", "translate", RuntimeError("bad api key"))

    state = load_workflow_state("wf1")

    assert state["version"] == 1
    assert state["stages"]["asr"]["status"] == "succeeded"
    assert state["stages"]["asr"]["output_artifact"] == "filtered.srt"
    assert state["stages"]["asr"]["resume_eligible"] is True
    assert state["stages"]["translate"]["status"] == "failed"
    assert state["stages"]["translate"]["retry_count"] == 1
    assert state["stages"]["translate"]["resume_eligible"] is False
    assert "bad api key" in state["stages"]["translate"]["error_summary"]


def test_stage_logs_are_bounded_and_redacted(tmp_project_dir):
    from app.engines.workflow_state import append_stage_log, stage_log_path

    secret = "sk-" + "x" * 48
    for _ in range(5000):
        append_stage_log("wf-log", "asr", f"message with {secret}")

    path = stage_log_path("wf-log", "asr")
    text = path.read_text(encoding="utf-8")

    assert secret not in text
    assert "sk-<redacted>" in text
    assert path.stat().st_size <= 200_000


def test_load_workflow_state_normalizes_invalid_file(tmp_project_dir):
    from app.engines.workflow_state import load_workflow_state

    pdir = tmp_project_dir / "wf-bad"
    pdir.mkdir()
    (pdir / "workflow_state.json").write_text(json.dumps({"stages": []}), encoding="utf-8")

    state = load_workflow_state("wf-bad")

    assert state["version"] == 1
    assert state["stages"] == {}


def test_load_workflow_state_normalizes_malformed_stage_fields(tmp_project_dir):
    from app.engines.workflow_state import load_workflow_state

    pdir = tmp_project_dir / "wf-dirty"
    pdir.mkdir()
    (pdir / "workflow_state.json").write_text(
        json.dumps(
            {
                "version": 99,
                "updated_at": ["bad"],
                "stages": {
                    "asr": {
                        "status": "nonsense",
                        "retry_count": -1,
                        "started_at": 123,
                        "resume_eligible": "false",
                        "error_summary": "api_key=secret sk-abcdef123456",
                    },
                    "nope": {"status": "running"},
                },
            }
        ),
        encoding="utf-8",
    )

    state = load_workflow_state("wf-dirty")

    assert state["version"] == 1
    assert set(state["stages"]) == {"asr"}
    assert state["stages"]["asr"]["status"] == "pending"
    assert state["stages"]["asr"]["retry_count"] == 0
    assert state["stages"]["asr"]["started_at"] is None
    assert state["stages"]["asr"]["resume_eligible"] is False
    assert "secret" not in state["stages"]["asr"]["error_summary"]
    assert "sk-abcdef123456" not in state["stages"]["asr"]["error_summary"]
    assert "<redacted>" in state["stages"]["asr"]["error_summary"]


def test_workflow_state_rejects_invalid_stage(tmp_project_dir):
    from app.engines.workflow_state import append_stage_log, reset_workflow, start_stage

    with pytest.raises(ValueError, match="invalid workflow stage"):
        start_stage("wf-invalid", "not-a-stage")

    with pytest.raises(ValueError, match="invalid workflow stage"):
        reset_workflow("wf-invalid", ["asr", "not-a-stage"])

    with pytest.raises(ValueError, match="invalid workflow stage"):
        append_stage_log("wf-invalid", "../asr", "nope")


def test_append_stage_log_rejects_symlinked_log_directory(tmp_project_dir):
    from app.engines.workflow_state import append_stage_log

    pdir = tmp_project_dir / "wf-log-link-dir"
    pdir.mkdir()
    outside = tmp_project_dir / "outside-logs"
    outside.mkdir()
    (pdir / "workflow_logs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="workflow log directory"):
        append_stage_log("wf-log-link-dir", "asr", "nope")


def test_append_stage_log_rejects_symlinked_stage_log(tmp_project_dir):
    from app.engines.workflow_state import append_stage_log

    pdir = tmp_project_dir / "wf-log-link-file"
    log_dir = pdir / "workflow_logs"
    log_dir.mkdir(parents=True)
    target = tmp_project_dir / "outside.log"
    target.write_text("outside", encoding="utf-8")
    (log_dir / "asr.log").symlink_to(target)

    with pytest.raises(ValueError, match="workflow log file"):
        append_stage_log("wf-log-link-file", "asr", "nope")

    assert target.read_text(encoding="utf-8") == "outside"


def test_append_stage_log_rejects_non_regular_stage_log(tmp_project_dir):
    from app.engines.workflow_state import append_stage_log

    pdir = tmp_project_dir / "wf-log-dir-file"
    (pdir / "workflow_logs" / "asr.log").mkdir(parents=True)

    with pytest.raises(ValueError, match="workflow log file"):
        append_stage_log("wf-log-dir-file", "asr", "nope")
