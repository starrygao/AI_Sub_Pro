import json
from pathlib import Path
from unittest.mock import Mock

from app.library.worker import LibraryWorker
from app.library.guard import fingerprint


def test_prepared_foreign_sidecar_starts_translation_only(tmp_path,monkeypatch):
    from app.services import translation_tasks as tasks
    from app.utils import media
    library=tmp_path/'media';library.mkdir();video=library/'Example.mkv';video.write_bytes(b'video')
    english=library/'Example.eng.srt';english.write_text('1\n00:00:00,000 --> 00:00:02,000\nHello there.\n')
    projects=tmp_path/'projects';projects.mkdir();monkeypatch.setattr(tasks,'PROJECTS_DIR',projects)
    start=Mock();monkeypatch.setattr(tasks,'start_translate',start)
    monkeypatch.setattr(tasks,'start_transcribe_translate',Mock(side_effect=AssertionError('must use available text')))
    worker=LibraryWorker({'allowed_roots':[str(library)]},tmp_path/'state')
    monkeypatch.setattr(worker.sources,'metadata',lambda path:{'tmdb_id':42,'tmdb_type':'movie'})
    worker.observe(video,{})
    info={'streams':[{'index':0,'codec_type':'video'},{'index':1,'codec_type':'audio','codec_name':'aac'}],'format':{'duration':'2'}}
    worker.prepare(worker.store.get(video),info,[english])
    row=worker.store.get(video);start.assert_called_once()
    p=json.loads((projects/row['project_id']/'project.json').read_text())
    assert p['workflow_mode']=='translate_only'
    assert p['tmdb_id']==42
    assert p['library_subtitle_source']==str(english)
    assert 'Hello there.' in (projects/row['project_id']/'filtered.srt').read_text()
    assert row['state']=='translating'


def test_failed_readiness_never_launches_or_publishes(tmp_path,monkeypatch):
    worker=LibraryWorker({},tmp_path)
    monkeypatch.setattr(worker,'refresh_readiness',Mock(side_effect=RuntimeError('offline')))
    finish=Mock();start=Mock();monkeypatch.setattr(worker,'finish',finish);monkeypatch.setattr(worker,'process_one',start)
    import pytest
    with pytest.raises(RuntimeError):worker.tick()
    finish.assert_not_called();start.assert_not_called()


def test_chinese_audio_skips_without_starting_model(tmp_path,monkeypatch):
    from app.engines.providers.codex_cli import CodexCliProvider
    from app.library import worker as module
    video=tmp_path/'Chinese.mkv';video.write_bytes(b'video')
    worker=LibraryWorker({'allowed_roots':[str(tmp_path)],'quiet_seconds':0},tmp_path/'state')
    worker.observe(video,{})
    monkeypatch.setattr(CodexCliProvider,'check_logged_in',lambda:True)
    monkeypatch.setattr(module.os,'getloadavg',lambda:(0,0,0))
    monkeypatch.setattr(worker,'probe',lambda p:{'streams':[{'codec_type':'audio','tags':{'language':'chi'}}]})
    prepare=Mock();monkeypatch.setattr(worker,'prepare',prepare)
    worker.process_one()
    assert worker.store.get(video)['state']=='native_language'
    prepare.assert_not_called()
    worker.config['skip_chinese_audio']=False
    row=worker.store.get(video);worker.save(row,state='waiting')
    monkeypatch.setattr(worker,'refresh_readiness',lambda:None)
    worker.process_one()
    prepare.assert_called_once()


def test_unknown_audio_uses_tmdb_original_language_before_asr(tmp_path,monkeypatch):
    from app.engines.providers.codex_cli import CodexCliProvider
    from app.library import worker as module
    video=tmp_path/'Unknown.mkv';video.write_bytes(b'video')
    worker=LibraryWorker({'allowed_roots':[str(tmp_path)],'quiet_seconds':0},tmp_path/'state')
    worker.observe(video,{'tmdb_id':101172,'tmdb_type':'tv'})
    monkeypatch.setattr(CodexCliProvider,'check_logged_in',lambda:True)
    monkeypatch.setattr(module.os,'getloadavg',lambda:(0,0,0))
    monkeypatch.setattr(worker,'probe',lambda p:{'streams':[{'codec_type':'audio','tags':{'language':'und'}}]})
    monkeypatch.setattr(worker.sources,'metadata',lambda p:{})
    monkeypatch.setattr(worker.sources,'original_language',lambda m:'zh',raising=False)
    monkeypatch.setattr(worker,'refresh_readiness',lambda:None)
    prepare=Mock();monkeypatch.setattr(worker,'prepare',prepare)
    worker.process_one()
    assert worker.store.get(video)['state']=='native_language'
    prepare.assert_not_called()
    # An explicit foreign dub must not inherit the original show's Chinese language.
    row=worker.store.get(video);worker.save(row,state='waiting')
    monkeypatch.setattr(worker,'probe',lambda p:{'streams':[{'codec_type':'audio','tags':{'language':'eng'}}]})
    language=Mock(side_effect=AssertionError('foreign audio must win'))
    monkeypatch.setattr(worker.sources,'original_language',language)
    worker.process_one()
    language.assert_not_called();prepare.assert_called_once()


def test_finish_publishes_certified_bilingual_srt_without_changing_video(tmp_path, tmp_project_dir, monkeypatch):
    import hashlib
    from tests.test_project_export import _seed_hash_bound_strict_certification, _sha256_identity
    from app.utils.srt import SubtitleBlock, write_bilingual_srt
    from datetime import timedelta
    from app.services import translation_tasks as tasks
    pid = _seed_hash_bound_strict_certification(tmp_project_dir, 'acde1234')
    pdir = tmp_project_dir / pid
    write_bilingual_srt([SubtitleBlock(1, timedelta(), timedelta(seconds=1), 'Hello', '你好')], str(pdir/'bilingual.srt'))
    report = json.loads((pdir/'translation_qa_report.json').read_text())
    report['delivery_artifact_hashes']['bilingual.srt'] = _sha256_identity((pdir/'bilingual.srt').read_bytes())
    (pdir/'translation_qa_report.json').write_text(json.dumps(report))
    video = tmp_path/'Episode.mkv'; video.write_bytes(b'original video unchanged')
    before = hashlib.sha256(video.read_bytes()).hexdigest()
    project = json.loads((pdir/'project.json').read_text())
    project.update(video_path=str(video), library_source_path=str(video), library_status='translating')
    (pdir/'project.json').write_text(json.dumps(project))
    worker = LibraryWorker({'allowed_roots':[str(tmp_path)]}, tmp_path/'state')
    worker.observe(video, {})
    row = worker.store.get(video); worker.save(row, state='translating', project_id=pid)
    monkeypatch.setattr(tasks, 'is_task_registered', lambda pid:False)
    monkeypatch.setattr(worker.sources, 'refresh_subtitles', lambda pid:None)
    worker.finish()
    assert worker.store.get(video)['state']=='done'
    assert video.with_suffix('.srt').read_text().splitlines()[2:4] == ['你好','Hello']
    assert hashlib.sha256(video.read_bytes()).hexdigest()==before
    assert not video.with_suffix('.chi.srt').exists()


def test_existing_same_name_foreign_srt_is_preserved_before_any_model_work(tmp_path, monkeypatch):
    from app.engines.providers.codex_cli import CodexCliProvider
    from app.library import worker as module
    video=tmp_path/'Episode.mkv'; video.write_bytes(b'video')
    source=video.with_suffix('.srt'); source.write_text('Original foreign subtitle')
    worker=LibraryWorker({'allowed_roots':[str(tmp_path)],'quiet_seconds':0}, tmp_path/'state')
    worker.observe(video,{})
    monkeypatch.setattr(CodexCliProvider,'check_logged_in',lambda:True)
    monkeypatch.setattr(module.os,'getloadavg',lambda:(0,0,0))
    monkeypatch.setattr(worker,'probe',Mock(side_effect=AssertionError('collision must be checked first')))
    worker.process_one()
    assert worker.store.get(video)['state']=='error'
    assert source.read_text()=='Original foreign subtitle'
