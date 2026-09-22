from pathlib import Path
from app.library.guard import fingerprint, ready_file, chinese_track, subtitle_files, vtrans_blockers


def test_upload_requires_two_stable_observations_and_quiet_period(tmp_path):
    p = tmp_path / 'Episode.mkv'
    p.write_bytes(b'video')
    f = fingerprint(p)
    assert not ready_file(p, None, now=1000, quiet_seconds=300)[0]
    previous = {'fingerprint': f, 'stable_since': 1000}
    assert not ready_file(p, previous, now=1100, quiet_seconds=300)[0]
    assert ready_file(p, previous, now=1400, quiet_seconds=300)[0]
    p.write_bytes(b'new video')
    assert not ready_file(p, previous, now=1500, quiet_seconds=300)[0]


def test_partial_sibling_and_temporary_directory_block(tmp_path):
    p = tmp_path / 'Episode.mkv'; p.write_bytes(b'v')
    old = {'fingerprint':fingerprint(p), 'stable_since':0}
    (tmp_path / 'Episode.mkv.!qB').touch()
    assert not ready_file(p, old, now=1000, quiet_seconds=300)[0]


def test_chinese_subtitle_includes_traditional_but_not_audio_or_forced_only():
    assert chinese_track({'codec_type':'subtitle','tags':{'language':'zho'}})
    assert chinese_track({'codec_type':'subtitle','tags':{'title':'繁體中文'}})
    assert not chinese_track({'codec_type':'audio','tags':{'language':'chi'}})
    assert not chinese_track({'codec_type':'subtitle','tags':{'language':'chi'},'disposition':{'forced':1}})


def test_sidecars_require_exact_video_stem_boundary(tmp_path):
    v=tmp_path/'Episode.mkv';v.touch()
    for name in ['Episode.zh.srt','Episode2.zh.srt','Episode.en.srt']:(tmp_path/name).touch()
    assert {p.name for p in subtitle_files(v)} == {'Episode.zh.srt','Episode.en.srt'}


def test_vtrans_waits_for_queued_and_pending_publication():
    rows=[{'source':'/media/show.mkv','state':'完成','server':{'pending':True}},
          {'source':'/media/done.mkv','state':'完成','server':{'pending':False}},
          {'source':'/media/new.mkv','state':'等待'}]
    blocked=vtrans_blockers(rows, {'/media':'/video'})
    assert '/video/show.mkv' in blocked
    assert '/video/new.mkv' in blocked
    assert '/video/done.mkv' not in blocked


def test_only_chinese_audio_can_skip_translation():
    from app.library.guard import chinese_audio_only
    assert chinese_audio_only([{'codec_type':'audio','tags':{'language':'cmn'}}])
    assert not chinese_audio_only([{'codec_type':'audio','tags':{'language':'chi'}},{'codec_type':'audio','tags':{'language':'eng'}}])
    assert not chinese_audio_only([{'codec_type':'audio','tags':{'language':'und'}}])
    assert not chinese_audio_only([])
