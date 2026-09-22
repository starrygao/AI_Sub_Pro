from app.library.worker import LibraryWorker
from app.library.guard import fingerprint


def test_replacement_resets_discovery_and_no_duplicate_on_stable_file(tmp_path):
    root=tmp_path/'media';root.mkdir();v=root/'movie.mkv';v.write_bytes(b'one')
    worker=LibraryWorker({'roots':[str(root)],'allowed_roots':[str(root)]},tmp_path/'state')
    worker.observe(v,{'tmdb_id':123})
    row=worker.store.get(v);row.update(state='done',output_path=str(root/'movie.chi.srt'));worker.store.put(row)
    (root/'movie.chi.srt').write_text('Chinese')
    worker.observe(v,{})
    assert worker.store.get(v)['state']=='done'
    v.write_bytes(b'replacement')
    worker.observe(v,{})
    assert worker.store.get(v)['state']=='waiting'
    assert worker.store.get(v)['fingerprint']==fingerprint(v)


def test_downloader_block_applies_to_hardlink(tmp_path):
    root=tmp_path/'media';root.mkdir();original=root/'download.mkv';original.write_bytes(b'v')
    target=root/'movie.mkv';target.hardlink_to(original)
    worker=LibraryWorker({'allowed_roots':[str(root)]},tmp_path/'state')
    worker.set_blockers({str(original):'still downloading'})
    assert worker.block_reason(target)=='still downloading'


def test_candidate_outside_allowed_roots_is_rejected(tmp_path):
    root=tmp_path/'media';root.mkdir();v=tmp_path/'other.mkv';v.write_bytes(b'v')
    worker=LibraryWorker({'allowed_roots':[str(root)]},tmp_path/'state')
    worker.observe(v,{})
    assert worker.store.get(v) is None


def test_removed_existing_chinese_sidecar_is_checked_again(tmp_path):
    video=tmp_path/'Movie.mkv';video.write_bytes(b'video')
    subtitle=tmp_path/'Movie.zh.srt';subtitle.write_text('中文内容')
    worker=LibraryWorker({'allowed_roots':[str(tmp_path)]},tmp_path/'state')
    worker.observe(video,{})
    row=worker.store.get(video)
    worker.save(row,state='skipped',existing_subtitles=[{'path':str(subtitle),'fingerprint':fingerprint(subtitle)}])
    worker.observe(video,{})
    assert worker.store.get(video)['state']=='skipped'
    subtitle.unlink();worker.observe(video,{})
    assert worker.store.get(video)['state']=='waiting'
