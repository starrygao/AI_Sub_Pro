import pytest
from app.library.guard import fingerprint
from app.library.publish import publish_sidecar


def test_publish_same_folder_no_overwrite_and_idempotent(tmp_path):
    video=tmp_path/'Episode.mkv';video.write_bytes(b'video')
    source=tmp_path/'translated.srt';source.write_text('1\n00:00:00,000 --> 00:00:02,000\n你好。\n')
    expected=fingerprint(video)
    out=publish_sidecar(video,source,expected)
    assert out.name=='Episode.chi.srt'
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
    assert not (tmp_path/'Episode.chi.srt').exists()
