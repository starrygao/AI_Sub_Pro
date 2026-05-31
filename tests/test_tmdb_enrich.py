"""Tests for tmdb_enrich.enrich_from_filename: filename → TMDB search →
auto-attach decision."""
import pytest
from unittest.mock import patch, AsyncMock


# Sample TMDB-shaped fixtures
MOVIE_RESULT = {
    "id": 12345,
    "title": "爱情抓马",
    "original_title": "The Drama",
    "release_date": "2026-03-15",
    "original_language": "zh",
    "poster_path": "/abc.jpg",
    "overview": "A romance",
    "vote_average": 7.4,
}

MOVIE_RESULT_OTHER_YEAR = {
    "id": 99999,
    "title": "爱情抓马",
    "release_date": "2018-01-01",
    "original_language": "zh",
    "poster_path": "/old.jpg",
    "vote_average": 5.0,
}

TV_RESULT = {
    "id": 7777,
    "name": "Black Mirror",
    "original_name": "Black Mirror",
    "first_air_date": "2011-12-04",
    "original_language": "en",
    "poster_path": "/bm.jpg",
    "vote_average": 8.7,
}


@pytest.mark.asyncio
async def test_movie_year_match_auto_attaches():
    from app.engines import tmdb_enrich
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "爱情抓马", "year": 2026, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie", new=AsyncMock(return_value=[MOVIE_RESULT])):
        out = await tmdb_enrich.enrich_from_filename("爱情抓马 (2026) - 1080p.mkv")

    assert out["auto_attached"] is True
    assert out["tmdb_id"] == 12345
    assert out["tmdb_type"] == "movie"
    assert out["year"] == 2026
    assert out["original_language"] == "zh"


@pytest.mark.asyncio
async def test_movie_year_mismatch_returns_candidates_only():
    """Year provided but top result's year differs → don't auto-attach,
    surface candidates so user can confirm or reject."""
    from app.engines import tmdb_enrich
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "爱情抓马", "year": 2026, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie",
               new=AsyncMock(return_value=[MOVIE_RESULT_OTHER_YEAR])):
        out = await tmdb_enrich.enrich_from_filename("爱情抓马 (2026).mkv")

    assert out["auto_attached"] is False
    assert out["tmdb_id"] is None
    assert len(out["candidates"]) == 1
    assert out["candidates"][0]["tmdb_id"] == 99999


@pytest.mark.asyncio
async def test_tv_episode_carries_season_number():
    from app.engines import tmdb_enrich
    parsed = {"title": "Black Mirror", "year": 2011, "type": "tv",
              "season": 5, "episode": 1}
    with patch.object(tmdb_enrich, "parse_filename", return_value=parsed), \
         patch("app.engines.tmdb.search_tv", new=AsyncMock(return_value=[TV_RESULT])):
        out = await tmdb_enrich.enrich_from_filename("Black.Mirror.S05E01.mkv")

    assert out["auto_attached"] is True
    assert out["tmdb_type"] == "tv"
    assert out["season_number"] == 5


@pytest.mark.asyncio
async def test_no_year_single_result_auto_attaches():
    """When user has no year hint and TMDB returns exactly one match,
    auto-attach (still better than guessing)."""
    from app.engines import tmdb_enrich
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "Inception", "year": None, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie",
               new=AsyncMock(return_value=[MOVIE_RESULT])):
        out = await tmdb_enrich.enrich_from_filename("Inception.mkv")
    assert out["auto_attached"] is True


@pytest.mark.asyncio
async def test_no_year_multiple_results_returns_candidates():
    from app.engines import tmdb_enrich
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "Foo", "year": None, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie",
               new=AsyncMock(return_value=[MOVIE_RESULT, MOVIE_RESULT_OTHER_YEAR])):
        out = await tmdb_enrich.enrich_from_filename("Foo.mkv")
    assert out["auto_attached"] is False
    assert len(out["candidates"]) == 2


@pytest.mark.asyncio
async def test_no_search_results_returns_empty():
    from app.engines import tmdb_enrich
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "Nonexistent", "year": 2099, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie", new=AsyncMock(return_value=[])):
        out = await tmdb_enrich.enrich_from_filename("Nonexistent.2099.mkv")
    assert out["auto_attached"] is False
    assert out["candidates"] == []
    assert out["tmdb_id"] is None


@pytest.mark.asyncio
async def test_tmdb_network_error_swallowed():
    """TMDB outage / no API key must NOT raise — return empty result so
    project creation continues unblocked."""
    from app.engines import tmdb_enrich
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "Foo", "year": 2020, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie",
               new=AsyncMock(side_effect=RuntimeError("network down"))):
        out = await tmdb_enrich.enrich_from_filename("Foo.2020.mkv")
    assert out["auto_attached"] is False
    assert out["candidates"] == []


@pytest.mark.asyncio
async def test_tmdb_search_error_log_redacts_api_key(caplog):
    from app.engines import tmdb_enrich

    caplog.set_level("INFO", logger="app.engines.tmdb_enrich")
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "Foo", "year": 2020, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie",
               new=AsyncMock(side_effect=RuntimeError("failed api_key=secret123"))):
        out = await tmdb_enrich.enrich_from_filename("Foo.2020.mkv")

    assert out["auto_attached"] is False
    assert "secret123" not in caplog.text
    assert "api_key=<redacted>" in caplog.text


@pytest.mark.asyncio
async def test_unparseable_filename_returns_empty():
    from app.engines import tmdb_enrich
    with patch.object(tmdb_enrich, "parse_filename", return_value=None):
        out = await tmdb_enrich.enrich_from_filename("garbage")
    assert out["auto_attached"] is False
    assert out["candidates"] == []


@pytest.mark.asyncio
async def test_malformed_parse_result_returns_empty():
    from app.engines import tmdb_enrich
    with patch.object(tmdb_enrich, "parse_filename", return_value={"title": "", "type": "book"}):
        out = await tmdb_enrich.enrich_from_filename("garbage")
    assert out["auto_attached"] is False
    assert out["candidates"] == []


@pytest.mark.asyncio
async def test_tv_candidate_uses_original_name_fallback():
    from app.engines import tmdb_enrich
    result = {
        "id": 222,
        "original_name": "Original Show",
        "first_air_date": "2020-01-01",
        "original_language": "en",
    }
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "Original Show", "year": 2020, "type": "tv"}), \
         patch("app.engines.tmdb.search_tv", new=AsyncMock(return_value=[result])):
        out = await tmdb_enrich.enrich_from_filename("Original.Show.S01E01.mkv")

    assert out["auto_attached"] is True
    assert out["show_title"] == "Original Show"


@pytest.mark.asyncio
async def test_malformed_tmdb_candidates_are_dropped():
    from app.engines import tmdb_enrich
    malformed = {"title": "No ID", "release_date": "2026-01-01"}
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "No ID", "year": 2026, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie", new=AsyncMock(return_value=[malformed])):
        out = await tmdb_enrich.enrich_from_filename("No.ID.2026.mkv")

    assert out["auto_attached"] is False
    assert out["candidates"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [True, "333", 0, -1])
async def test_tmdb_candidate_rejects_non_positive_or_non_integer_ids(bad_id):
    from app.engines import tmdb_enrich
    malformed = {"id": bad_id, "title": "Bad ID", "release_date": "2026-01-01"}
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "Bad ID", "year": 2026, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie", new=AsyncMock(return_value=[malformed])):
        out = await tmdb_enrich.enrich_from_filename("Bad.ID.2026.mkv")

    assert out["auto_attached"] is False
    assert out["candidates"] == []


@pytest.mark.asyncio
async def test_tmdb_candidate_bad_field_types_do_not_crash():
    from app.engines import tmdb_enrich
    malformed_fields = {
        "id": 333,
        "title": "Odd Movie",
        "release_date": 20260101,
        "overview": None,
    }
    with patch.object(tmdb_enrich, "parse_filename",
                      return_value={"title": "Odd Movie", "year": None, "type": "movie"}), \
         patch("app.engines.tmdb.search_movie", new=AsyncMock(return_value=[malformed_fields])):
        out = await tmdb_enrich.enrich_from_filename("Odd.Movie.mkv")

    assert out["auto_attached"] is True
    assert out["year"] is None
    assert out["candidates"][0]["overview"] == ""
