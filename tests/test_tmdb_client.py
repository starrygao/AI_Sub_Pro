import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


def test_tmdb_client_requires_api_key(monkeypatch):
    from app.engines import tmdb
    monkeypatch.setattr(tmdb, "_get_api_key", lambda: "")
    with pytest.raises(tmdb.TmdbAuthError):
        asyncio.run(tmdb.search_multi("test"))


def test_tmdb_api_key_can_come_from_environment(monkeypatch):
    from app.engines import tmdb

    monkeypatch.setattr(tmdb.Config, "get", lambda *a, **kw: "")
    monkeypatch.setenv("AI_SUB_PRO_TMDB_API_KEY", "env-key")
    assert tmdb._get_api_key() == "env-key"

    monkeypatch.delenv("AI_SUB_PRO_TMDB_API_KEY")
    assert tmdb._get_api_key() == ""


def test_tmdb_config_values_require_strings(monkeypatch):
    from app.engines import tmdb

    monkeypatch.setattr(tmdb.Config, "get", lambda *a, **kw: 123)
    monkeypatch.setenv("AI_SUB_PRO_TMDB_API_KEY", "env-key")

    assert tmdb._get_api_key() == "env-key"
    assert tmdb._get_language() == "zh-CN"


def test_tmdb_search_multi_calls_expected_endpoint(monkeypatch):
    from app.engines import tmdb
    monkeypatch.setattr(tmdb, "_get_api_key", lambda: "test-key")

    captured = {}

    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"results": [{"id": 123, "media_type": "tv", "name": "Foo"}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr(tmdb.httpx, "AsyncClient", FakeClient)

    results = asyncio.run(tmdb.search_multi("权力的游戏"))
    assert "/search/multi" in captured["url"]
    assert captured["params"]["query"] == "权力的游戏"
    assert captured["params"]["api_key"] == "test-key"
    assert captured["params"]["language"] == "zh-CN"
    assert len(results) == 1
    assert results[0]["id"] == 123


def test_tmdb_get_tv_videos_sorts_official_trailers_first(monkeypatch):
    from app.engines import tmdb
    monkeypatch.setattr(tmdb, "_get_api_key", lambda: "test-key")

    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                {"key": "a", "type": "Teaser", "official": True, "published_at": "2024-01-01", "iso_639_1": "en"},
                {"key": "b", "type": "Trailer", "official": True, "published_at": "2024-06-01", "iso_639_1": "en"},
                {"key": "c", "type": "Trailer", "official": False, "published_at": "2024-07-01", "iso_639_1": "en"},
                {"key": "d", "type": "Behind the Scenes", "official": True, "published_at": "2024-08-01", "iso_639_1": "en"},
            ]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(tmdb.httpx, "AsyncClient", FakeClient)
    videos = asyncio.run(tmdb.get_tv_videos(1399))
    assert videos[0]["key"] == "b"  # official trailer
    assert videos[1]["key"] == "c"  # unofficial trailer
    assert videos[2]["key"] == "a"  # teaser
    assert videos[-1]["key"] == "d"  # behind-the-scenes last


def test_tmdb_rate_limit_retry_once(monkeypatch):
    from app.engines import tmdb
    monkeypatch.setattr(tmdb, "_get_api_key", lambda: "test-key")

    call_count = [0]

    class FakeResponse429:
        status_code = 429
        def raise_for_status(self): pass
        def json(self): return {}

    class FakeResponse200:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"results": [{"id": 1}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, timeout=None):
            call_count[0] += 1
            return FakeResponse429() if call_count[0] == 1 else FakeResponse200()

    monkeypatch.setattr(tmdb.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(tmdb.asyncio, "sleep", AsyncMock())
    results = asyncio.run(tmdb.search_multi("x"))
    assert call_count[0] == 2
    assert len(results) == 1


def test_tmdb_invalid_json_retries(monkeypatch):
    from app.engines import tmdb
    monkeypatch.setattr(tmdb, "_get_api_key", lambda: "test-key")

    call_count = [0]

    class FakeBadJson:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            raise ValueError("not json")

    class FakeResponse200:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"results": [{"id": 1}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, timeout=None):
            call_count[0] += 1
            return FakeBadJson() if call_count[0] == 1 else FakeResponse200()

    monkeypatch.setattr(tmdb.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(tmdb.asyncio, "sleep", AsyncMock())

    results = asyncio.run(tmdb.search_multi("x"))

    assert call_count[0] == 2
    assert results == [{"id": 1}]


def test_tmdb_search_ignores_non_list_results(monkeypatch):
    from app.engines import tmdb
    monkeypatch.setattr(tmdb, "_get_api_key", lambda: "test-key")

    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"results": {"id": 1, "title": "bad shape"}}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(tmdb.httpx, "AsyncClient", FakeClient)

    assert asyncio.run(tmdb.search_movie("x")) == []


def test_tmdb_videos_drop_non_object_results(monkeypatch):
    from app.engines import tmdb
    monkeypatch.setattr(tmdb, "_get_api_key", lambda: "test-key")

    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                "bad",
                {"key": "ok", "type": "Trailer", "official": True, "published_at": "2026-01-01"},
                None,
            ]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None, timeout=None):
            return FakeResponse()

    monkeypatch.setattr(tmdb.httpx, "AsyncClient", FakeClient)

    videos = asyncio.run(tmdb.get_movie_videos(123))

    assert [v["key"] for v in videos] == ["ok"]
