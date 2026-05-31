"""Tests for trailer API routes (Phase 3 / Task 7)."""
from unittest.mock import patch, AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def patched_projects_dir(tmp_project_dir, monkeypatch):
    """Patch PROJECTS_DIR in every module that captured it at import time."""
    from app.api import projects as projects_api
    from app.api import trailer as trailer_api
    monkeypatch.setattr(projects_api, "PROJECTS_DIR", tmp_project_dir)
    monkeypatch.setattr(
        trailer_api,
        "require_translation_ready",
        lambda: {"translation_ready": True, "translation_hint": "已配置"},
    )
    try:
        from app.engines import trailer_pipeline as tp
        monkeypatch.setattr(tp, "PROJECTS_DIR", tmp_project_dir)
    except ImportError:
        pass
    return tmp_project_dir


def test_search_endpoint_returns_results(tmp_project_dir):
    from app.main import app
    client = TestClient(app)
    with patch("app.api.trailer.tmdb_search_multi", new_callable=AsyncMock) as mock:
        mock.return_value = [{"id": 1, "name": "Foo", "media_type": "tv"}]
        r = client.post("/api/trailer/search", json={"query": "foo"})
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["name"] == "Foo"


def test_videos_endpoint_tv_with_season(tmp_project_dir):
    from app.main import app
    client = TestClient(app)
    with patch("app.api.trailer.tmdb_get_tv_videos", new_callable=AsyncMock) as mock:
        mock.return_value = [{"key": "a", "type": "Trailer", "official": True}]
        r = client.get("/api/trailer/videos/1399?type=tv&season=1")
    assert r.status_code == 200
    assert r.json()["videos"][0]["key"] == "a"
    mock.assert_awaited_once()


def test_resolve_endpoint_rejects_non_positive_tmdb_id():
    from app.main import app
    client = TestClient(app)

    r = client.get("/api/trailer/resolve/-1")

    assert r.status_code == 400
    assert "tmdb_id" in r.json()["detail"]


def test_videos_endpoint_rejects_non_positive_ids_and_season():
    from app.main import app
    client = TestClient(app)

    r = client.get("/api/trailer/videos/0?type=tv")
    assert r.status_code == 400
    assert "tmdb_id" in r.json()["detail"]

    r = client.get("/api/trailer/videos/1399?type=tv&season=0")
    assert r.status_code == 400
    assert "season" in r.json()["detail"]


def test_require_non_blank_rejects_non_string_value():
    from fastapi import HTTPException
    from app.api.trailer import _require_non_blank

    with pytest.raises(HTTPException) as exc:
        _require_non_blank("name", 123)

    assert exc.value.status_code == 400
    assert "name" in exc.value.detail


def test_start_endpoint_creates_projects_and_schedules(patched_projects_dir, monkeypatch):
    """POST /api/trailer/start spawns background thread per video_key."""
    from app.main import app
    client = TestClient(app)

    threaded = []

    def fake_spawn(pid):
        threaded.append(pid)

    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", fake_spawn)

    r = client.post("/api/trailer/start", json={
        "tmdb_id": 1,
        "tmdb_type": "movie",
        "season": None,
        "video_keys": ["vidkey1abc", "vidkey2xyz"],
        "original_language": "en",
        "name": "Foo",
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["pids"]) == 2
    assert threaded == data["pids"]


def test_start_endpoint_rejects_missing_translation_provider_before_creating_projects(patched_projects_dir, monkeypatch):
    from app.main import app
    from app.api import trailer as trailer_api

    client = TestClient(app)

    def fail_ready():
        raise HTTPException(status_code=400, detail="请配置 OpenAI API 密钥")

    def fail_create(*args, **kwargs):
        raise AssertionError("project should not be created when translation is not ready")

    monkeypatch.setattr(trailer_api, "require_translation_ready", fail_ready)
    monkeypatch.setattr(trailer_api, "create_trailer_project", fail_create)
    monkeypatch.setattr(trailer_api, "_spawn_pipeline_thread", fail_create)

    r = client.post("/api/trailer/start", json={
        "tmdb_id": 1,
        "tmdb_type": "movie",
        "season": None,
        "video_keys": ["vidkey1abc"],
        "original_language": "en",
        "name": "Foo",
    })

    assert r.status_code == 400
    assert "OpenAI" in r.json()["detail"]
    assert list(patched_projects_dir.iterdir()) == []


def test_start_endpoint_strips_and_deduplicates_video_keys(patched_projects_dir, monkeypatch):
    from app.main import app
    from app.api.projects import _load_project
    client = TestClient(app)

    threaded = []
    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", lambda pid: threaded.append(pid))

    r = client.post("/api/trailer/start", json={
        "tmdb_id": 1,
        "tmdb_type": "movie",
        "season": None,
        "video_keys": [" vidkey1abc ", "vidkey1abc"],
        "original_language": " en ",
        "name": " Foo ",
    })

    assert r.status_code == 200
    data = r.json()
    assert len(data["pids"]) == 1
    assert threaded == data["pids"]
    project = _load_project(data["pids"][0])
    assert project["tmdb_video_key"] == "vidkey1abc"
    assert project["original_language"] == "en"
    assert project["name"].startswith("Foo ")


def test_start_endpoint_applies_configured_target_and_original_asr_language(patched_projects_dir, monkeypatch):
    from app.main import app
    from app.api.projects import _load_project
    import app.api.trailer as trailer_api

    client = TestClient(app)
    threaded = []
    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", lambda pid: threaded.append(pid))
    monkeypatch.setattr(
        trailer_api.Config,
        "get",
        lambda *keys, default=None: "English" if keys == ("translation", "target_language") else default,
    )

    r = client.post("/api/trailer/start", json={
        "tmdb_id": 1,
        "tmdb_type": "movie",
        "season": None,
        "video_keys": ["vidkey1abc"],
        "original_language": "ja",
        "name": "Foo",
    })

    assert r.status_code == 200
    data = r.json()
    assert threaded == data["pids"]
    project = _load_project(data["pids"][0])
    assert project["target_language"] == "English"
    assert project["asr_language"] == "ja"


def test_pipeline_submitter_uses_fixed_worker_pool(monkeypatch):
    """Scheduling many trailer jobs must queue them behind a fixed worker pool,
    not create one bare thread per video key."""
    import queue
    import app.api.trailer as trailer_api

    started = []

    class FakeThread:
        def __init__(self, target, name=None, daemon=None):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            started.append((self.name, self.daemon))

    monkeypatch.setattr(trailer_api, "_PIPELINE_QUEUE", queue.Queue(), raising=False)
    monkeypatch.setattr(trailer_api, "_WORKERS_STARTED", False, raising=False)
    monkeypatch.setattr(trailer_api, "_pipeline_worker_count", lambda: 2, raising=False)
    monkeypatch.setattr(trailer_api.threading, "Thread", FakeThread)

    for i in range(5):
        trailer_api._spawn_pipeline_thread(f"pid{i}")

    assert len(started) == 2
    assert trailer_api._PIPELINE_QUEUE.qsize() == 5


def test_pipeline_worker_count_ignores_boolean_config(monkeypatch):
    import app.api.trailer as trailer_api

    monkeypatch.setattr(trailer_api.Config, "get", lambda *keys: {"download": True} if keys == ("concurrency",) else None)

    assert trailer_api._pipeline_worker_count() == 3


def test_pipeline_worker_count_ignores_non_finite_config(monkeypatch):
    import app.api.trailer as trailer_api

    monkeypatch.setattr(trailer_api.Config, "get", lambda *keys: {"download": float("inf")} if keys == ("concurrency",) else None)

    assert trailer_api._pipeline_worker_count() == 3


def test_pipeline_worker_count_ignores_overflowing_config(monkeypatch):
    import app.api.trailer as trailer_api

    monkeypatch.setattr(trailer_api.Config, "get", lambda *keys: {"download": 10**10000} if keys == ("concurrency",) else None)

    assert trailer_api._pipeline_worker_count() == 3


def test_pipeline_worker_count_ignores_non_object_config_sections(monkeypatch):
    import app.api.trailer as trailer_api

    monkeypatch.setattr(trailer_api.Config, "get", lambda *keys: ["bad"])

    assert trailer_api._pipeline_worker_count() == 3


def test_resolve_endpoint_returns_tmdb_id_details(tmp_project_dir, monkeypatch):
    from app.main import app
    client = TestClient(app)

    async def fake_details(tmdb_id, media_type):
        if media_type == "tv":
            return {
                "id": tmdb_id,
                "name": "Game of Thrones",
                "overview": "A fantasy series.",
                "poster_path": "/poster.jpg",
                "original_language": "en",
                "first_air_date": "2011-04-17",
                "number_of_seasons": 8,
            }
        from app.engines.tmdb import TmdbNotFoundError
        raise TmdbNotFoundError("not found")

    monkeypatch.setattr("app.api.trailer.tmdb_get_show_details", fake_details)

    r = client.get("/api/trailer/resolve/1399")
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["id"] == 1399
    assert results[0]["media_type"] == "tv"
    assert results[0]["name"] == "Game of Thrones"
    assert results[0]["number_of_seasons"] == 8


def test_resolve_endpoint_reports_upstream_failure_without_leaking_key(tmp_project_dir, monkeypatch):
    from app.main import app
    client = TestClient(app)

    async def fake_details(tmdb_id, media_type):
        raise RuntimeError("GET https://api.test/tv/1?api_key=secret123&language=zh-CN failed")

    monkeypatch.setattr("app.api.trailer.tmdb_get_show_details", fake_details)

    r = client.get("/api/trailer/resolve/1399")

    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "TMDB detail lookup failed" in detail
    assert "secret123" not in detail
    assert "api_key=<redacted>" in detail


def test_resolve_endpoint_reports_malformed_detail_response(tmp_project_dir, monkeypatch):
    from app.main import app
    client = TestClient(app)

    async def fake_details(tmdb_id, media_type):
        return ["bad shape"]

    monkeypatch.setattr("app.api.trailer.tmdb_get_show_details", fake_details)

    r = client.get("/api/trailer/resolve/1399")

    assert r.status_code == 502
    assert "TMDB detail lookup failed" in r.json()["detail"]


def test_search_endpoint_surfaces_auth_error():
    from app.main import app
    client = TestClient(app)
    with patch("app.api.trailer.tmdb_search_multi", new_callable=AsyncMock) as mock:
        from app.engines.tmdb import TmdbAuthError
        mock.side_effect = TmdbAuthError("no key")
        r = client.post("/api/trailer/search", json={"query": "foo"})
    assert r.status_code in (400, 401)
    detail = r.json().get("detail", "")
    assert "TMDB" in detail or "key" in detail.lower()


def test_search_endpoint_redacts_generic_upstream_errors():
    from app.main import app
    client = TestClient(app)
    with patch("app.api.trailer.tmdb_search_multi", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("GET https://api.test/search?api_key=secret123 failed")
        r = client.post("/api/trailer/search", json={"query": "foo"})

    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "TMDB search failed" in detail
    assert "secret123" not in detail
    assert "api_key=<redacted>" in detail


def test_search_endpoint_rejects_invalid_media_type():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/trailer/search", json={"query": "foo", "media_type": "book"})

    assert r.status_code == 400
    assert "media_type" in r.json()["detail"]


def test_search_endpoint_rejects_empty_query():
    from app.main import app
    client = TestClient(app)

    r = client.post("/api/trailer/search", json={"query": "   "})

    assert r.status_code == 400
    assert "query" in r.json()["detail"]


def test_start_endpoint_rejects_invalid_tmdb_type(patched_projects_dir, monkeypatch):
    from app.main import app
    client = TestClient(app)

    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", lambda pid: None)

    r = client.post("/api/trailer/start", json={
        "tmdb_id": 1,
        "tmdb_type": "book",
        "season": None,
        "video_keys": ["vidkey1abc"],
        "original_language": "en",
        "name": "Foo",
    })

    assert r.status_code == 400
    assert "tmdb_type" in r.json()["detail"]


def test_videos_endpoint_redacts_generic_upstream_errors():
    from app.main import app
    client = TestClient(app)
    with patch("app.api.trailer.tmdb_get_movie_videos", new_callable=AsyncMock) as mock:
        mock.side_effect = RuntimeError("GET https://api.test/movie?api_key=secret123 failed")
        r = client.get("/api/trailer/videos/1399?type=movie")

    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "TMDB video lookup failed" in detail
    assert "secret123" not in detail
    assert "api_key=<redacted>" in detail


def test_start_endpoint_rejects_non_positive_tmdb_id_and_season(patched_projects_dir, monkeypatch):
    from app.main import app
    client = TestClient(app)

    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", lambda pid: None)

    payload = {
        "tmdb_id": 0,
        "tmdb_type": "tv",
        "season": 1,
        "video_keys": ["vidkey1abc"],
        "original_language": "en",
        "name": "Foo",
    }
    r = client.post("/api/trailer/start", json=payload)
    assert r.status_code == 400
    assert "tmdb_id" in r.json()["detail"]

    payload["tmdb_id"] = 1
    payload["season"] = 0
    r = client.post("/api/trailer/start", json=payload)
    assert r.status_code == 400
    assert "season" in r.json()["detail"]


@pytest.mark.parametrize("payload_update", [
    {"tmdb_id": True},
    {"season": True},
])
def test_start_endpoint_rejects_boolean_integer_fields(patched_projects_dir, monkeypatch, payload_update):
    from app.main import app
    client = TestClient(app)

    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", lambda pid: None)

    payload = {
        "tmdb_id": 1,
        "tmdb_type": "tv",
        "season": 1,
        "video_keys": ["vidkey1abc"],
        "original_language": "en",
        "name": "Foo",
    }
    payload.update(payload_update)

    r = client.post("/api/trailer/start", json=payload)

    assert r.status_code == 422


def test_start_endpoint_rejects_empty_video_keys(patched_projects_dir, monkeypatch):
    from app.main import app
    client = TestClient(app)

    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", lambda pid: None)

    r = client.post("/api/trailer/start", json={
        "tmdb_id": 1,
        "tmdb_type": "movie",
        "season": None,
        "video_keys": [],
        "original_language": "en",
        "name": "Foo",
    })

    assert r.status_code == 400
    assert "video_keys" in r.json()["detail"]


def test_start_endpoint_rejects_blank_name_and_language(patched_projects_dir, monkeypatch):
    from app.main import app
    client = TestClient(app)

    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", lambda pid: None)

    payload = {
        "tmdb_id": 1,
        "tmdb_type": "movie",
        "season": None,
        "video_keys": ["vidkey1abc"],
        "original_language": "en",
        "name": " ",
    }
    r = client.post("/api/trailer/start", json=payload)
    assert r.status_code == 400
    assert "name" in r.json()["detail"]

    payload["name"] = "Foo"
    payload["original_language"] = " "
    r = client.post("/api/trailer/start", json=payload)
    assert r.status_code == 400
    assert "original_language" in r.json()["detail"]


def test_start_endpoint_rejects_when_all_video_keys_are_invalid(patched_projects_dir, monkeypatch):
    from app.main import app
    client = TestClient(app)

    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", lambda pid: None)

    r = client.post("/api/trailer/start", json={
        "tmdb_id": 1,
        "tmdb_type": "movie",
        "season": None,
        "video_keys": ["bad"],
        "original_language": "en",
        "name": "Foo",
    })

    assert r.status_code == 400
    assert "valid video" in r.json()["detail"]
