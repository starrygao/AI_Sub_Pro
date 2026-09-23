"""Regressions from the four desktop deliveries reviewed on 2026-09-23."""
from datetime import timedelta

import pytest

from app.engines.entity_registry import aligned_name_span, build_entity_registry
from app.engines.translation_qa import annotate_contextual_speaker_translations
from app.utils.srt import SubtitleBlock


@pytest.mark.parametrize('source,expected', [
    ("[woman's voice] WIBC.", 'WIBC电台。'),
    ('[male voice] Hello.', 'WIBC电台。'),
    ('[voice on phone] Hello.', '【电话】WIBC电台。'),
    ('[offscreen voice] Hello.', '【画外音】WIBC电台。'),
    ('[narrator] Hello.', '【旁白】WIBC电台。'),
    ('[voiceover] Hello.', '【旁白】WIBC电台。'),
])
def test_voice_gender_does_not_invent_narration(source, expected):
    block = SubtitleBlock(1, timedelta(0), timedelta(seconds=2), source, 'WIBC电台。')
    annotate_contextual_speaker_translations([block])
    assert block.translation == expected


@pytest.mark.parametrize('name,source,target', [
    ('Meridian Mortgage', "Dick's father, and the owner of Meridian Mortgage?", '迪克的父亲、子午线抵押贷款公司的老板？'),
    ('Lady Chiyome', 'Lady Chiyome, Lady Tsubone, your visit to Lalatoya is related?', '千代女大人、局大人，你们来拉拉托亚也与此事有关吧？'),
    ('Logan', '- Logan.\n- Mr. Hollingsworth.', '- 洛根。\n- 霍林斯沃思先生。'),
])
def test_multiple_source_entities_do_not_license_an_unrelated_target(name, source, target):
    assert aligned_name_span(name, source, target) is None


def test_standalone_address_keeps_nonphonetic_name_characters():
    assert aligned_name_span('Hezekiah', 'Hezekiah?', '希西家？') == ('希西家', 'standalone_address')


def test_literal_acronym_is_not_aligned_to_an_adjacent_person():
    assert aligned_name_span('WIBC', 'This is Fred Heckman on WIBC.', '这里是WIBC，我是弗雷德·赫克曼。') == ('WIBC', 'literal_source')


def test_explicit_name_labels_anchor_later_mentions_without_truncation():
    entities = build_entity_registry(
        {'1': '[Hezekiah] Yes.', '2': 'Who? Hezekiah?'},
        {'1': '[希西家]是的。', '2': '谁？希西家？'},
    )
    entity = next(e for e in entities if e['source'] == 'Hezekiah')
    assert entity['target_forms'] == ['希西家']
    assert len(entity['observations']) == 2


@pytest.mark.parametrize('word', ['Uh', 'Can', 'Welcome', 'Sorry', 'Seriously', 'Goddammit', 'Man', 'WOMAN'])
def test_generic_dialogue_and_anonymous_labels_are_not_proper_names(word):
    source = {'1': f'[{word}] Fred?', '2': f'[{word}] Judy?'}
    target = {'1': '[声音]弗雷德？', '2': '[另一声音]朱迪？'}
    assert word.casefold() not in {e['source'].casefold() for e in build_entity_registry(source, target)}


def test_explicit_short_name_does_not_match_another_person_name_prefix():
    assert aligned_name_span(
        'Fred', 'Fred met Frederick.', '弗雷德里克遇见了他。',
        known_forms={'弗雷德'},
    ) is None


def test_context_marker_before_name_is_not_a_translated_person_name():
    assert aligned_name_span('Kateri', 'KATERI: Hello?', '【电话】-卡特里：喂？') == ('卡特里', 'speaker_label')
    assert aligned_name_span('Kateri', 'KATERI: Hello?', '【电话】喂？') is None
