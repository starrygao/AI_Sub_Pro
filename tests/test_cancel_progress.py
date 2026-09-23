"""Cancellation must not turn a stored completion percentage into a stage floor."""
import json

import pytest


@pytest.mark.parametrize('stored', [None, 0, 72])
def test_cancel_preserves_recorded_progress_or_unknown(tmp_project_dir, monkeypatch, stored):
    from app.engines import scheduler
    from app.services import translation_tasks as tasks
    from app.utils.project_store import atomic_write_json, load_project

    monkeypatch.setattr(tasks, 'active_tasks', {})
    monkeypatch.setattr(tasks, '_task_generations', {})
    pid = 'deadbeef'
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    atomic_write_json(pdir / 'project.json', {
        'id': pid, 'name': 'Fixture episode', 'status': 'processing',
        'pipeline_stage': 'translate', 'workflow_mode': 'translate_only',
        'progress': stored or 0,
    })
    if stored is not None:
        atomic_write_json(pdir / 'progress.json', {
            'progress': stored, 'stage': 'translate', 'message': 'Before cancel',
            'updated_at': '2026-01-01T00:00:00+00:00',
        })
        # Cancellation must read the durable record, not an older memory value.
        scheduler.progress_store[pid] = {'progress': 15, 'stage': 'asr', 'message': 'Stale memory'}
    try:
        assert tasks.cancel_task(pid)['status'] == 'cancelled'
        assert load_project(pid)['status'] == 'cancelled'
        after = scheduler.get_progress(pid)
        if stored is None:
            assert after is None
            assert not (pdir / 'progress.json').exists()
        else:
            assert after['progress'] == stored
            assert after['message'] == '已取消'
            assert json.loads((pdir / 'progress.json').read_text())['progress'] == stored
        # A cooperative worker can reach its cancellation checkpoint after the
        # API has acknowledged it. That terminal callback must preserve it too.
        tasks._run_translate_pipeline(pid, '简体中文', burn_follows=False)
        final = scheduler.get_progress(pid)
        assert final is None if stored is None else final['progress'] == stored
        assert load_project(pid)['status'] == 'cancelled'
    finally:
        scheduler.reset_cancel(pid)
