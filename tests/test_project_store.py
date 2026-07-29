import json
import os
import stat
import threading

import pytest

from app.utils import project_store


def test_validate_pid_accepts_normal_id():
    assert project_store.validate_pid("a1b2c3d4") == "a1b2c3d4"


@pytest.mark.parametrize("bad", ["../etc", "a/b", "..", "", "x" * 65, "a.b", "/abs", "a\\b"])
def test_validate_pid_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        project_store.validate_pid(bad)


def test_project_dir_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    with pytest.raises(ValueError):
        project_store.project_dir("../outside")


def test_project_dir_normal(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    assert project_store.project_dir("abcd1234") == (tmp_path / "abcd1234").resolve()


def test_project_dir_rejects_project_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    target = tmp_path / "realproj"
    target.mkdir()
    link = tmp_path / "linkproj"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        project_store.project_dir("linkproj")


def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "x.json"
    project_store.atomic_write_json(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert not (tmp_path / "x.json.tmp").exists()


def test_atomic_write_durably_orders_file_fsync_replace_and_directory_fsync(
    tmp_path,
    monkeypatch,
):
    """Catches publishing JSON before its bytes and directory entry are durable."""
    destination = tmp_path / "project.json"
    events = []
    real_fsync = os.fsync
    real_replace = os.replace

    def recording_fsync(descriptor):
        kind = (
            "directory_fsync"
            if stat.S_ISDIR(os.fstat(descriptor).st_mode)
            else "file_fsync"
        )
        events.append(kind)
        return real_fsync(descriptor)

    def recording_replace(source, target):
        events.append("replace")
        return real_replace(source, target)

    monkeypatch.setattr(project_store.os, "fsync", recording_fsync)
    monkeypatch.setattr(project_store.os, "replace", recording_replace)

    project_store.atomic_write_json(destination, {"status": "completed"})

    assert events == ["file_fsync", "replace", "directory_fsync"]
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "status": "completed",
    }


def test_atomic_write_file_fsync_failure_preserves_original_and_cleans_temp(
    tmp_path,
    monkeypatch,
):
    """Catches promotion after the private temporary file failed to sync."""
    destination = tmp_path / "project.json"
    destination.write_text('{"status":"old"}', encoding="utf-8")

    def fail_fsync(_descriptor):
        raise OSError("injected file fsync failure")

    monkeypatch.setattr(project_store.os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="file fsync failure"):
        project_store.atomic_write_json(
            destination,
            {"status": "completed"},
        )

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "status": "old",
    }
    assert not list(tmp_path.glob("project.json.*.tmp"))


def test_atomic_write_preserves_original_on_failure(tmp_path, monkeypatch):
    p = tmp_path / "x.json"
    p.write_text('{"original": true}', encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(project_store.json, "dump", boom)
    with pytest.raises(RuntimeError):
        project_store.atomic_write_json(p, {"new": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"original": True}
    assert not (tmp_path / "x.json.tmp").exists()


def test_atomic_write_rejects_non_finite_json_numbers(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"original": true}', encoding="utf-8")

    with pytest.raises(ValueError):
        project_store.atomic_write_json(p, {"bad": float("nan")})

    assert json.loads(p.read_text(encoding="utf-8")) == {"original": True}
    assert not list(tmp_path.glob("x.json.*.tmp"))


def test_atomic_write_uses_unique_temp_files_for_overlapping_writes(tmp_path, monkeypatch):
    p = tmp_path / "x.json"
    real_dump = project_store.json.dump
    barrier = threading.Barrier(2)
    replace_sources = []
    lock = threading.Lock()

    def slow_dump(data, f, **kwargs):
        barrier.wait(timeout=2)
        return real_dump(data, f, **kwargs)

    def fake_replace(src, dst):
        with lock:
            replace_sources.append(src.name)

    monkeypatch.setattr(project_store.json, "dump", slow_dump)
    monkeypatch.setattr(project_store.os, "replace", fake_replace)

    t1 = threading.Thread(target=project_store.atomic_write_json, args=(p, {"v": 1}))
    t2 = threading.Thread(target=project_store.atomic_write_json, args=(p, {"v": 2}))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(replace_sources) == 2
    assert len(set(replace_sources)) == 2


def _make_project(tmp_path, monkeypatch, pid="proj0001"):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    pdir = tmp_path / pid
    pdir.mkdir()
    project_store.atomic_write_json(pdir / "project.json", {"counter": 0})
    return pid


def test_load_project_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        project_store.load_project("nope0001")


def test_load_project_reads_data(tmp_path, monkeypatch):
    pid = _make_project(tmp_path, monkeypatch)
    assert project_store.load_project(pid) == {"counter": 0}


def test_load_project_rejects_non_object_json(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    pdir = tmp_path / "proj0001"
    pdir.mkdir()
    (pdir / "project.json").write_text("[]", encoding="utf-8")

    with pytest.raises(project_store.ProjectFileInvalid, match="Project file is invalid"):
        project_store.load_project("proj0001")


def test_mutate_project_rejects_overlong_json_number(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    pdir = tmp_path / "proj0001"
    pdir.mkdir()
    (pdir / "project.json").write_text('{"duration": ' + ("9" * 5000) + "}", encoding="utf-8")

    with pytest.raises(project_store.ProjectFileInvalid, match="Project file is invalid"):
        project_store.mutate_project("proj0001", lambda p: p.update({"name": "x"}))


def test_mutate_project_serializes_concurrent_writes(tmp_path, monkeypatch):
    pid = _make_project(tmp_path, monkeypatch)
    threads_n, per_thread = 8, 50

    def bump():
        for _ in range(per_thread):
            project_store.mutate_project(
                pid, lambda p: p.__setitem__("counter", p["counter"] + 1)
            )

    ts = [threading.Thread(target=bump) for _ in range(threads_n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert project_store.load_project(pid)["counter"] == threads_n * per_thread


def test_mutate_project_applies_normalize(tmp_path, monkeypatch):
    pid = _make_project(tmp_path, monkeypatch)

    def normalize(d):
        d.setdefault("added_by_normalize", True)
        return d

    result = project_store.mutate_project(
        pid, lambda p: p.__setitem__("counter", 99), normalize=normalize
    )
    assert result["counter"] == 99
    assert result["added_by_normalize"] is True
