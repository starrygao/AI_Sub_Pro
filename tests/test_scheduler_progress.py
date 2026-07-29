import json
import hashlib
import os
import threading

import pytest
from fastapi.testclient import TestClient


def test_update_progress_writes_to_store(tmp_project_dir):
    from app.engines.scheduler import update_progress, get_progress

    update_progress("pid1", stage="asr", local_pct=50, msg="half")
    p = get_progress("pid1")
    assert p["stage"] == "asr"
    assert 15 <= p["progress"] <= 40, f"asr stage maps to 15..40, got {p['progress']}"
    assert p["message"] == "half"


def test_update_progress_persists_to_disk(tmp_project_dir):
    from app.engines.scheduler import update_progress

    update_progress("pid2", stage="translate", local_pct=0, msg="starting")
    fp = tmp_project_dir / "pid2" / "progress.json"
    assert fp.exists()
    payload = json.loads(fp.read_text())
    assert payload["stage"] == "translate"
    assert payload["progress"] == 40


def test_update_progress_appends_stage_log(tmp_project_dir):
    from app.engines.scheduler import update_progress
    from app.engines.workflow_state import stage_log_path

    update_progress("pid_log", stage="asr", local_pct=10, msg="正在识别")

    path = stage_log_path("pid_log", "asr")
    assert path.exists()
    assert "正在识别" in path.read_text(encoding="utf-8")


def test_get_progress_reads_disk_when_memory_empty(tmp_project_dir):
    from app.engines.scheduler import get_progress, progress_store

    pdir = tmp_project_dir / "pid_disk"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 64,
        "stage": "translate",
        "message": "from disk",
        "updated_at": "2026-04-19T00:00:00",
    }))
    progress_store.clear()

    payload = get_progress("pid_disk")

    assert payload["stage"] == "translate"
    assert payload["message"] == "from disk"
    assert progress_store["pid_disk"]["progress"] == 64


def test_get_progress_refreshes_stale_memory_from_disk(tmp_project_dir):
    from app.engines.scheduler import get_progress, progress_store

    pdir = tmp_project_dir / "pid_stale"
    pdir.mkdir()
    progress_store["pid_stale"] = {
        "progress": 15,
        "stage": "asr",
        "message": "stale",
        "updated_at": "2026-04-19T00:00:00",
    }
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 88,
        "stage": "burn",
        "message": "fresh",
        "updated_at": "2026-04-19T00:01:00",
    }))

    payload = get_progress("pid_stale")

    assert payload["stage"] == "burn"
    assert payload["message"] == "fresh"
    assert progress_store["pid_stale"]["progress"] == 88


def test_get_progress_sanitizes_disk_payload(tmp_project_dir):
    from app.engines.scheduler import get_progress, progress_store

    pdir = tmp_project_dir / "pid_dirty"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": "999",
        "stage": ["translate"],
        "message": {"text": "bad"},
        "updated_at": ["not", "a", "timestamp"],
    }))
    progress_store.clear()

    payload = get_progress("pid_dirty")

    assert payload == {"progress": 100, "stage": "", "message": ""}
    assert progress_store["pid_dirty"] == payload


def test_get_progress_sanitizes_non_finite_disk_progress(tmp_project_dir):
    from app.engines.scheduler import get_progress, progress_store

    pdir = tmp_project_dir / "pid_nonfinite"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": float("inf"),
        "stage": "asr",
        "message": "bad number",
    }))
    progress_store.clear()

    payload = get_progress("pid_nonfinite")

    assert payload["progress"] == 0
    assert payload["stage"] == "asr"


def test_progress_endpoint_reads_disk_when_memory_empty(tmp_project_dir):
    from app.engines.scheduler import progress_store
    from app.main import app

    pdir = tmp_project_dir / "pid_api"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 71,
        "stage": "translate",
        "message": "visible across workers",
        "updated_at": "2026-04-19T00:00:00",
    }))
    progress_store.clear()

    resp = TestClient(app).get("/api/projects/pid_api/progress")

    assert resp.status_code == 200
    assert resp.json()["message"] == "visible across workers"


def test_update_progress_stage_ranges(tmp_project_dir):
    from app.engines.scheduler import update_progress, get_progress

    cases = [
        ("download", 0, 0, 0),
        ("download", 100, 15, 15),
        ("asr", 0, 15, 15),
        ("asr", 100, 40, 40),
        ("translate", 50, 57, 58),  # 40 + 0.5*(75-40) = 57.5 → int 57
        ("burn", 100, 100, 100),
    ]
    for stage, local, lo, hi in cases:
        update_progress(f"p-{stage}-{local}", stage=stage, local_pct=local, msg="")
        p = get_progress(f"p-{stage}-{local}")
        assert lo <= p["progress"] <= hi, f"{stage}/{local}: got {p['progress']}"


@pytest.mark.parametrize("local_pct", [None, "bad", True, float("nan"), float("inf"), -10])
def test_update_progress_treats_invalid_local_pct_as_zero(tmp_project_dir, local_pct):
    from app.engines.scheduler import update_progress, get_progress

    update_progress("pid_invalid_pct", stage="asr", local_pct=local_pct, msg="invalid")

    assert get_progress("pid_invalid_pct")["progress"] == 15


def test_update_progress_treats_overflowing_local_pct_as_zero(tmp_project_dir):
    from app.engines.scheduler import update_progress, get_progress

    update_progress("pid_overflow_pct", stage="asr", local_pct=10**10000, msg="invalid")

    assert get_progress("pid_overflow_pct")["progress"] == 15


def test_update_progress_sanitizes_malformed_stage_and_message(tmp_project_dir):
    from app.engines.scheduler import update_progress, get_progress

    update_progress("pid_bad_progress_fields", stage=["asr"], local_pct=50, msg={"text": "bad"})

    payload = get_progress("pid_bad_progress_fields")
    assert payload["stage"] == ""
    assert payload["message"] == ""
    assert payload["progress"] == 50


def test_update_progress_caps_local_pct_at_hundred(tmp_project_dir):
    from app.engines.scheduler import update_progress, get_progress

    update_progress("pid_big_pct", stage="asr", local_pct=200, msg="too high")

    assert get_progress("pid_big_pct")["progress"] == 40


def test_complete_progress_reconciles_memory_disk_and_reader(tmp_project_dir):
    from app.engines.scheduler import (
        complete_progress,
        get_progress,
        progress_store,
        update_progress,
    )

    pid = "pid_terminal"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    update_progress(pid, stage="translate", local_pct=100, msg="translation stage done")
    assert get_progress(pid)["progress"] == 75

    complete_progress(pid, msg="translation workflow complete")

    expected = {
        "progress": 100,
        "stage": "",
        "message": "translation workflow complete",
    }
    assert {key: progress_store[pid][key] for key in expected} == expected
    assert {key: get_progress(pid)[key] for key in expected} == expected
    persisted = json.loads((pdir / "progress.json").read_text(encoding="utf-8"))
    assert {key: persisted[key] for key in expected} == expected


def test_update_progress_threadsafe(tmp_project_dir):
    from app.engines.scheduler import update_progress, progress_store

    def worker(i):
        for _ in range(50):
            update_progress(f"pid{i}", stage="asr", local_pct=50, msg=f"from {i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()

    for i in range(8):
        assert f"pid{i}" in progress_store


def test_load_progress_store_from_disk(tmp_project_dir):
    from app.engines.scheduler import progress_store, load_progress_store_from_disk

    pdir = tmp_project_dir / "seed1"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 45, "stage": "translate", "message": "restored",
        "updated_at": "2026-04-19T00:00:00",
    }))
    progress_store.clear()

    count = load_progress_store_from_disk()
    assert count >= 1
    assert progress_store["seed1"]["stage"] == "translate"
    assert progress_store["seed1"]["progress"] == 45


def test_load_progress_store_from_disk_skips_symlinked_project_dirs(tmp_project_dir):
    from app.engines.scheduler import progress_store, load_progress_store_from_disk

    real = tmp_project_dir / "real_seed"
    real.mkdir()
    (real / "progress.json").write_text(json.dumps({
        "progress": 55, "stage": "translate", "message": "should not load",
    }))
    link = tmp_project_dir / "link_seed"
    link.symlink_to(real, target_is_directory=True)
    progress_store.clear()

    count = load_progress_store_from_disk()

    assert count == 1
    assert "real_seed" in progress_store
    assert "link_seed" not in progress_store


def test_load_progress_store_from_disk_sanitizes_payload(tmp_project_dir):
    from app.engines.scheduler import progress_store, load_progress_store_from_disk

    pdir = tmp_project_dir / "dirty_seed"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": -10,
        "stage": None,
        "message": ["bad"],
        "updated_at": 123,
    }))
    progress_store.clear()

    count = load_progress_store_from_disk()

    assert count >= 1
    assert progress_store["dirty_seed"] == {"progress": 0, "stage": "", "message": ""}


def test_mark_interrupted_tasks_from_previous_session_fails_running_workflow(tmp_project_dir):
    from app.engines.scheduler import mark_interrupted_tasks_from_previous_session, progress_store
    from app.engines.workflow_state import load_workflow_state, start_stage

    pid = "stucktrans"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "stuck translate",
        "video_path": "/fake/movie.mkv",
        "status": "processing",
        "pipeline_stage": None,
    }), encoding="utf-8")
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 40,
        "stage": "translate",
        "message": "翻译中: 批次 1/172",
    }), encoding="utf-8")
    start_stage(pid, "translate", input_artifact="filtered.srt")

    count = mark_interrupted_tasks_from_previous_session()

    assert count == 1
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "error"
    assert project["pipeline_stage"] is None
    assert "应用重启中断" in project["error"]
    state = load_workflow_state(pid)
    assert state["stages"]["translate"]["status"] == "failed"
    assert "应用重启中断" in state["stages"]["translate"]["error_summary"]
    progress = json.loads((pdir / "progress.json").read_text(encoding="utf-8"))
    assert progress["stage"] == ""
    assert progress["message"] == project["error"]
    assert progress_store[pid]["stage"] == ""


def test_mark_interrupted_tasks_from_previous_session_handles_legacy_processing(tmp_project_dir):
    from app.engines.scheduler import mark_interrupted_tasks_from_previous_session
    from app.engines.workflow_state import load_workflow_state

    pid = "legacyrun"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "legacy processing",
        "video_path": "/fake/movie.mkv",
        "status": "processing",
        "pipeline_stage": None,
    }), encoding="utf-8")
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 57,
        "stage": "translate",
        "message": "翻译中: 批次 2/4",
    }), encoding="utf-8")

    count = mark_interrupted_tasks_from_previous_session()

    assert count == 1
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "error"
    assert project["pipeline_stage"] is None
    state = load_workflow_state(pid)
    assert state["stages"]["translate"]["status"] == "failed"


def _seed_crashed_burn_transaction(
    root,
    *,
    pid,
    existing_output,
    crash_point,
):
    from app.utils.burn_transaction import burn_project_generation_hash

    pdir = root / pid
    pdir.mkdir()
    transaction_id = "a" * 32
    final_path = pdir / "movie_subtitled.mp4"
    stage_path = pdir / (
        f".movie_subtitled.mp4.burn.{transaction_id}.tmp.mp4"
    )
    backup_path = pdir / (
        f".movie_subtitled.mp4.rollback.{transaction_id}.mp4"
    )
    manifest_path = pdir / ".burn-output-transaction.json"
    project = {
        "id": pid,
        "name": "crashed burn",
        "video_path": str(pdir / "movie.mp4"),
        "status": "processing",
        "pipeline_stage": "burn",
        "output_video": None,
    }
    (pdir / "project.json").write_text(
        json.dumps(project),
        encoding="utf-8",
    )
    (pdir / "workflow_state.json").write_text(json.dumps({
        "version": 1,
        "stages": {
            "burn": {
                "status": "running",
                "input_artifact": str(pdir / "movie.mp4"),
            },
        },
    }), encoding="utf-8")
    stage_path.write_bytes(b"new-burn")
    if existing_output:
        final_path.write_bytes(b"prior-burn")
    state = {
        "manifest": "staged",
        "backup": "backed_up",
        "promoted": "promoted",
        "project_committed": "project_committed",
        "cleanup_pending": "project_committed",
    }[crash_point]
    manifest_path.write_text(json.dumps({
        "schema_version": 2,
        "transaction_id": transaction_id,
        "project_id": pid,
        "project_generation_hash": burn_project_generation_hash(project),
        "state": state,
        "stage_name": stage_path.name,
        "final_name": final_path.name,
        "backup_name": backup_path.name if existing_output else "",
        "snapshot_names": [],
        "had_previous_output": existing_output,
        "previous_output_size": len(b"prior-burn") if existing_output else 0,
        "previous_output_hash": (
            "sha256:" + hashlib.sha256(b"prior-burn").hexdigest()
            if existing_output
            else ""
        ),
        "staged_output_size": len(b"new-burn"),
        "staged_output_hash": (
            "sha256:" + hashlib.sha256(b"new-burn").hexdigest()
        ),
    }), encoding="utf-8")

    if crash_point != "manifest" and existing_output:
        backup_path.write_bytes(final_path.read_bytes())
    if crash_point not in {"manifest", "backup"}:
        stage_path.replace(final_path)
    if crash_point in {"project_committed", "cleanup_pending"}:
        project.update({
            "status": "completed",
            "pipeline_stage": None,
            "output_video": str(final_path),
            "burn_output_transaction_id": transaction_id,
        })
        (pdir / "project.json").write_text(
            json.dumps(project),
            encoding="utf-8",
        )
    if crash_point == "cleanup_pending":
        if backup_path.exists():
            backup_path.unlink()

    return pdir, final_path, stage_path, backup_path, manifest_path


@pytest.mark.parametrize("existing_output", [False, True])
@pytest.mark.parametrize(
    "crash_point",
    [
        "manifest",
        "backup",
        "promoted",
        "project_committed",
        "cleanup_pending",
    ],
)
def test_startup_recovers_crashed_burn_transaction_idempotently(
    tmp_project_dir,
    existing_output,
    crash_point,
):
    from app.engines.scheduler import (
        mark_interrupted_tasks_from_previous_session,
    )
    from app.engines.workflow_state import load_workflow_state

    pid = f"burncrash-{existing_output}-{crash_point}"
    pdir, final_path, stage_path, backup_path, manifest_path = (
        _seed_crashed_burn_transaction(
            tmp_project_dir,
            pid=pid,
            existing_output=existing_output,
            crash_point=crash_point,
        )
    )
    committed = crash_point in {"project_committed", "cleanup_pending"}

    first_count = mark_interrupted_tasks_from_previous_session()

    if committed:
        assert first_count == 0
        assert final_path.read_bytes() == b"new-burn"
        project = json.loads(
            (pdir / "project.json").read_text(encoding="utf-8")
        )
        assert project["status"] == "completed"
        assert (
            load_workflow_state(pid)["stages"]["burn"]["status"]
            == "succeeded"
        )
    else:
        assert first_count == 1
        if existing_output:
            assert final_path.read_bytes() == b"prior-burn"
        else:
            assert not final_path.exists()
    assert not stage_path.exists()
    assert not backup_path.exists()
    assert not manifest_path.exists()
    after_first_recovery = {
        path.name: path.read_bytes()
        for path in pdir.iterdir()
        if path.is_file()
    }

    assert mark_interrupted_tasks_from_previous_session() == 0
    assert {
        path.name: path.read_bytes()
        for path in pdir.iterdir()
        if path.is_file()
    } == after_first_recovery


@pytest.mark.parametrize(
    "manifest_content,unsafe_kind",
    [
        ("{not-json", "malformed"),
        (
            json.dumps({
                "schema_version": 2,
                "transaction_id": "b" * 32,
                "project_id": "unsafe-burn-manifest",
                "project_generation_hash": "sha256:" + "c" * 64,
                "state": "staged",
                "stage_name": "../../outside.mp4",
                "final_name": "movie_subtitled.mp4",
                "backup_name": "",
                "snapshot_names": [],
                "had_previous_output": False,
                "previous_output_size": 0,
                "previous_output_hash": "",
                "staged_output_size": len(b"stage"),
                "staged_output_hash": (
                    "sha256:" + hashlib.sha256(b"stage").hexdigest()
                ),
            }),
            "escape",
        ),
        (
            json.dumps({
                "schema_version": 2,
                "transaction_id": "b" * 32,
                "project_id": "unsafe-burn-manifest",
                "project_generation_hash": "sha256:" + "c" * 64,
                "state": "staged",
                "stage_name": (
                    ".movie_subtitled.mp4.burn."
                    + "b" * 32
                    + ".tmp.mp4"
                ),
                "final_name": "movie_subtitled.mp4",
                "backup_name": "",
                "snapshot_names": [],
                "had_previous_output": False,
                "previous_output_size": 0,
                "previous_output_hash": "",
                "staged_output_size": len(b"stage"),
                "staged_output_hash": (
                    "sha256:" + hashlib.sha256(b"stage").hexdigest()
                ),
            }),
            "symlink",
        ),
    ],
)
def test_startup_burn_recovery_rejects_unsafe_manifest_without_deleting(
    tmp_project_dir,
    manifest_content,
    unsafe_kind,
):
    from app.engines.scheduler import (
        mark_interrupted_tasks_from_previous_session,
    )

    pid = "unsafe-burn-manifest"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    outside_path = tmp_project_dir / "outside.mp4"
    outside_path.write_bytes(b"outside")
    stage_path = pdir / (
        ".movie_subtitled.mp4.burn."
        + "b" * 32
        + ".tmp.mp4"
    )
    if unsafe_kind == "symlink":
        stage_path.symlink_to(outside_path)
    else:
        stage_path.write_bytes(b"stage")
    final_path = pdir / "movie_subtitled.mp4"
    final_path.write_bytes(b"final")
    manifest_path = pdir / ".burn-output-transaction.json"
    manifest_path.write_text(manifest_content, encoding="utf-8")
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "unsafe burn recovery",
        "video_path": str(pdir / "movie.mp4"),
        "status": "processing",
        "pipeline_stage": "burn",
    }), encoding="utf-8")

    assert mark_interrupted_tasks_from_previous_session() == 1

    assert outside_path.read_bytes() == b"outside"
    assert final_path.read_bytes() == b"final"
    assert manifest_path.read_text(encoding="utf-8") == manifest_content
    assert stage_path.is_symlink() if unsafe_kind == "symlink" else stage_path.exists()


def test_startup_burn_recovery_rejects_truncated_backup_without_overwrite(
    tmp_project_dir,
):
    from app.engines.scheduler import (
        mark_interrupted_tasks_from_previous_session,
    )

    pdir, final_path, stage_path, backup_path, manifest_path = (
        _seed_crashed_burn_transaction(
            tmp_project_dir,
            pid="burncrash-truncated-backup",
            existing_output=True,
            crash_point="promoted",
        )
    )
    backup_path.write_bytes(b"PARTIAL")

    assert mark_interrupted_tasks_from_previous_session() == 1

    assert final_path.read_bytes() == b"new-burn"
    assert backup_path.read_bytes() == b"PARTIAL"
    assert manifest_path.is_file()
    assert not stage_path.exists()


def test_startup_committed_burn_keeps_manifest_until_workflow_sync_retries(
    tmp_project_dir,
    monkeypatch,
):
    from app.engines import scheduler
    from app.engines.workflow_state import load_workflow_state

    pid = "burncrash-workflow-retry"
    pdir, final_path, _, _, manifest_path = (
        _seed_crashed_burn_transaction(
            tmp_project_dir,
            pid=pid,
            existing_output=True,
            crash_point="project_committed",
        )
    )
    real_finish_stage = scheduler.finish_stage
    attempts = {"count": 0}

    def fail_once(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise OSError("injected workflow sync failure")
        return real_finish_stage(*args, **kwargs)

    monkeypatch.setattr(scheduler, "finish_stage", fail_once)

    assert scheduler.mark_interrupted_tasks_from_previous_session() == 0
    assert final_path.read_bytes() == b"new-burn"
    assert manifest_path.is_file()
    assert load_workflow_state(pid)["stages"]["burn"]["status"] == "running"

    assert scheduler.mark_interrupted_tasks_from_previous_session() == 0
    assert final_path.read_bytes() == b"new-burn"
    assert not manifest_path.exists()
    assert load_workflow_state(pid)["stages"]["burn"]["status"] == "succeeded"


def test_startup_orphan_cleanup_skips_registered_active_worker(
    tmp_project_dir,
    monkeypatch,
):
    import threading

    from app.api import translate
    from app.engines.scheduler import (
        mark_interrupted_tasks_from_previous_session,
        reset_cancel,
    )

    pid = "burn-orphan-active-worker"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "id": pid,
        "name": "active burn",
        "status": "processing",
        "pipeline_stage": "burn",
        "video_path": str(pdir / "movie.mp4"),
    }), encoding="utf-8")
    transaction_id = "2" * 32
    orphan = pdir / (
        f".movie_subtitled.mp4.burn.{transaction_id}.tmp.mp4"
    )
    orphan.write_bytes(b"active-stage")
    monkeypatch.setattr(translate, "active_tasks", {})
    worker = threading.Thread(target=lambda: None)
    translate.try_register_task(
        pid,
        lambda: worker,
        reset_cancellation=True,
        launch_stage="burn",
    )

    try:
        assert mark_interrupted_tasks_from_previous_session() == 0
        assert orphan.read_bytes() == b"active-stage"
        project = json.loads(
            (pdir / "project.json").read_text(encoding="utf-8")
        )
        assert project["status"] == "processing"
    finally:
        translate.unregister_task(pid, task=worker)
        reset_cancel(pid)

    assert mark_interrupted_tasks_from_previous_session() == 1
    assert not orphan.exists()


def test_burn_recovery_copy_partial_fallback_is_private_and_removed(
    tmp_path,
    monkeypatch,
):
    from app.utils import burn_transaction

    final_path = tmp_path / "movie_subtitled.mp4"
    backup_path = tmp_path / ".movie_subtitled.mp4.rollback.copy.mp4"
    final_path.write_bytes(b"prior-burn")
    expected_hash = (
        "sha256:" + hashlib.sha256(b"prior-burn").hexdigest()
    )
    monkeypatch.setattr(
        burn_transaction.os,
        "link",
        lambda *args: (_ for _ in ()).throw(OSError("no hardlink")),
    )

    def fail_after_partial(source, target):
        target.write(b"PARTIAL")
        raise OSError("injected partial copy failure")

    monkeypatch.setattr(
        burn_transaction.shutil,
        "copyfileobj",
        fail_after_partial,
    )
    old_umask = os.umask(0)
    try:
        with pytest.raises(OSError, match="partial copy failure"):
            burn_transaction.create_burn_recovery_copy(
                final_path,
                backup_path,
                expected_size=len(b"prior-burn"),
                expected_hash=expected_hash,
            )
    finally:
        os.umask(old_umask)

    assert final_path.read_bytes() == b"prior-burn"
    assert not backup_path.exists()
    assert list(tmp_path.glob(".*.copy.*.tmp")) == []


def test_burn_recovery_copy_and_manifest_are_private_and_independent(
    tmp_path,
    monkeypatch,
):
    from app.utils import burn_transaction

    transaction_id = "e" * 32
    final_path = tmp_path / "movie_subtitled.mp4"
    stage_path = tmp_path / (
        f".movie_subtitled.mp4.burn.{transaction_id}.tmp.mp4"
    )
    backup_path = tmp_path / (
        f".movie_subtitled.mp4.rollback.{transaction_id}.mp4"
    )
    final_path.write_bytes(b"prior-burn")
    stage_path.write_bytes(b"new-burn")
    final_path.chmod(0o644)
    expected_hash = (
        "sha256:" + hashlib.sha256(b"prior-burn").hexdigest()
    )
    manifest = burn_transaction.new_burn_transaction_manifest(
        pid=tmp_path.name,
        project={"id": tmp_path.name, "status": "processing"},
        stage_path=stage_path,
        final_path=final_path,
        backup_path=backup_path,
        had_previous_output=True,
        transaction_id=transaction_id,
    )
    old_umask = os.umask(0)
    try:
        burn_transaction.persist_burn_transaction_manifest(
            tmp_path,
            manifest,
        )
        hardlink_calls = []
        monkeypatch.setattr(
            burn_transaction.os,
            "link",
            lambda *args: hardlink_calls.append(args),
        )
        burn_transaction.create_burn_recovery_copy(
            final_path,
            backup_path,
            expected_size=len(b"prior-burn"),
            expected_hash=expected_hash,
        )
    finally:
        os.umask(old_umask)

    assert backup_path.read_bytes() == b"prior-burn"
    assert backup_path.stat().st_mode & 0o777 == 0o600
    assert (
        tmp_path / burn_transaction.BURN_TRANSACTION_MANIFEST
    ).stat().st_mode & 0o777 == 0o600
    assert hardlink_calls == []
    assert not os.path.samefile(final_path, backup_path)


def test_mark_interrupted_tasks_from_previous_session_skips_orphan_progress_dir(tmp_project_dir):
    from app.engines.scheduler import mark_interrupted_tasks_from_previous_session

    pdir = tmp_project_dir / "orphan1"
    pdir.mkdir()
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 40,
        "stage": "translate",
        "message": "旧进度",
    }), encoding="utf-8")

    assert mark_interrupted_tasks_from_previous_session() == 0


@pytest.mark.parametrize("status", ["cancelled", "translated", "error", "completed"])
def test_mark_interrupted_tasks_from_previous_session_ignores_terminal_or_review_states(
    tmp_project_dir,
    status,
):
    from app.engines.scheduler import mark_interrupted_tasks_from_previous_session

    pid = f"stale-{status}"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    project = {
        "id": pid,
        "name": "stale progress",
        "video_path": "/fake/movie.mkv",
        "status": status,
        "progress": 100,
        "progress_msg": "已取消" if status == "cancelled" else "翻译完成",
        "pipeline_stage": None,
    }
    if status == "translated":
        project["translation_quality_status"] = "needs_review"
        project["translation_quality_message"] = "翻译质量未达标"
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (pdir / "progress.json").write_text(json.dumps({
        "progress": 57,
        "stage": "translate",
        "message": "旧的翻译进度",
    }), encoding="utf-8")

    count = mark_interrupted_tasks_from_previous_session()

    assert count == 0
    loaded = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert loaded["status"] == status
    assert loaded["progress_msg"] == project["progress_msg"]
    assert loaded.get("error") != "任务因应用重启中断，请点击恢复流程或重试失败阶段。"
