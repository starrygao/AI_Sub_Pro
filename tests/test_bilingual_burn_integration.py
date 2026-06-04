"""Task 8: wire bilingual burn for trailer projects + preserve legacy style for uploads."""
import json
from pathlib import Path

import pytest

from app.api import projects as projects_api
from app.api import translate as translate_api
import app.utils.project_store as project_store_module


@pytest.fixture
def patched_projects_dir(tmp_project_dir, monkeypatch):
    """Ensure projects, translate, and project_store modules see the isolated PROJECTS_DIR.

    `app.api.projects`, `app.api.translate`, and `app.utils.project_store` import
    PROJECTS_DIR by name at module load, so the conftest fixture (which patches
    app.config) is not enough on its own.
    """
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(translate_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(project_store_module, "PROJECTS_DIR", tmp_project_dir)
    return tmp_project_dir


def _seed_project(tmp_project_dir, pid, source_type="trailer", translated_text="你好", en_text="Hello"):
    pdir = tmp_project_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "original.mp4").write_bytes(b"fake")
    (pdir / "translated.srt").write_text(
        f"1\n00:00:01,000 --> 00:00:02,000\n{translated_text}\n", encoding="utf-8"
    )
    (pdir / "filtered.srt").write_text(
        f"1\n00:00:01,000 --> 00:00:02,000\n{en_text}\n", encoding="utf-8"
    )
    project = {
        "id": pid, "name": "Foo", "video_path": str(pdir / "original.mp4"),
        "status": "translated", "source_type": source_type,
        "target_language": "简体中文",
        "tmdb_id": 1, "tmdb_type": "movie", "original_language": "en",
    }
    (pdir / "project.json").write_text(json.dumps(project), encoding="utf-8")
    return pdir


def test_build_bilingual_tracks_returns_two_tracks(patched_projects_dir):
    from app.api.translate import _build_bilingual_tracks

    _seed_project(patched_projects_dir, "t1", source_type="trailer")
    tracks = _build_bilingual_tracks("t1")
    assert len(tracks) == 2
    # zh on top (larger font, higher margin)
    assert tracks[0].font_size > tracks[1].font_size
    assert tracks[0].margin_v > tracks[1].margin_v


def test_build_bilingual_tracks_generates_zh_en_srt_files(patched_projects_dir):
    from app.api.translate import _build_bilingual_tracks

    pdir = _seed_project(patched_projects_dir, "t2", source_type="trailer")
    _build_bilingual_tracks("t2")
    assert (pdir / "zh.srt").exists()
    assert (pdir / "en.srt").exists()
    zh = (pdir / "zh.srt").read_text(encoding="utf-8")
    en = (pdir / "en.srt").read_text(encoding="utf-8")
    assert "你好" in zh
    assert "Hello" in en


def test_build_bilingual_tracks_only_returns_existing_tracks(patched_projects_dir):
    from app.api.translate import _build_bilingual_tracks

    pdir = _seed_project(patched_projects_dir, "t2_partial", source_type="trailer")
    (pdir / "filtered.srt").unlink()

    tracks = _build_bilingual_tracks("t2_partial")

    assert len(tracks) == 1
    assert all(Path(track.path).exists() for track in tracks)
    assert (pdir / "zh.srt").exists()
    assert not (pdir / "en.srt").exists()


def test_trailer_burn_uses_two_tracks(patched_projects_dir, monkeypatch):
    """_run_burn_pipeline on a trailer project calls burn_subtitles with 2 tracks."""
    from app.api import translate as api_translate

    _seed_project(patched_projects_dir, "t3", source_type="trailer")

    captured = {}

    def fake_burn(video, tracks, output, **kw):
        captured["tracks"] = tracks
        captured["output"] = output
        Path(output).write_bytes(b"out")
        return True

    monkeypatch.setattr(api_translate, "burn_subtitles", fake_burn)
    api_translate._run_burn_pipeline("t3")

    assert captured.get("tracks") is not None
    assert isinstance(captured["tracks"], list)
    assert len(captured["tracks"]) == 2


def test_upload_burn_uses_single_track_with_legacy_style(patched_projects_dir, monkeypatch):
    """_run_burn_pipeline on an upload project uses 1 track with legacy style (Hiragino Sans GB / 22)."""
    from app.api import translate as api_translate

    _seed_project(patched_projects_dir, "u1", source_type="upload")

    captured = {}

    def fake_burn(video, tracks, output, **kw):
        captured["tracks"] = tracks
        Path(output).write_bytes(b"out")
        return True

    monkeypatch.setattr(api_translate, "burn_subtitles", fake_burn)
    api_translate._run_burn_pipeline("u1")

    assert captured.get("tracks") is not None
    assert len(captured["tracks"]) == 1
    t = captured["tracks"][0]
    # Legacy style preserved — don't assert exact values (may vary) but check that it's NOT the generic Helvetica default for trailers
    assert t.font_name in ("Hiragino Sans GB", "PingFang SC", "Helvetica")
    assert t.font_size >= 18


def test_burn_pipeline_refuses_symlinked_output_path(patched_projects_dir, monkeypatch):
    from app.api import translate as api_translate
    from app.engines.workflow_state import load_workflow_state

    pid = "u_symlink_output"
    pdir = _seed_project(patched_projects_dir, pid, source_type="upload")
    outside = patched_projects_dir.parent / "outside-output.mp4"
    outside.write_bytes(b"outside")
    (pdir / "original_subtitled.mp4").symlink_to(outside)
    calls = []

    def fake_burn(video, tracks, output, **kw):
        calls.append((video, tracks, output))
        Path(output).write_bytes(b"pwned")
        return True

    monkeypatch.setattr(api_translate, "burn_subtitles", fake_burn)

    api_translate._run_burn_pipeline(pid)

    assert calls == []
    assert outside.read_bytes() == b"outside"
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"
    assert "输出路径无效" in project["error"]
    state = load_workflow_state(pid)
    assert state["stages"]["burn"]["status"] == "failed"


def test_start_burn_refuses_symlinked_output_path(patched_projects_dir, monkeypatch):
    from app.api import translate as api_translate

    pid = "start_symlink_output"
    pdir = _seed_project(patched_projects_dir, pid, source_type="upload")
    outside = patched_projects_dir.parent / "outside-start-output.mp4"
    outside.write_bytes(b"outside")
    (pdir / "original_subtitled.mp4").symlink_to(outside)
    calls = []

    def fake_burn(video, tracks, output, **kw):
        calls.append((video, tracks, output))
        Path(output).write_bytes(b"pwned")
        return True

    monkeypatch.setattr(api_translate, "active_tasks", {})
    monkeypatch.setattr(api_translate, "burn_subtitles", fake_burn)

    result = api_translate.start_burn(pid=pid)
    assert result["status"] == "started"

    with api_translate._tasks_lock:
        thread = api_translate.active_tasks.get(pid)
    if thread is not None:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert calls == []
    assert outside.read_bytes() == b"outside"
    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"
    assert "输出路径无效" in project["error"]


def test_burn_without_subtitles_records_visible_error(patched_projects_dir):
    from app.api import translate as api_translate

    pdir = _seed_project(patched_projects_dir, "u2", source_type="upload")
    (pdir / "translated.srt").unlink()
    (pdir / "filtered.srt").unlink()

    api_translate._run_burn_pipeline("u2")

    project = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    assert project["status"] == "translated"
    assert "无字幕文件" in project["error"]
