"""Pure readiness rules, shared by discovery and the final publication gate."""
from pathlib import Path
import re

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.ts', '.m2ts', '.webm'}
SUBTITLE_EXTENSIONS = {'.srt', '.ass', '.ssa', '.vtt', '.sub', '.idx', '.sup'}
TEMP_MARKERS = {'.parts', '.partial', '.part', '.tmp', '.!qb', '.crdownload', '.download'}
CHINESE = re.compile(r'(?:^|[._\s-])(?:zh(?:-cn|-tw|-hans|-hant)?|zho|chi|cmn|chs|cht)(?:$|[._\s-])|中文|简体|繁体|簡體|繁體|chinese', re.I)


def map_path(path, mappings):
    for source, dest in sorted(mappings.items(), key=lambda x: len(x[0]), reverse=True):
        if path == source or path.startswith(source.rstrip('/') + '/'):
            return dest.rstrip('/') + path[len(source.rstrip('/')):]
    return path


def fingerprint(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns]


def ready_file(path, previous, *, now, quiet_seconds):
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        return False, '等待视频文件完整可读'
    if any(part.startswith('.') or part.lower() in {'tmp', 'temp', 'incomplete', 'vtrans-staging'} for part in path.parts):
        return False, '暂存目录中的文件不处理'
    if any(Path(str(path) + suffix).exists() for suffix in ['.!qB', '.part', '.partial', '.tmp', '.crdownload']):
        return False, '检测到下载或上传临时文件'
    if not previous or previous.get('fingerprint') != fingerprint(path):
        return False, '文件发生变化，等待稳定'
    if now - previous.get('stable_since', now) < quiet_seconds:
        return False, '等待上传或下载完成后的稳定窗口'
    return True, ''


def chinese_track(stream):
    tags = stream.get('tags') or {}
    return (stream.get('codec_type') == 'subtitle'
            and not (stream.get('disposition') or {}).get('forced')
            and bool(CHINESE.search(str(tags.get('language','')) + ' ' + str(tags.get('title','')))))


def chinese_audio_only(streams):
    """Skip only unambiguous Chinese audio; unknown or multilingual audio needs checking."""
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    languages = {'zh', 'zho', 'chi', 'cmn', 'yue', 'wuu', 'nan', 'hak'}
    return bool(audio) and all(
        str((s.get('tags') or {}).get('language', '')).lower().split('-')[0] in languages
        for s in audio
    )


def subtitle_files(video):
    video = Path(video)
    return [p for p in video.parent.iterdir() if p.is_file()
            and p.suffix.lower() in SUBTITLE_EXTENSIONS
            and (p.stem == video.stem or p.name.startswith(video.stem + '.'))]


def chinese_sidecar(path):
    path = Path(path)
    if re.search(r'(?:^|[. _-])(?:forced|foreign)(?:$|[. _-])', path.name, re.I):
        return False
    if not path.stat().st_size:
        return False
    if CHINESE.search(path.name):
        return True
    if path.suffix.lower() in {'.srt','.ass','.ssa','.vtt'}:
        raw = path.read_bytes()[:131072]
        for encoding in ['utf-8-sig','utf-16','gb18030','big5']:
            try:
                value = raw.decode(encoding)
                if re.search(r'[\u3040-\u30ff]', value):
                    return False
                if len(re.findall(r'[\u3400-\u9fff]', value)) >= 8:
                    return True
                break
            except UnicodeError:
                pass
    return False


def vtrans_blockers(rows, mappings):
    blocked = {}
    for row in rows:
        server = row.get('server') or {}
        terminal = row.get('state') in {'完成','取消','失败','completed','cancelled','failed'}
        if terminal and not server.get('pending') and not server.get('downloadStopPending'):
            continue
        if server.get('replace') and isinstance(row.get('source'),str):
            blocked[map_path(str(Path(row['source']).with_suffix('.mkv')),mappings)]='VTrans：等待最终文件发布'
        for field in ['source','output']:
            value = row.get(field)
            if isinstance(value,str) and value.startswith('/'):
                blocked[map_path(value,mappings)] = 'VTrans：' + str(row.get('state','等待发布'))
    return blocked
