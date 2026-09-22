"""Resolve the current macOS drag without pywebview's DOM callback registry."""
import logging
from pathlib import Path
import stat

log = logging.getLogger(__name__)


def macos_dropped_paths(files) -> list[str]:
    if not isinstance(files, list) or not files or len(files) > 500:
        return []
    expected = []
    for item in files:
        if not isinstance(item, dict):
            return []
        name, size = item.get("name"), item.get("size")
        if not isinstance(name, str) or not name or type(size) is not int or size < 0:
            return []
        expected.append((name, size))
    from AppKit import (
        NSPasteboard, NSDragPboard, NSURL, NSPasteboardURLReadingFileURLsOnlyKey,
    )
    board = NSPasteboard.pasteboardWithName_(NSDragPboard)
    urls = board.readObjectsForClasses_options_(
        [NSURL], {NSPasteboardURLReadingFileURLsOnlyKey: True},
    ) or []
    available = []
    try:
        for url in urls:
            path = Path(str(url.path()))
            if not path.is_absolute():
                return []
            info = path.stat()
            size = 0 if stat.S_ISDIR(info.st_mode) else info.st_size
            available.append((path.name, size, str(path)))
    except OSError:
        log.warning("Cannot stat a native dropped file", exc_info=True)
        return []
    # Match the entire gesture, never reuse an unrelated previous drag.
    if len(available) != len(expected):
        return []
    paths = []
    for name, size in expected:
        match = next((item for item in available if item[:2] == (name, size)), None)
        if match is None:
            return []
        available.remove(match)
        paths.append(match[2])
    log.info("Resolved %d native drop path(s) directly", len(paths))
    return paths
