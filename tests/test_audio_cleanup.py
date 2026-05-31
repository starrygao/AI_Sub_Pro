"""Phase 5 — audio intermediate cleanup after burn success.

raw_audio.wav + demucs_out/ live in the project dir. Once the burn step
produces the subtitled video, the intermediates can be deleted. Failures
preserve them so the user can re-run ASR / debug.
"""
import json
from pathlib import Path

import pytest


def test_cleanup_intermediate_removes_raw_and_demucs(tmp_path):
    """cleanup_intermediate removes raw_audio.wav and the demucs_out tree."""
    from app.engines.audio import cleanup_intermediate

    (tmp_path / "raw_audio.wav").write_bytes(b"\x00" * 1024)
    demucs = tmp_path / "demucs_out" / "htdemucs" / "raw_audio"
    demucs.mkdir(parents=True)
    (demucs / "vocals.wav").write_bytes(b"\x00" * 1024)
    (demucs / "no_vocals.wav").write_bytes(b"\x00" * 1024)

    cleanup_intermediate(str(tmp_path))

    assert not (tmp_path / "raw_audio.wav").exists()
    assert not (tmp_path / "demucs_out").exists()


def test_cleanup_intermediate_is_noop_when_absent(tmp_path):
    """cleanup_intermediate must not raise when files are already gone."""
    from app.engines.audio import cleanup_intermediate
    # No files exist in tmp_path — must not raise
    cleanup_intermediate(str(tmp_path))


def test_burn_success_triggers_cleanup(tmp_project_dir, monkeypatch):
    """End-to-end: _run_burn_pipeline success removes audio intermediates."""
    from app.api import translate as tr
    from app.api import projects as projects_api

    pid = "burnok01"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    project = projects_api._apply_safe_defaults({
        "id": pid, "name": "t", "video_path": "/fake.mp4",
        "status": "translated", "error": None, "source_type": "upload",
    })
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
    )
    (pdir / "raw_audio.wav").write_bytes(b"\x00" * 1024)
    (pdir / "demucs_out").mkdir()
    (pdir / "demucs_out" / "marker").write_bytes(b"x")

    # Make burn "succeed" without shelling out, and write the output file
    # so the success branch in _run_burn_pipeline accepts it.
    def _fake_burn(video, tracks, output_path, callback=None):
        Path(output_path).write_bytes(b"\x00" * 64)
        return True
    monkeypatch.setattr(tr, "burn_subtitles", _fake_burn)

    tr._run_burn_pipeline(pid)

    assert not (pdir / "raw_audio.wav").exists(), "raw_audio should be cleaned"
    assert not (pdir / "demucs_out").exists(), "demucs_out should be cleaned"


def test_burn_failure_preserves_intermediates(tmp_project_dir, monkeypatch):
    """Failure path: intermediates remain so user can debug / re-run ASR."""
    from app.api import translate as tr
    from app.api import projects as projects_api

    pid = "burnfail1"
    pdir = tmp_project_dir / pid
    pdir.mkdir()
    project = projects_api._apply_safe_defaults({
        "id": pid, "name": "t", "video_path": "/fake.mp4",
        "status": "translated", "error": None, "source_type": "upload",
    })
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (pdir / "translated.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
    )
    (pdir / "raw_audio.wav").write_bytes(b"\x00" * 1024)

    monkeypatch.setattr(tr, "burn_subtitles", lambda *a, **kw: False)

    tr._run_burn_pipeline(pid)

    assert (pdir / "raw_audio.wav").exists(), \
        "raw_audio.wav must remain on burn failure (user may re-run)"
