import json
import threading
from contextlib import contextmanager

import pytest


@pytest.mark.parametrize("pipeline_name", ["_run_full_pipeline", "_run_asr_translate_pipeline"])
def test_pipeline_waiting_for_translation_remains_busy(
    tmp_project_dir, monkeypatch, pipeline_name,
):
    from app.config import Config
    from app.engines import scheduler
    from app.services import translation_tasks as tasks
    from app.utils.project_store import load_project, mutate_project

    monkeypatch.setattr(tasks, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(Config, "_data", {"concurrency": {"translate": 1}})
    scheduler._reset_sem_cache_for_testing()
    pid = "queued-full"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text(json.dumps({"id": pid, "status": "created"}))
    (pdir / "filtered.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")

    def finish_asr(*args, **kwargs):
        mutate_project(pid, lambda p: p.update(status="asr_done", pipeline_stage=None))

    waiting = threading.Event()

    @contextmanager
    def observed_slot(stage, project_id):
        waiting.set()
        with scheduler.slot(stage, project_id):
            yield

    def stop_before_model(*args, **kwargs):
        scheduler.request_cancel(pid)
        tasks._check_cancel(pid)

    monkeypatch.setattr(tasks, "_run_asr_pipeline", finish_asr)
    monkeypatch.setattr(tasks, "slot", observed_slot)
    monkeypatch.setattr(tasks, "_begin_translation_quality_run", stop_before_model)
    sem = scheduler.get_semaphore("translate")
    sem.acquire()
    worker = threading.Thread(target=getattr(tasks, pipeline_name), args=(pid, 0, "auto", "简体中文"))
    try:
        worker.start()
        assert waiting.wait(timeout=2)
        project = load_project(pid)
        assert project["status"] == "processing"
        assert project["pipeline_stage"] == "translate"
        assert "等待翻译" in project["progress_msg"]
        progress = scheduler.get_progress(pid)
        assert progress["stage"] == "translate"
        assert "等待翻译" in progress["message"]
        assert worker.is_alive()
    finally:
        sem.release()
        worker.join(timeout=5)
        scheduler.reset_cancel(pid)
        scheduler._reset_sem_cache_for_testing()
    assert not worker.is_alive()
