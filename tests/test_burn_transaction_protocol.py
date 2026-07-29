import hashlib
import json
import os
from pathlib import Path

import pytest


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _manifest(
    pdir: Path,
    *,
    transaction_id: str,
    project: dict,
    had_previous_output: bool,
    state: str,
) -> tuple[dict, Path, Path, Path]:
    from app.utils.burn_transaction import burn_project_generation_hash

    final = pdir / "movie_subtitled.mp4"
    stage = pdir / (
        f".movie_subtitled.mp4.burn.{transaction_id}.tmp.mp4"
    )
    backup = pdir / (
        f".movie_subtitled.mp4.rollback.{transaction_id}.mp4"
    )
    old = b"old-final"
    new = b"new-final"
    manifest = {
        "schema_version": 2,
        "transaction_id": transaction_id,
        "project_id": pdir.name,
        "project_generation_hash": burn_project_generation_hash(project),
        "state": state,
        "stage_name": stage.name,
        "final_name": final.name,
        "backup_name": backup.name if had_previous_output else "",
        "snapshot_names": [],
        "had_previous_output": had_previous_output,
        "previous_output_size": len(old) if had_previous_output else 0,
        "previous_output_hash": _sha(old) if had_previous_output else "",
        "staged_output_size": len(new),
        "staged_output_hash": _sha(new),
    }
    return manifest, final, stage, backup


def test_persist_burn_manifest_is_create_exclusive(tmp_path):
    from app.utils.burn_transaction import (
        BURN_TRANSACTION_MANIFEST,
        persist_burn_transaction_manifest,
    )

    path = tmp_path / BURN_TRANSACTION_MANIFEST
    path.write_bytes(b"pending-transaction")

    with pytest.raises(FileExistsError):
        persist_burn_transaction_manifest(
            tmp_path,
            {"schema_version": 2},
        )

    assert path.read_bytes() == b"pending-transaction"


def test_committed_recovery_rejects_tampered_final_and_preserves_backup(
    tmp_path,
):
    from app.utils.burn_transaction import (
        BURN_RECOVERY_BLOCKED,
        BURN_TRANSACTION_MANIFEST,
        recover_burn_output_transaction,
    )

    pid = tmp_path.name
    transaction_id = "a" * 32
    initial = {
        "id": pid,
        "status": "processing",
        "pipeline_stage": "burn",
    }
    manifest, final, stage, backup = _manifest(
        tmp_path,
        transaction_id=transaction_id,
        project=initial,
        had_previous_output=True,
        state="project_committed",
    )
    final.write_bytes(b"TAMPERED")
    backup.write_bytes(b"old-final")
    committed = {
        **initial,
        "status": "completed",
        "pipeline_stage": None,
        "output_video": str(final),
        "burn_output_transaction_id": transaction_id,
    }
    (tmp_path / BURN_TRANSACTION_MANIFEST).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    assert (
        recover_burn_output_transaction(tmp_path, committed)
        == BURN_RECOVERY_BLOCKED
    )
    assert final.read_bytes() == b"TAMPERED"
    assert backup.read_bytes() == b"old-final"
    assert (tmp_path / BURN_TRANSACTION_MANIFEST).is_file()
    assert not stage.exists()


def test_recovery_handles_backup_replace_after_effect_idempotently(
    tmp_path,
    monkeypatch,
):
    from app.utils import burn_transaction

    pid = tmp_path.name
    transaction_id = "b" * 32
    project = {
        "id": pid,
        "status": "processing",
        "pipeline_stage": "burn",
    }
    manifest, final, stage, backup = _manifest(
        tmp_path,
        transaction_id=transaction_id,
        project=project,
        had_previous_output=True,
        state="promoted",
    )
    final.write_bytes(b"new-final")
    backup.write_bytes(b"old-final")
    (tmp_path / burn_transaction.BURN_TRANSACTION_MANIFEST).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    real_replace = burn_transaction.os.replace
    injected = {"done": False}

    def replace_then_raise(source, destination):
        if Path(source) == backup and Path(destination) == final:
            real_replace(source, destination)
            if not injected["done"]:
                injected["done"] = True
                raise OSError("injected restore after-effect")
            return
        return real_replace(source, destination)

    monkeypatch.setattr(
        burn_transaction.os,
        "replace",
        replace_then_raise,
    )

    assert (
        burn_transaction.recover_burn_output_transaction(
            tmp_path,
            project,
        )
        == burn_transaction.BURN_RECOVERY_REVERTED
    )
    assert final.read_bytes() == b"old-final"
    assert not backup.exists()
    assert not (
        tmp_path / burn_transaction.BURN_TRANSACTION_MANIFEST
    ).exists()
    assert (
        burn_transaction.recover_burn_output_transaction(
            tmp_path,
            project,
        )
        == burn_transaction.BURN_RECOVERY_NONE
    )


def test_orphan_cleanup_is_strict_and_skips_active_worker(
    tmp_path,
):
    from app.utils.burn_transaction import cleanup_orphaned_burn_artifacts

    tx = "c" * 32
    safe_stage = tmp_path / (
        f".movie_subtitled.mp4.burn.{tx}.tmp.mp4"
    )
    safe_snapshot = tmp_path / f".burn-subtitle.{tx}.0.srt"
    lookalike = tmp_path / (
        f".movie_subtitled.mp4.burn.{tx}.tmp.mp4.keep"
    )
    safe_stage.write_bytes(b"stage")
    safe_snapshot.write_bytes(b"snapshot")
    lookalike.write_bytes(b"keep")

    assert (
        cleanup_orphaned_burn_artifacts(
            tmp_path,
            active_worker=True,
        )
        == 0
    )
    assert safe_stage.is_file()
    assert safe_snapshot.is_file()

    assert (
        cleanup_orphaned_burn_artifacts(
            tmp_path,
            active_worker=False,
        )
        == 2
    )
    assert not safe_stage.exists()
    assert not safe_snapshot.exists()
    assert lookalike.read_bytes() == b"keep"


def test_orphan_cleanup_refuses_symlink(tmp_path):
    from app.utils.burn_transaction import cleanup_orphaned_burn_artifacts

    outside = tmp_path.parent / f"{tmp_path.name}-outside.mp4"
    outside.write_bytes(b"outside")
    tx = "d" * 32
    orphan = tmp_path / (
        f".movie_subtitled.mp4.burn.{tx}.tmp.mp4"
    )
    orphan.symlink_to(outside)

    assert (
        cleanup_orphaned_burn_artifacts(
            tmp_path,
            active_worker=False,
        )
        == 0
    )
    assert orphan.is_symlink()
    assert outside.read_bytes() == b"outside"


def test_first_output_rollback_durably_unlinks_final_before_manifest(
    tmp_path,
    monkeypatch,
):
    """Catches recovery evidence disappearing before final deletion is durable."""
    from app.utils import burn_transaction

    transaction_id = "e" * 32
    project = {
        "id": tmp_path.name,
        "status": "processing",
        "pipeline_stage": "burn",
    }
    manifest, final, stage, _ = _manifest(
        tmp_path,
        transaction_id=transaction_id,
        project=project,
        had_previous_output=False,
        state="promoted",
    )
    final.write_bytes(b"new-final")
    (tmp_path / burn_transaction.BURN_TRANSACTION_MANIFEST).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    events = []
    real_safe_unlink = burn_transaction._safe_unlink
    real_fsync_directory = burn_transaction._fsync_directory

    def recording_unlink(path):
        events.append(("unlink", Path(path).name))
        return real_safe_unlink(path)

    def recording_fsync(directory):
        events.append(("fsync_directory", Path(directory).name))
        return real_fsync_directory(directory)

    monkeypatch.setattr(
        burn_transaction,
        "_safe_unlink",
        recording_unlink,
    )
    monkeypatch.setattr(
        burn_transaction,
        "_fsync_directory",
        recording_fsync,
    )

    assert (
        burn_transaction.recover_burn_output_transaction(
            tmp_path,
            project,
        )
        == burn_transaction.BURN_RECOVERY_REVERTED
    )

    final_unlink = events.index(("unlink", final.name))
    manifest_unlink = events.index(
        ("unlink", burn_transaction.BURN_TRANSACTION_MANIFEST)
    )
    assert (
        "fsync_directory",
        tmp_path.name,
    ) in events[final_unlink + 1:manifest_unlink]


def test_first_output_rollback_fsync_failure_keeps_manifest_for_restart(
    tmp_path,
    monkeypatch,
):
    """Catches a crash window where an uncommitted final can revive untracked."""
    from app.utils import burn_transaction

    transaction_id = "f" * 32
    project = {
        "id": tmp_path.name,
        "status": "processing",
        "pipeline_stage": "burn",
    }
    manifest, final, stage, _ = _manifest(
        tmp_path,
        transaction_id=transaction_id,
        project=project,
        had_previous_output=False,
        state="promoted",
    )
    final.write_bytes(b"new-final")
    manifest_path = tmp_path / burn_transaction.BURN_TRANSACTION_MANIFEST
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    real_fsync_directory = burn_transaction._fsync_directory
    injected = {"done": False}

    def fail_first_directory_sync(directory):
        if not injected["done"]:
            injected["done"] = True
            raise OSError("injected rollback directory fsync failure")
        return real_fsync_directory(directory)

    monkeypatch.setattr(
        burn_transaction,
        "_fsync_directory",
        fail_first_directory_sync,
    )

    assert (
        burn_transaction.recover_burn_output_transaction(
            tmp_path,
            project,
        )
        == burn_transaction.BURN_RECOVERY_BLOCKED
    )
    assert not final.exists()
    assert manifest_path.is_file()

    monkeypatch.setattr(
        burn_transaction,
        "_fsync_directory",
        real_fsync_directory,
    )
    assert (
        burn_transaction.recover_burn_output_transaction(
            tmp_path,
            project,
        )
        == burn_transaction.BURN_RECOVERY_REVERTED
    )
    assert not final.exists()
    assert not stage.exists()
    assert not manifest_path.exists()


@pytest.mark.parametrize("had_previous_output", [False, True])
def test_generation_mismatch_abort_fsync_failure_recovers_on_restart(
    tmp_path,
    monkeypatch,
    had_previous_output,
):
    """Catches a safe unpromoted transaction becoming permanently blocked."""
    from app.utils import burn_transaction

    transaction_id = "1" * 32
    original_project = {
        "id": tmp_path.name,
        "status": "processing",
        "pipeline_stage": "burn",
        "target_language": "简体中文",
    }
    current_project = {
        **original_project,
        "target_language": "繁體中文",
    }
    manifest, final, stage, backup = _manifest(
        tmp_path,
        transaction_id=transaction_id,
        project=original_project,
        had_previous_output=had_previous_output,
        state="staged",
    )
    if had_previous_output:
        final.write_bytes(b"old-final")
    stage.write_bytes(b"new-final")
    manifest_path = tmp_path / burn_transaction.BURN_TRANSACTION_MANIFEST
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    real_fsync_directory = burn_transaction._fsync_directory
    injected = {"done": False}

    def fail_first_directory_sync(directory):
        if not injected["done"]:
            injected["done"] = True
            raise OSError("injected generation abort fsync failure")
        return real_fsync_directory(directory)

    monkeypatch.setattr(
        burn_transaction,
        "_fsync_directory",
        fail_first_directory_sync,
    )

    assert (
        burn_transaction.abort_unpromoted_burn_transaction(
            tmp_path,
            transaction_id,
        )
        is False
    )
    assert manifest_path.is_file()
    assert not stage.exists()
    if had_previous_output:
        assert final.read_bytes() == b"old-final"
    else:
        assert not final.exists()

    monkeypatch.setattr(
        burn_transaction,
        "_fsync_directory",
        real_fsync_directory,
    )
    assert (
        burn_transaction.recover_burn_output_transaction(
            tmp_path,
            current_project,
        )
        == burn_transaction.BURN_RECOVERY_REVERTED
    )
    assert not manifest_path.exists()
    assert not backup.exists()
    if had_previous_output:
        assert final.read_bytes() == b"old-final"
    else:
        assert not final.exists()
