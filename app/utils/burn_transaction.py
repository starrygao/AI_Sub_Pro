"""Durable, project-local recovery for burn output publication."""

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)

BURN_TRANSACTION_MANIFEST = ".burn-output-transaction.json"
_SCHEMA_VERSION = 1
_TRANSACTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_GENERATION_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def burn_project_generation_hash(project: dict) -> str:
    payload = json.dumps(
        project,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _safe_regular_or_absent(path: Path) -> bool:
    return not _path_lexists(path) or (
        not path.is_symlink() and path.is_file()
    )


def _safe_unlink(path: Path) -> None:
    if not _path_lexists(path):
        return
    if path.is_symlink() or path.is_dir():
        raise RuntimeError(f"unsafe burn transaction path: {path.name}")
    path.unlink()


def _plain_project_filename(value) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    name = Path(value)
    if (
        name.is_absolute()
        or len(name.parts) != 1
        or name.name != value
        or value in {".", ".."}
    ):
        return None
    return value


def new_burn_transaction_manifest(
    *,
    pid: str,
    project: dict,
    stage_path: Path,
    final_path: Path,
    backup_path: Optional[Path],
    had_previous_output: bool,
) -> dict:
    return {
        "schema_version": _SCHEMA_VERSION,
        "transaction_id": uuid.uuid4().hex,
        "project_id": pid,
        "project_generation_hash": burn_project_generation_hash(project),
        "stage_name": Path(stage_path).name,
        "final_name": Path(final_path).name,
        "backup_name": Path(backup_path).name if backup_path else "",
        "had_previous_output": bool(had_previous_output),
    }


def persist_burn_transaction_manifest(pdir: Path, manifest: dict) -> Path:
    pdir = Path(pdir)
    manifest_path = pdir / BURN_TRANSACTION_MANIFEST
    if _path_lexists(manifest_path) and (
        manifest_path.is_symlink() or manifest_path.is_dir()
    ):
        raise RuntimeError("burn transaction manifest path is unsafe")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=pdir,
        prefix=f"{BURN_TRANSACTION_MANIFEST}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        try:
            json.dump(
                manifest,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            handle.close()
            _safe_unlink(temp_path)
            raise
    try:
        os.replace(temp_path, manifest_path)
        _fsync_directory(pdir)
    finally:
        _safe_unlink(temp_path)
    return manifest_path


def remove_burn_transaction_manifest(pdir: Path) -> None:
    pdir = Path(pdir)
    _safe_unlink(pdir / BURN_TRANSACTION_MANIFEST)
    _fsync_directory(pdir)


def sync_burn_transaction_directory(pdir: Path) -> None:
    _fsync_directory(Path(pdir))


def create_burn_recovery_copy(final_path: Path, backup_path: Path) -> None:
    """Create and durably record a same-directory copy of the prior final."""
    final_path = Path(final_path)
    backup_path = Path(backup_path)
    if (
        final_path.parent != backup_path.parent
        or not final_path.is_file()
        or final_path.is_symlink()
        or _path_lexists(backup_path)
    ):
        raise RuntimeError("burn recovery copy path is unsafe")
    try:
        os.link(final_path, backup_path)
    except OSError:
        with final_path.open("rb") as source, backup_path.open("xb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
    else:
        descriptor = os.open(backup_path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    _fsync_directory(final_path.parent)


def _validated_manifest_paths(
    pdir: Path,
    pid: str,
    manifest: dict,
) -> Optional[tuple[Path, Path, Optional[Path]]]:
    if (
        manifest.get("schema_version") != _SCHEMA_VERSION
        or manifest.get("project_id") != pid
        or not isinstance(manifest.get("had_previous_output"), bool)
        or not isinstance(manifest.get("transaction_id"), str)
        or not _TRANSACTION_ID_RE.fullmatch(manifest["transaction_id"])
        or not isinstance(manifest.get("project_generation_hash"), str)
        or not _GENERATION_HASH_RE.fullmatch(
            manifest["project_generation_hash"]
        )
    ):
        return None
    stage_name = _plain_project_filename(manifest.get("stage_name"))
    final_name = _plain_project_filename(manifest.get("final_name"))
    backup_value = manifest.get("backup_name")
    backup_name = (
        _plain_project_filename(backup_value)
        if backup_value
        else None
    )
    had_previous = manifest["had_previous_output"]
    if (
        stage_name is None
        or final_name is None
        or not final_name.endswith("_subtitled.mp4")
        or not stage_name.startswith(f".{final_name}.burn.")
        or not stage_name.endswith(".tmp.mp4")
        or (had_previous and backup_name is None)
        or (not had_previous and backup_value != "")
        or (
            backup_name is not None
            and (
                not backup_name.startswith(f".{final_name}.rollback.")
                or not backup_name.endswith(".mp4")
            )
        )
    ):
        return None
    stage_path = pdir / stage_name
    final_path = pdir / final_name
    backup_path = pdir / backup_name if backup_name else None
    candidates = [stage_path, final_path]
    if backup_path is not None:
        candidates.append(backup_path)
    if not all(_safe_regular_or_absent(path) for path in candidates):
        return None
    return stage_path, final_path, backup_path


def recover_burn_output_transaction(pdir: Path, project: dict) -> bool:
    """Recover one interrupted burn commit, or fail closed without mutation."""
    pdir = Path(pdir)
    manifest_path = pdir / BURN_TRANSACTION_MANIFEST
    if not _path_lexists(manifest_path):
        return False
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(manifest, dict):
        return False
    pid = pdir.name
    validated = _validated_manifest_paths(pdir, pid, manifest)
    if validated is None:
        return False
    stage_path, final_path, backup_path = validated
    transaction_id = manifest["transaction_id"]
    committed = (
        project.get("status") == "completed"
        and project.get("burn_output_transaction_id") == transaction_id
        and isinstance(project.get("output_video"), str)
        and Path(project["output_video"]) == final_path
    )
    if not committed and (
        burn_project_generation_hash(project)
        != manifest["project_generation_hash"]
    ):
        return False
    if committed and not final_path.is_file():
        return False

    try:
        if committed:
            _safe_unlink(stage_path)
            if backup_path is not None:
                _safe_unlink(backup_path)
        elif manifest["had_previous_output"]:
            if backup_path is not None and backup_path.is_file():
                _safe_unlink(final_path)
                os.replace(backup_path, final_path)
            elif not final_path.is_file():
                return False
            _safe_unlink(stage_path)
        else:
            _safe_unlink(final_path)
            _safe_unlink(stage_path)
        _safe_unlink(manifest_path)
        _fsync_directory(pdir)
        return True
    except Exception as exc:
        log.warning(
            "burn transaction recovery failed pid=%s: %s",
            pid,
            exc,
        )
        return False
