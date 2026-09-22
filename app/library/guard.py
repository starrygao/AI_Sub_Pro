"""Pure readiness rules, shared by discovery and the final publication gate."""
from pathlib import Path
import re

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.m4v', '.ts', '.m2ts', '.webm'}
SUBTITLE_EXTENSIONS = {'.srt', '.ass', '.ssa', '.vtt', '.sub', '.idx', '.sup'}
TEMP_MARKERS = {'.parts', '.partial', '.part', '.tmp', '.!qb', '.crdownload', '.download'}
CHINESE = re.compile(r'(?<![a-z0-9])(?:zh(?:[-_](?:cn|tw|hans|hant))?|zho|chi|cmn|yue|wuu|nan|hak|chs|cht|chinese)(?![a-z0-9])|中文|简体|繁体|簡體|繁體', re.I)
CHINESE_LANGUAGES = {'zh', 'zho', 'chi', 'cmn', 'yue', 'wuu', 'nan', 'hak'}
PARTIAL_SUBTITLE = re.compile(r'(?<![a-z0-9])(?:forced|foreign|commentary)(?![a-z0-9])|强制|強制|导评|導評', re.I)
COMMENTARY = re.compile(r'(?<![a-z0-9])commentary(?![a-z0-9])|导评|導評', re.I)
UNKNOWN_LANGUAGES = {'', 'und', 'unknown', 'mul'}


def stream_tags(stream):
    return {str(k).lower(): str(v) for k, v in (stream.get('tags') or {}).items()}


def language_code(stream):
    return re.split('[-_]', stream_tags(stream).get('language', '').lower())[0]


def subtitle_label(value, video=None, *, filename=False):
    """Classify subtitle labels, never words belonging to the video's own title."""
    value = Path(value).stem if filename else str(value).strip()
    if video is not None:
        stem = Path(video).stem
        if value.casefold() == stem.casefold():
            return ''
        if value.casefold().startswith(stem.casefold()) and value[len(stem):len(stem)+1] in '._ []()-':
            return value[len(stem):].lstrip('._ []()-')
    return value


def complete_subtitle_stream(stream, video=None):
    disposition = stream.get('disposition') or {}
    return (stream.get('codec_type') == 'subtitle'
            and not disposition.get('forced') and not disposition.get('comment')
            and not PARTIAL_SUBTITLE.search(subtitle_label(stream_tags(stream).get('title', ''), video)))


def complete_sidecar(path, video=None):
    return not PARTIAL_SUBTITLE.search(subtitle_label(Path(path).name, video, filename=True))


def dialogue_audio(stream):
    return (stream.get('codec_type') == 'audio'
            and not (stream.get('disposition') or {}).get('comment')
            and not COMMENTARY.search(stream_tags(stream).get('title', '')))


def select_audio_track(streams):
    """Return an AUDIO-relative index for ffmpeg's 0:a:N, not a global stream index."""
    audio = [stream for stream in streams if stream.get('codec_type') == 'audio']
    usable = [(index, stream) for index, stream in enumerate(audio) if dialogue_audio(stream)]
    if not usable:
        return None
    def priority(item):
        index, stream = item
        language = language_code(stream)
        disposition = stream.get('disposition') or {}
        return (language in CHINESE_LANGUAGES, not disposition.get('original'),
                language in UNKNOWN_LANGUAGES, not disposition.get('default'), index)
    return min(usable, key=priority)[0]


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


def chinese_track(stream, video=None):
    tags = stream_tags(stream)
    return (complete_subtitle_stream(stream, video)
            and bool(CHINESE.search(tags.get('language', '') + ' ' + subtitle_label(tags.get('title', ''), video))))


def chinese_subtitle_attachment(stream, video=None):
    """Recognize explicitly labelled text-subtitle attachments without extracting them."""
    if stream.get('codec_type') != 'attachment':
        return False
    tags = stream_tags(stream)
    filename = tags.get('filename', '')
    if Path(filename).suffix.lower() not in {'.srt', '.ass', '.ssa', '.vtt'}:
        return False
    if tags.get('mimetype', '').lower() not in {
        'application/x-subrip', 'application/x-srt', 'text/srt', 'text/plain',
        'application/x-ass', 'application/x-ssa', 'text/x-ass', 'text/x-ssa', 'text/vtt',
    }:
        return False
    if not stream.get('extradata_size') or (stream.get('disposition') or {}).get('forced'):
        return False
    label = subtitle_label(filename, video, filename=True) + ' ' + subtitle_label(tags.get('title', ''), video)
    return not PARTIAL_SUBTITLE.search(label) and bool(CHINESE.search(tags.get('language', '') + ' ' + label))


def chinese_audio_only(streams):
    """Skip only unambiguous Chinese audio; unknown or multilingual audio needs checking."""
    audio = [s for s in streams if dialogue_audio(s)]
    return bool(audio) and all(
        language_code(s) in CHINESE_LANGUAGES
        for s in audio
    )


def has_foreign_audio(streams):
    return any(language_code(s) not in CHINESE_LANGUAGES | UNKNOWN_LANGUAGES
               for s in streams if dialogue_audio(s))


def subtitle_files(video):
    video = Path(video)
    return [p for p in video.parent.iterdir() if p.is_file()
            and p.suffix.lower() in SUBTITLE_EXTENSIONS
            and (p.stem == video.stem or p.name.startswith(video.stem + '.'))]


def chinese_sidecar(path, video=None):
    path = Path(path)
    if not complete_sidecar(path, video):
        return False
    if not path.stat().st_size:
        return False
    if CHINESE.search(subtitle_label(path.name, video, filename=True)):
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
