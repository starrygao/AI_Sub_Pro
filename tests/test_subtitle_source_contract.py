from datetime import timedelta
from unittest.mock import Mock
import pytest
from app.utils.srt import SubtitleBlock, parse_srt_file, write_srt
from app.engines import translation_qa as qa
from app.engines import translator as tr

@pytest.mark.parametrize('source,kind,required', [
    ('(audience applauding)', 'sound', False),
    ('(he breathes gingerly)', 'sound', False),
    ('(he breathes heavily)', 'sound', False),
    ('(she coughs softly)', 'sound', False),
    ('(he hears music)', 'dialogue', True),
    ('(he calls me)', 'dialogue', True),
    ('He breathes heavily', 'dialogue', True),
    ('[music] Come back!', 'mixed', True),
    ('[music]\n♪ Stay with me ♪', 'mixed', True),
    ('[unfamiliar mechanism zorbles]', 'uncertain', True),
    ('(Music is my life.)', 'dialogue', True),
    ('[Turn off the radio!]', 'dialogue', True),
    ('I hear music.', 'dialogue', True),
    ('I hear music', 'dialogue', True),
    ('[你听到音乐了吗]', 'dialogue', True),
])
def test_source_classification_and_consumers_agree(source, kind, required, tmp_path):
    decision = qa.classify_subtitle_source(source)
    assert decision.kind == kind
    assert decision.requires_translation is required
    assert decision.reason
    b = SubtitleBlock(1, timedelta(), timedelta(seconds=2), source)
    assert qa.is_sound_description_source(source) is (not required)
    issues = qa.run_quality_checks([b]).issues
    assert any(i.type == 'missing_translation' for i in issues) is required
    assert tr._is_retryable_translation_result({'translation': ''}, {'id': 1, 'original': source}) is required
    if required:
        b.translation = '这是已有译文。'
    report = write_srt([b], str(tmp_path/'out.srt'), use_translation=True, return_report=True)
    assert bool(report.written_ids) is required

@pytest.mark.parametrize('full_doc', [False, True])
def test_translation_skips_known_sounds_and_restored_drafts_but_translates_unknowns(monkeypatch, full_doc):
    provider = Mock(supports_full_document_mode=full_doc, context_window_tokens=100000)
    provider.full_document_max_items = None
    calls = []
    def translate(items, prompt):
        calls.extend(items)
        assert '每个输入' in prompt
        return [{'id': i['id'], 'translation': '未知装置发出声音。'} for i in items]
    provider.translate_batch.side_effect = translate
    monkeypatch.setattr(tr, 'get_provider', lambda *args: provider)
    t = tr.SubtitleTranslator({'translation': {'primary_provider': 'codex_cli', 'polish_provider': '', 'full_doc_mode': full_doc, 'use_translation_memory': False, 'use_phrase_library': False}})
    t.resume_existing = True
    blocks = [SubtitleBlock(i, timedelta(seconds=i), timedelta(seconds=i+1), s, v) for i,s,v in [
        (1, '(sirens blaring)', ''), (2, 'Come back.', '回来。'),
        (3, '[unfamiliar mechanism zorbles]', ''),
    ]]
    t.translate(blocks)
    assert [i['id'] for i in calls] == [3]
    assert blocks[1].translation == '回来。'
    assert blocks[0].translation == ''


def test_unknown_source_translation_is_not_erased_by_target_sound_words():
    b = SubtitleBlock(1, timedelta(), timedelta(seconds=2), '[unfamiliar mechanism zorbles]', '[机械声]')
    qa.normalize_sound_description_translations([b])
    assert b.translation == '[机械声]'


def test_recovery_keeps_neighboring_restored_dialogue_in_prompt(monkeypatch):
    provider = Mock(supports_full_document_mode=True, context_window_tokens=100000)
    provider.full_document_max_items = None
    provider.translate_batch.side_effect = lambda items,prompt: [{'id':i['id'],'translation':'没问题。'} for i in items]
    monkeypatch.setattr(tr,'get_provider',lambda *args:provider)
    t=tr.SubtitleTranslator({'translation':{'primary_provider':'codex_cli','polish_provider':'','full_doc_mode':True,'context_window':3,'use_translation_memory':False,'use_phrase_library':False}})
    t.resume_existing=True
    captured=[]
    def prompt(target,meta,kb,before,after,items=None):
        captured.append((before,after))
        return 'context fixture'
    monkeypatch.setattr(t,'_build_prompt',prompt)
    rows=[SubtitleBlock(i,timedelta(seconds=i),timedelta(seconds=i+1),s,v) for i,s,v in [
        (1,'Can you help?','能帮我吗？'),(2,'Sure.',''),(3,'Thank you.','谢谢。')]]
    t.translate(rows)
    assert captured==[([{'original':'Can you help?','translated':'能帮我吗？'}],['Thank you.'])]
