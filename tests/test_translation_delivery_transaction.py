import os
import stat

import pytest


def test_promote_staged_files_fsyncs_all_bytes_before_any_replace(
    tmp_path,
    monkeypatch,
):
    """Catches exposing one final artifact before every staged peer is durable."""
    from app.utils import translation_delivery

    stages = [tmp_path / ".a.tmp", tmp_path / ".b.tmp"]
    finals = [tmp_path / "a.srt", tmp_path / "b.srt"]
    stages[0].write_bytes(b"a")
    stages[1].write_bytes(b"b")
    events = []
    real_fsync = os.fsync
    real_replace = os.replace

    def recording_fsync(descriptor):
        events.append(
            "directory_fsync"
            if stat.S_ISDIR(os.fstat(descriptor).st_mode)
            else "file_fsync"
        )
        return real_fsync(descriptor)

    def recording_replace(source, target):
        events.append(f"replace:{target.name}")
        return real_replace(source, target)

    monkeypatch.setattr(translation_delivery.os, "fsync", recording_fsync)
    monkeypatch.setattr(translation_delivery.os, "replace", recording_replace)

    assert translation_delivery.promote_staged_files(
        list(zip(stages, finals))
    ) is True
    assert events == [
        "file_fsync",
        "file_fsync",
        "replace:a.srt",
        "replace:b.srt",
        "directory_fsync",
    ]
    assert [path.read_bytes() for path in finals] == [b"a", b"b"]


def test_promote_staged_files_rejects_final_identity_change(
    tmp_path,
    monkeypatch,
):
    """Catches clearing the fail-closed sentinel after a promoted file changed."""
    from app.utils import translation_delivery

    stage = tmp_path / ".artifact.tmp"
    final = tmp_path / "artifact.srt"
    stage.write_bytes(b"certified")
    real_replace = os.replace

    def tampering_replace(source, target):
        real_replace(source, target)
        target.write_bytes(b"tampered")

    monkeypatch.setattr(translation_delivery.os, "replace", tampering_replace)

    with pytest.raises(RuntimeError, match="identity"):
        translation_delivery.promote_staged_files([(stage, final)])

