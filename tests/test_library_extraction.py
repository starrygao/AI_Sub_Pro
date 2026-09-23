import json
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.library.worker import LibraryWorker


def test_extraction_is_visible_before_model_start_and_clears_on_handoff(tmp_path, tmp_project_dir, monkeypatch):
    from app import server
    from app.services import translation_tasks as tasks
    from app.library import worker as module
    video = tmp_path / 'Episode.mkv'; video.write_bytes(b'video')
    worker = LibraryWorker({'allowed_roots': [str(tmp_path)]}, tmp_path / 'state')
    worker.observe(video, {})
    monkeypatch.setattr(worker.sources, 'metadata', lambda p: {})
    monkeypatch.setattr(server, 'worker', worker)
    start = Mock(); monkeypatch.setattr(tasks, 'start_translate', start)
    info = {'streams': [{'index': 1, 'codec_type': 'subtitle', 'codec_name': 'subrip', 'tags': {'language': 'eng'}}], 'format': {'duration': '10'}}

    def extract(cmd, source, report, stop_event, **kwargs):
        row = server.library_tasks(view='processed')['items'][0]
        assert row['state'] == 'translating'
        assert row['progress']['stage'] == 'subtitle_extract'
        assert row['progress']['progress'] is None
        assert row.get('project_id') is None
        assert server.library_tasks(view='waiting')['total'] == 0
        start.assert_not_called()
        report(50, 100, 12)
        row = server.library_tasks(view='processed')['items'][0]
        assert row['progress']['progress'] == 50
        assert '12 秒' in row['progress']['message']
        Path(cmd[-1]).write_text('1\n00:00:00,000 --> 00:00:01,000\nHello.\n')
    monkeypatch.setattr(module, 'extract_subtitles', extract)
    worker.prepare(worker.store.get(video), info, [])
    row = worker.store.get(video)
    assert row['preparation_progress'] is None
    assert row['project_id']
    assert json.loads((tmp_project_dir / row['project_id'] / 'project.json').read_text())['status'] == 'asr_done'
    start.assert_called_once()


def test_restart_turns_interrupted_extraction_into_retryable_error(tmp_path, monkeypatch):
    from app.api import projects
    video = tmp_path / 'Episode.mkv'; video.write_bytes(b'video')
    worker = LibraryWorker({'allowed_roots': [str(tmp_path)]}, tmp_path / 'state')
    worker.observe(video, {})
    worker.save(worker.store.get(video), state='translating', project_id=None,
                preparation_progress={'stage': 'subtitle_extract', 'progress': 42, 'message': '正在提取字幕'})
    export = Mock(side_effect=AssertionError('must not publish partial extraction'))
    monkeypatch.setattr(projects, 'export_srt', export)
    restarted = LibraryWorker(worker.config, tmp_path / 'state')
    restarted.finish()
    row = restarted.store.get(video)
    assert row['state'] == 'error'
    assert '中断' in row['reason']
    assert row['preparation_progress']['progress'] == 42
    export.assert_not_called()


def test_linux_input_position_matches_source_inode_and_handles_missing_proc(tmp_path):
    from app.library.extraction import input_position
    source = tmp_path / 'source.mkv'; source.write_bytes(b'media')
    proc = tmp_path / 'proc'; (proc / '123/fd').mkdir(parents=True); (proc / '123/fdinfo').mkdir()
    (proc / '123/fd/3').symlink_to(source)
    (proc / '123/fdinfo/3').write_text('pos:\t4321\nflags:\t0100000\n')
    assert input_position(123, source, proc) == 4321
    assert input_position(456, source, proc) is None


@pytest.mark.parametrize('case', ['timeout', 'stop', 'failure', 'success'])
def test_extraction_runner_reaps_child_and_reports_real_position(tmp_path, monkeypatch, case):
    import sys
    from app.library import extraction
    source = tmp_path / 'source'; source.write_bytes(b'x' * 100)
    monkeypatch.setattr(extraction, 'input_position', lambda *a: 25)
    original = extraction.subprocess.Popen
    children = []
    def launch(*a, **kw):
        process = original(*a, **kw); children.append(process); return process
    monkeypatch.setattr(extraction.subprocess, 'Popen', launch)
    event = threading.Event(); reports = []
    if case == 'stop': event.set()
    code = 'import time; time.sleep(10)' if case in {'stop', 'timeout'} else 'raise SystemExit(1)' if case == 'failure' else 'pass'
    kwargs = dict(timeout=.1 if case == 'timeout' else 5, poll_seconds=.02)
    cmd = [sys.executable, '-c', code]
    if case == 'success':
        extraction.extract_subtitles(cmd, source, lambda *p: reports.append(p), event, **kwargs)
    else:
        message = {'timeout': '超时', 'stop': '中断', 'failure': '失败'}[case]
        with pytest.raises(RuntimeError, match=message):
            extraction.extract_subtitles(cmd, source, lambda *p: reports.append(p), event, **kwargs)
    assert children[0].poll() is not None
    if case != 'stop': assert reports and reports[0][:2] == (25, 100)


def test_failed_extraction_remains_visible_and_retry_clears_old_progress(tmp_path, tmp_project_dir, monkeypatch):
    from app import server
    from app.services import translation_tasks as tasks
    from app.library import worker as module
    from app.engines.providers.codex_cli import CodexCliProvider
    video = tmp_path / 'Episode.mkv'; video.write_bytes(b'video')
    worker = LibraryWorker({'allowed_roots': [str(tmp_path)], 'quiet_seconds': 0}, tmp_path / 'state')
    worker.observe(video, {})
    monkeypatch.setattr(CodexCliProvider, 'check_logged_in', lambda: True)
    monkeypatch.setattr(module.os, 'getloadavg', lambda: (0, 0, 0))
    monkeypatch.setattr(worker.sources, 'metadata', lambda p: {})
    monkeypatch.setattr(worker, 'refresh_readiness', lambda: None)
    info = {'streams': [{'index': 1, 'codec_type': 'subtitle', 'codec_name': 'subrip', 'tags': {'language': 'eng'}},
                        {'index': 2, 'codec_type': 'audio', 'tags': {'language': 'eng'}}], 'format': {'duration': '10'}}
    monkeypatch.setattr(worker, 'probe', lambda p: info)
    monkeypatch.setattr(server, 'worker', worker)
    start = Mock(); monkeypatch.setattr(tasks, 'start_translate', start)
    def extract(cmd, source, report, stop_event):
        report(40, 100, 15)
        raise RuntimeError('字幕提取超时')
    monkeypatch.setattr(module, 'extract_subtitles', extract)
    worker.process_one()
    row = server.library_tasks(view='processed')['items'][0]
    assert row['state'] == 'error' and '超时' in row['reason']
    assert row['progress']['progress'] == 40
    start.assert_not_called()
    server.library_retry(server.Retry(path=str(video)))
    row = server.library_tasks(view='waiting')['items'][0]
    assert row['state'] == 'waiting' and row['preparation_progress'] is None
