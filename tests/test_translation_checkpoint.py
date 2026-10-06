from datetime import timedelta
from copy import deepcopy
import json
import pytest
from app.utils.srt import SubtitleBlock, write_srt, write_bilingual_srt
from app.utils.subtitle_generation import subtitle_source_generation_hash
from app.utils.translation_checkpoint import save_translation_checkpoint, restore_translation_checkpoint


def blocks():
    return [SubtitleBlock(7, timedelta(seconds=1), timedelta(seconds=3), 'Come back.', '回来。'),
            SubtitleBlock(9, timedelta(seconds=4), timedelta(seconds=5), '(audience applauding)', '')]


def setup_project(tmp_path):
    rows=blocks()
    write_srt(rows, str(tmp_path/'filtered.srt'))
    return rows, subtitle_source_generation_hash(tmp_path)


def test_checkpoint_restores_exact_drafts_and_rejects_source_config_or_tampering(tmp_path):
    rows, sh=setup_project(tmp_path)
    save_translation_checkpoint(tmp_path, rows, sh, 'cfg')
    for source_hash, config_hash, count in [(sh,'cfg',1),(sh,'changed',0),('changed','cfg',0)]:
        fresh=deepcopy(rows)
        for b in fresh:b.translation=''
        assert restore_translation_checkpoint(tmp_path,fresh,source_hash,config_hash)==count
        assert bool(fresh[0].translation)==bool(count)
    data=json.loads((tmp_path/'translation_checkpoint.json').read_text())
    data['blocks'][0]['text']='Different source'
    (tmp_path/'translation_checkpoint.json').write_text(json.dumps(data))
    fresh=blocks();fresh[0].translation=''
    assert restore_translation_checkpoint(tmp_path,fresh,sh,'cfg')==0


def test_legacy_partial_requires_matching_source_config_and_bilingual_evidence(tmp_path):
    rows,sh=setup_project(tmp_path)
    write_srt(rows,str(tmp_path/'partial_translated.srt'),use_translation=True)
    write_bilingual_srt(rows,str(tmp_path/'partial_bilingual.srt'))
    (tmp_path/'translation_qa_report.json').write_text(json.dumps({'source_generation_hash':sh,'configuration_hash':'cfg'}))
    fresh=deepcopy(rows);fresh[0].translation=''
    assert restore_translation_checkpoint(tmp_path,fresh,sh,'cfg')==1
    assert fresh[0].translation=='回来。'
    (tmp_path/'partial_bilingual.srt').write_text('')
    fresh[0].translation=''
    assert restore_translation_checkpoint(tmp_path,fresh,sh,'cfg')==0


def test_mismatched_checkpoint_does_not_fall_back_to_stale_partial(tmp_path):
    rows,sh=setup_project(tmp_path)
    save_translation_checkpoint(tmp_path,rows,sh,'old-config')
    fresh=deepcopy(rows);fresh[0].translation=''
    assert restore_translation_checkpoint(tmp_path,fresh,sh,'new-config')==0


def test_checkpoint_source_timeline_must_match(tmp_path):
    rows,sh=setup_project(tmp_path)
    save_translation_checkpoint(tmp_path,rows,sh,'cfg')
    fresh=deepcopy(rows);fresh[0].translation='';fresh[0].end+=timedelta(seconds=1)
    assert restore_translation_checkpoint(tmp_path,fresh,sh,'cfg')==0


def test_checkpoint_invalid_ids_and_whitespace_are_not_restored(tmp_path):
    rows,sh=setup_project(tmp_path);rows[0].translation='  '
    save_translation_checkpoint(tmp_path,rows,sh,'cfg')
    fresh=deepcopy(rows);fresh[0].translation=''
    assert restore_translation_checkpoint(tmp_path,fresh,sh,'cfg')==0


@pytest.mark.parametrize(("source", "translation"), [
    ("Go for it!\n- Ooh!", "上吧！\n- 哦！"),
    ("♪ I don't want ♪\nCome on!", "我不想\n加油！"),
    ("I need to talk\nabout the case.", "我要谈谈这个案子。"),
])
def test_partial_restores_real_bilingual_layout_without_losing_structure(
    tmp_path, source, translation,
):
    rows = [SubtitleBlock(7, timedelta(seconds=1), timedelta(seconds=3), source, translation)]
    write_srt(rows, str(tmp_path / 'filtered.srt'))
    source_hash = subtitle_source_generation_hash(tmp_path)
    write_srt(rows, str(tmp_path / 'partial_translated.srt'), use_translation=True)
    write_bilingual_srt(rows, str(tmp_path / 'partial_bilingual.srt'))
    (tmp_path / 'translation_qa_report.json').write_text(json.dumps({
        'source_generation_hash': source_hash, 'configuration_hash': 'cfg',
    }))
    fresh = deepcopy(rows)
    fresh[0].translation = ''
    assert restore_translation_checkpoint(tmp_path, fresh, source_hash, 'cfg') == 1
    assert fresh[0].translation == translation
    (tmp_path / 'partial_bilingual.srt').write_text('unrelated dialogue')
    fresh[0].translation = ''
    assert restore_translation_checkpoint(tmp_path, fresh, source_hash, 'cfg') == 0
    assert fresh[0].translation == ''
