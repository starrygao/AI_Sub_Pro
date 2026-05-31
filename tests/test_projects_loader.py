import json

import pytest
from fastapi import HTTPException

from app.api import projects as projects_api
from app.api.projects import _load_project


@pytest.fixture
def patched_projects_dir(tmp_project_dir, monkeypatch):
    """Ensure the projects module uses the isolated PROJECTS_DIR too.

    `app.api.projects` and `app.utils.project_store` both import PROJECTS_DIR
    by name at module load, so the conftest fixture (which patches app.config)
    is not enough on its own — patch each module's binding directly.
    """
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    from app.utils import project_store
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_project_dir)
    return tmp_project_dir


def test_legacy_project_gets_safe_defaults(patched_projects_dir):
    pid = "legacy01"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid,
        "name": "old",
        "video_path": "/old.mp4",
        "created_at": "2024-01-01",
        "status": "completed",
        "progress": 100,
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = _load_project(pid)

    # Existing fields preserved
    assert loaded["status"] == "completed"
    assert loaded["name"] == "old"
    # New fields defaulted
    assert loaded["source_type"] == "upload"
    assert loaded["auto_run"] is False
    assert loaded["tmdb_id"] is None
    assert loaded["tmdb_type"] is None
    assert loaded["season_number"] is None
    assert loaded["tmdb_video_key"] is None
    assert loaded["youtube_url"] is None
    assert loaded["original_language"] is None
    assert loaded["parent_project_id"] is None
    assert loaded["pipeline_stage"] is None
    assert loaded["archived"] is False


def test_legacy_project_progress_fields_are_sanitized(patched_projects_dir):
    pid = "badprog1"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid,
        "name": "bad progress",
        "video_path": "/old.mp4",
        "status": "processing",
        "progress": "999",
        "progress_msg": {"bad": "shape"},
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = _load_project(pid)

    assert loaded["progress"] == 100
    assert loaded["progress_msg"] == ""


def test_legacy_project_metadata_fields_are_sanitized(patched_projects_dir):
    pid = "badmeta1"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid,
        "name": "bad metadata",
        "video_path": "/old.mp4",
        "status": "created",
        "duration": -12,
        "tmdb_id": "42",
        "tmdb_type": "book",
        "season_number": 0,
        "archived": "false",
        "asr_skipped": "no",
        "prefer_embedded_subtitle": "yes",
        "asr_language": ["bad"],
        "target_language": "",
        "source_type": "bad-source",
        "error": {"bad": "shape"},
        "tmdb_candidates": {"bad": "shape"},
        "selected_audio_track": 9,
        "selected_subtitle_track": 9,
        "output_video": ["bad"],
        "audio_tracks": [{"index": 0, "codec": "aac"}],
        "subtitle_tracks": [{"index": 1, "codec": "subrip"}],
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = _load_project(pid)

    assert loaded["tmdb_id"] is None
    assert loaded["tmdb_type"] is None
    assert loaded["season_number"] is None
    assert loaded["archived"] is False
    assert loaded["asr_skipped"] is False
    assert loaded["prefer_embedded_subtitle"] is True
    assert loaded["asr_language"] == "auto"
    assert loaded["target_language"] == "简体中文"
    assert loaded["source_type"] == "upload"
    assert loaded["error"] is None
    assert loaded["tmdb_candidates"] is None
    assert loaded["selected_audio_track"] == 0
    assert loaded["selected_subtitle_track"] is None
    assert loaded["duration"] == 0
    assert loaded["output_video"] is None


def test_legacy_project_filters_malformed_track_entries_before_subtitle_pick(patched_projects_dir):
    pid = "badtrack"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid,
        "name": "bad tracks",
        "video_path": "/old.mp4",
        "status": "created",
        "target_language": ["bad"],
        "selected_subtitle_track": None,
        "subtitle_tracks": [
            "bad-entry",
            {"index": 1, "codec": {"bad": "shape"}, "lang": "eng"},
            {"index": 2, "codec": "subrip", "lang": {"bad": "shape"}},
            {"index": 2, "codec": "subrip", "lang": "eng"},
        ],
        "audio_tracks": ["bad-entry", {"index": 0, "codec": "aac"}],
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = _load_project(pid)

    assert loaded["target_language"] == "简体中文"
    assert loaded["audio_tracks"] == [{"index": 0, "codec": "aac"}]
    assert loaded["subtitle_tracks"] == [
        {"index": 1, "codec": {"bad": "shape"}, "lang": "eng"},
        {"index": 2, "codec": "subrip", "lang": {"bad": "shape"}},
        {"index": 2, "codec": "subrip", "lang": "eng"},
    ]
    assert loaded["selected_subtitle_track"] == 2


def test_legacy_project_resets_audio_selection_when_no_tracks(patched_projects_dir):
    pid = "badaudio"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid,
        "name": "bad audio",
        "video_path": "/old.mp4",
        "status": "created",
        "audio_tracks": [],
        "selected_audio_track": 9,
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = _load_project(pid)

    assert loaded["selected_audio_track"] == 0


def test_legacy_project_filters_malformed_tmdb_candidate_entries(patched_projects_dir):
    pid = "badcandidates"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid,
        "name": "bad candidates",
        "video_path": "/old.mp4",
        "status": "created",
        "tmdb_candidates": [
            "bad-entry",
            {"tmdb_id": 1, "title": "Good", "vote_average": float("nan")},
            None,
        ],
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = _load_project(pid)

    assert loaded["tmdb_candidates"] == [{"tmdb_id": 1, "title": "Good", "vote_average": None}]


def test_load_project_rejects_non_object_json(patched_projects_dir):
    pid = "badshape1"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text(json.dumps(["bad"]))

    with pytest.raises(HTTPException) as exc:
        _load_project(pid)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Project file is invalid"


def test_load_project_rejects_corrupt_json(patched_projects_dir):
    pid = "badjson1"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    (pdir / "project.json").write_text("{")

    with pytest.raises(HTTPException) as exc:
        _load_project(pid)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Project file is invalid"


@pytest.mark.parametrize("duration", [float("inf"), float("-inf"), float("nan")])
def test_legacy_project_non_finite_duration_is_sanitized(patched_projects_dir, duration):
    pid = "baddur01"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    legacy = {
        "id": pid,
        "name": "bad duration",
        "video_path": "/old.mp4",
        "status": "created",
        "duration": duration,
    }
    (pdir / "project.json").write_text(json.dumps(legacy))

    loaded = _load_project(pid)

    assert loaded["duration"] == 0


def test_legacy_project_overflowing_duration_is_sanitized(patched_projects_dir):
    from app.api.projects import _apply_safe_defaults

    loaded = _apply_safe_defaults({
        "id": "hugedur1",
        "name": "huge duration",
        "video_path": "/old.mp4",
        "status": "created",
        "duration": 10**10000,
    })

    assert loaded["duration"] == 0


def test_load_project_reports_overlong_json_number_as_invalid_file(patched_projects_dir):
    pid = "longnum1"
    pdir = patched_projects_dir / pid
    pdir.mkdir()
    huge_digits = "1" * 5000
    (pdir / "project.json").write_text(
        '{"id":"longnum1","name":"bad","video_path":"/old.mp4","status":"created","duration":'
        + huge_digits
        + "}",
        encoding="utf-8",
    )

    with pytest.raises(HTTPException) as exc:
        _load_project(pid)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Project file is invalid"
