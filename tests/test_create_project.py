import pytest
import json
from fastapi import HTTPException


class _FakeUuid:
    def __init__(self, hex_value):
        self.hex = hex_value


@pytest.mark.asyncio
async def test_create_project_rejects_directory_path(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import CreateProjectReq, create_project

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)

    with pytest.raises(HTTPException) as ei:
        await create_project(CreateProjectReq(video_path=str(tmp_path)))

    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_create_project_rejects_empty_video_file(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import CreateProjectReq, create_project

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    empty_video = tmp_path / "empty.mp4"
    empty_video.write_bytes(b"")
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)

    with pytest.raises(HTTPException) as ei:
        await create_project(CreateProjectReq(video_path=str(empty_video)))

    assert ei.value.status_code == 400
    assert "empty" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_create_project_rejects_non_video_extension(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import CreateProjectReq, create_project

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    text_file = tmp_path / "notes.txt"
    text_file.write_bytes(b"not a video")
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)

    with pytest.raises(HTTPException) as ei:
        await create_project(CreateProjectReq(video_path=str(text_file)))

    assert ei.value.status_code == 400
    assert "video" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_create_project_blank_name_falls_back_to_filename(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import CreateProjectReq, create_project

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    video = tmp_path / "Movie.Name.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projects_api, "get_tracks", lambda *args, **kwargs: [])
    monkeypatch.setattr(projects_api, "get_duration", lambda *args, **kwargs: 12.3)

    project = await create_project(CreateProjectReq(video_path=str(video), name="   "))

    assert project["name"] == "Movie.Name.mp4"


@pytest.mark.asyncio
async def test_create_project_uses_requested_workflow_languages_for_defaults(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import CreateProjectReq, create_project

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    video = tmp_path / "Movie.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projects_api, "get_tracks", lambda path, kind: (
        [{"codec": "aac", "lang": "und"}] if kind == "a" else [
            {"codec": "subrip", "lang": "eng"},
            {"codec": "subrip", "lang": "chi"},
        ]
    ))
    monkeypatch.setattr(projects_api, "get_duration", lambda *args, **kwargs: 12.3)

    project = await create_project(CreateProjectReq(
        video_path=str(video),
        asr_language="en",
        target_language="English",
    ))

    assert project["asr_language"] == "en"
    assert project["target_language"] == "English"
    assert project["selected_subtitle_track"] == 1


@pytest.mark.asyncio
async def test_create_project_skips_existing_generated_project_id(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import CreateProjectReq, create_project

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "aaaaaaaa").mkdir()
    video = tmp_path / "Movie.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projects_api, "get_tracks", lambda *args, **kwargs: [])
    monkeypatch.setattr(projects_api, "get_duration", lambda *args, **kwargs: 12.3)
    ids = iter([_FakeUuid("aaaaaaaa0000"), _FakeUuid("bbbbbbbb0000")])
    monkeypatch.setattr(projects_api.uuid, "uuid4", lambda: next(ids))

    project = await create_project(CreateProjectReq(video_path=str(video)))

    assert project["id"] == "bbbbbbbb"
    assert (projects_dir / "bbbbbbbb" / "project.json").exists()
    assert not (projects_dir / "aaaaaaaa" / "project.json").exists()


@pytest.mark.asyncio
async def test_create_project_sanitizes_non_finite_duration_before_save(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import CreateProjectReq, create_project

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    video = tmp_path / "Movie.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projects_api, "get_tracks", lambda *args, **kwargs: [])
    monkeypatch.setattr(projects_api, "get_duration", lambda *args, **kwargs: float("nan"))

    project = await create_project(CreateProjectReq(video_path=str(video)))

    saved = json.loads((projects_dir / project["id"] / "project.json").read_text(encoding="utf-8"))
    assert project["duration"] == 0
    assert saved["duration"] == 0


@pytest.mark.asyncio
async def test_create_project_sanitizes_non_finite_tmdb_candidates_before_save(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import CreateProjectReq, create_project
    from app.engines import tmdb_enrich

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    video = tmp_path / "Movie.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projects_api, "get_tracks", lambda *args, **kwargs: [])
    monkeypatch.setattr(projects_api, "get_duration", lambda *args, **kwargs: 12.3)

    async def fake_enrich(_name):
        return {
            "auto_attached": False,
            "candidates": [{"tmdb_id": 1, "title": "Movie", "vote_average": float("nan")}],
        }

    monkeypatch.setattr(tmdb_enrich, "enrich_from_filename", fake_enrich)

    project = await create_project(CreateProjectReq(video_path=str(video)))

    saved = json.loads((projects_dir / project["id"] / "project.json").read_text(encoding="utf-8"))
    assert project["tmdb_candidates"][0]["vote_average"] is None
    assert saved["tmdb_candidates"][0]["vote_average"] is None
