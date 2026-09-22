"""Durable watch-folder edits, applied between library jobs."""
from pathlib import Path

from .guard import fingerprint, map_path


class DirectorySettings:
    def __init__(self, worker):
        self.worker = worker

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
        pending = self.worker.store.setting('pending_roots')
        return {'current': [self.host(p) for p in self.worker.roots],
                'desired': [self.host(p) for p in (pending if pending is not None else self.worker.roots)],
                'pending': pending is not None, 'error': self.worker.store.setting('roots_error', ''),
                'allowed': [self.host(p) for p in self.worker.config.get('allowed_roots', [])]}

    def queue(self, paths):
        desired = self.validate(paths)
        self.worker.store.set_setting('pending_roots', desired if desired != self.worker.roots else None)
        self.worker.store.set_setting('roots_error', '')
        self.worker.wake.set()
        return self.read()

    def apply(self):
        from app.services.translation_tasks import run_when_tasks_idle
        def commit():
            desired = self.worker.store.setting('pending_roots')
            if desired is None or self.worker.store.rows(['translating', 'publishing'], limit=1): return False
            try:
                desired = self.validate([self.host(p) for p in desired])
                old_roots = list(self.worker.roots)
                added = [p for p in desired if p not in old_roots]
                if self.worker.config.get('new_only', False) and added:
                    entries = []
                    for path in self.worker.filesystem(added, strict=True):
                        if any(path.is_relative_to(root) for root in old_roots): continue
                        try: entries.append((str(path), fingerprint(path)))
                        except FileNotFoundError: entries.append((str(path), None))
                    self.worker.store.install_baseline(entries, added, preserve_roots=old_roots)
                self.worker.store.set_setting('watch_roots', desired)
                self.worker.roots = desired; self.worker.manual_roots = True; self.worker.walker = None
                self.worker.store.exclude_unstarted_outside_roots(desired)
                self.worker.store.set_setting('pending_roots', None)
                self.worker.store.set_setting('roots_error', '')
                return True
            except Exception as exc:
                self.worker.store.set_setting('roots_error', str(exc))
                return False
        return run_when_tasks_idle(commit)
