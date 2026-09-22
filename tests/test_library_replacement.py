import hashlib
from app.library.publish import archive_stale_sidecar


def test_replacement_archives_only_our_unchanged_previous_subtitle(tmp_path):
    old=tmp_path/'Episode.chi.srt';old.write_text('old translation')
    digest=hashlib.sha256(old.read_bytes()).hexdigest()
    backup=archive_stale_sidecar(old,digest)
    assert not old.exists()
    assert backup.read_text()=='old translation'
    old.write_text('user corrected this subtitle')
    assert archive_stale_sidecar(old,digest) is None
    assert old.read_text()=='user corrected this subtitle'
