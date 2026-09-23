import pytest
from app.library.guard import fingerprint
from app.library.publish import publish_sidecar


def test_publish_same_folder_no_overwrite_and_idempotent(tmp_path):
    video=tmp_path/'Episode.mkv';video.write_bytes(b'video')
    source=tmp_path/'bilingual.srt';source.write_text('1\n00:00:00,000 --> 00:00:02,000\n你好。\nHello.\n')
    expected=fingerprint(video)
    out=publish_sidecar(video,source,expected)
    assert out.name=='Episode.双语.zh-CN.srt'
    assert out.read_text()==source.read_text()
    assert publish_sidecar(video,source,expected)==out
    source.write_text('different')
    with pytest.raises(FileExistsError):publish_sidecar(video,source,expected)
    assert '你好' in out.read_text()


def test_replaced_video_never_receives_old_subtitle(tmp_path):
    video=tmp_path/'Episode.mkv';video.write_bytes(b'old')
    expected=fingerprint(video);video.write_bytes(b'newer')
    source=tmp_path/'s.srt';source.write_text('subtitle')
    with pytest.raises(RuntimeError):publish_sidecar(video,source,expected)
    assert not (tmp_path/'Episode.双语.zh-CN.srt').exists()


def test_published_short_bilingual_subtitle_is_skipped_without_task_history(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from app.library.worker import LibraryWorker
    from app.library import worker as module
    from app.engines.providers.codex_cli import CodexCliProvider
    video=tmp_path/'Episode.mkv';video.write_bytes(b'video')
    source=tmp_path/'result.srt';source.write_text('1\n00:00:00,000 --> 00:00:01,000\n是。\nYes.\n')
    output=publish_sidecar(video,source,fingerprint(video))
    worker=LibraryWorker({'allowed_roots':[str(tmp_path)],'quiet_seconds':0},tmp_path/'new-state')
    worker.observe(video,{},manual=True)
    monkeypatch.setattr(CodexCliProvider,'check_logged_in',lambda:True)
    monkeypatch.setattr(module.os,'getloadavg',lambda:(0,0,0))
    probe=Mock(side_effect=AssertionError('Must skip before probing or translation'))
    monkeypatch.setattr(worker,'probe',probe)
    worker.process_one()
    row=worker.store.get(video)
    assert row['state']=='skipped' and row['reason']=='已有同目录中文字幕'
    assert row['existing_subtitles'][0]['path']==str(output)
    probe.assert_not_called()
