"""Filename → media metadata extraction (used to enrich a project with
TMDB data when the user drops a local video file).

We delegate to `guessit` for tokenization (release-group naming, episode
patterns, year detection — including unicode/CJK titles) and normalize
its output to the small shape we actually consume downstream:

    {
        "title":   str,           # show or movie title
        "year":    int | None,
        "type":    "movie"|"tv",  # normalized from guessit's "movie"/"episode"
        "season":  int | None,    # only when type == "tv"
        "episode": int | None,    # only when type == "tv"
    }

If guessit can't extract a usable title, returns None (so callers can
skip the TMDB step rather than search for garbage).
"""
from __future__ import annotations

import os
from typing import Optional, Dict


def parse_filename(name: str) -> Optional[Dict]:
    """Parse a filename or filepath into a normalized metadata dict.

    Returns None when no usable title was found.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    base = os.path.basename(name)

    try:
        from guessit import guessit
    except ImportError:
        # guessit not bundled (e.g. dev env without the dep) — degrade gracefully
        return None

    try:
        g = dict(guessit(base))
    except Exception:
        return None

    title = g.get("title")
    if not title or not isinstance(title, str):
        return None
    title = title.strip()
    if not title:
        return None

    raw_type = g.get("type")
    if raw_type == "episode":
        norm_type = "tv"
    elif raw_type == "movie":
        norm_type = "movie"
    else:
        # guessit defaults to "movie" when ambiguous; mirror that.
        norm_type = "movie"

    out = {
        "title": title,
        "year": _coerce_int(g.get("year")),
        "type": norm_type,
    }
    if norm_type == "tv":
        out["season"] = _coerce_int(g.get("season"))
        out["episode"] = _coerce_int(g.get("episode"))
    return out


def _coerce_int(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, list) and v:
        v = v[0]
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return None
