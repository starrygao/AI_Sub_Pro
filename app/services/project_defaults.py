"""Shared configuration/domain rules, independent of HTTP routing."""
import math
import re
from typing import Optional
from app.engines.project_metadata import normalize_content_type
from app.utils.media import is_text_subtitle_codec

_FORCED_SUBTITLE_TITLE_RE = re.compile(
    r"\b(forced|foreign\s+only|signs?\s*(?:&|and)\s*songs?)\b",
    re.IGNORECASE,
)

_COMMENTARY_SUBTITLE_TITLE_RE = re.compile(
    r"\b(commentary|director'?s?\s+commentary)\b",
    re.IGNORECASE,
)

_SDH_SUBTITLE_TITLE_RE = re.compile(
    r"\b(sdh|cc|closed\s+captions?|hearing\s+impaired|descriptive)\b",
    re.IGNORECASE,
)

_PROJECT_SAFE_DEFAULTS = {
    "source_type": "upload",
    "auto_run": False,
    "workflow_mode": "translate_burn",
    "tmdb_id": None,
    "tmdb_type": None,
    "season_number": None,
    "tmdb_video_key": None,
    "youtube_url": None,
    "original_language": None,
    "parent_project_id": None,
    "pipeline_stage": None,
    "archived": False,
    "prefer_embedded_subtitle": True,
    "tmdb_candidates": None,
    "show_title": None,
    "poster_path": None,
    "asr_skipped": False,
    "asr_language": "auto",
    "target_language": "简体中文",
    "error": None,
    "network_metadata": None,
    "source_title": None,
    "source_uploader": None,
    "source_channel": None,
    "source_duration": None,
    "source_webpage_url": None,
    "source_extractor": None,
    "source_language": None,
    "source_has_subtitles": False,
    "subtitle_source": None,
    "native_subtitle_language": None,
    "network_video_plan": None,
    "content_type": "auto",
    "academic_field": "",
    "content_notes": "",
    "manual_terms": "",
    "metadata_source": "",
    "translated_srt": None,
    "bilingual_srt": None,
    "translation_quality_configuration_hash": "",
}

_TARGET_LANG_TO_ISO = {
    "简体中文": {"zh", "chi", "zho", "cmn", "chs"},
    "繁體中文": {"zh", "chi", "zho", "cht"},
    "繁体中文": {"zh", "chi", "zho", "cht"},
    "English": {"en", "eng"},
    "日本語": {"ja", "jpn"},
    "Japanese": {"ja", "jpn"},
    "日语": {"ja", "jpn"},
    "한국어": {"ko", "kor"},
}

_WORKFLOW_MODES = {"translate_burn", "translate_only"}

def _normalize_workflow_mode(value) -> str:
    if isinstance(value, str) and value.strip() in _WORKFLOW_MODES:
        return value.strip()
    return "translate_burn"

def _json_safe_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    return value

def _subtitle_track_title(track: dict) -> str:
    title = track.get("title") if isinstance(track, dict) else ""
    return title.strip() if isinstance(title, str) else ""

def _is_forced_or_commentary_subtitle(track: dict) -> bool:
    title = _subtitle_track_title(track)
    return bool(
        title
        and (
            _FORCED_SUBTITLE_TITLE_RE.search(title)
            or _COMMENTARY_SUBTITLE_TITLE_RE.search(title)
        )
    )

def _subtitle_track_penalty(track: dict) -> int:
    title = _subtitle_track_title(track)
    if title and _SDH_SUBTITLE_TITLE_RE.search(title):
        return 5
    return 0

def _pick_subtitle_track(tracks: list, target_language: str) -> Optional[int]:
    """Pick the best embedded subtitle track to bypass ASR.

    Returns the 0-based index into `tracks` (the list returned by
    `get_tracks(path, 's')` — i.e. all subtitle streams in the input
    file). This index is suitable for ffmpeg's `-map 0:s:N` selector.
    The frontend must NOT pre-filter `subtitle_tracks` before indexing —
    use the raw list, otherwise the index misaligns when image-based
    tracks (PGS/DVD/DVB) sit ahead of text tracks.

    Selection rules:
      1. Drop image-based codecs (PGS/DVD/DVB) — they need OCR, can't transcode.
      2. Drop forced/commentary tracks — they are usually incomplete or not
         the program dialogue; fall back to ASR if those are the only tracks.
      3. Prefer regular English (most common source language for translation).
      4. Then prefer regular non-target-language tracks.
      5. Prefer SDH/CC only when there is no regular source track.
    Returns None if no usable text track exists.
    """
    target_iso = _TARGET_LANG_TO_ISO.get(target_language, set())
    text_subs = [
        (i, t) for i, t in enumerate(tracks)
        if is_text_subtitle_codec(t.get("codec"))
        and not _is_forced_or_commentary_subtitle(t)
    ]
    if not text_subs:
        return None

    def lang(t):
        value = t.get("lang")
        return value.lower() if isinstance(value, str) else ""

    def score(item):
        i, t = item
        track_lang = lang(t)
        if not ({"en", "eng"} & target_iso) and track_lang in {"en", "eng"}:
            lang_score = 0
        elif track_lang and track_lang not in target_iso:
            lang_score = 10
        elif track_lang in target_iso:
            lang_score = 20
        else:
            lang_score = 15
        return (lang_score + _subtitle_track_penalty(t), i)

    return min(text_subs, key=score)[0]

def _apply_safe_defaults(project: dict) -> dict:
    """Backward-compat: ensure new schema fields exist with sane defaults on load."""
    if not isinstance(project, dict):
        raise ValueError("Project file is invalid")
    project = _json_safe_value(project)
    for k, v in _PROJECT_SAFE_DEFAULTS.items():
        project.setdefault(k, v)
    for field in ("audio_tracks", "subtitle_tracks"):
        if not isinstance(project.get(field), list):
            project[field] = []
        else:
            project[field] = [t for t in project[field] if isinstance(t, dict)]
    for field in ("video_path", "output_video", "translated_srt", "bilingual_srt"):
        if project.get(field) is not None and not isinstance(project.get(field), str):
            project[field] = None
    for field in (
        "tmdb_video_key",
        "youtube_url",
        "original_language",
        "parent_project_id",
        "pipeline_stage",
        "show_title",
        "poster_path",
        "error",
        "source_title",
        "source_uploader",
        "source_channel",
        "source_webpage_url",
        "source_extractor",
        "source_language",
        "subtitle_source",
        "native_subtitle_language",
        "academic_field",
        "content_notes",
        "manual_terms",
        "metadata_source",
    ):
        if project.get(field) is not None and not isinstance(project.get(field), str):
            project[field] = None
    if not isinstance(project.get("network_metadata"), dict):
        project["network_metadata"] = {}
    if project.get("network_video_plan") is not None and not isinstance(project.get("network_video_plan"), dict):
        project["network_video_plan"] = None
    project["content_type"] = normalize_content_type(project.get("content_type"))
    for field, limit in (
        ("academic_field", 80),
        ("content_notes", 1200),
        ("manual_terms", 2400),
        ("metadata_source", 40),
    ):
        value = project.get(field)
        if value is None:
            project[field] = ""
        elif isinstance(value, str):
            project[field] = value.strip()[:limit]
        else:
            project[field] = ""
    for field, limit in (
        ("source_title", 160),
        ("source_uploader", 160),
        ("source_channel", 160),
        ("source_webpage_url", 500),
        ("source_extractor", 80),
        ("source_language", 32),
        ("subtitle_source", 40),
        ("native_subtitle_language", 32),
    ):
        value = project.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            project[field] = value.strip()[:limit] or None
        else:
            project[field] = None
    if project.get("source_type") not in ("upload", "trailer", "subtitle", "audio"):
        project["source_type"] = "upload"
    project["workflow_mode"] = _normalize_workflow_mode(project.get("workflow_mode"))
    for field, default in (("asr_language", "auto"), ("target_language", "简体中文")):
        value = project.get(field)
        if not isinstance(value, str) or not value.strip():
            project[field] = default
    if project.get("tmdb_candidates") is not None:
        if not isinstance(project.get("tmdb_candidates"), list):
            project["tmdb_candidates"] = None
        else:
            project["tmdb_candidates"] = [
                candidate for candidate in project["tmdb_candidates"]
                if isinstance(candidate, dict)
            ]

    def positive_int_or_none(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return None
        return value

    project["tmdb_id"] = positive_int_or_none(project.get("tmdb_id"))
    project["season_number"] = positive_int_or_none(project.get("season_number"))
    try:
        duration = float(project.get("duration", 0))
    except (OverflowError, TypeError, ValueError):
        duration = 0
    if not math.isfinite(duration):
        duration = 0
    project["duration"] = max(0, duration)
    source_duration = project.get("source_duration")
    if source_duration is not None:
        try:
            source_duration = float(source_duration)
        except (OverflowError, TypeError, ValueError):
            source_duration = None
        if source_duration is not None and (not math.isfinite(source_duration) or source_duration < 0):
            source_duration = None
        if isinstance(source_duration, float) and source_duration.is_integer():
            source_duration = int(source_duration)
    project["source_duration"] = source_duration
    if project.get("tmdb_type") not in (None, "movie", "tv"):
        project["tmdb_type"] = None
    for field, default in (
        ("archived", False),
        ("asr_skipped", False),
        ("prefer_embedded_subtitle", True),
        ("auto_run", False),
        ("source_has_subtitles", False),
    ):
        if not isinstance(project.get(field), bool):
            project[field] = default
    audio_track_count = len(project.get("audio_tracks") or [])
    selected_audio_track = project.get("selected_audio_track")
    if (
        isinstance(selected_audio_track, bool)
        or not isinstance(selected_audio_track, int)
        or selected_audio_track < 0
        or (audio_track_count > 0 and selected_audio_track >= audio_track_count)
        or (audio_track_count == 0 and selected_audio_track != 0)
    ):
        project["selected_audio_track"] = 0

    subtitle_track_count = len(project.get("subtitle_tracks") or [])
    selected_subtitle_track = project.get("selected_subtitle_track")
    invalid_selected_subtitle_track = (
        selected_subtitle_track is not None
        and (
            isinstance(selected_subtitle_track, bool)
            or not isinstance(selected_subtitle_track, int)
            or selected_subtitle_track < 0
            or selected_subtitle_track >= subtitle_track_count
        )
    )
    if invalid_selected_subtitle_track:
        project["selected_subtitle_track"] = None

    raw_progress = project.get("progress", 0)
    try:
        progress = int(raw_progress) if not isinstance(raw_progress, bool) else 0
    except (OverflowError, TypeError, ValueError):
        progress = 0
    project["progress"] = max(0, min(100, progress))
    if not isinstance(project.get("progress_msg", ""), str):
        project["progress_msg"] = ""
    # Backfill: pre-existing projects detected subtitle tracks before the
    # auto-picker existed, so they have subtitle_tracks but a null
    # selected_subtitle_track. Run the picker once so the user can use the
    # embedded-subtitle bypass without re-creating the project.
    if (not invalid_selected_subtitle_track
            and project.get("selected_subtitle_track") is None
            and project.get("subtitle_tracks")):
        idx = _pick_subtitle_track(project["subtitle_tracks"],
                                    project.get("target_language", "简体中文"))
        if idx is not None:
            project["selected_subtitle_track"] = idx
    return project
