from app.library.sources import emby_metadata, pending_download_paths
from unittest.mock import Mock

import pytest


def test_episode_tmdb_uses_series_id_not_episode_id():
    item={'Type':'Episode','ProviderIds':{'Tmdb':'900'},'SeriesId':'series','ParentIndexNumber':2,'IndexNumber':3}
    value=emby_metadata(item, lambda _:{'Name':'Example','ProviderIds':{'Tmdb':'100'}})
    assert value['tmdb_id']==100
    assert value['season_number']==2
    assert value['episode_number']==3


def test_incomplete_and_checking_torrents_block_files_but_seeding_does_not():
    torrents=[{'hash':'a','progress':.99,'state':'pausedDL','save_path':'/pt'},
              {'hash':'b','progress':1,'state':'checkingUP','save_path':'/video'},
              {'hash':'c','progress':1,'state':'stalledUP','save_path':'/video'}]
    paths=pending_download_paths(torrents, lambda h:[{'name':h+'.mkv'}], {'/pt':'/video/pt'})
    assert paths=={'/video/pt/a.mkv','/video/b.mkv'}


@pytest.mark.parametrize('state',['downloading','forcedDL','stalledDL','pausedDL','queuedDL'])
def test_completed_episode_is_not_blocked_by_incomplete_season(state):
    torrents=[{'hash':'season','content_path':'/pt/Season','save_path':'/pt','progress':.36,'state':state}]
    files=[{'name':'Season/Episode02.mkv','progress':1,'priority':1},
           {'name':'Season/Episode03.mkv','progress':.1,'priority':1},
           {'name':'Season/Episode04.mkv','progress':0,'priority':0}]
    paths=pending_download_paths(torrents,lambda _:files,{'/pt':'/video/downloads'})
    assert paths=={'/video/downloads/Season/Episode03.mkv','/video/downloads/Season/Episode04.mkv'}


@pytest.mark.parametrize('state',['checkingUP','checkingDL','checkingResumeData','moving','error','missingFiles'])
def test_unsafe_torrent_state_still_blocks_whole_content_even_if_files_complete(state):
    torrents=[{'hash':'season','content_path':'/pt/Season','save_path':'/pt','progress':1,'state':state}]
    get_files=Mock(return_value=[{'name':'Season/Episode02.mkv','progress':1}])
    assert pending_download_paths(torrents,get_files,{'/pt':'/video/downloads'})=={'/video/downloads/Season'}
    get_files.assert_not_called()


def test_completed_torrent_needs_no_file_api_call():
    torrents=[{'hash':'season','content_path':'/pt/Season','save_path':'/pt','progress':1,'state':'stalledUP'}]
    get_files=Mock(side_effect=AssertionError('finished torrent does not need per-file status'))
    assert pending_download_paths(torrents,get_files,{},candidates=['/pt/Season/Episode02.mkv'])==set()
    get_files.assert_not_called()


def test_failed_file_status_lookup_cannot_release_completed_episode():
    torrents=[{'hash':'season','content_path':'/pt/Season','save_path':'/pt','progress':.36,'state':'downloading'}]
    with pytest.raises(RuntimeError,match='unavailable'):
        pending_download_paths(torrents,Mock(side_effect=RuntimeError('file status unavailable')), {})


def test_file_lookup_is_limited_to_candidate_torrents_and_others_stay_blocked():
    torrents=[{'hash':name,'content_path':'/pt/'+name,'save_path':'/pt','progress':.5,'state':'downloading'} for name in ['Relevant','Other']]
    get_files=Mock(return_value=[{'name':'Relevant/Episode02.mkv','progress':1}, {'name':'Relevant/Episode03.mkv','progress':0}])
    paths=pending_download_paths(torrents,get_files,{'/pt':'/video/downloads'},candidates=['/video/downloads/Relevant/Episode02.mkv'])
    assert paths=={'/video/downloads/Relevant/Episode03.mkv','/video/downloads/Other'}
    get_files.assert_called_once_with('Relevant')
    get_files.reset_mock()
    assert pending_download_paths(torrents,get_files,{},candidates=[])=={'/pt/Relevant','/pt/Other'}
    get_files.assert_not_called()


def test_empty_file_status_response_keeps_torrent_blocked():
    torrents=[{'hash':'season','content_path':'/pt/Season','save_path':'/pt','progress':.36,'state':'downloading'}]
    assert pending_download_paths(torrents,lambda _:[],{})=={'/pt/Season'}


def test_readiness_without_qb_does_not_query_download_history(tmp_path,monkeypatch):
    import sqlite3
    from app.library.sources import Sources
    database=tmp_path/'moviepilot.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE transferpending(src_path TEXT, state TEXT)')
    source=Sources({'moviepilot':{'database':str(database)}})
    source.client.close()
    monkeypatch.setattr(source,'emby',lambda *_:[])
    assert source.readiness(candidates=['/library/Episode02.mkv'])=={}


@pytest.mark.parametrize('protector',['uploads','moviepilot','vtrans'])
def test_completed_qb_episode_keeps_other_readiness_protections(tmp_path,monkeypatch,protector):
    import json
    import sqlite3
    import time
    import httpx
    from app.library.sources import Sources
    database=tmp_path/'moviepilot.sqlite3'
    target='/library/Episode02.mkv';original='/downloads/Season/Episode02.mkv'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE transferhistory(id INTEGER, src TEXT, dest TEXT, status INTEGER)')
        db.execute('INSERT INTO transferhistory VALUES(1,?,?,1)',(original,target))
        db.execute('CREATE TABLE transferpending(src_path TEXT, state TEXT)')
        if protector=='moviepilot':db.execute('INSERT INTO transferpending VALUES(?,?)',(original,'pending'))
    config={'qbittorrent':[{'name':'qB','url':'http://fixture-qb','username':'fixture','password':'fixture'}],
            'moviepilot':{'database':str(database)}}
    if protector=='uploads':
        snapshot=tmp_path/'writers.json';snapshot.write_text(json.dumps({'ok':True,'updated':time.time(),'paths':[original]}))
        config['open_writes']={'file':str(snapshot)}
    if protector=='vtrans':
        queue=tmp_path/'vtrans.json';queue.write_text(json.dumps([{'source':original,'state':'转码中'}]))
        config['vtrans']={'queue':str(queue)}
    calls=[]
    def api(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/auth/login'):return httpx.Response(200,text='Ok.')
        if request.url.path.endswith('/torrents/info'):return httpx.Response(200,json=[{'hash':'season','content_path':'/downloads/Season','save_path':'/downloads','progress':.36,'state':'downloading'}])
        return httpx.Response(200,json=[{'name':'Season/Episode02.mkv','progress':1},{'name':'Season/Episode03.mkv','progress':.1}])
    source=Sources(config)
    source.client.close()
    client=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:client(transport=httpx.MockTransport(api),**kwargs))
    monkeypatch.setattr(source,'emby',lambda *_:[])
    blocked=source.readiness(candidates=[target])
    assert calls.count('/api/v2/torrents/files')==1  # MP maps the renamed episode back to its download.
    assert '/downloads/Season' not in blocked
    assert original in blocked
    assert '下载或校验' not in blocked[original]
    assert blocked['/downloads/Season/Episode03.mkv']=='qB：下载或校验尚未完成'


def test_item_refresh_uses_supported_emby_modes():
    import httpx
    from app.library.sources import Sources
    seen=[]
    def api(request):
        seen.append(request)
        modes=[request.url.params.get('MetadataRefreshMode'),request.url.params.get('ImageRefreshMode')]
        return httpx.Response(204 if modes==['Default','Default'] else 400)
    source=Sources({'emby':{'url':'http://emby.test','token':'fixture'}})
    source.client.close()
    source.client=httpx.Client(transport=httpx.MockTransport(api))
    source.refresh_subtitles('13')
    assert seen[0].url.path=='/Items/13/Refresh'
    assert seen[0].url.params['Recursive']=='false'
    assert seen[0].url.params['ReplaceAllMetadata']=='false'
    source.client.close()


def test_moviepilot_reads_live_committed_history_without_writing(tmp_path):
    import sqlite3
    from app.library.sources import Sources
    database = tmp_path / 'moviepilot.db'
    source = Sources({'moviepilot': {'database': str(database)}})
    source.client.close()
    with sqlite3.connect(database) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE transferhistory(id INTEGER,src TEXT,dest TEXT,status INTEGER)')
        writer.execute('INSERT INTO transferhistory VALUES(1,?,?,1)', ('/downloads/old.mkv', '/library/Episode.mkv'))
        writer.commit()
        assert source.download_source('/library/Episode.mkv') == '/downloads/old.mkv'
        writer.execute('INSERT INTO transferhistory VALUES(2,?,?,1)', ('/downloads/new.mkv', '/library/Episode.mkv'))
        writer.commit()
        assert source.download_source('/library/Episode.mkv') == '/downloads/new.mkv'
        with source._moviepilot_db() as reader:
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                reader.execute('DELETE FROM transferhistory')
        assert writer.execute('SELECT src FROM transferhistory ORDER BY id').fetchall() == [
            ('/downloads/old.mkv',), ('/downloads/new.mkv',)]
