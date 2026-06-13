"""Content-type translation profile inference and prompt snippets."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContentProfile:
    id: str
    label: str
    rules: tuple[str, ...]
    signals: tuple[str, ...] = ()
    examples: tuple[tuple[str, str], ...] = ()


_PROFILES: tuple[ContentProfile, ...] = (
    ContentProfile(
        id="us_series",
        label="US/English-language series",
        rules=(
            "Translate as modern spoken Chinese for episodic TV; keep lines concise and natural.",
            "Localize slang and jokes by intent, but do not invent plot facts or over-explain subtext.",
            "Keep recurring names, relationship labels, and catchphrases stable across episodes.",
        ),
        signals=("original_language=en", "tv"),
    ),
    ContentProfile(
        id="interview",
        label="Interview",
        rules=(
            "Preserve Q/A structure, speaker stance, and topic transitions.",
            "Compress filler/repetition when it hurts subtitle readability, without deleting meaning.",
            "Keep quoted wording, titles, names, and factual claims precise.",
        ),
        signals=("interview", "talk show", "podcast"),
    ),
    ContentProfile(
        id="documentary_unscripted",
        label="Documentary / unscripted",
        rules=(
            "Keep factual claims, chronology, measurements, and quoted wording precise.",
            "Translate speaker titles only when they first appear unless the source repeats them for clarity.",
            "Do not dramatize neutral narration; preserve evidence, uncertainty, and attribution.",
        ),
        signals=("documentary", "unscripted", "non-fiction"),
    ),
    ContentProfile(
        id="academic_lecture",
        label="Academic lecture / research talk",
        rules=(
            "Translate dense academic claims faithfully; preserve caveats, hedges, definitions, and proof/theorem structure.",
            "Preserve equations, symbols, variables, units, citations, paper titles, and formal abbreviations when they are part of the source.",
            "Keep discipline terms consistent; when an English abbreviation is standard, preserve it and translate the surrounding explanation.",
        ),
        signals=("academic_lecture", "lecture", "seminar", "research talk"),
    ),
    ContentProfile(
        id="sitcom_comedy",
        label="Sitcom / comedy",
        rules=(
            "Preserve punchline timing; keep setup lines compact so the joke lands on the right subtitle.",
            "Localize idioms and sarcasm by intent, but do not explain the joke inside the subtitle.",
            "Keep recurring catchphrases and character-specific comic voice consistent.",
        ),
        signals=("sitcom", "comedy"),
    ),
    ContentProfile(
        id="korean_drama",
        label="Korean drama",
        rules=(
            "Preserve honorific/register shifts; reflect respect, intimacy, and hierarchy in Chinese.",
            "Translate relationship terms by context instead of mechanically transliterating them.",
            "Keep character names and recurring address forms consistent.",
        ),
        signals=("original_language=ko", "k-drama"),
    ),
    ContentProfile(
        id="japanese_drama",
        label="Japanese drama",
        rules=(
            "Preserve honorific/register shifts; convert suffixes like san/kun/chan/senpai by context.",
            "Keep Japanese names readable in Chinese and avoid leaving particles or honorifics unexplained.",
            "Keep emotional restraint, indirect refusals, and workplace/school address forms natural.",
        ),
        signals=("original_language=ja", "j-drama"),
    ),
    ContentProfile(
        id="anime",
        label="Anime",
        rules=(
            "Preserve character voice, relationship hierarchy, and genre register without over-literal particles.",
            "Translate attack names, school ranks, club terms, and recurring catchphrases consistently.",
            "Keep emotional outbursts punchy; avoid adding explanatory lore not present in the subtitle.",
        ),
        signals=("anime", "animation"),
    ),
    ContentProfile(
        id="legal_adult",
        label="Legal adult content",
        rules=(
            "Only apply this profile when metadata clearly indicates legal adult content.",
            "保持成年、自愿语境；不要添加源字幕没有表达的露骨细节。",
            "Keep address terms and intimacy level consistent; compress moans, filler, and repeated fragments for readable subtitles.",
        ),
        signals=("adult", "av"),
        examples=(
            ("Fuck me.", "操我。"),
            ("I'm coming.", "我要去了。"),
            ("Harder.", "用力点。"),
            ("Don't stop.", "别停。"),
            ("That feels good.", "这样好爽。"),
        ),
    ),
    ContentProfile(
        id="technical_tutorial",
        label="Technical tutorial",
        rules=(
            "Preserve commands, code identifiers, API names, filenames, flags, and error messages exactly unless the source explains them.",
            "Keep step order explicit and translate instruction verbs consistently.",
            "Do not paraphrase technical claims in a way that changes prerequisites, units, or version constraints.",
        ),
        signals=("tutorial", "course", "programming"),
    ),
    ContentProfile(
        id="movie",
        label="Movie",
        rules=(
            "Translate with cinematic economy: preserve subtext, tension, and scene rhythm.",
            "Avoid explaining visual information already carried by the shot.",
            "Keep titles, quoted lines, and recurring motifs consistent.",
        ),
        signals=("movie", "film"),
    ),
)


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _iter_metadata_strings(meta_info: dict) -> list[str]:
    if not isinstance(meta_info, dict):
        return []
    values: list[str] = []
    for key in (
        "name",
        "show_title",
        "title",
        "original_title",
        "plot",
        "overview",
        "tmdb_type",
        "source_type",
        "source_title",
        "source_uploader",
        "source_channel",
        "category",
        "content_type",
        "academic_field",
        "content_notes",
        "manual_terms",
    ):
        value = meta_info.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    for key in ("genres", "genre", "tags", "categories"):
        value = meta_info.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str) and item.strip())
    return values


def _metadata_blob(meta_info: dict) -> str:
    return " ".join(_iter_metadata_strings(meta_info)).casefold()


def _metadata_token_set(meta_info: dict) -> set[str]:
    blob = _metadata_blob(meta_info)
    return {token for token in re.split(r"[^a-z0-9+-]+", blob) if token}


def _language_code(meta_info: dict) -> str:
    if not isinstance(meta_info, dict):
        return ""
    for key in ("original_language", "source_language", "language"):
        value = meta_info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    return ""


def _normalized_type(meta_info: dict) -> str:
    if not isinstance(meta_info, dict):
        return ""
    value = meta_info.get("tmdb_type") or meta_info.get("media_type") or meta_info.get("source_type")
    return value.strip().casefold() if isinstance(value, str) else ""


def _has_token(meta_info: dict, *tokens: str) -> bool:
    available = _metadata_token_set(meta_info)
    return any(token.casefold() in available for token in tokens)


def _has_phrase(meta_info: dict, *phrases: str) -> bool:
    blob = _metadata_blob(meta_info)
    return any(phrase.casefold() in blob for phrase in phrases)


def _looks_episode_like(meta_info: dict) -> bool:
    blob = _metadata_blob(meta_info)
    return bool(re.search(r"\bs\d{1,2}e\d{1,2}\b", blob)) or _has_token(meta_info, "series", "tv")


def _is_tv_like(meta_info: dict) -> bool:
    media_type = _normalized_type(meta_info)
    return media_type in {"tv", "series"} or _looks_episode_like(meta_info)


def _is_english_series(meta_info: dict) -> bool:
    lang = _language_code(meta_info)
    media_type = _normalized_type(meta_info)
    return lang in {"en", "eng", "english"} and (
        media_type in {"tv", "series"} or _looks_episode_like(meta_info)
    )


def _is_interview(meta_info: dict) -> bool:
    return _has_token(meta_info, "interview", "podcast", "q+a", "qa") or _has_phrase(
        meta_info,
        "talk show",
        "q&a",
        "cast interview",
        "访谈",
        "采访",
    )


def _is_documentary_unscripted(meta_info: dict) -> bool:
    return _has_token(meta_info, "documentary", "docuseries", "unscripted") or _has_phrase(
        meta_info,
        "non-fiction",
        "nonfiction",
        "纪录片",
        "紀錄片",
        "真人秀",
    )


def _is_academic_lecture(meta_info: dict) -> bool:
    return _has_token(meta_info, "academic_lecture", "lecture", "seminar", "colloquium") or _has_phrase(
        meta_info,
        "academic lecture",
        "research talk",
        "conference talk",
        "guest lecture",
        "paper presentation",
        "学术",
        "讲座",
    )


def _is_sitcom_comedy(meta_info: dict) -> bool:
    return _has_token(meta_info, "sitcom", "comedy") or _has_phrase(
        meta_info,
        "situation comedy",
        "情景喜剧",
        "情境喜劇",
        "喜剧",
        "喜劇",
    )


def _is_korean_drama(meta_info: dict) -> bool:
    lang = _language_code(meta_info)
    if _has_phrase(
        meta_info,
        "k-drama",
        "korean drama",
        "韩剧",
        "韓劇",
    ):
        return True
    return (
        lang in {"ko", "kor", "korean"}
        and _is_tv_like(meta_info)
        and not _is_interview(meta_info)
        and not _is_documentary_unscripted(meta_info)
        and not _is_anime(meta_info)
    )


def _is_japanese_drama(meta_info: dict) -> bool:
    lang = _language_code(meta_info)
    if _has_phrase(
        meta_info,
        "j-drama",
        "japanese drama",
        "日剧",
        "日劇",
    ):
        return True
    return (
        lang in {"ja", "jp", "jpn", "japanese"}
        and _is_tv_like(meta_info)
        and not _is_interview(meta_info)
        and not _is_documentary_unscripted(meta_info)
        and not _is_anime(meta_info)
    )


def _is_anime(meta_info: dict) -> bool:
    return _has_token(meta_info, "anime") or _has_phrase(
        meta_info,
        "japanese animation",
        "anime series",
        "动画",
        "動畫",
        "アニメ",
    )


def _is_legal_adult(meta_info: dict) -> bool:
    genre_tokens = {
        token.casefold()
        for key in ("genres", "genre", "tags", "categories", "category", "content_type")
        for token in (
            meta_info.get(key)
            if isinstance(meta_info.get(key), list)
            else [meta_info.get(key)]
        )
        if isinstance(token, str) and token.strip()
    }
    explicit_tag = bool(genre_tokens & {"adult", "av", "legal_adult", "explicit_adult", "xxx"})
    return explicit_tag or _has_phrase(
        meta_info,
        "legal adult",
        "adult video",
        "adult film",
        "adult content",
        "porn",
        "xxx",
        "成人视频",
        "成人片",
        "成人电影",
    )


def _is_technical_tutorial(meta_info: dict) -> bool:
    return _has_token(
        meta_info,
        "tutorial",
        "course",
        "lesson",
        "programming",
        "coding",
        "developer",
    ) or _has_phrase(
        meta_info,
        "how-to",
        "how to",
        "technical tutorial",
        "coding tutorial",
        "编程",
        "教程",
    )


def _is_movie(meta_info: dict) -> bool:
    media_type = _normalized_type(meta_info)
    return media_type in {"movie", "film"} or _has_token(meta_info, "movie", "film")


_PREDICATES = {
    "us_series": _is_english_series,
    "interview": _is_interview,
    "documentary_unscripted": _is_documentary_unscripted,
    "academic_lecture": _is_academic_lecture,
    "sitcom_comedy": _is_sitcom_comedy,
    "korean_drama": _is_korean_drama,
    "japanese_drama": _is_japanese_drama,
    "anime": _is_anime,
    "legal_adult": _is_legal_adult,
    "technical_tutorial": _is_technical_tutorial,
    "movie": _is_movie,
}


def infer_content_profiles(meta_info: dict) -> list[ContentProfile]:
    if not isinstance(meta_info, dict):
        return []
    matches: list[ContentProfile] = []
    for profile in _PROFILES:
        predicate = _PREDICATES[profile.id]
        if predicate(meta_info):
            matches.append(profile)
    return matches


def build_content_profile_prompt_snippet(meta_info: dict) -> tuple[str, list[dict]]:
    profiles = infer_content_profiles(meta_info)
    if not profiles:
        return "", []
    lines = [
        "Content profile guidance (lower priority than project KB and terminology; apply only when consistent with the source):"
    ]
    hits: list[dict] = []
    for profile in profiles:
        lines.append(f"[{profile.label}]")
        for rule in profile.rules:
            lines.append(f"  - {rule}")
        if profile.examples:
            lines.append("  Explicit adult subtitle examples (legal consenting adult context only):")
            for source, target in profile.examples:
                lines.append(f"    - {source} → {target}")
        hits.append({
            "id": profile.id,
            "label": profile.label,
            "scope": "content_profile",
            "signals": list(profile.signals),
            "example_count": len(profile.examples),
        })
    return "\n".join(lines), hits
