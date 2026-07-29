"""Visibility contract for the final translation artifact set."""

import hashlib
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from app.utils.project_store import (
    atomic_write_json,
    fsync_directory,
    fsync_regular_file,
)


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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def promote_staged_files(
    pairs: list[tuple[Path, Path]],
) -> bool:
    """Durably promote one same-directory artifact set.

    Every staged file is synced before the first name becomes visible. After
    all replaces, the directory is synced once and every final byte identity
    is revalidated. Callers keep the delivery sentinel until this returns.
    """
    normalized = [(Path(stage), Path(final)) for stage, final in pairs]
    if not normalized:
        return True
    directory = normalized[0][1].parent
    if any(
        stage.parent != directory or final.parent != directory
        for stage, final in normalized
    ):
        raise ValueError("staged delivery files must share one directory")
    expected_hashes = {}
    for stage, final in normalized:
        fsync_regular_file(stage)
        expected_hashes[final] = _file_sha256(stage)
    for stage, final in normalized:
        os.replace(stage, final)
    durable = fsync_directory(directory)
    for _stage, final in normalized:
        if (
            final.is_symlink()
            or not final.is_file()
            or _file_sha256(final) != expected_hashes[final]
        ):
            raise RuntimeError(
                f"promoted delivery artifact identity mismatch: {final.name}"
            )
    return durable


def hide_invalid_translation_artifact_fields(project: dict, project_path: Path) -> dict:
    if translation_delivery_is_invalid(project_path):
        project["translated_srt"] = None
        project["bilingual_srt"] = None
    return project
