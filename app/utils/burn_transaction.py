"""Crash-safe, project-local publication of burned video outputs."""

from __future__ import annotations

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
BURN_RECOVERY_NONE = "none"
BURN_RECOVERY_REVERTED = "reverted"
BURN_RECOVERY_COMMITTED = "committed"
BURN_RECOVERY_BLOCKED = "blocked"

_SCHEMA_VERSION = 2
_TRANSACTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_GENERATION_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TRANSACTION_STATES = {
    "prepared",
    "burning",
    "staged",
    "backed_up",
    "promoted",
    "project_committed",
}
_SNAPSHOT_SUFFIXES = {"srt", "ass", "ssa", "vtt"}
_ORPHAN_STAGE_RE = re.compile(
    r"^\.(?!\.)[^/]+_subtitled\.mp4\.burn\.[0-9a-f]{32}"
    r"\.tmp\.mp4$"
)
_ORPHAN_BACKUP_RE = re.compile(
    r"^\.(?!\.)[^/]+_subtitled\.mp4\.rollback\.[0-9a-f]{32}"
    r"\.mp4$"
)
_ORPHAN_SNAPSHOT_RE = re.compile(
    r"^\.burn-subtitle\.[0-9a-f]{32}\.[0-9]+\."
    r"(?:srt|ass|ssa|vtt)$"
)
_ORPHAN_COPY_TEMP_RE = re.compile(
    r"^\.\.(?!\.)[^/]+_subtitled\.mp4\.rollback\.[0-9a-f]{32}"
    r"\.mp4\.copy\.[0-9a-f]{32}\.tmp$"
)
_ORPHAN_MANIFEST_TEMP_RE = re.compile(
    rf"^{re.escape(BURN_TRANSACTION_MANIFEST)}\.[A-Za-z0-9_-]+\.tmp$"
)


def burn_project_generation_hash(project: dict) -> str:
    volatile = {
        "status",
        "pipeline_stage",
        "error",
        "progress",
        "progress_msg",
        "updated_at",
        "output_video",
        "burn_output_transaction_id",
    }
    stable_project = {
        key: value
        for key, value in project.items()
        if key not in volatile
    }
    payload = json.dumps(
        stable_project,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, f"sha256:{digest.hexdigest()}"


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"burn transaction file is unsafe: {path.name}")
    descriptor = os.open(path, os.O_RDONLY)
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


def _valid_identity(size, digest, *, allow_empty: bool) -> bool:
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(digest, str)
    ):
        return False
    if allow_empty and size == 0 and digest == "":
        return True
    return size > 0 and bool(_GENERATION_HASH_RE.fullmatch(digest))


def _identity_matches(path: Path, size: int, digest: str) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return file_identity(path) == (size, digest)
    except OSError:
        return False


def new_burn_transaction_manifest(
    *,
    pid: str,
    project: dict,
    stage_path: Path,
    final_path: Path,
    backup_path: Optional[Path],
    had_previous_output: bool,
    transaction_id: Optional[str] = None,
    snapshot_paths: tuple[Path, ...] | list[Path] = (),
    state: str = "staged",
) -> dict:
    transaction_id = transaction_id or uuid.uuid4().hex
    if not _TRANSACTION_ID_RE.fullmatch(transaction_id):
        raise ValueError("invalid burn transaction id")
    previous_size = 0
    previous_hash = ""
    if had_previous_output:
        previous_size, previous_hash = file_identity(final_path)
    staged_size = 0
    staged_hash = ""
    if state in {"staged", "backed_up", "promoted", "project_committed"}:
        staged_size, staged_hash = file_identity(stage_path)
    return {
        "schema_version": _SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "project_id": pid,
        "project_generation_hash": burn_project_generation_hash(project),
        "state": state,
        "stage_name": Path(stage_path).name,
        "final_name": Path(final_path).name,
        "backup_name": Path(backup_path).name if backup_path else "",
        "snapshot_names": [Path(path).name for path in snapshot_paths],
        "had_previous_output": bool(had_previous_output),
        "previous_output_size": previous_size,
        "previous_output_hash": previous_hash,
        "staged_output_size": staged_size,
        "staged_output_hash": staged_hash,
    }


def _write_manifest_temp(pdir: Path, manifest: dict) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=pdir,
        prefix=f"{BURN_TRANSACTION_MANIFEST}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        os.chmod(temp_path, 0o600)
        with handle:
            json.dump(
                manifest,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        return temp_path
    except Exception:
        handle.close()
        _safe_unlink(temp_path)
        raise


def persist_burn_transaction_manifest(pdir: Path, manifest: dict) -> Path:
    """Create the manifest without ever replacing an existing transaction."""
    pdir = Path(pdir)
    manifest_path = pdir / BURN_TRANSACTION_MANIFEST
    if _path_lexists(manifest_path):
        raise FileExistsError(
            f"burn transaction already exists: {manifest_path.name}"
        )
    temp_path = _write_manifest_temp(pdir, manifest)
    try:
        # Linking a private temporary manifest gives create-exclusive publish
        # semantics; it is unrelated to recovery-copy creation.
        os.link(temp_path, manifest_path)
        _fsync_directory(pdir)
    finally:
        _safe_unlink(temp_path)
    return manifest_path


def update_burn_transaction_manifest(pdir: Path, manifest: dict) -> Path:
    pdir = Path(pdir)
    manifest_path = pdir / BURN_TRANSACTION_MANIFEST
    current = read_burn_transaction_manifest(pdir)
    if (
        current is None
        or current.get("transaction_id") != manifest.get("transaction_id")
    ):
        raise RuntimeError("burn transaction identity changed")
    temp_path = _write_manifest_temp(pdir, manifest)
    try:
        os.replace(temp_path, manifest_path)
        _fsync_directory(pdir)
    finally:
        if _path_lexists(temp_path):
            _safe_unlink(temp_path)
    return manifest_path


def read_burn_transaction_manifest(pdir: Path) -> Optional[dict]:
    manifest_path = Path(pdir) / BURN_TRANSACTION_MANIFEST
    if (
        not _path_lexists(manifest_path)
        or manifest_path.is_symlink()
        or not manifest_path.is_file()
    ):
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def remove_burn_transaction_manifest(pdir: Path) -> None:
    pdir = Path(pdir)
    _safe_unlink(pdir / BURN_TRANSACTION_MANIFEST)
    _fsync_directory(pdir)


def sync_burn_transaction_directory(pdir: Path) -> None:
    _fsync_directory(Path(pdir))


def validate_burn_recovery_copy(
    backup_path: Path,
    *,
    expected_size: int,
    expected_hash: str,
) -> bool:
    return _identity_matches(
        Path(backup_path),
        expected_size,
        expected_hash,
    )


def create_burn_recovery_copy(
    final_path: Path,
    backup_path: Path,
    *,
    expected_size: int,
    expected_hash: str,
) -> None:
    """Create a private independent copy, then atomically publish it."""
    final_path = Path(final_path)
    backup_path = Path(backup_path)
    if (
        final_path.parent != backup_path.parent
        or final_path.is_symlink()
        or not final_path.is_file()
        or _path_lexists(backup_path)
        or not _identity_matches(
            final_path,
            expected_size,
            expected_hash,
        )
    ):
        raise RuntimeError("burn recovery copy path or source is unsafe")

    temp_path = backup_path.parent / (
        f".{backup_path.name}.copy.{uuid.uuid4().hex}.tmp"
    )
    descriptor = os.open(
        temp_path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            with final_path.open("rb") as source:
                shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        if (
            not validate_burn_recovery_copy(
                temp_path,
                expected_size=expected_size,
                expected_hash=expected_hash,
            )
            or not _identity_matches(
                final_path,
                expected_size,
                expected_hash,
            )
        ):
            raise RuntimeError("burn recovery copy identity mismatch")
        os.replace(temp_path, backup_path)
        if not validate_burn_recovery_copy(
            backup_path,
            expected_size=expected_size,
            expected_hash=expected_hash,
        ):
            raise RuntimeError("burn recovery copy identity mismatch")
        _fsync_directory(final_path.parent)
    finally:
        if _path_lexists(temp_path):
            _safe_unlink(temp_path)
        if (
            _path_lexists(backup_path)
            and not validate_burn_recovery_copy(
                backup_path,
                expected_size=expected_size,
                expected_hash=expected_hash,
            )
        ):
            _safe_unlink(backup_path)


def _validated_manifest_paths(
    pdir: Path,
    pid: str,
    manifest: dict,
) -> Optional[tuple[Path, Path, Optional[Path], tuple[Path, ...]]]:
    transaction_id = manifest.get("transaction_id")
    state = manifest.get("state")
    if (
        manifest.get("schema_version") != _SCHEMA_VERSION
        or manifest.get("project_id") != pid
        or not isinstance(transaction_id, str)
        or not _TRANSACTION_ID_RE.fullmatch(transaction_id)
        or state not in _TRANSACTION_STATES
        or not isinstance(manifest.get("had_previous_output"), bool)
        or not isinstance(manifest.get("project_generation_hash"), str)
        or not _GENERATION_HASH_RE.fullmatch(
            manifest["project_generation_hash"]
        )
        or not _valid_identity(
            manifest.get("previous_output_size"),
            manifest.get("previous_output_hash"),
            allow_empty=not manifest["had_previous_output"],
        )
        or not _valid_identity(
            manifest.get("staged_output_size"),
            manifest.get("staged_output_hash"),
            allow_empty=state in {"prepared", "burning"},
        )
    ):
        return None
    if (
        manifest["had_previous_output"]
        and not _GENERATION_HASH_RE.fullmatch(
            manifest["previous_output_hash"]
        )
    ):
        return None
    if (
        not manifest["had_previous_output"]
        and (
            manifest["previous_output_size"] != 0
            or manifest["previous_output_hash"] != ""
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
    snapshot_values = manifest.get("snapshot_names")
    if not isinstance(snapshot_values, list):
        return None
    snapshot_names = [
        _plain_project_filename(value) for value in snapshot_values
    ]
    expected_stage = (
        f".{final_name}.burn.{transaction_id}.tmp.mp4"
        if final_name is not None
        else ""
    )
    expected_backup = (
        f".{final_name}.rollback.{transaction_id}.mp4"
        if final_name is not None
        else ""
    )
    if (
        stage_name is None
        or final_name is None
        or not final_name.endswith("_subtitled.mp4")
        or stage_name != expected_stage
        or (
            manifest["had_previous_output"]
            and backup_name != expected_backup
        )
        or (
            not manifest["had_previous_output"]
            and backup_value != ""
        )
        or any(name is None for name in snapshot_names)
        or len(set(snapshot_names)) != len(snapshot_names)
    ):
        return None
    for name in snapshot_names:
        match = re.fullmatch(
            rf"\.burn-subtitle\.{transaction_id}\.([0-9]+)\."
            rf"({'|'.join(sorted(_SNAPSHOT_SUFFIXES))})",
            name or "",
        )
        if match is None:
            return None

    stage_path = pdir / stage_name
    final_path = pdir / final_name
    backup_path = pdir / backup_name if backup_name else None
    snapshot_paths = tuple(pdir / name for name in snapshot_names if name)
    candidates = [stage_path, final_path, *snapshot_paths]
    if backup_path is not None:
        candidates.append(backup_path)
    if not all(_safe_regular_or_absent(path) for path in candidates):
        return None
    return stage_path, final_path, backup_path, snapshot_paths


def validated_burn_transaction(
    pdir: Path,
) -> Optional[tuple[dict, Path, Path, Optional[Path], tuple[Path, ...]]]:
    pdir = Path(pdir)
    manifest = read_burn_transaction_manifest(pdir)
    if manifest is None:
        return None
    validated = _validated_manifest_paths(pdir, pdir.name, manifest)
    if validated is None:
        return None
    stage, final, backup, snapshots = validated
    return manifest, stage, final, backup, snapshots


def mark_burn_transaction_burning(pdir: Path, transaction_id: str) -> dict:
    validated = validated_burn_transaction(pdir)
    if validated is None or validated[0]["transaction_id"] != transaction_id:
        raise RuntimeError("burn transaction is invalid")
    manifest = dict(validated[0])
    manifest["state"] = "burning"
    update_burn_transaction_manifest(pdir, manifest)
    return manifest


def mark_burn_transaction_staged(
    pdir: Path,
    transaction_id: str,
) -> dict:
    validated = validated_burn_transaction(pdir)
    if validated is None or validated[0]["transaction_id"] != transaction_id:
        raise RuntimeError("burn transaction is invalid")
    manifest, stage, _, _, _ = validated
    os.chmod(stage, 0o600)
    _fsync_regular_file(stage)
    size, digest = file_identity(stage)
    if size <= 0:
        raise RuntimeError("burn output stage is empty")
    updated = dict(manifest)
    updated.update({
        "state": "staged",
        "staged_output_size": size,
        "staged_output_hash": digest,
    })
    update_burn_transaction_manifest(pdir, updated)
    return updated


def mark_burn_transaction_state(
    pdir: Path,
    transaction_id: str,
    state: str,
) -> dict:
    if state not in _TRANSACTION_STATES:
        raise ValueError("invalid burn transaction state")
    validated = validated_burn_transaction(pdir)
    if validated is None or validated[0]["transaction_id"] != transaction_id:
        raise RuntimeError("burn transaction is invalid")
    manifest = dict(validated[0])
    manifest["state"] = state
    update_burn_transaction_manifest(pdir, manifest)
    return manifest


def _cleanup_transaction_artifacts(
    *,
    stage: Path,
    backup: Optional[Path],
    snapshots: tuple[Path, ...],
) -> None:
    _safe_unlink(stage)
    if backup is not None:
        _safe_unlink(backup)
    for snapshot in snapshots:
        _safe_unlink(snapshot)


def abort_unpromoted_burn_transaction(
    pdir: Path,
    transaction_id: str,
) -> bool:
    """Discard one validated transaction before it can replace the final."""
    pdir = Path(pdir)
    validated = validated_burn_transaction(pdir)
    if validated is None:
        return False
    manifest, stage, final, backup, snapshots = validated
    if (
        manifest["transaction_id"] != transaction_id
        or manifest["state"] not in {"prepared", "burning", "staged"}
    ):
        return False
    if manifest["had_previous_output"]:
        final_is_unchanged = _identity_matches(
            final,
            manifest["previous_output_size"],
            manifest["previous_output_hash"],
        )
    else:
        final_is_unchanged = not _path_lexists(final)
    if not final_is_unchanged:
        return False
    try:
        _cleanup_transaction_artifacts(
            stage=stage,
            backup=backup,
            snapshots=snapshots,
        )
        _fsync_directory(pdir)
        remove_burn_transaction_manifest(pdir)
        return True
    except Exception as exc:
        log.warning(
            "unpromoted burn cleanup deferred pid=%s: %s",
            pdir.name,
            exc,
        )
        return False


def _restore_verified_backup(
    backup: Path,
    final: Path,
    *,
    expected_size: int,
    expected_hash: str,
) -> bool:
    if not validate_burn_recovery_copy(
        backup,
        expected_size=expected_size,
        expected_hash=expected_hash,
    ):
        return False
    try:
        os.replace(backup, final)
        _fsync_directory(final.parent)
    except OSError:
        if not (
            not _path_lexists(backup)
            and _identity_matches(
                final,
                expected_size,
                expected_hash,
            )
        ):
            raise
    return _identity_matches(final, expected_size, expected_hash)


def recover_burn_output_transaction(pdir: Path, project: dict) -> str:
    """Recover one interrupted transaction without guessing file identity."""
    pdir = Path(pdir)
    manifest_path = pdir / BURN_TRANSACTION_MANIFEST
    if not _path_lexists(manifest_path):
        return BURN_RECOVERY_NONE
    validated = validated_burn_transaction(pdir)
    if validated is None:
        return BURN_RECOVERY_BLOCKED
    manifest, stage, final, backup, snapshots = validated
    transaction_id = manifest["transaction_id"]
    committed = (
        project.get("status") == "completed"
        and project.get("burn_output_transaction_id") == transaction_id
        and isinstance(project.get("output_video"), str)
        and Path(project["output_video"]) == final
    )
    if committed:
        if not _identity_matches(
            final,
            manifest["staged_output_size"],
            manifest["staged_output_hash"],
        ):
            return BURN_RECOVERY_BLOCKED
        return BURN_RECOVERY_COMMITTED
    if (
        burn_project_generation_hash(project)
        != manifest["project_generation_hash"]
    ):
        if (
            manifest["state"] in {"prepared", "burning", "staged"}
            and abort_unpromoted_burn_transaction(
                pdir,
                transaction_id,
            )
        ):
            return BURN_RECOVERY_REVERTED
        return BURN_RECOVERY_BLOCKED

    try:
        if manifest["had_previous_output"]:
            final_is_previous = _identity_matches(
                final,
                manifest["previous_output_size"],
                manifest["previous_output_hash"],
            )
            backup_is_previous = bool(
                backup is not None
                and validate_burn_recovery_copy(
                    backup,
                    expected_size=manifest["previous_output_size"],
                    expected_hash=manifest["previous_output_hash"],
                )
            )
            if not final_is_previous:
                if not backup_is_previous or backup is None:
                    return BURN_RECOVERY_BLOCKED
                if not _restore_verified_backup(
                    backup,
                    final,
                    expected_size=manifest["previous_output_size"],
                    expected_hash=manifest["previous_output_hash"],
                ):
                    return BURN_RECOVERY_BLOCKED
            elif backup is not None:
                _safe_unlink(backup)
        else:
            if _path_lexists(final):
                if not _identity_matches(
                    final,
                    manifest["staged_output_size"],
                    manifest["staged_output_hash"],
                ):
                    return BURN_RECOVERY_BLOCKED
                _safe_unlink(final)
            # The final output must be durably absent before recovery
            # evidence can be removed. This also closes an after-effect
            # restart where the unlink succeeded but its first fsync failed.
            _fsync_directory(pdir)

        _cleanup_transaction_artifacts(
            stage=stage,
            backup=backup,
            snapshots=snapshots,
        )
        remove_burn_transaction_manifest(pdir)
        _fsync_directory(pdir)
        return BURN_RECOVERY_REVERTED
    except Exception as exc:
        # os.replace may report failure after the directory entry changed.
        if (
            manifest["had_previous_output"]
            and _identity_matches(
                final,
                manifest["previous_output_size"],
                manifest["previous_output_hash"],
            )
            and (backup is None or not _path_lexists(backup))
        ):
            try:
                _cleanup_transaction_artifacts(
                    stage=stage,
                    backup=backup,
                    snapshots=snapshots,
                )
                remove_burn_transaction_manifest(pdir)
                return BURN_RECOVERY_REVERTED
            except Exception:
                pass
        log.warning(
            "burn transaction recovery blocked pid=%s: %s",
            pdir.name,
            exc,
        )
        return BURN_RECOVERY_BLOCKED


def finalize_committed_burn_transaction(
    pdir: Path,
    project: dict,
) -> bool:
    """Remove recovery evidence only after project and workflow are durable."""
    pdir = Path(pdir)
    validated = validated_burn_transaction(pdir)
    if validated is None:
        return False
    manifest, stage, final, backup, snapshots = validated
    if not (
        project.get("status") == "completed"
        and project.get("burn_output_transaction_id")
        == manifest["transaction_id"]
        and project.get("output_video") == str(final)
        and _identity_matches(
            final,
            manifest["staged_output_size"],
            manifest["staged_output_hash"],
        )
    ):
        return False
    try:
        _cleanup_transaction_artifacts(
            stage=stage,
            backup=backup,
            snapshots=snapshots,
        )
        remove_burn_transaction_manifest(pdir)
        return True
    except Exception as exc:
        log.warning(
            "committed burn cleanup deferred pid=%s: %s",
            pdir.name,
            exc,
        )
        return False


def cleanup_orphaned_burn_artifacts(
    pdir: Path,
    *,
    active_worker: bool,
) -> int:
    """Remove only exact hidden transaction artifacts with no manifest."""
    pdir = Path(pdir)
    if active_worker or _path_lexists(pdir / BURN_TRANSACTION_MANIFEST):
        return 0
    removed = 0
    for path in pdir.iterdir():
        name = path.name
        if not any(regex.fullmatch(name) for regex in (
            _ORPHAN_STAGE_RE,
            _ORPHAN_BACKUP_RE,
            _ORPHAN_SNAPSHOT_RE,
            _ORPHAN_COPY_TEMP_RE,
            _ORPHAN_MANIFEST_TEMP_RE,
        )):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            log.warning(
                "orphan burn cleanup failed pid=%s file=%s: %s",
                pdir.name,
                name,
                exc,
            )
    if removed:
        _fsync_directory(pdir)
    return removed
