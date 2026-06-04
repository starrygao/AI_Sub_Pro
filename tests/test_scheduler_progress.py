import json
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
