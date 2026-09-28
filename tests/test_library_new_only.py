import os
from unittest.mock import Mock

import pytest

from app.library.worker import LibraryWorker


def make_worker(tmp_path):
    root=tmp_path/'media';root.mkdir(exist_ok=True)
    return LibraryWorker({'new_only':True,'roots':[str(root)],'allowed_roots':[str(root)],'quiet_seconds':0},tmp_path/'state'),root


def test_baseline_excludes_history_after_restart_but_accepts_new_file_with_old_mtime(tmp_path,monkeypatch):
    worker,root=make_worker(tmp_path)
    old=root/'old.mkv';old.write_bytes(b'existing video')
    # Upgrade from the former whole-library discovery queue.
    worker.config['new_only']=False;worker.observe(old,{})
    worker.config['new_only']=True
    worker.establish_baseline()
    assert worker.store.counts()=={}
    assert worker.status()['baseline']['count']==1
    worker,root=make_worker(tmp_path)
    worker.establish_baseline()
    old.write_bytes(b'replaced existing video')
    worker.observe(old,{})
    assert worker.store.get(old) is None
    new=root/'new.mkv';new.write_bytes(b'new arrival')
    os.utime(new,(100,100))
    worker.observe(new,{})
    assert worker.store.get(new)['state']=='waiting'
    assert worker.status()['baseline']['count']==1


def test_baseline_keeps_completed_history_and_cancels_old_job_without_publishing(tmp_path,monkeypatch):
    from app.services import translation_tasks as tasks
    worker,root=make_worker(tmp_path)
    worker.config['new_only']=False
    for name,state in [('done','done'),('active','translating')]:
        video=root/(name+'.mkv');video.write_bytes(b'video');worker.observe(video,{})
        worker.save(worker.store.get(video),state=state,project_id=name)
    worker.config['new_only']=True
    cancel=Mock();monkeypatch.setattr(tasks,'cancel_task',cancel)
    worker.establish_baseline()
    assert worker.store.get(root/'done.mkv')['state']=='done'
    assert worker.store.get(root/'active.mkv')['state']=='cancelled'
    cancel.assert_called_once_with('active')
    monkeypatch.setattr(tasks,'_load_project',Mock(side_effect=AssertionError('old job cannot publish')))
    worker.finish()
    assert worker.store.rows(['waiting','translating','publishing'])==[]


def test_missing_root_cannot_seal_partial_baseline_or_start_work(tmp_path,monkeypatch):
    worker,root=make_worker(tmp_path)
    worker.roots.append(str(root/'unavailable'))
    with pytest.raises(OSError):worker.establish_baseline()
    assert not worker.store.setting('baseline',{}).get('completed_at')
    new=root/'new.mkv';new.write_bytes(b'video');worker.observe(new,{})
    assert worker.store.get(new) is None


def test_baseline_matches_hardlink_and_limits_emby_discovery_to_monitored_roots(tmp_path):
    worker,root=make_worker(tmp_path)
    old=root/'old.mkv';old.write_bytes(b'video')
    worker.establish_baseline()
    alias=root/'renamed.mkv';alias.hardlink_to(old)
    worker.observe(alias,{})
    assert worker.store.get(alias) is None
    outside=tmp_path/'elsewhere.mkv';outside.write_bytes(b'outside')
    worker.config['allowed_roots']=[str(tmp_path)]
    worker.observe(outside,{})
    assert worker.store.get(outside) is None


def test_moviepilot_arrival_is_discovered_before_emby_import(tmp_path,monkeypatch):
    import sqlite3
    worker,root=make_worker(tmp_path);worker.establish_baseline()
    video=root/'new.mkv';video.write_bytes(b'new')
    database=tmp_path/'moviepilot.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE transferhistory(id INTEGER,dest TEXT,media_id TEXT,type TEXT,title TEXT,media_source TEXT,status INTEGER)')
        db.execute('INSERT INTO transferhistory VALUES(1,?,42,?,?,?,1)',(str(video),'电视剧','Example','tmdb'))
    worker.config['moviepilot']={'database':str(database)}
    monkeypatch.setattr(worker.sources,'recent',lambda *a:([],0))
    monkeypatch.setattr(worker,'filesystem',lambda *a,**k:iter([]))
    worker.discover()
    row=worker.store.get(video)
    assert row['metadata']['tmdb_id']==42
    assert row['metadata']['metadata_source']=='moviepilot'
    assert not row['metadata'].get('emby_id')
    assert row['state']=='waiting'


@pytest.mark.parametrize('kind',['embedded','sidecar','chinese_audio','foreign'])
def test_new_arrivals_only_translate_without_chinese_subtitles_or_chinese_audio(tmp_path,monkeypatch,kind):
    from app.engines.providers.codex_cli import CodexCliProvider
    worker,root=make_worker(tmp_path);worker.establish_baseline()
    video=root/'new.mkv';video.write_bytes(b'video');worker.observe(video,{})
    streams=[{'codec_type':'audio','tags':{'language':'chi' if kind=='chinese_audio' else 'eng'}}]
    if kind=='embedded':streams.append({'codec_type':'subtitle','tags':{'language':'chi'}})
    if kind=='sidecar':video.with_suffix('.zh.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n这是已经存在的中文字幕\n')
    monkeypatch.setattr(CodexCliProvider,'check_logged_in',lambda:True)
    monkeypatch.setattr(os,'getloadavg',lambda:(0,0,0))
    monkeypatch.setattr(worker,'probe',lambda p:{'streams':streams})
    monkeypatch.setattr(worker,'refresh_readiness',lambda:None)
    prepare=Mock();monkeypatch.setattr(worker,'prepare',prepare)
    worker.process_one()
    assert prepare.call_count==int(kind=='foreign')
    if kind!='foreign':assert worker.store.get(video)['state'] in {'skipped','native_language'}


pytestmark = pytest.mark.usefixtures("library_codex_config")
