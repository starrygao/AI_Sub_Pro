import json,time
import pytest
from app.library.sources import Sources,pending_download_paths
from app.library.guard import chinese_sidecar


def test_qbit_large_inventory_uses_content_path_without_per_torrent_requests():
    def no_files(_):raise AssertionError('one HTTP request per torrent is too expensive')
    assert pending_download_paths([{'hash':'a','content_path':'/pt/Show','progress':0.9,'state':'pausedDL'}],no_files,{'/pt':'/video/pt'},candidates=[])=={'/video/pt/Show'}


def test_expired_upload_snapshot_fails_closed(tmp_path):
    p=tmp_path/'writers.json';p.write_text(json.dumps({'ok':True,'updated':time.time()-60,'paths':[]}))
    s=Sources({'open_writes':{'file':str(p)}})
    with pytest.raises(RuntimeError,match='过期'):s.readiness()


def test_japanese_kanji_is_not_mistaken_for_chinese_sidecar(tmp_path):
    p=tmp_path/'movie.srt';p.write_text('日本語の字幕です。今日の会議は午後三時に始まります。')
    assert not chinese_sidecar(p)


def test_nfo_series_identity_wins_over_episode_id(tmp_path):
    season=tmp_path/'Season 1';season.mkdir();video=season/'show.S01E01.mkv';video.touch()
    video.with_suffix('.nfo').write_text('<episodedetails><uniqueid type="tmdb">999</uniqueid></episodedetails>')
    (tmp_path/'tvshow.nfo').write_text('<tvshow><title>Show</title><uniqueid type="tmdb">123</uniqueid></tvshow>')
    assert Sources({}).metadata(video)['tmdb_id']==123


def test_vtrans_future_replacement_path_is_blocked():
    from app.library.guard import vtrans_blockers
    blocked=vtrans_blockers([{'source':'/media/show.mp4','state':'等待','server':{'replace':True}}],{'/media':'/video'})
    assert '/video/show.mkv' in blocked
    assert '/video/show.mp4' in blocked
