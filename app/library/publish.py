"""Publish a certified translation without replacing any existing subtitle."""
import os
from pathlib import Path
import tempfile
from .guard import fingerprint


def publish_sidecar(video, source, expected):
    video,source=Path(video),Path(source)
    if fingerprint(video)!=expected:
        raise RuntimeError('视频已变化，旧版本译文不能发布')
    output=video.with_suffix('.srt')
    content=source.read_bytes()
    if not content:raise ValueError('译文为空')
    fd,temporary=tempfile.mkstemp(prefix='.aisub-',suffix='.tmp',dir=video.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(content);f.flush();os.fsync(f.fileno())
        os.chmod(temporary,0o644)
        if fingerprint(video)!=expected:raise RuntimeError('发布前视频已变化')
        try:os.link(temporary,output)  # atomic create-if-absent
        except FileExistsError:
            if output.is_symlink() or output.read_bytes()!=content:raise
        if fingerprint(video)!=expected:
            # Remove only the exact inode that we just published, never another writer's file.
            if output.stat().st_ino==Path(temporary).stat().st_ino:output.unlink()
            raise RuntimeError('发布时视频已被替换')
        parent=os.open(video.parent,os.O_RDONLY)
        try:os.fsync(parent)
        finally:os.close(parent)
        return output
    finally:Path(temporary).unlink(missing_ok=True)


def archive_stale_sidecar(output, expected_hash):
    """Keep a backup of our old result after video replacement; never move user edits."""
    import hashlib
    output=Path(output)
    if output.is_symlink() or not output.is_file():return None
    if hashlib.sha256(output.read_bytes()).hexdigest()!=expected_hash:return None
    backups=output.parent/'.aisub-backups'
    if backups.is_symlink():raise RuntimeError('字幕备份目录不可为符号链接')
    backups.mkdir(exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=output.name+'.',suffix='.bak',dir=backups)
    os.close(fd)
    backup=Path(name)
    try:
        # Retain the original inode in the backup, including any concurrent edits.
        old=output.stat()
        backup.unlink()
        os.link(output,backup)
        if output.stat().st_ino!=old.st_ino or hashlib.sha256(output.read_bytes()).hexdigest()!=expected_hash:
            backup.unlink();return None
        output.unlink()
        return backup
    except Exception:
        if not backup.stat().st_size:backup.unlink(missing_ok=True)
        raise
