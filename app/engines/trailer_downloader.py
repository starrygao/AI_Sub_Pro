"""yt-dlp wrapper for downloading trailers from YouTube (whitelisted)."""
import logging
import math
import os
import re
from typing import Callable, Optional, Tuple
from urllib.parse import urlparse

import yt_dlp

from app.utils.errors import redact_error_message

log = logging.getLogger(__name__)

_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def _detect_browser_for_cookies() -> Optional[Tuple[str]]:
    """Detect an installed browser to pull YouTube cookies from (bypasses HTTP 403).
    Returns ('chrome',) / ('safari',) / etc., or None if no supported browser found."""
    home = os.path.expanduser("~")
    candidates = [
        ("chrome", f"{home}/Library/Application Support/Google/Chrome/Default/Cookies"),
        ("edge", f"{home}/Library/Application Support/Microsoft Edge/Default/Cookies"),
        ("brave", f"{home}/Library/Application Support/BraveSoftware/Brave-Browser/Default/Cookies"),
        ("firefox", f"{home}/Library/Application Support/Firefox"),
        ("safari", f"{home}/Library/Cookies/Cookies.binarycookies"),
    ]
    for name, path in candidates:
        if os.path.exists(path):
            return (name,)
    return None


def _validate_youtube_url(url: str) -> None:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a non-empty string")
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"URL {url!r} must use http or https")
    if host not in _ALLOWED_HOSTS:
        raise ValueError(f"URL {url!r} is not a YouTube domain (host={host!r})")


def _download_progress_percent(done, total) -> float:
    try:
        done_value = float(done)
        total_value = float(total)
    except (OverflowError, TypeError, ValueError):
        return 0
    if not math.isfinite(done_value) or not math.isfinite(total_value) or total_value <= 0:
        return 0
    return max(0, min(100, done_value / total_value * 100))


def build_youtube_url(video_key: str) -> str:
    """Build a YouTube watch URL from a TMDB video `key`."""
    if not isinstance(video_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_key):
        raise ValueError(f"invalid YouTube video key: {video_key!r}")
    return f"https://www.youtube.com/watch?v={video_key}"


def download_trailer(
    url: str,
    output_path: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    timeout_sec: int = 120,
    max_height: int = 1080,
) -> str:
    """Download a YouTube trailer to output_path (.mp4). Returns the final path.

    max_height: 0 = best available, otherwise cap at the given pixel height (e.g. 720, 1080).
    """
    _validate_youtube_url(url)

    def hook(d):
        if not progress_callback:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = _download_progress_percent(done, total)
            try:
                progress_callback(pct, "downloading")
            except Exception:
                pass
        elif d.get("status") == "finished":
            try:
                progress_callback(100, "download finished")
            except Exception:
                pass

    # Build format selector — prefer separate video+audio (DASH/HLS) which gives 1080p+,
    # fall back to progressive combined streams (often capped at 720p).
    # Drop ext=mp4 restriction so yt-dlp can pick webm 1080p+ then merge to mp4.
    h = f"[height<=?{max_height}]" if max_height else ""
    fmt = (
        f"bestvideo{h}+bestaudio/"      # primary: best DASH video + audio (often 1080p+)
        f"best{h}/"                     # fallback: best progressive combined stream
        "best"                          # last resort
    )

    base_opts = {
        "format": fmt,
        "outtmpl": output_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "socket_timeout": timeout_sec,
        "retries": 2,
        "fragment_retries": 3,
        "skip_unavailable_fragments": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
        # Player client list — yt-dlp tries them in order. `mweb` (mobile web) often bypasses
        # 403 without auth and still provides 1080p HLS. `ios` is a reliable low-res fallback.
        # `web` tends to 403 unauthenticated on modern YouTube, so it goes last (used via cookies).
        "extractor_args": {"youtube": {"player_client": ["mweb", "android", "ios", "web"]}},
        # Also pull YouTube native subtitles (manual + auto-generated). When available
        # they're MUCH better than ASR — accurate speaker recognition + correct spelling.
        # The trailer pipeline checks for the .srt file post-download and skips ASR if found.
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-US", "en-GB", "en-orig"],
        "subtitlesformat": "srt/vtt/best",
    }

    # Strategy for YouTube HTTP 403 (anti-bot tightening):
    #   1st attempt: no cookies (fast path, works for public trailers)
    #   2nd attempt: fall back to browser cookies (real user session)
    # yt-dlp cookies-from-browser reads Chrome/Safari/etc. cookie store automatically.
    attempts = [base_opts]
    browser = _detect_browser_for_cookies()
    if browser:
        opts_with_cookies = dict(base_opts, cookiesfrombrowser=browser)
        attempts.append(opts_with_cookies)

    last_exc: Optional[Exception] = None
    for i, opts in enumerate(attempts, start=1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if not (os.path.exists(output_path) and os.path.getsize(output_path) > 0):
                raise RuntimeError("download completed but output file is missing or empty")
            return output_path
        except Exception as e:
            last_exc = e
            label = "with-cookies" if opts.get("cookiesfrombrowser") else "no-cookies"
            log.warning("yt-dlp attempt %d (%s) failed: %s", i, label, redact_error_message(e, 150))
            if i < len(attempts):
                continue
            raise
    # unreachable
    raise last_exc if last_exc else RuntimeError("download failed with no attempts")
