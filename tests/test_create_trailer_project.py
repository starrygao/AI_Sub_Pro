import json

import pytest

from app.api import projects as projects_api


class _FakeUuid:
    def __init__(self, hex_value):
        self.hex = hex_value


@pytest.fixture
def patched_projects_dir(tmp_project_dir, monkeypatch):
    """Ensure the projects module uses the isolated PROJECTS_DIR.

    `app.api.projects` imports PROJECTS_DIR by name at module load, so the
    conftest fixture (which patches app.config) is not enough on its own.
    """
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    return tmp_project_dir


def test_create_trailer_project_writes_project_json(patched_projects_dir):
    from app.api.projects import create_trailer_project

    meta = create_trailer_project(
        tmdb_id=1399,
        tmdb_type="tv",
        season_number=1,
        video_key="abc123",
        youtube_url="https://www.youtube.com/watch?v=abc123",
        original_language="en",
        name="Game of Thrones \u00b7 Season 1 \u00b7 Trailer",
    )
    pid = meta["id"]
    pfile = patched_projects_dir / pid / "project.json"
    assert pfile.exists()
    data = json.loads(pfile.read_text())
    assert data["source_type"] == "trailer"
    assert data["tmdb_id"] == 1399
    assert data["tmdb_type"] == "tv"
    assert data["season_number"] == 1
    assert data["tmdb_video_key"] == "abc123"
    assert data["youtube_url"] == "https://www.youtube.com/watch?v=abc123"
    assert data["original_language"] == "en"
    assert data["auto_run"] is True
    assert data["status"] == "created"
    assert data["pipeline_stage"] == "download"
    assert data["name"].startswith("Game of Thrones")


def test_create_trailer_project_movie_no_season(patched_projects_dir):
    from app.api.projects import create_trailer_project

    meta = create_trailer_project(
        tmdb_id=550,
        tmdb_type="movie",
        season_number=None,
        video_key="xyz789",
        youtube_url="https://youtu.be/xyz789",
        original_language="en",
        name="Fight Club",
    )
    assert meta["season_number"] is None
    assert meta["tmdb_type"] == "movie"


def test_create_trailer_project_skips_existing_generated_project_id(patched_projects_dir, monkeypatch):
    from app.api.projects import create_trailer_project

    (patched_projects_dir / "aaaaaaaa").mkdir()
    ids = iter([_FakeUuid("aaaaaaaa0000"), _FakeUuid("cccccccc0000")])
    monkeypatch.setattr(projects_api.uuid, "uuid4", lambda: next(ids))

    meta = create_trailer_project(
        tmdb_id=550,
        tmdb_type="movie",
        season_number=None,
        video_key="xyz789",
        youtube_url="https://youtu.be/xyz789",
        original_language="en",
        name="Fight Club",
    )

    assert meta["id"] == "cccccccc"
    assert (patched_projects_dir / "cccccccc" / "project.json").exists()
    assert not (patched_projects_dir / "aaaaaaaa" / "project.json").exists()
