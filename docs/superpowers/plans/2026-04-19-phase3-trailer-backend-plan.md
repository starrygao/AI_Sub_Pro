# Phase 3 — Trailer Backend + Bilingual Burn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** End-to-end trailer translation workflow: user inputs TMDB ID or show name → TMDB search → candidate videos → yt-dlp download → reuse existing ASR/translate pipeline (now via Claude CLI if configured) → bilingual (中+英) hard-subtitle mp4 via ffmpeg filter chain. Keeps existing single-language burn path intact.

**Architecture:**
- `app/engines/tmdb.py` — TMDB client (search, videos, details) using `httpx.AsyncClient`
- `app/engines/trailer_downloader.py` — yt-dlp wrapper with URL whitelist + progress hook
- `app/engines/trailer_pipeline.py` — orchestrator: download → ASR → translate → burn per project
- `app/api/trailer.py` — HTTP routes: `/api/trailer/search`, `/videos/{id}`, `/start`
- `app/utils/media.py` — extended `burn_subtitles()` accepts `List[SubtitleTrack]`; new ffmpeg filter chain helper
- `app/utils/srt.py` — new `write_mono_srt()` helper for zh-only / en-only output files

Bilingual burn outputs both `zh.srt` and `en.srt` with matching timestamps; ffmpeg's `subtitles` filter is chained twice with independent `force_style` (PingFang SC big on top, Helvetica small below).

**Tech Stack:** `yt-dlp`, `httpx` (already in requirements for openai SDK), ffmpeg (bundled), pytest. No new runtime deps besides `yt-dlp`.

**Spec reference:** Sections 6 (trailer module), 8 (bilingual burn) of `docs/superpowers/specs/2026-04-19-trailer-translation-and-foundations-design.md`.

**Out of scope (Plan 4):**
- Frontend UI (trailer wizard, claude_cli settings panel, homepage entry)
- UI style redesign
- E2E regression across all 7 scenarios

---

## Prerequisites

Phase 2 complete; tag `phase2-translator-claude-complete` exists. 60 tests passing.

---

## Task 0: Install yt-dlp + verify ffmpeg merge

**Files:** `requirements.txt` (append)

### Steps

- [ ] **Step 1: Install yt-dlp**

```bash
python3 -m pip install yt-dlp 2>&1 | tail -5
python3 -c "import yt_dlp; print(yt_dlp.version.__version__)"
```

Note the installed version.

- [ ] **Step 2: Smoke-check ffmpeg supports libass + subtitles filter**

```bash
ffmpeg -filters 2>&1 | grep -i "subtitles\|libass" | head -3
```

Expect at least `subtitles` filter present. If missing, check bundled ffmpeg at `app/bin/ffmpeg` or document the gap.

- [ ] **Step 3: Append to requirements.txt**

```bash
echo "yt-dlp" >> requirements.txt
```

(Leave unpinned for now; we can tighten to a specific version if stability requires.)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): add yt-dlp for trailer download"
```

Report: yt-dlp version, ffmpeg filter availability, commit SHA.

---

## Task 1: SubtitleTrack dataclass + extend burn_subtitles

**Files:**
- Modify: `app/utils/media.py`
- Test: `tests/test_subtitle_track.py`

### Steps

- [ ] **Step 1: Inspect current burn_subtitles**

```bash
grep -n "def burn_subtitles\|force_style\|ffmpeg" app/utils/media.py
```

Read the existing function signature and body. Note current callers (grep for `burn_subtitles(` in `app/`).

- [ ] **Step 2: Write failing tests `tests/test_subtitle_track.py`**

```python
from pathlib import Path


def test_subtitle_track_defaults():
    from app.utils.media import SubtitleTrack
    t = SubtitleTrack(path="/tmp/foo.srt")
    assert t.path == "/tmp/foo.srt"
    assert t.font_name == "Helvetica"
    assert t.font_size == 20
    assert t.primary_color == "&H00FFFFFF"
    assert t.outline_color == "&H00000000"
    assert t.outline_width == 1.5
    assert t.margin_v == 30
    assert t.alignment == 2


def test_subtitle_track_custom_values():
    from app.utils.media import SubtitleTrack
    t = SubtitleTrack(path="/a/b/zh.srt", font_name="PingFang SC", font_size=28, margin_v=70, outline_width=2.0)
    assert t.font_name == "PingFang SC"
    assert t.font_size == 28
    assert t.margin_v == 70
    assert t.outline_width == 2.0


def test_build_filter_chain_single_track():
    from app.utils.media import SubtitleTrack, build_filter_chain
    track = SubtitleTrack(path="/tmp/zh.srt", font_name="PingFang SC", font_size=28, margin_v=70, outline_width=2.0)
    out = build_filter_chain([track])
    assert "subtitles='/tmp/zh.srt'" in out
    assert "FontName=PingFang SC" in out
    assert "FontSize=28" in out
    assert "MarginV=70" in out
    assert "Outline=2.0" in out


def test_build_filter_chain_two_tracks_are_comma_joined():
    from app.utils.media import SubtitleTrack, build_filter_chain
    tracks = [
        SubtitleTrack(path="/tmp/zh.srt", font_name="PingFang SC", font_size=28, margin_v=70),
        SubtitleTrack(path="/tmp/en.srt", font_name="Helvetica", font_size=20, margin_v=30),
    ]
    out = build_filter_chain(tracks)
    # Two subtitles= filters joined by comma
    assert out.count("subtitles=") == 2
    parts = out.split("subtitles=")
    # first part empty (string starts with subtitles=); second contains zh; third contains en
    assert "zh.srt" in parts[1]
    assert "en.srt" in parts[2]


def test_escape_ffmpeg_filter_path_handles_spaces_and_colons():
    from app.utils.media import _escape_ffmpeg_filter_path
    assert _escape_ffmpeg_filter_path("/tmp/foo bar.srt") == "/tmp/foo bar.srt"
    assert _escape_ffmpeg_filter_path("/tmp/a:b.srt") == "/tmp/a\\:b.srt"
    # Backslashes normalize to forward slashes (Windows → POSIX)
    assert _escape_ffmpeg_filter_path(r"C:\Users\foo\x.srt") == "C\\:/Users/foo/x.srt"
```

- [ ] **Step 3:** Run → expect FAIL (SubtitleTrack not defined).

- [ ] **Step 4: Add to `app/utils/media.py`**

Near the top of `media.py`, after imports:

```python
from dataclasses import dataclass


@dataclass
class SubtitleTrack:
    """One subtitle track to burn. Used by burn_subtitles() for bilingual output."""
    path: str
    font_name: str = "Helvetica"
    font_size: int = 20
    primary_color: str = "&H00FFFFFF"     # white (ASS format: &HAABBGGRR)
    outline_color: str = "&H00000000"     # black
    outline_width: float = 1.5
    margin_v: int = 30                     # distance from bottom (px)
    alignment: int = 2                     # 2 = bottom-center (libass)


def _escape_ffmpeg_filter_path(path: str) -> str:
    """Escape a path for use inside ffmpeg 'subtitles=' filter (single-quoted wrapper)."""
    p = path.replace("\\", "/")
    p = p.replace(":", r"\:")
    p = p.replace("'", r"\'")
    return p


def build_filter_chain(tracks: list) -> str:
    """Build the ffmpeg -vf argument for one or more SubtitleTrack inputs."""
    parts = []
    for t in tracks:
        style = (
            f"FontName={t.font_name},FontSize={t.font_size},"
            f"PrimaryColour={t.primary_color},OutlineColour={t.outline_color},"
            f"Outline={t.outline_width},Shadow=0,"
            f"Alignment={t.alignment},MarginV={t.margin_v}"
        )
        parts.append(f"subtitles='{_escape_ffmpeg_filter_path(t.path)}':force_style='{style}'")
    return ",".join(parts)
```

- [ ] **Step 5: Extend `burn_subtitles()` to accept either a string or a list of SubtitleTrack**

Find the existing `burn_subtitles` function. Update signature:

```python
def burn_subtitles(video_path, tracks, output_path, callback=None, *args, **kwargs):
    """Burn one or more subtitle tracks into a video.

    Backward-compat: if `tracks` is a string (legacy SRT path), treat it as a single track.
    If `tracks` is a list of SubtitleTrack, build a filter chain.
    """
    if isinstance(tracks, str):
        tracks = [SubtitleTrack(path=tracks)]
    elif isinstance(tracks, list) and tracks and isinstance(tracks[0], SubtitleTrack):
        pass
    else:
        raise TypeError("burn_subtitles: 'tracks' must be a SRT path string or List[SubtitleTrack]")

    vf = build_filter_chain(tracks)
    # existing ffmpeg invocation; pass `vf` as -vf value
    # keep existing progress parsing, error handling, and audio-copy logic
    ...
```

Preserve all existing behavior (progress parsing, error handling, audio codec decision). Just swap the filter construction path.

- [ ] **Step 6:** Run tests. Also verify no existing test uses `burn_subtitles` in a way that breaks — grep `grep -rn "burn_subtitles" app/ tests/`.

- [ ] **Step 7:** Run full suite. Expect 65 passed (60 + 5 new).

- [ ] **Step 8: Commit**

```bash
git add app/utils/media.py tests/test_subtitle_track.py
git commit -m "feat(media): SubtitleTrack dataclass + multi-track ffmpeg filter chain"
```

---

## Task 2: Bilingual SRT writer + dynamic font sizing + platform font fallback

**Files:**
- Modify: `app/utils/srt.py` (add `write_mono_srt`)
- Modify: `app/utils/media.py` (add `compute_font_sizes`, `resolve_font`)
- Test: `tests/test_bilingual_srt.py`

### Steps

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path
import tempfile
from datetime import timedelta


def _make_block(idx, text, translation=""):
    from app.utils.srt import SubtitleBlock
    return SubtitleBlock(
        index=idx, start=timedelta(seconds=idx),
        end=timedelta(seconds=idx + 1), text=text, translation=translation,
    )


def test_write_mono_srt_translation_only(tmp_path):
    from app.utils.srt import write_mono_srt
    blocks = [_make_block(1, "Hello", "你好"), _make_block(2, "World", "世界")]
    out = tmp_path / "zh.srt"
    n = write_mono_srt(blocks, str(out), use_translation=True)
    assert n == 2
    text = out.read_text(encoding="utf-8")
    assert "你好" in text
    assert "世界" in text
    assert "Hello" not in text  # translation-only


def test_write_mono_srt_source_only(tmp_path):
    from app.utils.srt import write_mono_srt
    blocks = [_make_block(1, "Hello", "你好"), _make_block(2, "World", "世界")]
    out = tmp_path / "en.srt"
    n = write_mono_srt(blocks, str(out), use_translation=False)
    text = out.read_text(encoding="utf-8")
    assert "Hello" in text
    assert "World" in text
    assert "你好" not in text


def test_write_mono_srt_skips_filtered(tmp_path):
    from app.utils.srt import write_mono_srt
    b1 = _make_block(1, "keep", "保留")
    b2 = _make_block(2, "skip", "跳过")
    b2.filtered = True
    out = tmp_path / "zh.srt"
    n = write_mono_srt([b1, b2], str(out), use_translation=True)
    assert n == 1
    text = out.read_text(encoding="utf-8")
    assert "保留" in text
    assert "跳过" not in text


def test_write_mono_srt_skips_empty_translation(tmp_path):
    """When use_translation=True and a block has empty translation, skip it."""
    from app.utils.srt import write_mono_srt
    b1 = _make_block(1, "keep", "保留")
    b2 = _make_block(2, "no-trans", "")
    out = tmp_path / "zh.srt"
    n = write_mono_srt([b1, b2], str(out), use_translation=True)
    assert n == 1


def test_compute_font_sizes_1080p():
    from app.utils.media import compute_font_sizes
    zh, en = compute_font_sizes(1080)
    assert zh >= 50  # ~5.5% of 1080
    assert en == int(zh * 0.7)


def test_compute_font_sizes_720p():
    from app.utils.media import compute_font_sizes
    zh, en = compute_font_sizes(720)
    assert 30 <= zh <= 50
    assert en == int(zh * 0.7)


def test_compute_font_sizes_min_floor():
    """Very short video → floor to at least 18 for readability."""
    from app.utils.media import compute_font_sizes
    zh, en = compute_font_sizes(200)
    assert zh >= 18
    assert en >= int(18 * 0.7)


def test_resolve_font_macos():
    from app.utils.media import resolve_font
    import platform
    if platform.system() != "Darwin":
        import pytest; pytest.skip("macOS-only")
    assert resolve_font("zh") == "PingFang SC"
    assert resolve_font("en") == "Helvetica"


def test_resolve_font_unknown_lang_defaults_latin():
    from app.utils.media import resolve_font
    # Non-zh language codes route to the Latin path
    assert resolve_font("en") in ("Helvetica", "Arial", "DejaVu Sans")
    assert resolve_font("fr") in ("Helvetica", "Arial", "DejaVu Sans")
```

- [ ] **Step 2:** Run → expect FAIL.

- [ ] **Step 3: Add `write_mono_srt` to `app/utils/srt.py`**

At module level in srt.py (look at existing write functions to match style):

```python
def write_mono_srt(blocks, out_path: str, use_translation: bool = True) -> int:
    """Write a one-language SRT.

    If use_translation=True: output b.translation (skip blocks with empty translation).
    If use_translation=False: output b.text (source language).
    Always skips filtered blocks. Returns number of entries written.
    """
    from pathlib import Path
    written = 0
    out_lines = []
    seq = 1
    for b in blocks:
        if b.filtered:
            continue
        text = (b.translation or "") if use_translation else (b.text or "")
        text = text.strip()
        if not text:
            continue
        out_lines.append(f"{seq}\n{fmt_time(b.start)} --> {fmt_time(b.end)}\n{text}\n")
        seq += 1
        written += 1
    Path(out_path).write_text("\n".join(out_lines), encoding="utf-8")
    return written
```

If `fmt_time` isn't imported at the top of srt.py, reference it from wherever it lives (`from app.utils.srt import fmt_time` or same-module).

- [ ] **Step 4: Add `compute_font_sizes` + `resolve_font` to `app/utils/media.py`**

```python
import platform


def compute_font_sizes(video_height: int) -> tuple:
    """Return (zh_size, en_size) given video pixel height."""
    zh = max(18, int(video_height * 0.055))
    en = max(int(18 * 0.7), int(zh * 0.7))
    return zh, en


def resolve_font(lang: str) -> str:
    """Pick a sane default font per language + platform."""
    sys_ = platform.system()
    if lang == "zh":
        return {"Darwin": "PingFang SC", "Windows": "Microsoft YaHei"}.get(sys_, "DejaVu Sans")
    return {"Darwin": "Helvetica", "Windows": "Arial"}.get(sys_, "DejaVu Sans")
```

- [ ] **Step 5:** Run tests + full suite → expect 74 passed (65 + 9).

- [ ] **Step 6: Commit**

```bash
git add app/utils/srt.py app/utils/media.py tests/test_bilingual_srt.py
git commit -m "feat(media): bilingual SRT writer + dynamic font sizing + platform fallback"
```

---

## Task 3: TMDB client

**Files:**
- Create: `app/engines/tmdb.py`
- Test: `tests/test_tmdb_client.py`

### Steps

- [ ] **Step 1: Write failing tests `tests/test_tmdb_client.py`**

```python
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio


def _run(coro):
    """Helper to run async coroutines in sync tests (Py3.9 compat)."""
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutine(coro) is False else asyncio.run(coro)


def test_tmdb_client_requires_api_key(monkeypatch):
    from app.engines import tmdb
    monkeypatch.setattr(tmdb, "_get_api_key", lambda: "")
    with pytest.raises(tmdb.TmdbAuthError):
        asyncio.run(tmdb.search_multi("test"))


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
    # Official trailers come first, then unofficial trailers, then teasers, then others
    assert videos[0]["key"] == "b"  # official trailer
    assert videos[1]["key"] == "c"  # unofficial trailer
    assert videos[2]["key"] == "a"  # teaser (official)
    # Behind the scenes last (non-trailer, non-teaser)
    assert videos[-1]["key"] == "d"


def test_tmdb_rate_limit_retry_once(monkeypatch):
    from app.engines import tmdb
    monkeypatch.setattr(tmdb, "_get_api_key", lambda: "test-key")

    call_count = [0]

    class FakeResponse429:
        status_code = 429
        def raise_for_status(self):
            import httpx
            raise httpx.HTTPStatusError("rate limited", request=MagicMock(), response=MagicMock(status_code=429))
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
    monkeypatch.setattr(tmdb.asyncio, "sleep", AsyncMock())  # don't actually sleep in tests
    results = asyncio.run(tmdb.search_multi("x"))
    assert call_count[0] == 2
    assert len(results) == 1
```

- [ ] **Step 2:** Run → FAIL (module missing).

- [ ] **Step 3: Write `app/engines/tmdb.py`**

```python
"""TMDB client: search + videos + details. Uses httpx.AsyncClient."""
import asyncio
import logging
from typing import List, Optional

import httpx

from app.config import Config

log = logging.getLogger(__name__)

_BASE_URL = "https://api.themoviedb.org/3"


class TmdbAuthError(RuntimeError):
    pass


class TmdbNotFoundError(RuntimeError):
    pass


def _get_api_key() -> str:
    return Config.get("tmdb", "api_key") or ""


def _get_language() -> str:
    return Config.get("tmdb", "language") or "zh-CN"


async def _get_json(path: str, params: dict, retries: int = 2) -> dict:
    """Low-level GET with one 429 retry."""
    api_key = _get_api_key()
    if not api_key:
        raise TmdbAuthError("TMDB API key not configured (set in Settings → TMDB)")
    params = dict(params, api_key=api_key)
    url = _BASE_URL + path

    last_exc = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, params=params, timeout=10.0)
                if r.status_code == 429:
                    log.warning("TMDB 429 rate-limited; retrying in 2s")
                    await asyncio.sleep(2)
                    continue
                if r.status_code == 404:
                    raise TmdbNotFoundError(f"TMDB 404 for {path}")
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as e:
            last_exc = e
            if attempt < retries - 1:
                await asyncio.sleep(1)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("TMDB unreachable after retries")


def _sort_videos(videos: List[dict]) -> List[dict]:
    """Sort: official trailers first, then unofficial trailers, teasers, then others. Within group: by published_at desc."""
    def bucket(v):
        t = v.get("type", "")
        off = v.get("official", False)
        if t == "Trailer" and off: return 0
        if t == "Trailer": return 1
        if t == "Teaser": return 2
        return 3
    return sorted(videos, key=lambda v: (bucket(v), -_parse_date(v.get("published_at", ""))))


def _parse_date(s: str) -> int:
    """Return a sortable int from an ISO date (or 0 if unparseable)."""
    try:
        return int(s.replace("-", "").replace(":", "").replace("T", "")[:14] or "0")
    except Exception:
        return 0


async def search_multi(query: str) -> List[dict]:
    """Search TV + movies together."""
    data = await _get_json("/search/multi", {"query": query, "language": _get_language()})
    return data.get("results", [])


async def search_tv(query: str, year: Optional[int] = None) -> List[dict]:
    params = {"query": query, "language": _get_language()}
    if year is not None:
        params["first_air_date_year"] = year
    data = await _get_json("/search/tv", params)
    return data.get("results", [])


async def search_movie(query: str, year: Optional[int] = None) -> List[dict]:
    params = {"query": query, "language": _get_language()}
    if year is not None:
        params["year"] = year
    data = await _get_json("/search/movie", params)
    return data.get("results", [])


async def get_tv_videos(tmdb_id: int, season: Optional[int] = None) -> List[dict]:
    path = f"/tv/{tmdb_id}/season/{season}/videos" if season is not None else f"/tv/{tmdb_id}/videos"
    data = await _get_json(path, {"language": _get_language()})
    return _sort_videos(data.get("results", []))


async def get_movie_videos(tmdb_id: int) -> List[dict]:
    data = await _get_json(f"/movie/{tmdb_id}/videos", {"language": _get_language()})
    return _sort_videos(data.get("results", []))


async def get_show_details(tmdb_id: int, media_type: str) -> dict:
    path = f"/{media_type}/{tmdb_id}"
    return await _get_json(path, {"language": _get_language()})
```

- [ ] **Step 4:** Run tests → expect 4 PASS. Full suite → 78 (74 + 4).

- [ ] **Step 5: Commit**

```bash
git add app/engines/tmdb.py tests/test_tmdb_client.py
git commit -m "feat(trailer): TMDB async client with search + videos + sort"
```

---

## Task 4: yt-dlp wrapper

**Files:**
- Create: `app/engines/trailer_downloader.py`
- Test: `tests/test_trailer_downloader.py`

### Steps

- [ ] **Step 1: Write failing tests**

```python
import pytest


def test_validate_youtube_url_accepts_youtube_com():
    from app.engines.trailer_downloader import _validate_youtube_url
    _validate_youtube_url("https://www.youtube.com/watch?v=abc")  # no raise


def test_validate_youtube_url_accepts_youtu_be():
    from app.engines.trailer_downloader import _validate_youtube_url
    _validate_youtube_url("https://youtu.be/abc")


def test_validate_youtube_url_rejects_other_domain():
    from app.engines.trailer_downloader import _validate_youtube_url
    with pytest.raises(ValueError, match="not a YouTube"):
        _validate_youtube_url("https://evil.example.com/abc")


def test_download_trailer_calls_ytdlp_with_expected_options(monkeypatch, tmp_path):
    from app.engines import trailer_downloader as td

    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def download(self, urls):
            captured["urls"] = urls
            # Simulate downloaded file
            out = tmp_path / "trailer.mp4"
            out.write_bytes(b"fake mp4")
            return 0

    monkeypatch.setattr(td.yt_dlp, "YoutubeDL", FakeYDL)

    out = td.download_trailer("https://www.youtube.com/watch?v=abc", str(tmp_path / "trailer.mp4"))
    assert out.endswith("trailer.mp4")
    assert captured["urls"] == ["https://www.youtube.com/watch?v=abc"]
    assert "format" in captured["opts"]
    assert captured["opts"]["outtmpl"] == str(tmp_path / "trailer.mp4")
    # Format should prefer 1080p mp4
    assert "1080" in captured["opts"]["format"] or "mp4" in captured["opts"]["format"]
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `app/engines/trailer_downloader.py`**

```python
"""yt-dlp wrapper for downloading trailers from YouTube (whitelisted)."""
import logging
import re
from typing import Callable, Optional
from urllib.parse import urlparse

import yt_dlp

log = logging.getLogger(__name__)

_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def _validate_youtube_url(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise ValueError(f"URL {url!r} is not a YouTube domain (host={host!r})")


def download_trailer(
    url: str,
    output_path: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    timeout_sec: int = 120,
) -> str:
    """Download a YouTube trailer to output_path (.mp4). Returns the final path.

    progress_callback receives (local_pct 0..100, status_msg). Called during download.
    """
    _validate_youtube_url(url)

    def hook(d):
        if not progress_callback:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = (done / total * 100) if total else 0
            try:
                progress_callback(pct, "downloading")
            except Exception:
                pass
        elif d.get("status") == "finished":
            try:
                progress_callback(100, "download finished")
            except Exception:
                pass

    opts = {
        "format": "bestvideo[ext=mp4][height<=?1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=?1080]/best[ext=mp4]/best",
        "outtmpl": output_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "socket_timeout": timeout_sec,
        "retries": 1,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    return output_path


def build_youtube_url(video_key: str) -> str:
    """Build a YouTube watch URL from a TMDB video key."""
    # TMDB stores just the YouTube video ID as `key`
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_key):
        raise ValueError(f"invalid YouTube video key: {video_key!r}")
    return f"https://www.youtube.com/watch?v={video_key}"
```

- [ ] **Step 4:** Run tests → 4 pass. Full suite → 82.

- [ ] **Step 5: Commit**

```bash
git add app/engines/trailer_downloader.py tests/test_trailer_downloader.py
git commit -m "feat(trailer): yt-dlp wrapper with YouTube-domain whitelist + progress hook"
```

---

## Task 5: create_trailer_project in projects.py

**Files:**
- Modify: `app/api/projects.py` (add `create_trailer_project` function — not an HTTP route yet; will be exposed via trailer API)
- Test: `tests/test_create_trailer_project.py`

### Steps

- [ ] **Step 1: Write failing test**

```python
import json


def test_create_trailer_project_writes_project_json(tmp_project_dir):
    from app.api.projects import create_trailer_project

    meta = create_trailer_project(
        tmdb_id=1399,
        tmdb_type="tv",
        season_number=1,
        video_key="abc123",
        youtube_url="https://www.youtube.com/watch?v=abc123",
        original_language="en",
        name="Game of Thrones · Season 1 · Trailer",
    )
    pid = meta["id"]
    pfile = tmp_project_dir / pid / "project.json"
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


def test_create_trailer_project_movie_no_season(tmp_project_dir):
    from app.api.projects import create_trailer_project

    meta = create_trailer_project(
        tmdb_id=550, tmdb_type="movie",
        season_number=None, video_key="xyz789",
        youtube_url="https://youtu.be/xyz789",
        original_language="en", name="Fight Club",
    )
    assert meta["season_number"] is None
    assert meta["tmdb_type"] == "movie"
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Add `create_trailer_project` to `app/api/projects.py`**

```python
def create_trailer_project(
    tmdb_id: int,
    tmdb_type: str,
    video_key: str,
    youtube_url: str,
    original_language: str,
    name: str,
    season_number: int = None,
    parent_project_id: str = None,
) -> dict:
    """Create a new trailer-source project directory + project.json. Returns the project dict."""
    import uuid
    from datetime import datetime

    pid = uuid.uuid4().hex[:8]
    pdir = PROJECTS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)

    project = {
        "id": pid,
        "name": name,
        "video_path": None,
        "created_at": datetime.utcnow().isoformat(),
        "status": "created",
        "progress": 0,
        "progress_msg": "",
        "duration": 0,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "selected_audio_track": 0,
        "selected_subtitle_track": None,
        "asr_language": "auto",
        "target_language": "简体中文",
        "error": None,
        "output_video": None,
        # Trailer-specific
        "source_type": "trailer",
        "tmdb_id": tmdb_id,
        "tmdb_type": tmdb_type,
        "season_number": season_number,
        "tmdb_video_key": video_key,
        "youtube_url": youtube_url,
        "original_language": original_language,
        "auto_run": True,
        "parent_project_id": parent_project_id,
        "pipeline_stage": "download",
        "archived": False,
    }

    with open(pdir / "project.json", "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)

    return project
```

- [ ] **Step 4:** Run tests + full suite → 84 passed.

- [ ] **Step 5: Commit**

```bash
git add app/api/projects.py tests/test_create_trailer_project.py
git commit -m "feat(projects): create_trailer_project helper for trailer pipeline"
```

---

## Task 6: Trailer pipeline orchestrator

**Files:**
- Create: `app/engines/trailer_pipeline.py`
- Test: `tests/test_trailer_pipeline.py`

### Steps

- [ ] **Step 1: Write failing tests**

```python
from unittest.mock import patch, MagicMock


def test_run_trailer_pipeline_happy_path(tmp_project_dir, monkeypatch):
    """Download succeeds → project video_path set, status progresses."""
    from app.engines import trailer_pipeline as tp
    from app.api.projects import create_trailer_project, _load_project

    project = create_trailer_project(
        tmdb_id=1, tmdb_type="movie", video_key="k", youtube_url="https://youtu.be/k",
        original_language="en", name="Test",
    )
    pid = project["id"]

    download_called = []
    asr_called = []
    translate_called = []
    burn_called = []

    def fake_download(url, out, progress_callback=None, **kw):
        download_called.append((url, out))
        import pathlib; pathlib.Path(out).write_bytes(b"x")
        return out

    monkeypatch.setattr(tp, "download_trailer", fake_download)
    monkeypatch.setattr(tp, "_run_asr_for_project", lambda pid_: asr_called.append(pid_))
    monkeypatch.setattr(tp, "_run_translate_for_project", lambda pid_: translate_called.append(pid_))
    monkeypatch.setattr(tp, "_run_burn_for_project", lambda pid_: burn_called.append(pid_))

    tp.run_trailer_pipeline(pid)

    assert len(download_called) == 1
    assert asr_called == [pid]
    assert translate_called == [pid]
    assert burn_called == [pid]

    p = _load_project(pid)
    assert p["video_path"] is not None
    assert p["status"] == "completed"


def test_run_trailer_pipeline_download_failure_sets_error(tmp_project_dir, monkeypatch):
    from app.engines import trailer_pipeline as tp
    from app.api.projects import create_trailer_project, _load_project

    project = create_trailer_project(
        tmdb_id=1, tmdb_type="movie", video_key="k", youtube_url="https://youtu.be/k",
        original_language="en", name="Test",
    )
    pid = project["id"]

    def fake_fail(*a, **kw):
        raise RuntimeError("network")

    monkeypatch.setattr(tp, "download_trailer", fake_fail)

    tp.run_trailer_pipeline(pid)  # should NOT raise

    p = _load_project(pid)
    assert p["status"] == "error"
    assert "network" in (p.get("error") or "").lower() or "download" in (p.get("error") or "").lower()
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `app/engines/trailer_pipeline.py`**

```python
"""Trailer-project orchestrator: download → ASR → translate → burn."""
import logging
from pathlib import Path

from app.api.projects import _load_project, _save_project, PROJECTS_DIR
from app.engines.scheduler import slot, update_progress, reset_cancel
from app.engines.trailer_downloader import download_trailer

log = logging.getLogger(__name__)


def _save_partial(pid: str, **fields) -> None:
    """Load, merge, save."""
    proj = _load_project(pid)
    proj.update(fields)
    _save_project(pid, proj)


def _run_asr_for_project(pid: str) -> None:
    """Invoke existing ASR pipeline on a project. Deferred import to avoid circular."""
    from app.api.translate import _run_asr_pipeline
    _run_asr_pipeline(pid)


def _run_translate_for_project(pid: str) -> None:
    from app.api.translate import _run_translate_pipeline
    _run_translate_pipeline(pid)


def _run_burn_for_project(pid: str) -> None:
    from app.api.translate import _run_burn_pipeline
    _run_burn_pipeline(pid)


def run_trailer_pipeline(pid: str) -> None:
    """Run the full 4-stage pipeline for a trailer project. Exceptions caught and recorded."""
    reset_cancel(pid)
    try:
        # Stage 1: download
        _download_stage(pid)
        # Stage 2-4: reuse existing ASR/translate/burn
        _run_asr_for_project(pid)
        _run_translate_for_project(pid)
        _run_burn_for_project(pid)

        _save_partial(pid, status="completed", pipeline_stage=None)
        update_progress(pid, "burn", 100, "trailer pipeline complete")
    except Exception as e:
        log.exception("trailer pipeline failed pid=%s", pid)
        _save_partial(pid, status="error", error=f"{type(e).__name__}: {str(e)[:200]}")


def _download_stage(pid: str) -> None:
    proj = _load_project(pid)
    url = proj.get("youtube_url") or ""
    out_path = str(PROJECTS_DIR / pid / "original.mp4")

    def on_progress(pct, msg):
        update_progress(pid, "download", int(pct), msg)

    _save_partial(pid, pipeline_stage="download", status="processing")
    update_progress(pid, "download", 0, "starting download")

    with slot("download", pid):
        try:
            download_trailer(url, out_path, progress_callback=on_progress)
        except Exception as e:
            raise RuntimeError(f"download failed: {str(e)[:120]}")

    # Record video_path + transition to asr stage
    _save_partial(pid, video_path=out_path, pipeline_stage="asr")
    update_progress(pid, "download", 100, "download complete")
```

NOTE: the test expects `_run_burn_for_project` to exist. Check `app/api/translate.py` — it has `_run_full_pipeline` and `_burn_task`. You may need to extract a `_run_burn_pipeline(pid)` function there that does just the burn step (split from `_run_full_pipeline`). If that extraction is too invasive right now, provide a wrapper here:

```python
def _run_burn_for_project(pid: str) -> None:
    """Burn stage — for now, reuse _run_full_pipeline starting from burn stage."""
    # Simplest: call the existing _burn_task directly, which handles slot("burn", ...).
    from app.api.translate import _burn_task
    proj = _load_project(pid)
    # _burn_task expects a project dict argument — adapt as needed based on its signature
    _burn_task(pid)
```

Adjust based on the actual signature of `_burn_task` in translate.py (grep it). The wrapper must NOT double-wrap semaphore slots.

- [ ] **Step 4:** Run tests + full suite.

- [ ] **Step 5: Commit**

```bash
git add app/engines/trailer_pipeline.py tests/test_trailer_pipeline.py
git commit -m "feat(trailer): pipeline orchestrator — download + ASR + translate + burn per project"
```

---

## Task 7: Trailer API routes

**Files:**
- Create: `app/api/trailer.py`
- Modify: `app/main.py` (register router)
- Test: `tests/test_trailer_api.py`

### Steps

- [ ] **Step 1: Write failing tests**

```python
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


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


def test_start_endpoint_creates_projects_and_schedules(tmp_project_dir, monkeypatch):
    """POST /api/trailer/start spawns background thread per video_key."""
    from app.main import app
    client = TestClient(app)

    threaded = []
    def fake_start_pipeline(pid):
        threaded.append(pid)

    monkeypatch.setattr("app.api.trailer._spawn_pipeline_thread", fake_start_pipeline)

    r = client.post("/api/trailer/start", json={
        "tmdb_id": 1,
        "tmdb_type": "movie",
        "season": None,
        "video_keys": ["k1", "k2"],
        "original_language": "en",
        "name": "Foo",
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["pids"]) == 2
    assert threaded == data["pids"]


def test_search_endpoint_surfaces_auth_error():
    from app.main import app
    client = TestClient(app)
    with patch("app.api.trailer.tmdb_search_multi", new_callable=AsyncMock) as mock:
        from app.engines.tmdb import TmdbAuthError
        mock.side_effect = TmdbAuthError("no key")
        r = client.post("/api/trailer/search", json={"query": "foo"})
    assert r.status_code in (400, 401)
    assert "TMDB" in r.json().get("detail", "") or "key" in r.json().get("detail", "").lower()
```

- [ ] **Step 2:** Run → FAIL.

- [ ] **Step 3: Write `app/api/trailer.py`**

```python
"""Trailer API routes: search, videos, start."""
import logging
import threading
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.engines.tmdb import (
    search_multi as tmdb_search_multi,
    search_tv as tmdb_search_tv,
    search_movie as tmdb_search_movie,
    get_tv_videos as tmdb_get_tv_videos,
    get_movie_videos as tmdb_get_movie_videos,
    get_show_details as tmdb_get_show_details,
    TmdbAuthError, TmdbNotFoundError,
)
from app.engines.trailer_downloader import build_youtube_url
from app.engines.trailer_pipeline import run_trailer_pipeline
from app.api.projects import create_trailer_project

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trailer", tags=["trailer"])


class SearchReq(BaseModel):
    query: str
    media_type: Optional[str] = None  # "tv" | "movie" | None (multi)


class StartReq(BaseModel):
    tmdb_id: int
    tmdb_type: str  # "tv" | "movie"
    season: Optional[int] = None
    video_keys: List[str]
    original_language: str
    name: str


@router.post("/search")
async def search(req: SearchReq):
    try:
        if req.media_type == "tv":
            results = await tmdb_search_tv(req.query)
        elif req.media_type == "movie":
            results = await tmdb_search_movie(req.query)
        else:
            results = await tmdb_search_multi(req.query)
    except TmdbAuthError as e:
        raise HTTPException(status_code=400, detail=f"TMDB API key missing or invalid: {e}")
    return {"results": results}


@router.get("/videos/{tmdb_id}")
async def videos(tmdb_id: int, type: str = "tv", season: Optional[int] = None):
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
    return {"videos": results}


def _spawn_pipeline_thread(pid: str) -> None:
    """Start the trailer pipeline in a background daemon thread."""
    t = threading.Thread(target=run_trailer_pipeline, args=(pid,), daemon=True)
    t.start()


@router.post("/start")
def start(req: StartReq):
    pids = []
    for key in req.video_keys:
        try:
            url = build_youtube_url(key)
        except ValueError as e:
            log.warning("skipping invalid key %s: %s", key, e)
            continue
        name = f"{req.name}"
        if req.tmdb_type == "tv" and req.season is not None:
            name += f" · S{req.season:02d}"
        name += f" · {key}"
        project = create_trailer_project(
            tmdb_id=req.tmdb_id,
            tmdb_type=req.tmdb_type,
            season_number=req.season,
            video_key=key,
            youtube_url=url,
            original_language=req.original_language,
            name=name,
        )
        pids.append(project["id"])
        _spawn_pipeline_thread(project["id"])

    return {"pids": pids, "status": "submitted"}
```

- [ ] **Step 4: Register router in `app/main.py`**

Near other `include_router` calls:
```python
from app.api.trailer import router as trailer_router
app.include_router(trailer_router)
```

- [ ] **Step 5:** Run tests + full suite.

- [ ] **Step 6: Commit**

```bash
git add app/api/trailer.py app/main.py tests/test_trailer_api.py
git commit -m "feat(trailer): API routes — search/videos/start + main.py registration"
```

---

## Task 8: Wire bilingual burn into translate pipeline (trailer projects only)

**Files:**
- Modify: `app/api/translate.py` (`_run_burn_pipeline` or equivalent)
- Test: `tests/test_bilingual_burn_integration.py`

### Steps

- [ ] **Step 1: Inspect burn code**

```bash
grep -n "_run_full_pipeline\|_burn_task\|burn_subtitles\|bilingual" app/api/translate.py
```

Find where the burn call is made. Likely inside `_run_full_pipeline` or `_burn_task`.

- [ ] **Step 2: Write failing test**

```python
from unittest.mock import patch, MagicMock
from pathlib import Path


def test_trailer_project_burn_uses_two_tracks(tmp_project_dir, monkeypatch):
    """When a trailer project reaches the burn stage, burn_subtitles must be called with 2 tracks."""
    from app.api.projects import create_trailer_project, _save_project, _load_project
    from app.utils.media import SubtitleTrack

    project = create_trailer_project(
        tmdb_id=1, tmdb_type="movie", video_key="k",
        youtube_url="https://youtu.be/k", original_language="en", name="Foo",
    )
    pid = project["id"]
    pdir = tmp_project_dir / pid
    # Seed required fixture files so the burn path has inputs
    (pdir / "original.mp4").write_bytes(b"fake")
    (pdir / "translated.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
    (pdir / "filtered.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    project["video_path"] = str(pdir / "original.mp4")
    project["status"] = "translated"
    _save_project(pid, project)

    captured = {}

    def fake_burn(video_path, tracks, output_path, **kw):
        captured["tracks"] = tracks
        captured["video_path"] = video_path
        captured["output_path"] = output_path
        Path(output_path).write_bytes(b"fake output")
        return True

    monkeypatch.setattr("app.utils.media.burn_subtitles", fake_burn)
    # Any other monkeypatches needed for the burn stage (ffprobe for height, etc.) — patch as needed

    # Invoke the burn pipeline directly
    from app.api.translate import _run_burn_pipeline  # if exists; else use _burn_task
    try:
        _run_burn_pipeline(pid)
    except Exception:
        pass  # might fail on ffmpeg call; we only care about tracks argument

    assert "tracks" in captured, "burn_subtitles was not called"
    tracks = captured["tracks"]
    assert isinstance(tracks, list), f"expected list of tracks, got {type(tracks)}"
    assert len(tracks) == 2, f"expected 2 tracks for bilingual burn, got {len(tracks)}"
    # Track 0: zh (larger font, higher margin)
    # Track 1: en (smaller font, lower margin)
    assert tracks[0].font_size > tracks[1].font_size
    assert tracks[0].margin_v > tracks[1].margin_v
```

This test is ambitious — it tests a lot of moving parts. If it's too fragile, simplify to a unit test of a new helper `build_bilingual_tracks(pid)` that's exercised in isolation.

- [ ] **Step 3:** Run → FAIL.

- [ ] **Step 4: Extract a `build_bilingual_tracks(pid)` helper + wire into burn path**

In `app/api/translate.py`:

```python
def _build_bilingual_tracks(pid: str):
    """For trailer projects: generate zh.srt + en.srt (if not already) and return SubtitleTrack list."""
    from app.utils.srt import parse_srt_file, write_mono_srt
    from app.utils.media import SubtitleTrack, compute_font_sizes, resolve_font, get_video_height

    pdir = PROJECTS_DIR / pid
    translated_srt = pdir / "translated.srt"
    filtered_srt = pdir / "filtered.srt"
    # Parse both → blocks with translation merged in for zh, original for en
    # Simplest: rewrite via write_mono_srt using the SubtitleBlock list produced by translate stage

    # Assumption: the translate stage leaves blocks in memory or re-parseable from these two files
    # If blocks aren't available, parse translated_srt for zh and filtered_srt for en directly

    zh_path = pdir / "zh.srt"
    en_path = pdir / "en.srt"

    # If the pipeline didn't pre-write zh/en, generate them now from existing SRT files
    if not zh_path.exists() and translated_srt.exists():
        zh_path.write_bytes(translated_srt.read_bytes())
    if not en_path.exists() and filtered_srt.exists():
        en_path.write_bytes(filtered_srt.read_bytes())

    # Get video height for dynamic sizing
    project = _load_project(pid)
    video_path = project.get("video_path")
    height = get_video_height(video_path) if video_path else 1080
    zh_size, en_size = compute_font_sizes(height)

    return [
        SubtitleTrack(
            path=str(zh_path), font_name=resolve_font("zh"),
            font_size=zh_size, outline_width=2.0, margin_v=70,
        ),
        SubtitleTrack(
            path=str(en_path), font_name=resolve_font("en"),
            font_size=en_size, outline_width=1.5, margin_v=30,
        ),
    ]
```

Then in the burn stage, check if project is trailer source:

```python
def _run_burn_pipeline(pid: str) -> None:
    """Burn stage: single-lang for uploads, bilingual for trailers."""
    project = _load_project(pid)
    out_path = str(PROJECTS_DIR / pid / f"{project.get('name', pid)}_subtitled.mp4")

    if project.get("source_type") == "trailer":
        tracks = _build_bilingual_tracks(pid)
    else:
        # existing single-lang path: pass bilingual.srt or translated.srt as string
        srt = PROJECTS_DIR / pid / "bilingual.srt"
        if not srt.exists():
            srt = PROJECTS_DIR / pid / "translated.srt"
        tracks = [SubtitleTrack(path=str(srt))]

    with slot("burn", pid):
        burn_subtitles(project["video_path"], tracks, out_path)

    _save_partial(pid, output_video=out_path, status="completed", pipeline_stage=None)
```

If a function named `_run_burn_pipeline` doesn't already exist in `translate.py`, extract it from `_run_full_pipeline` or `_burn_task`. Keep existing callers working — `_run_full_pipeline` should delegate to `_run_burn_pipeline` for the burn portion.

⚠️ `get_video_height(path)` may not exist in media.py. If not, use `ffprobe` to probe dimensions. If ffprobe call is complex, hardcode 1080 initially and refine later (noted in a comment).

- [ ] **Step 5:** Run tests + full suite.

- [ ] **Step 6: Commit**

```bash
git add app/api/translate.py app/utils/media.py tests/test_bilingual_burn_integration.py
git commit -m "feat(burn): bilingual track generation for trailer projects"
```

---

## Task 9: Phase 3 smoke + tag + audit gate

**Files:** none

### Steps

- [ ] **Step 1: Full suite**
`python3 -m pytest -v` → expect ~90+ passed.

- [ ] **Step 2: Import smoke**
`python3 -c "from app.main import app; print('ok')"`

- [ ] **Step 3: Tag**
`git tag phase3-trailer-backend-complete`

- [ ] **Step 4: Audit gate** — 3 parallel agents:
  - **Agent A** — TMDB + yt-dlp correctness: URL whitelist actually prevents non-YouTube hosts; TMDB search/sort logic sound; rate-limit retry works
  - **Agent B** — Bilingual burn: SubtitleTrack defaults sane; ffmpeg filter chain string correct for libass; backward-compat string path still works; font fallback reasonable
  - **Agent C** — Pipeline orchestration: trailer_pipeline.run_trailer_pipeline properly updates status on each stage; errors are captured and surfaced; backward-compat with upload projects preserved

If any audit fails, fix before Plan 4.

---

## Out of this plan (Plan 4)

- Frontend: trailer wizard, homepage entry card, settings claude_cli panel, stage badges in project cards
- UI style redesign (Linear/Raycast/Notion-inspired mockup selection, CSS extraction to app.css)
- End-to-end regression scenarios 1–7 from spec §13.2
