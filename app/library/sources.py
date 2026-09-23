"""Read-only integrations. Unavailable readiness sources fail closed."""
import json
import sqlite3
import time
from pathlib import Path
import xml.etree.ElementTree as ET
import httpx
from .guard import map_path, vtrans_blockers
from .artwork import Artwork, emby_artwork


def emby_metadata(item, get_item):
    episode = item.get('Type') == 'Episode'
    identity = get_item(item['SeriesId']) if episode and item.get('SeriesId') else item
    raw = (identity.get('ProviderIds') or {}).get('Tmdb')
    result = {'name': item.get('Name',''), 'emby_id':str(item.get('Id','')),
              'season_number':item.get('ParentIndexNumber'), 'episode_number':item.get('IndexNumber'),
              'show_title':identity.get('Name',''), 'overview':item.get('Overview') or identity.get('Overview',''),'date_created':item.get('DateCreated','')}
    result['emby_artwork'] = emby_artwork(identity, item.get('SeriesId') if episode else item.get('Id'))
    if str(raw).isdigit():
        result.update(tmdb_id=int(raw),tmdb_type='tv' if episode else 'movie',metadata_source='emby')
    return result


def pending_download_paths(torrents, get_files, mappings):
    paths = set()
    for torrent in torrents:
        state = str(torrent.get('state','')).lower()
        if float(torrent.get('progress',0)) >= 1 and not any(x in state for x in ['check','moving','error','missing']):
            continue
        content=torrent.get('content_path')
        if isinstance(content,str) and content.startswith('/'):
            paths.add(map_path(content,mappings))
            continue
        for file in get_files(torrent['hash']):
            paths.add(map_path(str(Path(torrent['save_path']) / file['name']),mappings))
    return paths


class Sources:
    def __init__(self, config):
        self.config=config
        self.client=httpx.Client(timeout=15,trust_env=False)
        self.health={}
        self.emby_cache={}
        self.language_cache={}
        self.artwork=Artwork(self)

    def emby(self, endpoint, **params):
        conf=self.config['emby']
        r=self.client.get(conf['url'].rstrip('/')+endpoint,params=params,headers={'X-Emby-Token':conf['token']})
        r.raise_for_status()
        return r.json()

    def item(self, item_id):
        if item_id not in self.emby_cache:
            items=self.emby('/Items',Ids=str(item_id),Fields='ProviderIds,Overview').get('Items',[])
            if not items:raise RuntimeError('Emby 系列信息暂不可用')
            self.emby_cache[item_id]=items[0]
        return self.emby_cache[item_id]

    def libraries(self):
        return [map_path(p,self.config.get('path_maps',{}))
                for lib in self.emby('/Library/VirtualFolders') for p in lib.get('Locations',[])
                if lib.get('CollectionType') in {'movies','tvshows','mixed',None} and not p.startswith('/config')]

    def recent(self, start=0, limit=100):
        payload=self.emby('/Items', Recursive='true',IncludeItemTypes='Movie,Episode',
                         SortBy='DateCreated',SortOrder='Descending',StartIndex=start,Limit=limit,
                         Fields='Path,ProviderIds,MediaStreams,DateCreated,Overview')
        results=[]
        for item in payload.get('Items',[]):
            if item.get('Path','').startswith('/'):
                results.append((map_path(item['Path'],self.config.get('path_maps',{})),emby_metadata(item,self.item)))
        return results,int(payload.get('TotalRecordCount',0))

    def recent_transfers(self):
        """MoviePilot arrivals can precede Emby import; status is still checked by readiness."""
        conf=self.config.get('moviepilot')
        if not conf:return []
        db=sqlite3.connect('file:'+conf['database']+'?mode=ro',uri=True,timeout=3)
        try:
            rows=db.execute('SELECT dest,media_id,type,title,media_source FROM transferhistory WHERE status=1 AND dest IS NOT NULL ORDER BY id DESC LIMIT 200').fetchall()
            result=[]
            for path,identity,kind,title,source in rows:
                if not isinstance(path,str) or not path.startswith('/'):continue
                meta={'show_title':title,'metadata_source':'moviepilot'}
                if source in {'tmdb','themoviedb'} and str(identity).isdigit():
                    meta.update(tmdb_id=int(identity),tmdb_type='tv' if kind in {'电视剧','tv','TV'} else 'movie')
                result.append((map_path(path,conf.get('path_maps',{})),meta))
            return result
        finally:db.close()

    def readiness(self):
        blocked={}
        self.health={}
        writers=self.config.get('open_writes')
        if writers:
            snapshot=json.loads(Path(writers['file']).read_text())
            if not snapshot.get('ok') or time.time()-snapshot.get('updated',0)>40:
                raise RuntimeError('上传写入检测不可用或已过期')
            blocked.update({map_path(p,writers.get('path_maps',{})):'视频仍被上传或写入进程打开' for p in snapshot['paths']})
            self.health['uploads']={'ok':True,'open_files':len(snapshot['paths'])}
        sessions=self.emby('/Sessions')
        self.health['emby']={'ok':True,'playing':sum(bool(x.get('NowPlayingItem')) for x in sessions),
                             'transcoding':sum(bool(x.get('TranscodingInfo')) for x in sessions)}
        for conf in self.config.get('qbittorrent',[]):
            name=conf['name'];base=conf['url'].rstrip('/')
            with httpx.Client(timeout=15,trust_env=False) as client:
                r=client.post(base+'/api/v2/auth/login',data={'username':conf['username'],'password':conf['password']})
                r.raise_for_status()
                if r.text.strip()!='Ok.':raise RuntimeError(name+' 登录失败')
                def get(route,**params):
                    r=client.get(base+'/api/v2/'+route,params=params);r.raise_for_status();return r.json()
                paths=pending_download_paths(get('torrents/info'),lambda h:get('torrents/files',hash=h),conf.get('path_maps',{}))
                blocked.update({p:name+'：下载或校验尚未完成' for p in paths})
                self.health[name]={'ok':True,'pending_files':len(paths)}
        conf=self.config.get('transmission')
        if conf:
            with httpx.Client(timeout=15,trust_env=False,auth=(conf['username'],conf['password'])) as client:
                body={'method':'torrent-get','arguments':{'fields':['downloadDir','percentDone','status','files']}}
                r=client.post(conf['url'],json=body)
                if r.status_code==409:
                    r=client.post(conf['url'],json=body,headers={'X-Transmission-Session-Id':r.headers['X-Transmission-Session-Id']})
                r.raise_for_status(); payload=r.json()
                if payload.get('result')!='success':raise RuntimeError('Transmission 状态不可用')
                for row in payload['arguments']['torrents']:
                    if row['percentDone']<1 or row['status'] in {1,2}:
                        for f in row['files']:
                            p=map_path(str(Path(row['downloadDir'])/f['name']),conf.get('path_maps',{}))
                            blocked[p]='Transmission：下载或校验尚未完成'
                self.health['transmission']={'ok':True}
        conf=self.config.get('moviepilot')
        if conf:
            db=sqlite3.connect('file:'+str(Path(conf['database']))+'?mode=ro',uri=True,timeout=3)
            try:
                rows=db.execute("SELECT src_path FROM transferpending WHERE state NOT IN ('completed','failed','cancelled','done','success')").fetchall()
                for (path,) in rows:
                    blocked[map_path(path,conf.get('path_maps',{}))]='MoviePilot：等待整理完成'
                self.health['moviepilot']={'ok':True,'pending_files':len(rows)}
            finally:db.close()
        conf=self.config.get('vtrans')
        if conf:
            rows=json.loads(Path(conf['queue']).read_text())
            blocked.update(vtrans_blockers(rows,conf.get('path_maps',{})))
            self.health['vtrans']={'ok':True,'tasks':len(rows),'pending_files':len(vtrans_blockers(rows,conf.get('path_maps',{})))}
        return blocked

    def download_source(self, video):
        conf=self.config.get('moviepilot')
        if not conf:return ''
        reverse={v:k for k,v in conf.get('path_maps',{}).items()}
        db=sqlite3.connect('file:'+conf['database']+'?mode=ro',uri=True,timeout=3)
        try:
            row=db.execute('SELECT src FROM transferhistory WHERE dest=? AND status=1 ORDER BY id DESC LIMIT 1',(map_path(str(video),reverse),)).fetchone()
            return map_path(row[0],conf.get('path_maps',{})) if row else ''
        finally:db.close()

    def metadata(self, video):
        # MoviePilot writes canonical identities to NFO beside the final video.
        video=Path(video)
        for p,kind in [(video.with_suffix('.nfo'),'movie'),(video.parent/'tvshow.nfo','tv'),(video.parent.parent/'tvshow.nfo','tv')]:
            if not p.is_file() or p.stat().st_size>2_000_000:continue
            try:
                root=ET.parse(p).getroot()
                if root.tag=='episodedetails':continue  # episode TMDB is not the series ID
                raw=root.findtext('tmdbid') or next((e.text for e in root.findall('uniqueid') if e.get('type')=='tmdb'),None)
                if raw and raw.isdigit():return {'tmdb_id':int(raw),'tmdb_type':kind,'show_title':root.findtext('title',''),'metadata_source':'nfo'}
            except (OSError,ET.ParseError):continue
        conf=self.config.get('moviepilot')
        if conf:
            # Restrict the read to one matching destination; never mutate MoviePilot's DB.
            reverse={v:k for k,v in conf.get('path_maps',{}).items()}
            path=map_path(str(video),reverse)
            db=sqlite3.connect('file:'+conf['database']+'?mode=ro',uri=True,timeout=3)
            try:
                row=db.execute("SELECT media_id,type,title FROM transferhistory WHERE dest=? AND media_source IN ('tmdb','themoviedb') AND status=1 ORDER BY id DESC LIMIT 1",(path,)).fetchone()
                if row and str(row[0]).isdigit():
                    return {'tmdb_id':int(row[0]),'tmdb_type':'tv' if row[1] in {'电视剧','tv','TV'} else 'movie','show_title':row[2],'metadata_source':'moviepilot'}
            finally:db.close()
        return {}

    def original_language(self,metadata):
        identity=(metadata.get('tmdb_type'),metadata.get('tmdb_id'))
        if identity[0] not in {'tv','movie'} or not identity[1]:return ''
        if identity not in self.language_cache:
            import asyncio
            from app.engines.tmdb import get_show_details
            detail=asyncio.run(get_show_details(identity[1],identity[0]))
            self.language_cache[identity]=str(detail.get('original_language','')).lower()
        return self.language_cache[identity]

    def refresh_subtitles(self,item_id):
        if not item_id:return
        conf=self.config['emby']
        r=self.client.post(conf['url'].rstrip('/')+'/Items/'+item_id+'/Refresh',
            headers={'X-Emby-Token':conf['token']},params={'Recursive':'false','MetadataRefreshMode':'Default','ImageRefreshMode':'Default','ReplaceAllMetadata':'false','ReplaceAllImages':'false'})
        r.raise_for_status()
