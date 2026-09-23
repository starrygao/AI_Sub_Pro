"""Centralized concurrency control, progress store, and cancellation for AI_Sub_Pro.

Usage:
    from app.engines.scheduler import slot

    with slot("asr", pid):
        run_asr(...)

Note: semaphores resolve lazily on first use so user-configured concurrency limits
from config.json (loaded at FastAPI startup) take effect, not just DEFAULT_CONFIG.
"""
import json
import logging
import math
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, Optional

from app import config as cfg
from app.config import PROJECTS_DIR
from app.engines.workflow_state import (
    append_stage_log,
    fail_stage,
    finish_stage,
    load_workflow_state,
)
from app.utils.project_store import (
    atomic_write_json,
    durable_replace,
    durable_unlink,
    load_project,
    mutate_project,
    project_dir,
    validate_pid,
)
from app.utils.burn_transaction import (
    BURN_RECOVERY_BLOCKED,
    BURN_RECOVERY_COMMITTED,
    BURN_RECOVERY_NONE,
    BURN_RECOVERY_REVERTED,
    cleanup_orphaned_burn_artifacts,
    finalize_committed_burn_transaction,
    recover_burn_output_transaction,
)

log = logging.getLogger(__name__)

_DEFAULTS = {"asr": 2, "translate": 4, "download": 3, "burn": 1}
_sem_cache: dict = {}
_sem_cache_lock = threading.Lock()


def _normalize_cap(raw, default: int) -> int:
    return _normalize_number(raw, default=default, minimum=1, maximum=16)


def get_semaphore(stage: str) -> threading.BoundedSemaphore:
    """Return the per-stage BoundedSemaphore, constructing it lazily on first access.

    Reads `Config.get("concurrency", stage)` at first-use time, so values from
    config.json (loaded at FastAPI startup) override DEFAULT_CONFIG fallbacks.
    """
    if stage not in _DEFAULTS:
        raise ValueError(f"unknown stage {stage!r}; expected one of {sorted(_DEFAULTS)}")
    with _sem_cache_lock:
        if stage not in _sem_cache:
            concurrency_cfg = cfg.Config.get("concurrency") or {}
            if not isinstance(concurrency_cfg, dict):
                concurrency_cfg = {}
            cap = _normalize_cap(concurrency_cfg.get(stage, _DEFAULTS[stage]), _DEFAULTS[stage])
            _sem_cache[stage] = threading.BoundedSemaphore(cap)
            log.debug("scheduler: built semaphore stage=%s cap=%d", stage, cap)
        return _sem_cache[stage]


@contextmanager
def slot(stage: str, pid: str) -> Iterator[None]:
    """Acquire a concurrency slot for a given pipeline stage."""
    sem = get_semaphore(stage)
    sem.acquire()
    log.debug("semaphore[%s] acquired pid=%s", stage, pid)
    try:
        yield
    finally:
        sem.release()
        log.debug("semaphore[%s] released pid=%s", stage, pid)


# --- Progress store ---

_progress_lock = threading.Lock()
progress_store: Dict[str, dict] = {}

_STAGE_RANGES = {
    "download":  (0, 15),
    "asr":       (15, 40),
    "translate": (40, 75),
    "burn":      (75, 100),
}
_RECOVERABLE_RUNNING_STAGES = {"download", "asr", "translate", "burn"}
_RUNNING_STAGE_PRIORITY = ("burn", "translate", "asr", "download")
_INTERRUPTED_TASK_MESSAGE = "任务因应用重启中断，请点击恢复流程或重试失败阶段。"


def _read_progress_file_bytes(pid: str) -> Optional[bytes]:
    path = project_dir(pid) / "progress.json"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError("progress path is unsafe")
    return path.read_bytes() if path.is_file() else None


def _restore_progress_file_bytes(
    pid: str,
    content: Optional[bytes],
) -> None:
    path = project_dir(pid) / "progress.json"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError("progress path is unsafe")
    if content is None:
        durable_unlink(path)
        return
    handle = tempfile.NamedTemporaryFile(
        "wb",
        dir=path.parent,
        prefix=".rollback-progress.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
        durable_replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def snapshot_progress_state(pid: str) -> dict:
    with _progress_lock:
        payload = progress_store.get(pid)
        return {
            "memory": (
                dict(payload) if isinstance(payload, dict) else None
            ),
            "file": _read_progress_file_bytes(pid),
        }


def restore_progress_state(pid: str, state: dict) -> None:
    with _progress_lock:
        _restore_progress_file_bytes(pid, state.get("file"))
        payload = state.get("memory")
        if payload is None:
            progress_store.pop(pid, None)
        else:
            progress_store[pid] = dict(payload)


def _map_global(stage: str, local_pct: int) -> int:
    lo, hi = _STAGE_RANGES.get(stage, (0, 100))
    local = _normalize_number(local_pct, default=0, minimum=0, maximum=100)
    return lo + int((hi - lo) * (local / 100))


def _normalize_number(raw, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(raw, bool):
        return default
    try:
        value = float(raw)
    except (OverflowError, TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return max(minimum, min(maximum, int(value)))


def update_progress(pid: str, stage: str, local_pct: int, msg: str) -> None:
    """Thread-safe progress update. Persists per-project progress.json."""
    validate_pid(pid)
    stage = stage if isinstance(stage, str) else ""
    payload = {
        "progress": _map_global(stage, local_pct),
        "stage": stage,
        "message": msg if isinstance(msg, str) else "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with _progress_lock:
        progress_store[pid] = payload
        try:
            atomic_write_json(
                project_dir(pid) / "progress.json",
                payload,
            )
        except Exception as e:
            log.warning("persist progress failed pid=%s: %s", pid, e)
    if payload["stage"] and payload["message"]:
        try:
            append_stage_log(pid, payload["stage"], payload["message"])
        except Exception as e:
            log.warning(
                "append stage log failed pid=%s stage=%s: %s",
                pid,
                payload["stage"],
                e,
            )


def complete_progress(pid: str, msg: str) -> None:
    """Persist terminal workflow progress with no active stage."""
    validate_pid(pid)
    payload = {
        "progress": 100,
        "stage": "",
        "message": msg if isinstance(msg, str) else "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with _progress_lock:
        progress_store[pid] = payload
        try:
            atomic_write_json(
                project_dir(pid) / "progress.json",
                payload,
            )
        except Exception as e:
            log.warning(
                "persist terminal progress failed pid=%s: %s",
                pid,
                e,
            )


def _normalize_progress_payload(data: dict) -> dict:
    payload = {
        "progress": _normalize_number(data.get("progress", 0), default=0, minimum=0, maximum=100),
        "stage": data.get("stage") if isinstance(data.get("stage"), str) else "",
        "message": data.get("message") if isinstance(data.get("message"), str) else "",
    }
    updated_at = data.get("updated_at")
    if isinstance(updated_at, str):
        payload["updated_at"] = updated_at
    return payload


def _read_progress_locked(pid: str, fp: Path) -> Optional[dict]:
    """Read the latest persisted value while the caller holds _progress_lock."""
    if fp.exists():
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("progress payload is not an object")
            data = _normalize_progress_payload(data)
            progress_store[pid] = data
            return dict(data)
        except Exception as e:
            log.warning("load progress failed pid=%s: %s", pid, e)
    data = progress_store.get(pid)
    if not isinstance(data, dict):
        return None
    data = _normalize_progress_payload(data)
    progress_store[pid] = data
    return dict(data)


def get_progress(pid: str) -> Optional[dict]:
    try:
        fp = project_dir(pid) / "progress.json"
    except ValueError:
        return None
    with _progress_lock:
        return _read_progress_locked(pid, fp)


def update_progress_message(pid: str, stage: str, msg: str) -> None:
    """Record a stop message without changing the last measured percentage.

    If there was no progress record, keep it unknown rather than inventing a
    stage-start percentage. The project/workflow still carries the stop state.
    """
    validate_pid(pid)
    fp = project_dir(pid) / "progress.json"
    with _progress_lock:
        payload = _read_progress_locked(pid, fp)
        if payload is not None:
            payload.update(stage=stage, message=msg, updated_at=datetime.now(timezone.utc).isoformat())
            progress_store[pid] = payload
            try:
                atomic_write_json(fp, payload)
            except Exception as e:
                log.warning("persist progress message failed pid=%s: %s", pid, e)
    if stage and msg:
        try:
            append_stage_log(pid, stage, msg)
        except Exception as e:
            log.warning("append stage log failed pid=%s stage=%s: %s", pid, stage, e)


def load_progress_store_from_disk() -> int:
    """Restore in-memory progress_store from disk. Returns count restored."""
    count = 0
    root = Path(PROJECTS_DIR)
    if not root.exists():
        return 0
    for pdir in root.iterdir():
        if pdir.is_symlink() or not pdir.is_dir():
            continue
        fp = pdir / "progress.json"
        if not fp.exists():
            continue
        try:
            validate_pid(pdir.name)
            data = json.loads(fp.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("progress payload is not an object")
            data = _normalize_progress_payload(data)
            with _progress_lock:
                progress_store[pdir.name] = data
            count += 1
        except Exception as e:
            log.warning("load progress failed pid=%s: %s", pdir.name, e)
    return count


def _running_stage_from_workflow_state(pid: str) -> str:
    state = load_workflow_state(pid)
    stages = state.get("stages") if isinstance(state, dict) else {}
    if not isinstance(stages, dict):
        return ""
    for stage in _RUNNING_STAGE_PRIORITY:
        item = stages.get(stage)
        if isinstance(item, dict) and item.get("status") == "running":
            return stage
    return ""


def _stage_from_progress_file(pdir: Path) -> str:
    fp = pdir / "progress.json"
    if not fp.exists():
        return ""
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    stage = data.get("stage")
    return stage if stage in _RECOVERABLE_RUNNING_STAGES else ""


def _clear_interrupted_progress(pid: str) -> None:
    payload = {
        "progress": 0,
        "stage": "",
        "message": _INTERRUPTED_TASK_MESSAGE,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with _progress_lock:
        progress_store[pid] = payload
    try:
        atomic_write_json(project_dir(pid) / "progress.json", payload)
    except Exception as e:
        log.warning("persist interrupted progress failed pid=%s: %s", pid, e)


def _mark_interrupted_task(pid: str, stage: str) -> None:
    try:
        fail_stage(pid, stage, _INTERRUPTED_TASK_MESSAGE)
        append_stage_log(pid, stage, _INTERRUPTED_TASK_MESSAGE)
    except Exception as e:
        log.warning("workflow interruption recovery failed pid=%s stage=%s: %s", pid, stage, e)

    def _apply(project: dict) -> None:
        project["status"] = "error"
        project["error"] = _INTERRUPTED_TASK_MESSAGE
        project["progress"] = 0
        project["progress_msg"] = _INTERRUPTED_TASK_MESSAGE
        project["pipeline_stage"] = None

    try:
        mutate_project(pid, _apply)
    except Exception as e:
        log.warning("project interruption recovery failed pid=%s stage=%s: %s", pid, stage, e)
    _clear_interrupted_progress(pid)


def _completed_asr_artifact(pdir: Path) -> str:
    from app.utils.srt import parse_srt_file

    for name in ("filtered.srt", "raw.srt", "native.srt"):
        path = pdir / name
        if path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_size > 0 and parse_srt_file(str(path)):
                return name
        except (OSError, UnicodeError, ValueError):
            continue
    return ""


def _reconcile_committed_running_stage(
    pid: str,
    pdir: Path,
    project: dict,
    stage: str,
) -> bool:
    project_stage = project.get("pipeline_stage")
    if project_stage not in {None, "", stage}:
        return False

    def clear_matching_pipeline_stage() -> None:
        if project_stage != stage:
            return

        def clear(project_state: dict) -> None:
            if project_state.get("pipeline_stage") == stage:
                project_state["pipeline_stage"] = None

        mutate_project(pid, clear)

    status = project.get("status")
    if stage == "asr" and status == "asr_done":
        artifact = _completed_asr_artifact(pdir)
        if not artifact:
            return False
        clear_matching_pipeline_stage()
        finish_stage(
            pid,
            "asr",
            output_artifact=artifact,
            resume_eligible=True,
        )
        complete_progress(pid, "识别结果已提交")
        return True
    if (
        stage == "translate"
        and status in {"translated", "completed"}
        and project.get("translation_quality_status") == "passed"
    ):
        from app.utils.translation_certification import (
            validate_translation_delivery,
        )
        from app.utils.translation_delivery import translation_delivery_lock

        with translation_delivery_lock(pid) as acquired:
            if not acquired:
                return False
            current_project = load_project(pid)
            validation = validate_translation_delivery(
                current_project,
                pdir,
            )
            if not (validation.valid and validation.passed):
                return False
            clear_matching_pipeline_stage()
            finish_stage(
                pid,
                "translate",
                output_artifact="translated.srt",
                resume_eligible=True,
            )
            complete_progress(pid, "翻译结果已认证并提交")
            return True
    return False


def mark_interrupted_tasks_from_previous_session() -> int:
    """Convert stale running task state from a previous process into retryable errors.

    Worker threads are process-local. After an app restart, a project may still
    have project.json/progress.json/workflow_state.json fields saying a stage is
    running even though no worker can continue it. Mark those projects as failed
    on startup so the UI offers retry/resume instead of showing a frozen task.
    """
    count = 0
    root = Path(PROJECTS_DIR)
    if not root.exists():
        return 0
    for pdir in root.iterdir():
        if pdir.is_symlink() or not pdir.is_dir():
            continue
        if not (pdir / "project.json").is_file():
            continue
        try:
            pid = validate_pid(pdir.name)
            try:
                from app.services.translation_tasks import is_task_registered

                active_worker = is_task_registered(pid)
            except Exception:
                active_worker = False
            if active_worker:
                continue
            project = load_project(pid)
            burn_recovery = recover_burn_output_transaction(pdir, project)
            if burn_recovery != BURN_RECOVERY_NONE:
                project = load_project(pid)
            if burn_recovery == BURN_RECOVERY_COMMITTED:
                finish_stage(
                    pid,
                    "burn",
                    output_artifact=project.get("output_video", ""),
                    resume_eligible=True,
                )
                if not finalize_committed_burn_transaction(pdir, project):
                    raise RuntimeError(
                        "committed burn cleanup could not be finalized"
                    )
                continue
            if burn_recovery == BURN_RECOVERY_REVERTED:
                _mark_interrupted_task(pid, "burn")
                cleanup_orphaned_burn_artifacts(
                    pdir,
                    active_worker=False,
                )
                count += 1
                continue
            if burn_recovery == BURN_RECOVERY_NONE:
                cleanup_orphaned_burn_artifacts(
                    pdir,
                    active_worker=False,
                )
            workflow_stage = _running_stage_from_workflow_state(pid)
            project_stage = project.get("pipeline_stage")
            if project_stage not in _RECOVERABLE_RUNNING_STAGES:
                project_stage = ""
            processing = project.get("status") == "processing"
            stage = workflow_stage or project_stage
            if not stage and processing:
                stage = _stage_from_progress_file(pdir) or "asr"
            if not stage:
                continue
            if _reconcile_committed_running_stage(
                pid,
                pdir,
                project,
                stage,
            ):
                continue
            _mark_interrupted_task(pid, stage)
            count += 1
        except Exception as e:
            log.warning("interrupted task recovery skipped pid=%s: %s", pdir.name, e)
    return count


# --- Cooperative cancellation ---
#
# Registered workers use an immutable task generation as their cancellation
# scope. The empty scope remains for process-local jobs that are not managed
# by the translation task registry.
_cancel_events: Dict[tuple[str, str], threading.Event] = {}
_cancel_lock = threading.Lock()


def prepare_cancel_generation(
    pid: str,
    generation: str,
    *,
    reset_legacy: bool,
) -> None:
    if not isinstance(generation, str) or not generation:
        raise ValueError("cancel generation must be non-empty")
    with _cancel_lock:
        legacy = _cancel_events.get((pid, ""))
        inherit_cancel = bool(
            not reset_legacy and legacy is not None and legacy.is_set()
        )
        for key in [key for key in _cancel_events if key[0] == pid]:
            _cancel_events.pop(key, None)
        event = threading.Event()
        if inherit_cancel:
            event.set()
        _cancel_events[(pid, generation)] = event


def discard_cancel_generation(pid: str, generation: str) -> None:
    if not generation:
        return
    with _cancel_lock:
        event = _cancel_events.get((pid, generation))
        if event is None or not event.is_set():
            _cancel_events.pop((pid, generation), None)


def request_cancel(pid: str, *, generation: str = "") -> None:
    with _cancel_lock:
        ev = _cancel_events.setdefault(
            (pid, generation),
            threading.Event(),
        )
        ev.set()


def is_cancelled(pid: str, *, generation: Optional[str] = None) -> bool:
    with _cancel_lock:
        if generation is not None:
            ev = _cancel_events.get((pid, generation))
            return bool(ev and ev.is_set())
        return any(
            key_pid == pid and event.is_set()
            for (key_pid, _), event in _cancel_events.items()
        )


def reset_cancel(pid: str, *, generation: Optional[str] = None) -> None:
    with _cancel_lock:
        if generation is not None:
            ev = _cancel_events.get((pid, generation))
            if ev is not None:
                ev.clear()
            return
        for (key_pid, _), event in _cancel_events.items():
            if key_pid == pid:
                event.clear()


# Backward-compat aliases (some downstream imports may still reference these by name).
# They resolve lazily via __getattr__ (PEP 562) — supported on Python 3.7+.
def __getattr__(name: str):
    _alias = {"SEM_ASR": "asr", "SEM_TRANSLATE": "translate",
              "SEM_DOWNLOAD": "download", "SEM_BURN": "burn"}
    if name in _alias:
        return get_semaphore(_alias[name])
    raise AttributeError(f"module 'app.engines.scheduler' has no attribute {name!r}")


def _reset_sem_cache_for_testing() -> None:
    """Test helper: clear the cached semaphores so a test can exercise fresh config."""
    with _sem_cache_lock:
        _sem_cache.clear()
