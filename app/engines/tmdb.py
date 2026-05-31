"""TMDB async client: search + videos + details. Uses httpx.AsyncClient.

Key source: Config.get("tmdb", "api_key"). Errors:
- TmdbAuthError: no key configured
- TmdbNotFoundError: 404 on specific resource
Generic 4xx/5xx propagate as httpx errors (caller can catch).
"""
import asyncio
import logging
import os
import re
from typing import List, Optional

import httpx

from app.config import Config

log = logging.getLogger(__name__)

_BASE_URL = "https://api.themoviedb.org/3"

_ENV_API_KEY = "AI_SUB_PRO_TMDB_API_KEY"


class TmdbAuthError(RuntimeError):
    pass


class TmdbNotFoundError(RuntimeError):
    pass


def public_error_message(exc: Exception, limit: int = 200) -> str:
    """Return a user-safe TMDB error message with credentials redacted."""
    text = str(exc)
    text = re.sub(r"(api_key=)[^&\s'\"<>]+", r"\1<redacted>", text)
    return text[:limit]


def _get_api_key() -> str:
    configured = Config.get("tmdb", "api_key")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return os.getenv(_ENV_API_KEY, "")


def _get_language() -> str:
    configured = Config.get("tmdb", "language")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return "zh-CN"


async def _get_json_with_key(path: str, params: dict, api_key: str, retries: int = 2) -> dict:
    api_key = api_key.strip() if isinstance(api_key, str) else ""
    if not api_key:
        raise TmdbAuthError("TMDB API key not configured (set in Settings -> TMDB)")
    params = dict(params, api_key=api_key)
    url = _BASE_URL + path

    last_exc = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, params=params, timeout=10.0)
                if r.status_code == 429:
                    log.warning("TMDB 429 rate-limited; retry %d/%d", attempt + 1, retries)
                    await asyncio.sleep(2)
                    continue
                if r.status_code == 404:
                    raise TmdbNotFoundError(f"TMDB 404 for {path}")
                r.raise_for_status()
                return r.json()
        except (TmdbNotFoundError, TmdbAuthError):
            raise
        except (httpx.HTTPError, ValueError) as e:
            last_exc = e
            if attempt < retries - 1:
                await asyncio.sleep(1)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("TMDB unreachable after retries")


async def _get_json(path: str, params: dict, retries: int = 2) -> dict:
    return await _get_json_with_key(path, params, _get_api_key(), retries=retries)


async def test_connection(api_key: Optional[str] = None, language: Optional[str] = None) -> bool:
    """Probe TMDB with the supplied key without mutating persistent settings."""
    key = api_key if isinstance(api_key, str) else _get_api_key()
    params = {}
    if isinstance(language, str) and language.strip():
        params["language"] = language.strip()
    data = await _get_json_with_key("/configuration", params, key, retries=1)
    return isinstance(data, dict)


def _parse_date(s: str) -> int:
    try:
        return int(s.replace("-", "").replace(":", "").replace("T", "")[:14] or "0")
    except Exception:
        return 0


def _sort_videos(videos: List[dict]) -> List[dict]:
    """Official trailers first, unofficial trailers, teasers, other. Within group: newest first."""
    def bucket(v):
        t = v.get("type", "")
        off = v.get("official", False)
        if t == "Trailer" and off: return 0
        if t == "Trailer": return 1
        if t == "Teaser": return 2
        return 3
    return sorted(videos, key=lambda v: (bucket(v), -_parse_date(v.get("published_at", ""))))


def _result_objects(data: dict) -> List[dict]:
    if not isinstance(data, dict):
        return []
    results = data.get("results", [])
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


async def search_multi(query: str) -> List[dict]:
    data = await _get_json("/search/multi", {"query": query, "language": _get_language()})
    return _result_objects(data)


async def search_tv(query: str, year: Optional[int] = None) -> List[dict]:
    params = {"query": query, "language": _get_language()}
    if year is not None:
        params["first_air_date_year"] = year
    data = await _get_json("/search/tv", params)
    return _result_objects(data)


async def search_movie(query: str, year: Optional[int] = None) -> List[dict]:
    params = {"query": query, "language": _get_language()}
    if year is not None:
        params["year"] = year
    data = await _get_json("/search/movie", params)
    return _result_objects(data)


async def get_tv_videos(tmdb_id: int, season: Optional[int] = None) -> List[dict]:
    path = f"/tv/{tmdb_id}/season/{season}/videos" if season is not None else f"/tv/{tmdb_id}/videos"
    # NOTE: don't pass `language` here — TMDB's /videos endpoint filters results BY that language,
    # so language=zh-CN would drop all English trailers for Western shows. Use include_video_language
    # to explicitly opt into en+zh videos regardless of the config language.
    data = await _get_json(path, {"include_video_language": "en,zh,null"})
    return _sort_videos(_result_objects(data))


async def get_movie_videos(tmdb_id: int) -> List[dict]:
    data = await _get_json(f"/movie/{tmdb_id}/videos", {"include_video_language": "en,zh,null"})
    return _sort_videos(_result_objects(data))


async def get_show_details(tmdb_id: int, media_type: str) -> dict:
    return await _get_json(f"/{media_type}/{tmdb_id}", {"language": _get_language()})
