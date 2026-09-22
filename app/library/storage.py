"""Managed Docker storage. Copy and verify only after the application has stopped."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import uuid

DEFAULTS = {'data': 'data', 'temporary': 'tmp', 'models': 'models'}


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as handle:
            temporary.chmod(0o600)
            json.dump(value, handle, ensure_ascii=False)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def manifest(root):
    result = {}
    for path in sorted(root.rglob('*')):
        mode = path.lstat().st_mode
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('存储目录包含指向外部的符号链接：' + str(path))
            result[str(path.relative_to(root))] = ('link', str(path.readlink()))
        elif stat.S_ISREG(mode):
            with path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            result[str(path.relative_to(root))] = (path.stat().st_size, digest)
        elif not stat.S_ISDIR(mode):
            raise ValueError('存储目录包含不支持迁移的特殊文件：' + str(path))
    return result


class StoragePaths:
    def __init__(self, root, host_root, links):
        self.root = Path(root).resolve()
        self.host_root = Path(host_root)
        self.links = Path(links)
        self.file = self.root / '.aisub-storage.json'
        self.lock = threading.RLock()

    @classmethod
    def from_env(cls):
        root = os.environ.get('AISUBPRO_STORAGE_ROOT')
        if not root: return None
        return cls(root, os.environ.get('AISUBPRO_HOST_STORAGE_ROOT', root),
                   os.environ.get('AISUBPRO_STORAGE_LINKS', '/run/aisub-storage'))

    def load(self):
        return json.loads(self.file.read_text())

    def initialize(self, initial_paths=None):
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.file.exists():
            active = dict(DEFAULTS)
            for role, value in (initial_paths or {}).items():
                if value:
                    try: active[role] = str(Path(value).relative_to(self.host_root))
                    except ValueError: raise ValueError('原保存目录不在挂载范围内，请先迁移或调整 AISUB_STORAGE_ROOT：' + value) from None
            for value in active.values(): self.local(value)
            atomic_json(self.file, {'active': active, 'pending': None, 'error': ''})
        for value in self.load()['active'].values(): self.local(value).mkdir(parents=True, exist_ok=True)

    def local(self, relative):
        path = self.root / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or not relative or relative == '.':
            raise ValueError('保存目录无效。')
        if any(part.startswith('.') for part in Path(relative).parts) or path.resolve() != path:
            raise ValueError('保存目录不能使用隐藏路径或符号链接。')
        return path

    def state(self):
        value = self.load()
        host = lambda paths: {k: str(self.host_root / p) for k, p in paths.items()}
        return {'supported': True, 'current': host(value['active']),
                'desired': host(value.get('pending') or value['active']),
                'pending': bool(value.get('pending')), 'phase': value.get('phase', ''),
                'error': value.get('error', ''), 'allowed': str(self.host_root)}

    def validate(self, paths, active):
        if not isinstance(paths, dict) or set(paths) != set(DEFAULTS):
            raise ValueError('请分别填写数据、临时文件和模型目录。')
        result = {}
        for role, value in paths.items():
            if not isinstance(value, str) or '..' in Path(value).parts:
                raise ValueError('保存目录必须是完整服务器路径。')
            try: relative = str(Path(value.strip()).relative_to(self.host_root))
            except ValueError: raise ValueError('保存目录必须位于已挂载范围：' + str(self.host_root)) from None
            path = self.local(relative)
            result[role] = relative
            if relative != active[role]:
                if path.exists() and (not path.is_dir() or any(path.iterdir())):
                    raise ValueError('新保存目录必须为空，避免覆盖已有文件：' + value)
                for prior in active.values():
                    original = self.local(prior)
                    if path.is_relative_to(original) or original.is_relative_to(path):
                        raise ValueError('新目录不能与当前存储目录重叠：' + value)
                parent = path if path.exists() else path.parent
                while not parent.exists(): parent = parent.parent
                if not os.access(parent, os.W_OK | os.X_OK): raise ValueError('没有目录写入权限：' + value)
        resolved = [self.local(p) for p in result.values()]
        if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(resolved) for b in resolved[i + 1:]):
            raise ValueError('数据、临时文件和模型目录不能互相重叠。')
        return result

    def queue(self, paths):
        with self.lock:
            value = self.load()
            if value.get('phase') == 'restarting': raise ValueError('正在迁移目录，请等待服务恢复。')
            desired = self.validate(paths, value['active'])
            value.update(pending=desired if desired != value['active'] else None, phase='queued' if desired != value['active'] else '', error='')
            atomic_json(self.file, value)
            return self.state()

    def mark_restarting(self):
        with self.lock:
            value = self.load()
            if not value.get('pending'): return False
            value['phase'] = 'restarting'; atomic_json(self.file, value)
            return True

    def apply_pending(self):
        value = self.load()
        if not value.get('pending'): return False
        try:
            desired = self.validate({k: str(self.host_root / p) for k, p in value['pending'].items()}, value['active'])
            prepared = []
            for role, relative in desired.items():
                if relative == value['active'][role]: continue
                source, target = self.local(value['active'][role]), self.local(relative)
                required = sum(p.stat().st_size for p in source.rglob('*') if p.is_file() and not p.is_symlink())
                if shutil.disk_usage(self.root).free < required + 64 * 1024 * 1024:
                    raise OSError('磁盘可用空间不足，原目录保持不变。')
                target.parent.mkdir(parents=True, exist_ok=True)
                stage = target.with_name('.aisub-copy-' + uuid.uuid4().hex)
                if role == 'temporary':
                    stage.mkdir(mode=0o700)
                    prepared.append((stage, target))
                    continue
                before = manifest(source)
                shutil.copytree(source, stage, symlinks=True)
                if manifest(stage) != before or manifest(source) != before:
                    raise OSError('文件校验失败，原目录保持不变。')
                prepared.append((stage, target))
            for stage, target in prepared:
                if target.exists(): target.rmdir()  # Only an explicitly selected empty directory.
                stage.rename(target)
            atomic_json(self.file, {**value, 'active': desired, 'pending': None, 'phase': '', 'error': ''})
            return True
        except Exception as exc:
            value.update(pending=None, phase='', error='迁移失败，继续使用原目录：' + str(exc))
            atomic_json(self.file, value)
            return False

    def configure_links(self):
        self.links.mkdir(parents=True, exist_ok=True)
        value = self.load()
        for role, relative in value['active'].items():
            link = self.links / role
            temporary = self.links / (role + '.' + uuid.uuid4().hex)
            temporary.symlink_to(self.local(relative), target_is_directory=True)
            os.replace(temporary, link)


def bootstrap_storage():
    manager = StoragePaths.from_env()
    if not manager: return
    manager.initialize({role: os.environ.get('AISUBPRO_HOST_' + key + '_DIR')
                        for role, key in [('data', 'DATA'), ('temporary', 'TEMP'), ('models', 'MODEL')]})
    manager.apply_pending()
    manager.configure_links()
    for role, key in [('data', 'DATA'), ('temporary', 'TEMP'), ('models', 'MODEL')]:
        os.environ['AISUBPRO_HOST_' + key + '_DIR'] = manager.state()['current'][role]
