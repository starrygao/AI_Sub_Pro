"""Tests for the trailer-project pipeline orchestrator (Phase 3 / Task 6)."""
import pytest

from app.api import projects as projects_api


@pytest.fixture
def patched_projects_dir(tmp_project_dir, monkeypatch):
    """Patch PROJECTS_DIR in every module that captured it at import time.

    The conftest `tmp_project_dir` fixture patches app.config.PROJECTS_DIR, but
    modules that did `from app.config import PROJECTS_DIR` at import time have
    their own reference that needs patching too.
    """
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    # Patch the trailer_pipeline module reference too
    from app.engines import trailer_pipeline as tp
    monkeypatch.setattr(tp, "PROJECTS_DIR", tmp_project_dir)
    # project_store binds PROJECTS_DIR at import time; patch its copy too
    from app.utils import project_store
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    return tmp_project_dir


def test_run_trailer_pipeline_happy_path(patched_projects_dir, monkeypatch):
    """Download succeeds -> each stage runs -> status reaches completed."""
    from app.engines import trailer_pipeline as tp
    from app.api.projects import create_trailer_project, _load_project

    project = create_trailer_project(
        tmdb_id=1, tmdb_type="movie", video_key="k", youtube_url="https://youtu.be/k",
        original_language="en", name="Test",
    )
    pid = project["id"]

    download_called = []
    asr_called = []
    translate_called = []
    burn_called = []

    def fake_download(url, out, progress_callback=None, **kw):
        download_called.append((url, out))
        import pathlib
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(out).write_bytes(b"x")
        return out

    monkeypatch.setattr(tp, "download_trailer", fake_download)
    monkeypatch.setattr(tp, "_run_asr_for_project", lambda pid_: asr_called.append(pid_))
    monkeypatch.setattr(tp, "_run_translate_for_project", lambda pid_: translate_called.append(pid_))
    monkeypatch.setattr(tp, "_run_burn_for_project", lambda pid_: burn_called.append(pid_))

    tp.run_trailer_pipeline(pid)

    assert len(download_called) == 1
    assert asr_called == [pid]
    assert translate_called == [pid]
    assert burn_called == [pid]

    p = _load_project(pid)
    assert p["video_path"] is not None
    assert p["status"] == "completed"


def test_run_trailer_pipeline_download_failure_sets_error(patched_projects_dir, monkeypatch):
    from app.engines import trailer_pipeline as tp
    from app.api.projects import create_trailer_project, _load_project

    project = create_trailer_project(
        tmdb_id=1, tmdb_type="movie", video_key="k", youtube_url="https://youtu.be/k",
        original_language="en", name="Test",
    )
    pid = project["id"]

    def fake_fail(*a, **kw):
        raise RuntimeError("network")

    monkeypatch.setattr(tp, "download_trailer", fake_fail)

    tp.run_trailer_pipeline(pid)  # must NOT raise

    p = _load_project(pid)
    assert p["status"] == "error"
    assert p["pipeline_stage"] is None
    err = (p.get("error") or "").lower()
    assert "network" in err or "download" in err


def test_run_trailer_pipeline_redacts_download_error(patched_projects_dir, monkeypatch):
    from app.engines import trailer_pipeline as tp
    from app.api.projects import create_trailer_project, _load_project

    project = create_trailer_project(
        tmdb_id=1, tmdb_type="movie", video_key="k", youtube_url="https://youtu.be/k",
        original_language="en", name="Test",
    )
    pid = project["id"]

    def fake_fail(*a, **kw):
        raise RuntimeError("download URL failed api_key=secret123 sk-live-secret-token")

    monkeypatch.setattr(tp, "download_trailer", fake_fail)

    tp.run_trailer_pipeline(pid)

    error = _load_project(pid).get("error") or ""
    assert "secret123" not in error
    assert "sk-live-secret-token" not in error
    assert "api_key=<redacted>" in error
    assert "sk-<redacted>" in error


def test_run_trailer_pipeline_stops_on_asr_stage_error(patched_projects_dir, monkeypatch):
    """If ASR sets status=error internally (doesn't raise), orchestrator must not advance to translate/burn."""
    from app.engines import trailer_pipeline as tp
    from app.api.projects import create_trailer_project, _load_project, _save_project

    project = create_trailer_project(
        tmdb_id=1, tmdb_type="movie", video_key="k", youtube_url="https://youtu.be/k",
        original_language="en", name="Test",
    )
    pid = project["id"]

    import pathlib
    def fake_download(url, out, progress_callback=None, **kw):
        pathlib.Path(out).write_bytes(b"x")
        return out

    def fake_asr_sets_error(pid_):
        # Mimic real behavior: catch exception internally, write status=error to project.json
        p = _load_project(pid_)
        p["status"] = "error"
        p["error"] = "ASR: whisper model failed"
        _save_project(pid_, p)

    translate_called = []
    burn_called = []

    monkeypatch.setattr(tp, "download_trailer", fake_download)
    monkeypatch.setattr(tp, "_run_asr_for_project", fake_asr_sets_error)
    monkeypatch.setattr(tp, "_run_translate_for_project", lambda pid_: translate_called.append(pid_))
    monkeypatch.setattr(tp, "_run_burn_for_project", lambda pid_: burn_called.append(pid_))

    tp.run_trailer_pipeline(pid)

    assert translate_called == [], "orchestrator should NOT have called translate after ASR set status=error"
    assert burn_called == [], "orchestrator should NOT have called burn after ASR set status=error"

    p = _load_project(pid)
    assert p["status"] == "error"
    assert p["pipeline_stage"] is None
    assert "ASR" in (p.get("error") or "")


def test_run_trailer_pipeline_stops_on_translate_stage_error(patched_projects_dir, monkeypatch):
    """Same guard after translate stage."""
    from app.engines import trailer_pipeline as tp
    from app.api.projects import create_trailer_project, _load_project, _save_project

    project = create_trailer_project(
        tmdb_id=1, tmdb_type="movie", video_key="k", youtube_url="https://youtu.be/k",
        original_language="en", name="Test",
    )
    pid = project["id"]

    import pathlib
    def fake_download(url, out, progress_callback=None, **kw):
        pathlib.Path(out).write_bytes(b"x")
        return out

    def fake_translate_sets_error(pid_):
        p = _load_project(pid_)
        p["status"] = "error"
        p["error"] = "Translate: provider failed"
        _save_project(pid_, p)

    burn_called = []

    monkeypatch.setattr(tp, "download_trailer", fake_download)
    monkeypatch.setattr(tp, "_run_asr_for_project", lambda pid_: None)  # no-op success
    monkeypatch.setattr(tp, "_run_translate_for_project", fake_translate_sets_error)
    monkeypatch.setattr(tp, "_run_burn_for_project", lambda pid_: burn_called.append(pid_))

    tp.run_trailer_pipeline(pid)

    assert burn_called == [], "burn should NOT run after translate set status=error"
    p = _load_project(pid)
    assert p["status"] == "error"
    assert p["pipeline_stage"] is None
    assert "Translate" in (p.get("error") or "")


def test_adopt_youtube_subtitles_rejects_empty_file(tmp_path):
    from app.engines import trailer_pipeline as tp

    (tmp_path / "original.en.srt").write_text("", encoding="utf-8")

    assert tp._adopt_youtube_subtitles(tmp_path) is False
    assert not (tmp_path / "filtered.srt").exists()
    assert not (tmp_path / "raw.srt").exists()


def test_run_trailer_pipeline_honors_cancel_before_worker_starts(tmp_project_dir, monkeypatch):
    from app.api.projects import create_trailer_project, _load_project
    from app.engines import trailer_pipeline as tp
    from app.engines.scheduler import request_cancel, reset_cancel

    project = create_trailer_project(
        tmdb_id=1,
        tmdb_type="movie",
        video_key="abc123",
        youtube_url="https://www.youtube.com/watch?v=abc123",
        original_language="en",
        name="Trailer",
    )
    called = []
    monkeypatch.setattr(tp, "_download_stage", lambda pid: called.append(pid))
    request_cancel(project["id"])

    try:
        tp.run_trailer_pipeline(project["id"])

        assert called == []
        loaded = _load_project(project["id"])
        assert loaded["status"] == "error"
        assert loaded["pipeline_stage"] is None
        assert loaded["error"] == "Cancelled by user"
    finally:
        reset_cancel(project["id"])


def test_download_stage_does_not_advance_after_cancel_during_download(tmp_project_dir, monkeypatch):
    import pytest
    from app.api.projects import create_trailer_project, _load_project
    from app.engines import trailer_pipeline as tp
    from app.engines.scheduler import request_cancel, reset_cancel

    project = create_trailer_project(
        tmdb_id=1,
        tmdb_type="movie",
        video_key="abc123",
        youtube_url="https://www.youtube.com/watch?v=abc123",
        original_language="en",
        name="Trailer",
    )

    def fake_download(url, out_path, progress_callback=None, max_height=1080):
        request_cancel(project["id"])
        return out_path

    monkeypatch.setattr(tp, "download_trailer", fake_download)

    try:
        with pytest.raises(RuntimeError, match="cancelled"):
            tp._download_stage(project["id"])

        loaded = _load_project(project["id"])
        assert loaded["video_path"] is None
        assert loaded["pipeline_stage"] == "download"
    finally:
        reset_cancel(project["id"])


def test_adopt_youtube_subtitles_tries_later_candidate_when_first_is_bad(tmp_path):
    from app.engines import trailer_pipeline as tp

    (tmp_path / "original.en-bad.srt").write_text("", encoding="utf-8")
    (tmp_path / "original.en.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n",
        encoding="utf-8",
    )

    assert tp._adopt_youtube_subtitles(tmp_path) is True
    assert "Hello" in (tmp_path / "filtered.srt").read_text(encoding="utf-8")
    assert "Hello" in (tmp_path / "raw.srt").read_text(encoding="utf-8")


def test_adopt_youtube_subtitles_skips_badly_encoded_vtt_candidate(tmp_path):
    from app.engines import trailer_pipeline as tp

    (tmp_path / "original.en-bad.vtt").write_bytes(b"\xff\xfe\xfa")
    (tmp_path / "original.en.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n",
        encoding="utf-8",
    )

    assert tp._adopt_youtube_subtitles(tmp_path) is True
    assert "Hello" in (tmp_path / "filtered.srt").read_text(encoding="utf-8")


def test_vtt_to_srt_supports_minute_timestamp_format():
    from app.engines.trailer_pipeline import _vtt_to_srt

    out = _vtt_to_srt("WEBVTT\n\n00:01.234 --> 00:03.456\nHello\n")

    assert "00:00:01,234 --> 00:00:03,456" in out
    assert "Hello" in out


def test_download_stage_defaults_bad_max_height(patched_projects_dir, monkeypatch):
    from app.engines import trailer_pipeline as tp
    from app.api.projects import create_trailer_project

    project = create_trailer_project(
        tmdb_id=1,
        tmdb_type="movie",
        video_key="k",
        youtube_url="https://youtu.be/k",
        original_language="en",
        name="Test",
    )
    captured = {}

    def fake_download(url, out, progress_callback=None, max_height=None, **kw):
        captured["max_height"] = max_height
        import pathlib
        pathlib.Path(out).write_bytes(b"x")
        return out

    monkeypatch.setattr("app.config.Config.get", lambda *args, **kwargs: "bad")
    monkeypatch.setattr(tp, "download_trailer", fake_download)

    tp._download_stage(project["id"])

    assert captured["max_height"] == 1080


def test_download_stage_tolerates_malformed_progress_callback_values(patched_projects_dir, monkeypatch):
    from app.engines import trailer_pipeline as tp
    from app.api.projects import create_trailer_project

    project = create_trailer_project(
        tmdb_id=1,
        tmdb_type="movie",
        video_key="k",
        youtube_url="https://youtu.be/k",
        original_language="en",
        name="Test",
    )

    def fake_download(url, out, progress_callback=None, max_height=None, **kw):
        if progress_callback:
            progress_callback(float("inf"), {"bad": "shape"})
        import pathlib
        pathlib.Path(out).write_bytes(b"x")
        return out

    monkeypatch.setattr(tp, "download_trailer", fake_download)

    tp._download_stage(project["id"])

    from app.engines.scheduler import get_progress
    progress = get_progress(project["id"])
    assert progress["progress"] == 15
    assert progress["message"] == "download complete"


@pytest.mark.parametrize("raw_value", [True, float("inf")])
def test_coerce_max_height_rejects_boolean_and_non_finite_values(raw_value):
    from app.engines.trailer_pipeline import _coerce_max_height

    assert _coerce_max_height(raw_value) == 1080
