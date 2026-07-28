"""Visibility contract for the final translation artifact set."""

import os
import threading
from contextlib import contextmanager
from pathlib import Path

from app.utils.project_store import atomic_write_json


TRANSLATION_DELIVERY_SENTINEL = ".translation_delivery_in_progress"
TRANSLATION_DELIVERY_ARTIFACTS = frozenset({
    "translated.srt",
    "bilingual.srt",
})
_delivery_locks_guard = threading.Lock()
_delivery_locks = {}


class _DeliveryLockEntry:
    def __init__(self):
        self.lock = threading.RLock()
        self.users = 0


class _DeliveryLockLease:
    def __init__(self, key: str, entry: _DeliveryLockEntry, acquired: bool):
        self._key = key
        self._entry = entry
        self.acquired = acquired
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self.acquired:
            self._entry.lock.release()
        with _delivery_locks_guard:
            self._entry.users -= 1
            if (
                self._entry.users == 0
                and _delivery_locks.get(self._key) is self._entry
            ):
                _delivery_locks.pop(self._key, None)


def _acquire_translation_delivery_lock(
    project_key: str,
    *,
    blocking: bool,
) -> _DeliveryLockLease:
    key = str(project_key)
    with _delivery_locks_guard:
        entry = _delivery_locks.get(key)
        if entry is None:
            entry = _DeliveryLockEntry()
            _delivery_locks[key] = entry
        entry.users += 1
    acquired = entry.lock.acquire(blocking=blocking)
    return _DeliveryLockLease(key, entry, acquired)


@contextmanager
def translation_delivery_lock(project_key: str, *, blocking: bool = True):
    """Hold the per-project delivery lock and report non-blocking contention."""
    lease = _acquire_translation_delivery_lock(project_key, blocking=blocking)
    try:
        yield lease.acquired
    finally:
        lease.release()


def translation_delivery_sentinel_path(project_path: Path) -> Path:
    return Path(project_path) / TRANSLATION_DELIVERY_SENTINEL


def translation_delivery_is_invalid(project_path: Path) -> bool:
    """Return true even for a malformed or symlinked sentinel."""
    return os.path.lexists(translation_delivery_sentinel_path(project_path))


def mark_translation_delivery_invalid(project_path: Path) -> Path:
    """Atomically hide the final translation artifact set."""
    sentinel = translation_delivery_sentinel_path(project_path)
    atomic_write_json(sentinel, {"status": "in_progress"})
    return sentinel


def hide_invalid_translation_artifact_fields(project: dict, project_path: Path) -> dict:
    if translation_delivery_is_invalid(project_path):
        project["translated_srt"] = None
        project["bilingual_srt"] = None
    return project
