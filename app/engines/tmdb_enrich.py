"""TMDB enrichment from a parsed filename.

Bridges `app.engines.file_metadata.parse_filename` → `app.engines.tmdb`
search, picks a high-confidence match when one exists, and otherwise
returns a small list of candidates for the UI to disambiguate.

Returned shape (always a dict, never raises on network errors — silent
degradation is preferable to blocking project creation on TMDB outage):

    {
        "auto_attached": bool,          # True iff the caller should
                                        # immediately set tmdb_id on
                                        # the project.
        "tmdb_id":          int | None,
        "tmdb_type":        "movie"|"tv"|None,
        "season_number":    int | None,
        "show_title":       str | None,  # display title (TMDB localized)
        "original_language": str | None,
        "year":             int | None,
        "poster_path":      str | None,
        "candidates":       list[dict], # full candidate list (may be
                                        # empty); UI shows when not auto.
    }
"""
from __future__ import annotations

import logging
from typing import Optional

from app.engines.file_metadata import parse_filename

log = logging.getLogger(__name__)


_EMPTY = {
    "auto_attached": False,
    "tmdb_id": None,
    "tmdb_type": None,
    "season_number": None,
    "show_title": None,
    "original_language": None,
    "year": None,
    "poster_path": None,
    "candidates": [],
}


def _string_field(c: dict, field: str) -> str:
    value = c.get(field)
    return value if isinstance(value, str) else ""


def _candidate_year(c: dict, kind: str) -> Optional[int]:
    date_field = "first_air_date" if kind == "tv" else "release_date"
    raw = _string_field(c, date_field)
    if len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return None


def _candidate_title(c: dict, kind: str) -> str:
    if kind == "tv":
        return _string_field(c, "name") or _string_field(c, "original_name")
    return _string_field(c, "title") or _string_field(c, "original_title")


def _positive_int(value) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _normalize_candidate(c: dict, kind: str) -> dict:
    return {
        "tmdb_id": _positive_int(c.get("id")),
        "tmdb_type": kind,
        "title": _candidate_title(c, kind),
        "original_title": c.get("original_name") if kind == "tv" else c.get("original_title"),
        "year": _candidate_year(c, kind),
        "original_language": _string_field(c, "original_language") or None,
        "poster_path": _string_field(c, "poster_path") or None,
        "overview": _string_field(c, "overview")[:200],
        "vote_average": c.get("vote_average", 0),
    }


async def enrich_from_filename(name: str) -> dict:
    """Parse `name` (filename or path), search TMDB, and pick a match.

    Network or parse failures are swallowed and return the empty result.
    """
    parsed = parse_filename(name)
    if not isinstance(parsed, dict) or not parsed:
        return dict(_EMPTY)

    title = parsed.get("title")
    if not isinstance(title, str) or not title.strip():
        return dict(_EMPTY)
    title = title.strip()
    year = parsed.get("year")
    kind = parsed.get("type")  # "movie" or "tv"
    if kind not in {"movie", "tv"}:
        return dict(_EMPTY)

    try:
        from app.engines import tmdb
        if kind == "tv":
            results = await tmdb.search_tv(title, year=year)
        else:
            results = await tmdb.search_movie(title, year=year)
    except Exception as e:
        try:
            safe_error = tmdb.public_error_message(e)
        except Exception:
            safe_error = str(e)[:200]
        log.info("TMDB search failed for %r: %s", name, safe_error)
        return dict(_EMPTY)

    if not results:
        return dict(_EMPTY)

    candidates = [
        c for c in (_normalize_candidate(r, kind) for r in results[:5])
        if c.get("tmdb_id") is not None and c.get("title")
    ]
    if not candidates:
        return dict(_EMPTY)
    top = candidates[0]

    # Confidence rules:
    #   1. If we have a year and the top result's year is within ±1, auto-attach.
    #   2. If we have no year but only one result, auto-attach.
    #   3. If we have no year and multiple results, return candidates for UI.
    #   4. If year mismatch, still return candidates (don't guess wrong).
    auto = False
    if year is not None and top["year"] is not None and abs(top["year"] - year) <= 1:
        auto = True
    elif year is None and len(candidates) == 1:
        auto = True

    out = dict(_EMPTY)
    out["candidates"] = candidates
    if auto:
        out.update({
            "auto_attached": True,
            "tmdb_id": top["tmdb_id"],
            "tmdb_type": kind,
            "season_number": parsed.get("season"),
            "show_title": top["title"],
            "original_language": top["original_language"],
            "year": top["year"],
            "poster_path": top["poster_path"],
        })
    return out
