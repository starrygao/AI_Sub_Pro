"""Trailer API routes: search, videos, start."""
import math
import queue
import logging
import threading
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StrictInt

from app.engines.tmdb import (
    search_multi as tmdb_search_multi,
    search_tv as tmdb_search_tv,
    search_movie as tmdb_search_movie,
    get_tv_videos as tmdb_get_tv_videos,
    get_movie_videos as tmdb_get_movie_videos,
    get_show_details as tmdb_get_show_details,
    TmdbAuthError,
    TmdbNotFoundError,
    public_error_message,
)
from app.config import Config
from app.api.settings import require_translation_ready
from app.engines.trailer_downloader import build_youtube_url
from app.engines.trailer_pipeline import run_trailer_pipeline
from app.api.projects import create_trailer_project

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trailer", tags=["trailer"])

_PIPELINE_QUEUE: "queue.Queue[str]" = queue.Queue()
_WORKERS_STARTED = False
_WORKERS_LOCK = threading.Lock()


class SearchReq(BaseModel):
    query: str
    media_type: Optional[str] = None  # "tv" | "movie" | None (multi)


class StartReq(BaseModel):
    tmdb_id: StrictInt
    tmdb_type: str  # "tv" | "movie"
    season: Optional[StrictInt] = None
    video_keys: List[str]
    original_language: str
    name: str
    target_language: Optional[str] = None


def _require_positive_int(name: str, value: Optional[int]) -> None:
    if value is not None and value < 1:
        raise HTTPException(status_code=400, detail=f"{name} must be positive")


def _require_non_blank(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{name} must be a string")
    value = value.strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{name} must not be empty")
    return value


def _configured_target_language(override: Optional[str] = None) -> str:
    if override is not None:
        return _require_non_blank("target_language", override)
    configured = Config.get("translation", "target_language", default="简体中文")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return "简体中文"


@router.post("/search")
async def search(req: SearchReq):
    if req.media_type not in (None, "tv", "movie"):
        raise HTTPException(status_code=400, detail="invalid media_type")
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    try:
        if req.media_type == "tv":
            results = await tmdb_search_tv(req.query)
        elif req.media_type == "movie":
            results = await tmdb_search_movie(req.query)
        else:
            results = await tmdb_search_multi(req.query)
    except TmdbAuthError as e:
        raise HTTPException(status_code=400, detail=f"TMDB API key missing or invalid: {e}")
    except Exception as e:
        log.warning("TMDB search failed: %s", public_error_message(e))
        raise HTTPException(
            status_code=502,
            detail=f"TMDB search failed: {public_error_message(e)}",
        )
    return {"results": results}


def _normalize_detail(tmdb_id: int, media_type: str, detail: dict) -> dict:
    if not isinstance(detail, dict):
        raise ValueError("TMDB detail response must be an object")
    item = {
        "id": detail.get("id") or tmdb_id,
        "media_type": media_type,
        "overview": detail.get("overview") or "",
        "poster_path": detail.get("poster_path"),
        "original_language": detail.get("original_language"),
    }
    if media_type == "tv":
        item.update({
            "name": detail.get("name") or "",
            "original_name": detail.get("original_name") or "",
            "first_air_date": detail.get("first_air_date") or "",
            "number_of_seasons": detail.get("number_of_seasons") or 0,
            "seasons": detail.get("seasons") or [],
        })
    else:
        item.update({
            "title": detail.get("title") or "",
            "original_title": detail.get("original_title") or "",
            "release_date": detail.get("release_date") or "",
        })
    return item


@router.get("/resolve/{tmdb_id}")
async def resolve(tmdb_id: int):
    """Resolve a bare TMDB id by trying TV and movie details."""
    _require_positive_int("tmdb_id", tmdb_id)
    results = []
    lookup_error: Optional[Exception] = None
    for media_type in ("tv", "movie"):
        try:
            detail = await tmdb_get_show_details(tmdb_id, media_type)
        except TmdbNotFoundError:
            continue
        except TmdbAuthError as e:
            raise HTTPException(status_code=400, detail=f"TMDB API key missing or invalid: {e}")
        except Exception as e:
            lookup_error = e
            log.warning(
                "TMDB detail lookup failed id=%s type=%s: %s",
                tmdb_id,
                media_type,
                public_error_message(e),
            )
            continue
        try:
            results.append(_normalize_detail(tmdb_id, media_type, detail))
        except ValueError as e:
            lookup_error = e
            log.warning(
                "TMDB detail normalization failed id=%s type=%s: %s",
                tmdb_id,
                media_type,
                public_error_message(e),
            )
            continue
    if not results:
        if lookup_error:
            raise HTTPException(
                status_code=502,
                detail=f"TMDB detail lookup failed: {public_error_message(lookup_error)}",
            )
        raise HTTPException(status_code=404, detail=f"TMDB id not found: {tmdb_id}")
    return {"results": results}


@router.get("/videos/{tmdb_id}")
async def videos(tmdb_id: int, type: str = "tv", season: Optional[int] = None):
    _require_positive_int("tmdb_id", tmdb_id)
    _require_positive_int("season", season)
    try:
        if type == "tv":
            results = await tmdb_get_tv_videos(tmdb_id, season=season)
        elif type == "movie":
            results = await tmdb_get_movie_videos(tmdb_id)
        else:
            raise HTTPException(status_code=400, detail=f"invalid type: {type}")
    except TmdbAuthError as e:
        raise HTTPException(status_code=400, detail=f"TMDB API key missing: {e}")
    except TmdbNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.warning("TMDB video lookup failed: %s", public_error_message(e))
        raise HTTPException(
            status_code=502,
            detail=f"TMDB video lookup failed: {public_error_message(e)}",
        )
    return {"videos": results}


def _pipeline_worker_count() -> int:
    cfg = Config.get("concurrency") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    general = Config.get("general") or {}
    if not isinstance(general, dict):
        general = {}
    raw = cfg.get("download") or general.get("max_workers") or 3
    if isinstance(raw, bool):
        raw = 3
    try:
        numeric = float(raw)
        if not math.isfinite(numeric):
            raise ValueError("non-finite worker count")
        count = int(numeric)
    except (OverflowError, TypeError, ValueError):
        count = 3
    return max(1, min(16, count))


def _pipeline_worker() -> None:
    while True:
        pid = _PIPELINE_QUEUE.get()
        try:
            run_trailer_pipeline(pid)
        except Exception:
            log.exception("uncaught trailer pipeline failure pid=%s", pid)
        finally:
            _PIPELINE_QUEUE.task_done()


def _ensure_pipeline_workers() -> None:
    global _WORKERS_STARTED
    if _WORKERS_STARTED:
        return
    with _WORKERS_LOCK:
        if _WORKERS_STARTED:
            return
        for i in range(_pipeline_worker_count()):
            t = threading.Thread(
                target=_pipeline_worker,
                name=f"trailer-pipeline-{i + 1}",
                daemon=True,
            )
            t.start()
        _WORKERS_STARTED = True


def _spawn_pipeline_thread(pid: str) -> None:
    """Queue a trailer pipeline job behind a fixed daemon worker pool."""
    _ensure_pipeline_workers()
    _PIPELINE_QUEUE.put(pid)


@router.post("/start")
def start(req: StartReq):
    _require_positive_int("tmdb_id", req.tmdb_id)
    _require_positive_int("season", req.season)
    if req.tmdb_type not in {"tv", "movie"}:
        raise HTTPException(status_code=400, detail="invalid tmdb_type")
    if not req.video_keys:
        raise HTTPException(status_code=400, detail="video_keys must not be empty")
    base_name = _require_non_blank("name", req.name)
    original_language = _require_non_blank("original_language", req.original_language)
    target_language = _configured_target_language(req.target_language)
    require_translation_ready()
    pids: List[str] = []
    seen_keys = set()
    for raw_key in req.video_keys:
        key = raw_key.strip()
        if key in seen_keys:
            continue
        try:
            url = build_youtube_url(key)
        except ValueError as e:
            log.warning("skipping invalid key %s: %s", key, e)
            continue
        seen_keys.add(key)
        name = f"{base_name}"
        if req.tmdb_type == "tv" and req.season is not None:
            name += f" \u00b7 S{req.season:02d}"
        name += f" \u00b7 {key}"
        project = create_trailer_project(
            tmdb_id=req.tmdb_id,
            tmdb_type=req.tmdb_type,
            season_number=req.season,
            video_key=key,
            youtube_url=url,
            original_language=original_language,
            name=name,
            asr_language=original_language,
            target_language=target_language,
        )
        pids.append(project["id"])
        _spawn_pipeline_thread(project["id"])
    if not pids:
        raise HTTPException(status_code=400, detail="no valid video_keys submitted")
    return {"pids": pids, "status": "submitted"}
