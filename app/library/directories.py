"""Durable watch-folder edits, applied between library jobs."""
from pathlib import Path
import threading
import uuid

from .guard import fingerprint, map_path


class DirectorySettings:
    def __init__(self, worker):
        self.worker = worker
        self.lock = threading.RLock()

    def host(self, path):
        return map_path(str(path), self.worker.config.get('host_path_maps', {}))

    def validate(self, paths):
        if not isinstance(paths, list) or len(paths) > 200 or any(not isinstance(p, str) for p in paths):
            raise ValueError('请提供监控文件夹列表，最多 200 个。')
        mappings = {host: container for container, host in self.worker.config.get('host_path_maps', {}).items()}
        allowed = [Path(p).resolve() for p in self.worker.config.get('allowed_roots', [])]
        result = []
        for value in paths:
            path = Path(map_path(value.strip(), mappings))
            if not path.is_absolute() or '..' in path.parts:
                raise ValueError('请填写完整服务器路径，不允许使用上级目录符号。')
            if not path.is_dir():
                raise ValueError('文件夹不存在或不可读取：' + value)
            real = path.resolve()
            if not any(real.is_relative_to(root) for root in allowed) or real != path:
                raise ValueError('文件夹必须位于已挂载的媒体目录内，且不能使用符号链接：' + value)
            if str(path) not in result: result.append(str(path))
        # Parent folders include their descendants; avoid duplicate walks.
        return [p for p in result if not any(p != other and Path(p).is_relative_to(other) for other in result)]

    def read(self):
        with self.lock:
            pending = self.worker.store.setting('pending_roots')
            return {'current': [self.host(p) for p in self.worker.roots],
                    'desired': [self.host(p) for p in (pending if pending is not None else self.worker.roots)],
                    'pending': pending is not None, 'error': self.worker.store.setting('roots_error', ''),
                    'allowed': [self.host(p) for p in self.worker.config.get('allowed_roots', [])]}

    def queue(self, paths):
        desired = self.validate(paths)
        with self.lock:
            self.worker.store.set_settings({
                'pending_roots': desired if desired != self.worker.roots else None,
                'pending_roots_revision': uuid.uuid4().hex,
                'roots_error': '',
            })
            self.worker.wake.set()
            return self.read()

    def apply(self):
        from app.services.translation_tasks import run_when_tasks_idle
        def commit():
            with self.lock:
                desired = self.worker.store.setting('pending_roots')
                revision = self.worker.store.setting('pending_roots_revision')
                if desired is None or self.worker.store.rows(['translating', 'publishing'], limit=1): return False
                old_roots = list(self.worker.roots)
            try:
                desired = self.validate([self.host(p) for p in desired])
                added = [p for p in desired if p not in old_roots]
                entries = []
                if self.worker.config.get('new_only', False) and added:
                    for path in self.worker.filesystem(added, strict=True):
                        if any(path.is_relative_to(root) for root in old_roots): continue
                        try: entries.append((str(path), fingerprint(path)))
                        except FileNotFoundError: entries.append((str(path), None))
                # Scanning can be slow. Keep saves responsive and discard an inventory
                # superseded by a later edit/cancellation, including A -> B -> A edits.
                with self.lock:
                    if self.worker.store.setting('pending_roots_revision') != revision: return False
                    if self.worker.config.get('new_only', False) and added:
                        self.worker.store.install_baseline(entries, added, preserve_roots=old_roots)
                    self.worker.store.set_settings({'watch_roots': desired, 'pending_roots': None, 'roots_error': ''})
                    self.worker.roots = desired; self.worker.manual_roots = True; self.worker.walker = None
                    self.worker.store.exclude_unstarted_outside_roots(desired)
                    return True
            except Exception as exc:
                with self.lock:
                    if self.worker.store.setting('pending_roots_revision') == revision:
                        self.worker.store.set_setting('roots_error', str(exc))
                return False
        return run_when_tasks_idle(commit)
