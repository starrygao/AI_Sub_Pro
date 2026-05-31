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
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, Optional

from app import config as cfg
from app.config import PROJECTS_DIR
from app.utils.project_store import atomic_write_json, project_dir, validate_pid

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
    # Persist outside lock; readers in other workers poll this file.
    try:
        atomic_write_json(project_dir(pid) / "progress.json", payload)
    except Exception as e:
        log.warning("persist progress failed pid=%s: %s", pid, e)


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


def get_progress(pid: str) -> Optional[dict]:
    try:
        fp = project_dir(pid) / "progress.json"
    except ValueError:
        return None
    if fp.exists():
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("progress payload is not an object")
            data = _normalize_progress_payload(data)
            with _progress_lock:
                progress_store[pid] = data
            return dict(data)
        except Exception as e:
            log.warning("load progress failed pid=%s: %s", pid, e)
    with _progress_lock:
        if pid not in progress_store:
            return None
        data = progress_store[pid]
        if not isinstance(data, dict):
            return None
        data = _normalize_progress_payload(data)
        progress_store[pid] = data
        return dict(data)


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


# --- Cooperative cancellation ---
_cancel_events: Dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


def request_cancel(pid: str) -> None:
    with _cancel_lock:
        ev = _cancel_events.setdefault(pid, threading.Event())
        ev.set()


def is_cancelled(pid: str) -> bool:
    with _cancel_lock:
        ev = _cancel_events.get(pid)
    return bool(ev and ev.is_set())


def reset_cancel(pid: str) -> None:
    with _cancel_lock:
        ev = _cancel_events.get(pid)
        if ev is not None:
            ev.clear()


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
