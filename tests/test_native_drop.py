"""Native macOS paths must not depend on pywebview DOM event delivery."""
from types import SimpleNamespace
import sys


def test_macos_drag_paths_are_read_without_document_callback(monkeypatch, tmp_path):
    from app.utils.native_drop import macos_dropped_paths
    file = tmp_path / '剧集 #1%20.mkv'
    file.write_bytes(b'video')
    url = SimpleNamespace(path=lambda: str(file))
    board = SimpleNamespace(readObjectsForClasses_options_=lambda *args: [url])
    monkeypatch.setitem(sys.modules, 'AppKit', SimpleNamespace(
        NSPasteboard=SimpleNamespace(pasteboardWithName_=lambda name: board),
        NSDragPboard='drag', NSURL=object, NSPasteboardURLReadingFileURLsOnlyKey='files-only'))
    assert macos_dropped_paths([{'name': file.name, 'size': 5}]) == [str(file)]
    assert macos_dropped_paths([{'name': file.name, 'size': 6}]) == []
    assert macos_dropped_paths([{'name': 'different.mkv', 'size': 5}]) == []
    assert macos_dropped_paths([]) == []
    assert macos_dropped_paths([{'name': file.name}]) == []


def test_drag_path_validation_rejects_partial_or_stale_payload(monkeypatch, tmp_path):
    from app.utils.native_drop import macos_dropped_paths
    file = tmp_path / 'first.mkv'
    file.write_bytes(b'video')
    url = SimpleNamespace(path=lambda: str(file))
    board = SimpleNamespace(readObjectsForClasses_options_=lambda *args: [url])
    monkeypatch.setitem(sys.modules, 'AppKit', SimpleNamespace(
        NSPasteboard=SimpleNamespace(pasteboardWithName_=lambda name: board),
        NSDragPboard='drag', NSURL=object, NSPasteboardURLReadingFileURLsOnlyKey='files-only'))
    assert macos_dropped_paths([{'name': file.name, 'size': 5}, {'name': 'second.mkv', 'size': 2}]) == []
