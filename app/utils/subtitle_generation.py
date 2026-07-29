"""Deterministic identities for subtitle source and delivery artifacts."""

import hashlib
from pathlib import Path


def subtitle_file_hash(path: Path) -> str:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return ""
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def subtitle_source_generation_hash(project_path: Path) -> str:
    project_path = Path(project_path)
    source_path = next(
        (
            project_path / name
            for name in ("filtered.srt", "raw.srt", "native.srt")
            if (project_path / name).is_file()
            and not (project_path / name).is_symlink()
        ),
        None,
    )
    if source_path is None:
        return ""
    payload = source_path.read_bytes()
    filter_path = project_path / "filter_state.json"
    if (
        source_path.name != "filtered.srt"
        and filter_path.is_file()
        and not filter_path.is_symlink()
    ):
        payload += b"\0filter_state.json\0" + filter_path.read_bytes()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
