"""Safe concurrent access to per-project JSON state.

Centralizes: pid validation (path-traversal defense), atomic JSON writes
(crash-safe, never leaves a torn file), and per-project locking for
read-modify-write sequences.

Framework-agnostic — does not import FastAPI. The API layer translates the
`ValueError` / `FileNotFoundError` raised here into HTTP responses.
"""
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from app.config import PROJECTS_DIR

PID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_PID_RE = re.compile(PID_PATTERN)


class ProjectFileInvalid(ValueError):
    """Raised when project.json exists but cannot be loaded as a JSON object."""


def validate_pid(pid: str) -> str:
    """Return `pid` unchanged if it is a safe project id, else raise ValueError."""
    if not isinstance(pid, str) or not _PID_RE.match(pid):
        raise ValueError(f"invalid project id: {pid!r}")
    return pid


def project_dir(pid: str) -> Path:
    """Resolve a project directory, rejecting any pid that escapes PROJECTS_DIR."""
    validate_pid(pid)
    root = Path(PROJECTS_DIR).resolve()
    raw_pdir = root / pid
    if raw_pdir.is_symlink():
        raise ValueError(f"project dir is a symlink: {pid!r}")
    pdir = raw_pdir.resolve()
    if not pdir.is_relative_to(root):
        raise ValueError(f"project id escapes projects dir: {pid!r}")
    return pdir


def atomic_write_json(path: Path, data: dict) -> None:
    """Write `data` as JSON to `path` atomically.

    Writes a sibling `<name>.tmp` file then `os.replace`s it into place. On
    failure the original file is left untouched and the `.tmp` is removed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    tmp = Path(tmp_handle.name)
    try:
        with tmp_handle as f:
            json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


_locks: dict = {}
_locks_guard = threading.Lock()


def get_project_lock(pid: str) -> threading.RLock:
    """Return the process-wide RLock for `pid`, creating it on first use."""
    validate_pid(pid)
    lock = _locks.get(pid)
    if lock is None:
        with _locks_guard:
            lock = _locks.get(pid)
            if lock is None:
                lock = threading.RLock()
                _locks[pid] = lock
    return lock


def load_project(pid: str) -> dict:
    """Read project.json. Raises FileNotFoundError if the project is absent.

    No lock is taken — writes go through atomic os.replace, so a reader always
    sees either the complete old file or the complete new file.
    """
    pfile = project_dir(pid) / "project.json"
    if not pfile.exists():
        raise FileNotFoundError(f"project not found: {pid}")
    try:
        with open(pfile, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProjectFileInvalid("Project file is invalid") from exc
    if not isinstance(data, dict):
        raise ProjectFileInvalid("Project file is invalid")
    return data


def mutate_project(
    pid: str,
    fn: Callable[[dict], None],
    *,
    normalize: Optional[Callable[[dict], dict]] = None,
) -> dict:
    """Atomically read-modify-write project.json under the per-pid lock.

    `fn` mutates the loaded dict in place. `normalize` (optional) is applied to
    the freshly loaded dict before `fn` runs (used to backfill default fields).
    Returns the final dict that was written.
    """
    with get_project_lock(pid):
        pfile = project_dir(pid) / "project.json"
        if not pfile.exists():
            raise FileNotFoundError(f"project not found: {pid}")
        try:
            with open(pfile, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProjectFileInvalid("Project file is invalid") from exc
        if not isinstance(data, dict):
            raise ProjectFileInvalid("Project file is invalid")
        if normalize is not None:
            data = normalize(data)
        fn(data)
        atomic_write_json(pfile, data)
        return data
