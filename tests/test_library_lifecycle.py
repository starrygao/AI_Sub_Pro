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
