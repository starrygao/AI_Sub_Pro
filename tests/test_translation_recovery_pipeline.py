from unittest.mock import Mock
import pytest
import json
from pathlib import Path
from app.services import translation_tasks as service
from app.utils import project_store
from app.engines import translator
from app.utils.translation_certification import validate_translation_delivery


@pytest.mark.parametrize('legacy', [False, True])
def test_failed_run_recovers_only_missing_dialogue_and_publishes_fresh_certificate(tmp_path, monkeypatch, legacy):
    pid='checkpoint-pipeline'; p=tmp_path/pid; p.mkdir()
    (p/'project.json').write_text(json.dumps({'id':pid,'name':'fixture','status':'asr_done','target_language':'简体中文','source_type':'subtitle'}))
    (p/'filtered.srt').write_text('1\n00:00:01,000 --> 00:00:03,000\nCome back.\n\n2\n00:00:04,000 --> 00:00:06,000\nWait here.\n\n3\n00:00:07,000 --> 00:00:08,000\n(audience applauding)\n')
    monkeypatch.setattr(service,'PROJECTS_DIR',tmp_path)
    monkeypatch.setattr(project_store,'PROJECTS_DIR',tmp_path)
    cfg={'translation':{'primary_provider':'codex_cli','polish_provider':'','quality_mode':'fast','semantic_qa':False,'qa_auto_repair':False,'missing_translation_retries':0,'use_translation_memory':False,'use_phrase_library':False}}
    monkeypatch.setattr(service.Config,'to_dict',lambda:cfg)
    calls=[];fail=True
    def translate(items,prompt):
        calls.append([i['id'] for i in items])
        return [{'id':i['id'],'translation': ('回来。' if i['id']==1 else ('' if fail else '在这儿等着。'))} for i in items]
    provider=Mock(supports_full_document_mode=False,context_window_tokens=100000)
    provider.translate_batch.side_effect=translate
    monkeypatch.setattr(translator,'get_provider',lambda *args:provider)
    service._run_translate_pipeline(pid,'简体中文',burn_follows=False)
    assert json.loads((p/'project.json').read_text())['status']=='error'
    assert (p/'translation_checkpoint.json').exists()
    first_report=json.loads((p/'translation_qa_report.json').read_text())
    assert any(i['type']=='missing_translation' for i in first_report['issues'])
    if legacy:
        (p/'translation_checkpoint.json').unlink()
        # The HTTP launch invalidates the old QA report before the worker starts.
        service._begin_translation_quality_run(pid, expected_policy='fast')
    calls.clear();fail=False
    service._run_translate_pipeline(pid,'简体中文',burn_follows=False)
    assert calls==[[2]]
    project=json.loads((p/'project.json').read_text())
    assert project['status']=='translated'
    assert validate_translation_delivery(project,p).valid
    assert '回来。' in (p/'translated.srt').read_text()
    assert '在这儿等着。' in (p/'translated.srt').read_text()
    assert 'applauding' not in (p/'bilingual.srt').read_text()
    assert json.loads((p/'subtitle_classification.json').read_text())['blocks'][2]['kind']=='sound'
