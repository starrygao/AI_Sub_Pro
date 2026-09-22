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
async def test_discover_local_videos_returns_supported_files_sorted(tmp_path):
    from app.api.projects import DiscoverLocalVideosReq, discover_local_videos

    folder = tmp_path / "shows"
    nested = folder / "season"
    nested.mkdir(parents=True)
    (folder / "B.Episode.mkv").write_bytes(b"video")
    (folder / "notes.txt").write_text("not video", encoding="utf-8")
    (folder / ".hidden.mp4").write_bytes(b"hidden")
    (nested / "A.Episode.mp4").write_bytes(b"video")
    (nested / "empty.mov").write_bytes(b"")

    result = await discover_local_videos(DiscoverLocalVideosReq(folder_path=str(folder)))

    assert [item["name"] for item in result["videos"]] == [
        "B.Episode.mkv",
        "A.Episode.mp4",
    ]
    assert result["count"] == 2
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_discover_local_videos_rejects_file_path(tmp_path):
    from app.api.projects import DiscoverLocalVideosReq, discover_local_videos

    video = tmp_path / "Movie.mp4"
    video.write_bytes(b"video")

    with pytest.raises(HTTPException) as ei:
        await discover_local_videos(DiscoverLocalVideosReq(folder_path=str(video)))

    assert ei.value.status_code == 400
    assert "folder" in ei.value.detail.lower()


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


@pytest.mark.asyncio
async def test_create_project_infers_academic_metadata_and_skips_tmdb(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import CreateProjectReq, create_project
    from app.engines import tmdb_enrich

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    video = tmp_path / "Stanford.CS229.Lecture.04.Gradient.Descent.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(projects_api, "get_tracks", lambda *args, **kwargs: [])
    monkeypatch.setattr(projects_api, "get_duration", lambda *args, **kwargs: 12.3)

    async def fake_enrich(_name):
        raise AssertionError("academic lecture should not trigger TMDB enrichment")

    monkeypatch.setattr(tmdb_enrich, "enrich_from_filename", fake_enrich)

    project = await create_project(CreateProjectReq(video_path=str(video)))

    assert project["content_type"] == "academic_lecture"
    assert project["academic_field"] == "computer science"
    assert project["metadata_source"] == "filename"


def test_patch_project_persists_manual_content_metadata(tmp_path, monkeypatch):
    from app.api import projects as projects_api
    from app.api.projects import PatchProjectReq, patch_project
    from app.utils import project_store

    projects_dir = tmp_path / "projects"
    pdir = projects_dir / "p1"
    pdir.mkdir(parents=True)
    (pdir / "project.json").write_text(json.dumps({
        "id": "p1",
        "name": "Lecture.mp4",
        "video_path": str(tmp_path / "Lecture.mp4"),
        "duration": 1,
    }), encoding="utf-8")
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)

    updated = patch_project(PatchProjectReq(
        content_type="academic_lecture",
        academic_field="economics",
        content_notes="Seminar about causal inference.",
        manual_terms="causal inference=因果推断",
    ), pid="p1")

    assert updated["content_type"] == "academic_lecture"
    assert updated["academic_field"] == "economics"
    assert updated["content_notes"] == "Seminar about causal inference."
    assert updated["manual_terms"] == "causal inference=因果推断"

    cleared = patch_project(PatchProjectReq(
        clear=["content_type", "academic_field", "content_notes", "manual_terms", "metadata_source"],
    ), pid="p1")
    assert cleared["content_type"] == "auto"
    assert cleared["academic_field"] == ""
    assert cleared["content_notes"] == ""
    assert cleared["manual_terms"] == ""
    assert cleared["metadata_source"] == ""


@pytest.mark.asyncio
async def test_create_project_retains_failed_tmdb_lookup_for_confirmation(tmp_path, monkeypatch):
    import httpx
    from unittest.mock import AsyncMock
    from app.api import projects as api
    from app.engines import tmdb

    video = tmp_path / 'American.Hostage.S01E01.My.Town.Indy.1080p.mkv'
    video.write_bytes(b'video')
    monkeypatch.setattr(api, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(api, 'get_tracks', lambda *a, **kw: [])
    monkeypatch.setattr(api, 'get_duration', lambda *a, **kw: 12.3)
    monkeypatch.setattr(tmdb, 'search_tv', AsyncMock(side_effect=httpx.ProxyError('503 Service Unavailable')))
    project = await api.create_project(api.CreateProjectReq(video_path=str(video)))
    saved = json.loads((tmp_path / 'projects' / project['id'] / 'project.json').read_text())
    assert not project.get('tmdb_id')
    assert saved['tmdb_lookup'] == project['tmdb_lookup']
    assert project['tmdb_lookup']['query'] == 'American Hostage'
    assert '503' in project['tmdb_lookup']['error']
