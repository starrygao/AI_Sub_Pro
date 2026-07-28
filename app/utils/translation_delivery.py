"""Visibility contract for the final translation artifact set."""

import os
from pathlib import Path

from app.utils.project_store import atomic_write_json


TRANSLATION_DELIVERY_SENTINEL = ".translation_delivery_in_progress"
TRANSLATION_DELIVERY_ARTIFACTS = frozenset({
    "translated.srt",
    "bilingual.srt",
})


def translation_delivery_sentinel_path(project_path: Path) -> Path:
    return Path(project_path) / TRANSLATION_DELIVERY_SENTINEL


def translation_delivery_is_invalid(project_path: Path) -> bool:
    """Return true even for a malformed or symlinked sentinel."""
    return os.path.lexists(translation_delivery_sentinel_path(project_path))


def mark_translation_delivery_invalid(project_path: Path) -> Path:
    """Atomically hide the final translation artifact set."""
    sentinel = translation_delivery_sentinel_path(project_path)
    atomic_write_json(sentinel, {"status": "in_progress"})
    return sentinel


def hide_invalid_translation_artifact_fields(project: dict, project_path: Path) -> dict:
    if translation_delivery_is_invalid(project_path):
        project["translated_srt"] = None
        project["bilingual_srt"] = None
    return project
