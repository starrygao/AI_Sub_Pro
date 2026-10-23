"""Authenticated Emby browsing and explicit, guarded requests for existing media."""
from pathlib import Path
import re
import time

from .guard import VIDEO_EXTENSIONS, fingerprint, map_path
from .sources import emby_metadata
from .publish import bilingual_sidecar_path

ITEM_ID = r'[A-Za-z0-9_-]{1,80}'
FIELDS = 'Path,ProviderIds,MediaStreams,DateCreated,Overview,ProductionYear'


class EmbySelection:
    def __init__(self, worker):
        self.worker = worker

    def path(self, item):
        raw = item.get('Path', '')
        if item.get('Type') not in {'Movie', 'Episode'} or not isinstance(raw, str) or not raw.startswith('/'):
            return None
        path = Path(map_path(raw, self.worker.config.get('path_maps', {})))
        if '..' in path.parts or path.suffix.lower() not in VIDEO_EXTENSIONS:
            return None
        # The video target and its sidecar's parent must both be in mounted media roots.
        roots = self.worker.config.get('allowed_roots', self.worker.roots)
        if not any(path.is_relative_to(Path(root)) for root in roots):
            return None
        if not self.worker.allowed(path) or not path.is_file():
            return None
        return path

    def describe(self, item):
        path = self.path(item)
        existing = self.worker.store.get(path) if path else None
        reopenable = existing and (existing['state']=='deleted' or (existing['state']=='historical' and not existing.get('project_id')))
        streams = item.get('MediaStreams') or []
        languages = lambda kind: list(dict.fromkeys(str(s.get('Language') or 'und') for s in streams if s.get('Type') == kind))
        result = {'id': str(item.get('Id', '')), 'name': item.get('Name') or '未命名',
                  'type': item.get('Type'), 'year': item.get('ProductionYear'),
                  'series_name': item.get('SeriesName'), 'season': item.get('ParentIndexNumber'),
                  'episode': item.get('IndexNumber'), 'audio_languages': languages('Audio'),
                  'subtitle_languages': languages('Subtitle'),
                  'selectable': bool(path and (not existing or reopenable)), 'state': existing.get('state') if existing else None,
                  'reason': ('可手动添加后重新检测' if reopenable else
                             '已有任务记录，请在原记录查看或重新检查' if existing else
                             '' if path or item.get('Type') == 'Series' else '文件未挂载、不可读或不是本地视频'),
                  'path': map_path(str(path), self.worker.config.get('host_path_maps', {})) if path else ''}
        return result

    def search(self, query, *, kind='all', offset=0, limit=30):
        query = query.strip()
        if not query: raise ValueError('请输入电影或剧集名称')
        types = {'all': 'Movie,Series', 'movie': 'Movie', 'series': 'Series'}
        payload = self.worker.sources.emby('/Items', SearchTerm=query, Recursive='true',
            IncludeItemTypes=types[kind], StartIndex=offset, Limit=limit, Fields=FIELDS,
            EnableUserData='false', EnableImages='false', EnableTotalRecordCount='true')
        return self.page(payload, offset, limit)

    def episodes(self, series_id, *, offset=0, limit=30):
        payload = self.worker.sources.emby('/Items', Ids=series_id, Fields='Path')
        series = next((i for i in payload.get('Items', []) if str(i.get('Id')) == series_id and i.get('Type') == 'Series'), None)
        if not series: raise ValueError('剧集不存在，请重新搜索')
        payload = self.worker.sources.emby('/Items', ParentId=series_id, Recursive='true',
            IncludeItemTypes='Episode', SortBy='ParentIndexNumber,IndexNumber,SortName', SortOrder='Ascending',
            StartIndex=offset, Limit=limit, Fields=FIELDS, EnableUserData='false', EnableImages='false',
            EnableTotalRecordCount='true')
        result = self.page(payload, offset, limit)
        result['series'] = {'id': series_id, 'name': series.get('Name') or '剧集'}
        return result

    def page(self, payload, offset, limit):
        raw = payload.get('Items', [])
        seen = offset + len(raw)
        reported = int(payload.get('TotalRecordCount') or 0)
        counted = reported >= seen and reported > 0
        return {'items': [self.describe(i) for i in raw
                          if i.get('Type') in {'Movie', 'Series', 'Episode'} and re.fullmatch(ITEM_ID, str(i.get('Id', '')))],
                'total': max(reported, seen), 'total_is_exact': counted or len(raw) < limit,
                'has_more': reported > seen if counted else len(raw) >= limit,
                'offset': offset, 'limit': limit}

    def enqueue(self, ids):
        # Re-fetch trusted paths at submission time. Browser paths / stream hints are never authoritative.
        ids = list(dict.fromkeys(ids))
        payload = self.worker.sources.emby('/Items', Ids=','.join(ids), Fields=FIELDS)
        items = {str(i.get('Id')): i for i in payload.get('Items', [])}
        results = []
        for item_id in ids:
            try:
                item = items.get(item_id, {})
                path = self.path(item)
                if not path:
                    results.append({'id': item_id, 'status': 'unavailable', 'message': '条目已移走、未挂载或不是可读取的本地视频'})
                    continue
                now = time.time()
                row = {'path': str(path), 'state': 'waiting', 'reason': '手动添加：等待文件稳定及音轨、字幕检查',
                       'fingerprint': fingerprint(path), 'stable_since': now, 'updated': now, 'priority': 1,
                       'manual_requested': True, 'manual_requested_at': now,
                       'metadata': emby_metadata(item, self.worker.sources.item), 'output_path': str(bilingual_sidecar_path(path))}
                actual, inserted = self.worker.store.insert_request(row)
                results.append({'id': item_id, 'status': 'queued' if inserted else 'existing',
                                'state': actual['state'], 'message': '已加入待检测，确认需要翻译后排队' if inserted else '已有任务记录，未重复添加'})
            except Exception as exc:
                results.append({'id': item_id, 'status': 'error', 'message': self.worker.safe_error(exc)})
        self.worker.wake.set()
        return {'items': results, 'enabled': self.worker.store.setting('enabled', self.worker.config.get('enabled', False))}
