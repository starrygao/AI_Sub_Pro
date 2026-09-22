from app.library.sources import emby_metadata, pending_download_paths


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
