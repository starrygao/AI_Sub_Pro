"""Wrapped dialogue must reach semantic QA without losing sound-like nouns."""
from datetime import timedelta

import pytest

from app.engines.translation_qa import (
    classify_subtitle_source, dialogue_only_qa_source_text,
    normalize_sound_description_translations,
)
from app.services.translation_tasks import _semantic_qa_requested_items
from app.utils.srt import SubtitleBlock, parse_srt_file, write_srt


@pytest.mark.parametrize("source,target", [
    ("Funeral bell\nmushrooms, so poisonous", "丧钟菇，毒性极强。"),
    ("if it isn't up and\nrunning by then,", "如果到时还没运转起来，"),
    ("It was only a bottle\nof cough medicine,", "那只是一瓶止咳药，"),
    ("Music\nlessons start tomorrow.", "音乐课明天开始。"),
    ("Phone\nrecords can prove it.", "通话记录可以证明。"),
    ("<i>Funeral bell</i>\nmushrooms, so poisonous", "丧钟菇，毒性极强。"),
])
def test_wrapped_dialogue_is_preserved_through_qa_and_export(source, target, tmp_path):
    block = SubtitleBlock(9, timedelta(seconds=50), timedelta(seconds=53),
                          source, target)
    assert dialogue_only_qa_source_text(source) == source
    assert classify_subtitle_source(source).requires_translation
    assert _semantic_qa_requested_items([block])[0]["original"] == source
    normalize_sound_description_translations([block])
    assert block.translation == target
    path = tmp_path / "translated.srt"
    write_srt([block], str(path), use_translation=True)
    assert parse_srt_file(str(path))[0].text == block.translation


@pytest.mark.parametrize("sound", ["[bell ringing]", "(phone ringing)",
                                       "♪ instrumental music ♪", "APPLAUSE"])
def test_explicit_sound_cues_still_strip_from_mixed_dialogue(sound):
    assert dialogue_only_qa_source_text(sound) == ""
    assert dialogue_only_qa_source_text(sound + "\n-Go!") == "-Go!"
