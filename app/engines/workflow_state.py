"""Structured workflow state and bounded per-stage logs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.utils.errors import redact_error_message
from app.utils.project_store import (
    atomic_write_json,
    get_project_lock,
    project_dir,
    validate_pid,
)

VALID_STATUSES = {"pending", "running", "succeeded", "failed", "cancelled", "skipped"}
VALID_STAGES = {"download", "asr", "subtitle_extract", "filter", "translate", "burn", "export"}
LOG_LIMIT_BYTES = 200_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_stage(stage: str) -> str:
    if not isinstance(stage, str) or stage not in VALID_STAGES:
        raise ValueError(f"invalid workflow stage: {stage!r}")
    return stage


def workflow_state_path(pid: str) -> Path:
    validate_pid(pid)
    return project_dir(pid) / "workflow_state.json"


def stage_log_path(pid: str, stage: str) -> Path:
    validate_pid(pid)
    stage = _clean_stage(stage)
    return project_dir(pid) / "workflow_logs" / f"{stage}.log"


def _empty_state() -> dict[str, Any]:
    return {"version": 1, "updated_at": _now(), "stages": {}}


def _empty_stage(status: str = "pending") -> dict[str, Any]:
    return {
        "status": status,
        "started_at": None,
        "finished_at": None,
        "input_artifact": "",
        "output_artifact": "",
        "retry_count": 0,
        "error_summary": "",
        "log_path": "",
        "resume_eligible": False,
    }


def _normalize_stage(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _empty_stage()

    status = raw.get("status")
    item = _empty_stage(status if status in VALID_STATUSES else "pending")
    for key in ("input_artifact", "output_artifact", "error_summary", "log_path"):
        value = raw.get(key)
        if isinstance(value, str):
            item[key] = value
    for key in ("started_at", "finished_at"):
        value = raw.get(key)
        if isinstance(value, str) or value is None:
            item[key] = value
    retry_count = raw.get("retry_count")
    if isinstance(retry_count, int) and not isinstance(retry_count, bool) and retry_count >= 0:
        item["retry_count"] = retry_count
    item["resume_eligible"] = bool(raw.get("resume_eligible"))
    return item


def _normalize_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _empty_state()

    raw_stages = data.get("stages")
    if not isinstance(raw_stages, dict):
        return _empty_state()

    updated_at = data.get("updated_at")
    state: dict[str, Any] = {
        "version": 1,
        "updated_at": updated_at if isinstance(updated_at, str) else _now(),
        "stages": {},
    }
    for stage, raw_stage in raw_stages.items():
        if stage in VALID_STAGES:
            state["stages"][stage] = _normalize_stage(raw_stage)
    return state


def load_workflow_state(pid: str) -> dict[str, Any]:
    path = workflow_state_path(pid)
    if not path.exists():
        return _empty_state()
    try:
        return _normalize_state(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return _empty_state()


def save_workflow_state(pid: str, state: dict[str, Any]) -> dict[str, Any]:
    with get_project_lock(pid):
        normalized = _normalize_state(state)
        normalized["updated_at"] = _now()
        atomic_write_json(workflow_state_path(pid), normalized)
        return normalized


def reset_workflow(pid: str, stages: Iterable[str]) -> dict[str, Any]:
    state = _empty_state()
    for stage in stages:
        state["stages"][_clean_stage(stage)] = _empty_stage("pending")
    return save_workflow_state(pid, state)


def start_stage(pid: str, stage: str, input_artifact: str = "") -> dict[str, Any]:
    stage = _clean_stage(stage)
    with get_project_lock(pid):
        pdir = project_dir(pid)
        state = load_workflow_state(pid)
        item = state["stages"].setdefault(stage, _empty_stage())
        item.update(
            {
                "status": "running",
                "started_at": _now(),
                "finished_at": None,
                "input_artifact": input_artifact if isinstance(input_artifact, str) else "",
                "error_summary": "",
                "log_path": str(stage_log_path(pid, stage).relative_to(pdir)),
                "resume_eligible": False,
            }
        )
        return save_workflow_state(pid, state)


def finish_stage(
    pid: str,
    stage: str,
    output_artifact: str = "",
    resume_eligible: bool = True,
) -> dict[str, Any]:
    stage = _clean_stage(stage)
    with get_project_lock(pid):
        state = load_workflow_state(pid)
        item = state["stages"].setdefault(stage, _empty_stage())
        item.update(
            {
                "status": "succeeded",
                "finished_at": _now(),
                "output_artifact": output_artifact if isinstance(output_artifact, str) else "",
                "error_summary": "",
                "resume_eligible": bool(resume_eligible),
            }
        )
        return save_workflow_state(pid, state)


def fail_stage(pid: str, stage: str, exc: BaseException | str) -> dict[str, Any]:
    stage = _clean_stage(stage)
    with get_project_lock(pid):
        state = load_workflow_state(pid)
        item = state["stages"].setdefault(stage, _empty_stage())
        retry_count = item.get("retry_count", 0)
        if not isinstance(retry_count, int) or isinstance(retry_count, bool) or retry_count < 0:
            retry_count = 0
        item.update(
            {
                "status": "failed",
                "finished_at": _now(),
                "retry_count": retry_count + 1,
                "error_summary": redact_error_message(exc),
                "resume_eligible": False,
            }
        )
        return save_workflow_state(pid, state)


def cancel_workflow(pid: str, stage: str) -> dict[str, Any]:
    stage = _clean_stage(stage)
    with get_project_lock(pid):
        state = load_workflow_state(pid)
        item = state["stages"].setdefault(stage, _empty_stage())
        item.update(
            {
                "status": "cancelled",
                "finished_at": _now(),
                "resume_eligible": False,
            }
        )
        return save_workflow_state(pid, state)


def _bound_log_bytes(data: bytes) -> bytes:
    if len(data) <= LOG_LIMIT_BYTES:
        return data
    data = data[-LOG_LIMIT_BYTES:]
    return data.decode("utf-8", errors="ignore").encode("utf-8")


def append_stage_log(pid: str, stage: str, message: str) -> Path:
    stage = _clean_stage(stage)
    with get_project_lock(pid):
        path = stage_log_path(pid, stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_message = redact_error_message(message if isinstance(message, str) else "")
        line = f"{_now()} {safe_message}\n".encode("utf-8")
        existing = path.read_bytes() if path.exists() else b""
        path.write_bytes(_bound_log_bytes(existing + line))
        return path
