"""Small, authenticated-library artwork cache; upstream URLs are never user supplied."""
from collections import OrderedDict
from dataclasses import dataclass
import json
import re
import threading
import time
from urllib.parse import urlencode

import httpx


_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_TAG = re.compile(r'[A-Za-z0-9_-]{1,160}\Z')
_TMDB_PATH = re.compile(r'/[A-Za-z0-9_-]{1,200}\.(?:jpg|jpeg|png|webp)\Z', re.I)
MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _safe(value, pattern):
    return value if isinstance(value, str) and pattern.fullmatch(value) else ''


def _descriptor(value):
    if not isinstance(value, dict):
        return None
    identity, tag = _safe(value.get('id'), _ID), _safe(value.get('tag'), _TAG)
    return {'id': identity, 'tag': tag} if identity and tag else None


def emby_artwork(item, fallback_id=''):
    """Retain image references already supplied with Emby's movie/series DTO."""
    result = {}
    identity = str(item.get('Id') or fallback_id)
    tags = item.get('ImageTags')
    tags = tags if isinstance(tags, dict) else {}
    primary = _descriptor({'id': identity, 'tag': tags.get('Primary')})
    if primary:
        result['poster'] = primary
    backdrops = item.get('BackdropImageTags')
    backdrops = backdrops if isinstance(backdrops, list) else []
    backdrop_id = identity
    if not backdrops:
        backdrops = item.get('ParentBackdropImageTags')
        backdrops = backdrops if isinstance(backdrops, list) else []
        backdrop_id = str(item.get('ParentBackdropItemId') or '')
    backdrop = _descriptor({'id': backdrop_id, 'tag': backdrops[0] if backdrops else None})
    if backdrop:
        result['backdrop'] = backdrop
    return result


def _metadata(row):
    value = row.get('metadata')
    return value if isinstance(value, dict) else {}


def _tmdb_paths(row):
    metadata = _metadata(row)
    paths = {kind: _safe(metadata.get(kind + '_path'), _TMDB_PATH) for kind in ('poster', 'backdrop')}
    if row.get('project_id') and not all(paths.values()):
        from app.utils.project_store import load_project
        try:
            # Validates the ID and project containment; never join a supplied path.
            project = load_project(row['project_id'])
        except (ValueError, OSError, RuntimeError):
            project = {}
        for kind in paths:
            paths[kind] = paths[kind] or _safe(project.get(kind + '_path'), _TMDB_PATH)
    return paths


def artwork_links(row):
    metadata = _metadata(row)
    known = metadata.get('emby_artwork')
    legacy = 'emby_artwork' not in metadata and bool(_safe(metadata.get('emby_id'), _ID))
    known = known if isinstance(known, dict) else {}
    available = {kind: legacy or bool(_descriptor(known.get(kind)))
                 for kind in ('poster', 'backdrop')}
    paths = {} if all(available.values()) else _tmdb_paths(row)
    return {kind + '_url': '/api/library/artwork?' + urlencode({'path': row['path'], 'kind': kind})
            if available[kind] or paths.get(kind) else None for kind in available}


def tmdb_image_client():
    # The configured server proxy may be needed for TMDB; Emby uses its separate LAN client.
    return httpx.Client(timeout=8, follow_redirects=False, trust_env=True)


@dataclass(frozen=True)
class ArtworkImage:
    content: bytes
    media_type: str


class Artwork:
    def __init__(self, sources):
        self.sources = sources
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.max_cache_bytes = 16 * 1024 * 1024
        self.max_cache_entries = 48
        self.lock = threading.Lock()
        self.inflight = {}

    def get(self, row, kind):
        if kind not in {'poster', 'backdrop'}:
            return None
        metadata = _metadata(row)
        paths = _tmdb_paths(row)
        key = json.dumps([kind, metadata.get('emby_id'), metadata.get('emby_artwork'), paths[kind]], sort_keys=True)
        with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                self.cache.move_to_end(key)
                return cached[1]
            waiting = self.inflight.get(key)
            if waiting is None:
                self.inflight[key] = threading.Event()
        if waiting is not None:
            # Do not duplicate a cold fetch, or hold the global cache lock during I/O.
            waiting.wait(10)
            with self.lock:
                cached = self.cache.get(key)
                return cached[1] if cached and cached[0] > time.monotonic() else None
        image = None
        try:
            image = self._load(row, kind, paths[kind])
        finally:
            with self.lock:
                previous = self.cache.pop(key, None)
                if previous and previous[1]:
                    self.cache_bytes -= len(previous[1].content)
                self.cache[key] = (time.monotonic() + (600 if image else 30), image)
                if image:
                    self.cache_bytes += len(image.content)
                while len(self.cache) > self.max_cache_entries or self.cache_bytes > self.max_cache_bytes:
                    _, (_, evicted) = self.cache.popitem(last=False)
                    if evicted:
                        self.cache_bytes -= len(evicted.content)
                self.inflight.pop(key).set()
        return image

    def _load(self, row, kind, tmdb_path):
        metadata = _metadata(row)
        config = self.sources.config.get('emby') or {}
        try:
            references = metadata.get('emby_artwork')
            if 'emby_artwork' not in metadata and _safe(metadata.get('emby_id'), _ID) and config:
                # Reuse existing scanner metadata, but do not add every browsed
                # episode to its long-lived cache. Our bounded image cache owns this lookup.
                item = self._item(metadata['emby_id'])
                if item.get('Type') == 'Episode' and _safe(str(item.get('SeriesId', '')), _ID):
                    item = self._item(str(item['SeriesId']))
                references = emby_artwork(item)
            reference = _descriptor(references.get(kind)) if isinstance(references, dict) else None
            if reference and config:
                image_type = 'Primary' if kind == 'poster' else 'Backdrop/0'
                url = config['url'].rstrip('/') + '/Items/' + reference['id'] + '/Images/' + image_type
                image = self._request(self.sources.client, url,
                    headers={'X-Emby-Token': config['token']},
                    params={'MaxWidth': 500 if kind == 'poster' else 1280, 'Quality': 85, 'Tag': reference['tag']})
                if image:
                    return image
        except (httpx.HTTPError, OSError, ValueError, KeyError):
            pass
        if tmdb_path:
            try:
                with tmdb_image_client() as client:
                    size = 'w500' if kind == 'poster' else 'w1280'
                    return self._request(client, 'https://image.tmdb.org/t/p/' + size + tmdb_path)
            except (httpx.HTTPError, OSError, ValueError):
                pass
        return None

    def _item(self, identity):
        cached = self.sources.emby_cache.get(identity)
        if isinstance(cached, dict):
            return cached
        items = self.sources.emby('/Items', Ids=identity, Fields='ProviderIds,Overview').get('Items', [])
        return items[0] if items and isinstance(items[0], dict) else {}

    @staticmethod
    def _request(client, url, **kwargs):
        with client.stream('GET', url, follow_redirects=False, timeout=8, **kwargs) as response:
            if response.status_code != 200:
                return None
            media_type = response.headers.get('content-type', '').split(';', 1)[0].lower()
            if media_type not in {'image/jpeg', 'image/png', 'image/webp'}:
                return None
            size = response.headers.get('content-length')
            if size and int(size) > MAX_IMAGE_BYTES:
                return None
            content = bytearray()
            for chunk in response.iter_bytes(65536):
                if len(content) + len(chunk) > MAX_IMAGE_BYTES:
                    return None
                content.extend(chunk)
            valid = ((media_type == 'image/jpeg' and content.startswith(b'\xff\xd8\xff'))
                     or (media_type == 'image/png' and content.startswith(b'\x89PNG\r\n\x1a\n'))
                     or (media_type == 'image/webp' and content[:4] == b'RIFF' and content[8:12] == b'WEBP'))
            return ArtworkImage(bytes(content), media_type) if valid else None
