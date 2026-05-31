"""Migrate knowledge.json from v1 (flat term→translation dict) to v2 (typed categories)."""
import logging
from typing import Dict

log = logging.getLogger(__name__)


def is_v2_shape(data: dict) -> bool:
    """Return True if data is already v2 (has characters/style_notes) or empty."""
    if not data:
        return True
    for key, val in data.items():
        if not isinstance(val, dict):
            return False
        if "characters" in val or "style_notes" in val:
            return True
        if "terms" in val or "keywords" in val:
            return False
    return True  # unknown → assume v2 to avoid destructive migration


def migrate_v1_to_v2(data: dict) -> dict:
    """Convert v1 {keywords, style, terms} → v2 ProjectKb-compatible structure."""
    if is_v2_shape(data):
        return data

    v2: Dict[str, dict] = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            log.warning("kb migration: skipping non-dict entry %r", name)
            continue
        terms_dict = entry.get("terms", {}) or {}
        if not isinstance(terms_dict, dict):
            log.warning("kb migration: skipping malformed terms for %r", name)
            terms_dict = {}
        characters = []
        for src, dst in terms_dict.items():
            if not isinstance(src, str) or not isinstance(dst, str):
                continue
            source = src.strip()
            target = dst.strip()
            if source and target:
                characters.append({"source": source, "target": target, "notes": ""})
        style_text = entry.get("style", "") or ""
        if not isinstance(style_text, str):
            style_text = ""
        raw_keywords = entry.get("keywords", [])
        if isinstance(raw_keywords, str):
            legacy_keywords = [raw_keywords.strip()] if raw_keywords.strip() else []
        elif isinstance(raw_keywords, list):
            legacy_keywords = [kw.strip() for kw in raw_keywords if isinstance(kw, str) and kw.strip()]
        else:
            legacy_keywords = []
        v2[name] = {
            "show_title": name,
            "tmdb_id": None,
            "characters": characters,
            "places": [],
            "brands": [],
            "slang": [],
            "style_notes": {
                "tone": style_text,
                "perspective": "",
                "rules": [],
            },
            "_legacy_keywords": legacy_keywords,
        }
    return v2
