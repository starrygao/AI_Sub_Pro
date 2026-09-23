from unittest.mock import Mock

from app.library.worker import LibraryWorker


def setup_worker(tmp_path, monkeypatch, *, new_only=False):
    from app.engines.providers.codex_cli import CodexCliProvider
    from app.library import worker as module
    root=tmp_path/'media';root.mkdir()
    worker=LibraryWorker({'roots':[str(root)],'allowed_roots':[str(root)],'quiet_seconds':0,'new_only':new_only},tmp_path/'state')
    if new_only:worker.establish_baseline()
    monkeypatch.setattr(module.os,'getloadavg',lambda:(0,0,0))
    monkeypatch.setattr(CodexCliProvider,'check_logged_in',lambda:True)
    monkeypatch.setattr(worker,'refresh_readiness',lambda:None)
    monkeypatch.setattr(worker,'prepare',Mock())
    monkeypatch.setattr(worker,'probe',Mock(return_value={'streams':[{'codec_type':'audio','tags':{'language':'eng'}}]}))
    return worker,root


def add(worker, root, name, meta=None):
    video=root/(name+'.mkv');video.write_bytes(b'video')
    worker.observe(video,meta or {})
    return video


def test_detection_continues_during_translation_and_batches_chinese_tracks(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch)
    active=add(w,root,'active');w.save(w.store.get(active),state='translating',project_id='1234abcd')
    videos=[add(w,root,str(i)) for i in range(6)]
    w.probe.return_value={'streams':[{'codec_type':'subtitle','tags':{'language':'chi'}}]}
    w.process_one()
    assert all(w.store.get(v)['state']=='skipped' for v in videos)
    w.prepare.assert_not_called()


def test_detected_foreign_file_waits_for_slot_then_rechecks_new_chinese_sidecar(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch)
    active=add(w,root,'active');w.save(w.store.get(active),state='translating',project_id='1234abcd')
    video=add(w,root,'foreign');w.process_one()
    assert w.store.get(video)['state']=='ready'
    assert '名额' in w.store.get(video)['reason']
    w.save(w.store.get(active),state='done')
    video.with_suffix('.zh.srt').write_text('已有中文字幕')
    w.process_one()
    assert w.store.get(video)['state']=='skipped'
    w.prepare.assert_not_called()


def test_old_emby_media_is_excluded_but_manual_request_is_allowed(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch,new_only=True)
    video=add(w,root,'moved-old',{'emby_id':'42','date_created':'2020-01-01T00:00:00Z'})
    w.process_one()
    assert w.store.get(video)['state']=='historical'
    w.probe.assert_not_called();w.prepare.assert_not_called()
    row=w.store.get(video);row.update(state='waiting',manual_requested=True)
    actual,inserted=w.store.insert_request(row)
    assert inserted and actual['manual_requested']
    w.process_one();w.prepare.assert_called_once()


def test_paused_detection_does_not_start_models_and_restart_keeps_ready_cache(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch)
    video=add(w,root,'foreign');w.process_one(start=False)
    assert w.store.get(video)['state']=='ready'
    assert '暂停' in w.store.get(video)['reason']
    w.prepare.assert_not_called()
    w.process_one()
    w.probe.assert_called_once();w.prepare.assert_called_once()


def test_ready_file_replaced_or_download_blocked_is_demoted_before_start(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch)
    video=add(w,root,'foreign');w.process_one(start=False)
    w.set_blockers({str(video):'下载尚未完成'})
    w.process_one()
    assert w.store.get(video)['state']=='waiting'
    w.prepare.assert_not_called()
    w.set_blockers({});video.write_bytes(b'replaced file')
    w.process_one()
    assert w.store.get(video)['state']=='waiting'
    w.prepare.assert_not_called()


def test_probe_replacement_cannot_cache_or_start_old_streams(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch)
    video=add(w,root,'foreign')
    def probe(p):
        p.write_bytes(b'new version while probing')
        return {'streams':[{'codec_type':'audio','tags':{'language':'eng'}}]}
    monkeypatch.setattr(w,'probe',probe)
    w.process_one()
    assert w.store.get(video)['state']=='waiting'
    assert not w.store.get(video).get('detection')
    w.prepare.assert_not_called()


def test_probe_batch_is_bounded(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch)
    for i in range(15):add(w,root,str(i))
    w.probe.return_value={'streams':[{'codec_type':'subtitle','tags':{'language':'chi'}}]}
    w.process_one(start=False)
    assert w.probe.call_count==10
    assert w.store.counts()=={'skipped':10,'waiting':5}
    w.process_one(start=False)
    assert w.store.counts()=={'skipped':15}


def test_detection_does_not_require_model_login(tmp_path, monkeypatch):
    from app.engines.providers.codex_cli import CodexCliProvider
    w,root=setup_worker(tmp_path,monkeypatch)
    monkeypatch.setattr(CodexCliProvider,'check_logged_in',lambda:False)
    video=add(w,root,'foreign')
    w.process_one()
    assert w.store.get(video)['state']=='ready'
    assert '尚未登录' in w.store.get(video)['reason']
    w.prepare.assert_not_called()


def test_old_directory_without_arrival_evidence_waits_for_confirmation(tmp_path, monkeypatch):
    outside=tmp_path/'outside';outside.mkdir();video=outside/'old.mkv';video.write_bytes(b'old')
    w,root=setup_worker(tmp_path,monkeypatch,new_only=True)
    outside.rename(root/'moved');video=root/'moved'/'old.mkv'
    w.observe(video,{})
    w.process_one()
    assert w.store.get(video)['state']=='waiting'
    assert '入库记录确认' in w.store.get(video)['reason']
    w.probe.assert_not_called();w.prepare.assert_not_called()


def test_history_arriving_after_detection_prevents_automatic_translation(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch,new_only=True)
    video=add(w,root,'file');w.process_one(start=False)
    assert w.store.get(video)['state']=='ready'
    w.observe(video,{'emby_id':'42','date_created':'2020-01-01T00:00:00Z'})
    w.process_one()
    assert w.store.get(video)['state']=='historical'
    w.prepare.assert_not_called()


def test_ready_cache_survives_restart_but_live_download_recheck_still_runs(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch)
    video=add(w,root,'file');w.process_one(start=False)
    restored=LibraryWorker(w.config,tmp_path/'state')
    probe=Mock(side_effect=AssertionError('unchanged input should reuse its checked streams'))
    monkeypatch.setattr(restored,'probe',probe)
    refresh=Mock(side_effect=lambda:restored.set_blockers({str(video):'下载仍在校验'}))
    monkeypatch.setattr(restored,'refresh_readiness',refresh)
    prepare=Mock();monkeypatch.setattr(restored,'prepare',prepare)
    restored.process_one()
    assert restored.store.get(video)['state']=='waiting'
    refresh.assert_called_once();probe.assert_not_called();prepare.assert_not_called()


def test_next_ready_job_gets_download_check_even_outside_oldest_candidate_page(tmp_path, monkeypatch):
    w,root=setup_worker(tmp_path,monkeypatch)
    video=add(w,root,'selected');w.process_one(start=False)
    for i in range(105):
        p=add(w,root,str(i))
        row=w.store.get(p);row['updated']=i;w.store.put(row)
    row=w.store.get(video);row.update(priority=100,updated=10**12);w.store.put(row)
    assert str(video) not in [r['path'] for r in w.store.waiting_ready(10**12)]
    monkeypatch.setattr(w,'refresh_readiness',LibraryWorker.refresh_readiness.__get__(w))
    checked=[]
    def readiness(*,candidates):
        checked.extend(candidates)
        return {str(video):'下载仍在校验'} if str(video) in candidates else {}
    monkeypatch.setattr(w.sources,'readiness',readiness)
    w.process_one()
    assert str(video) in checked
    assert w.store.get(video)['state']=='waiting'
    w.prepare.assert_not_called()
