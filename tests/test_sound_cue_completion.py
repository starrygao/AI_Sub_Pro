"""Sound cues from a failed episode must not trigger missing-translation retries."""
from datetime import timedelta
from unittest.mock import Mock

import pytest

from app.engines.translation_qa import (
    dialogue_only_qa_source_text,
    is_sound_description_source,
    normalize_sound_description_translations,
    run_quality_checks,
)
from app.services.translation_tasks import (
    _incomplete_translation_message,
    _retry_missing_translations_before_quality,
    _semantic_qa_requested_items,
    _translation_completion_counts,
)
from app.utils.srt import SubtitleBlock, parse_srt_file, write_srt


CUES = [
    "(gun firing)", "(foot stamping)",
    "(seagulls mewing)\n(brooding ambient music)", "(seagulls mewing)",
    "(hand rapping)", "(hand raps)", "(cutter snips)", "(pliers snip)",
    "(driver vomits)",
    "(motorbike engines vrooming)\n(brooding music)",
    "(motorbike engines vrooming)", "(gun fires)",
]

# Missing cues from the four failed S04E03–S04E06 runs.
CUES += [
    '(Geiger counter smacking)',
    '(Helen rummaging)',
    '(IED bleeps)',
    '(audience applauding)',
    '(audience applauding)\n(suspenseful music)',
    '(baby yawns)',
    '(back pats)',
    '(bonnet slamming)',
    '(clippers stabbing)\n(Pinchbeck screams)',
    '(device booms)',
    '(device powering up)',
    '(device powering up)\n(magnetic clunk)',
    '(dog barking)',
    '(door slamming)\n(sirens blaring)',
    '(door slamming)\n(traffic faintly whizzing)',
    '(dramatic beat)',
    '(dramatic chord)',
    '(dramatic music)\n(audience applauding)',
    '(explosion bangs)\n(flesh spattering)',
    '(gun cocks)',
    '(gun firing)\n(room booms)',
    '(harmonic synth tones)',
    '(intense music)\n(blood splattering)',
    '(message whooshing)',
    '(people chattering)\n(audience cheering)',
    '(people chattering)\n(dramatic music)',
    '(people whacking)\n(people crying out)',
    '(rummaging)',
    '(sirens blaring)',
    '(solution sloshing)',
    '(suspenseful music)\n(sirens blaring)',
    '(tracker bleeps)',
    '(traffic faintly whizzing)',
    '(train tracks squealing)',
    '(train whizzing)',
    '(transition booming)',
    '(transition whooshing)',
    '(vehicle revs)\n(brakes squeal)',
    '(wings flapping)',
    '(wings flapping)\n(phone buzzing)',
    '(wire casing tearing)',
    '(wire snipping)',
]


def block(index, source, translation=""):
    return SubtitleBlock(index, timedelta(seconds=index),
                         timedelta(seconds=index + 1), source, translation)


@pytest.mark.parametrize("source", CUES)
def test_bracketed_action_cues_allow_empty_translation(source):
    assert is_sound_description_source(source)
    assert dialogue_only_qa_source_text(source) == ""
    blocks = [block(1, source, "[音效]")]
    normalize_sound_description_translations(blocks)
    assert blocks[0].translation == ""
    assert run_quality_checks(blocks).issues == []
    assert _translation_completion_counts(blocks) == (0, 0, 0)
    assert _semantic_qa_requested_items(blocks) == []


@pytest.mark.parametrize("source", [
    "(The gun fires only when I pull the trigger.)",
    "(The audience applauding made me nervous.)",
    "(People chattering outside kept me awake.)",
    "(I heard sirens blaring.)", "(device powering up)\nRun!",
    "(audience applauding)\n♪ Stay with me ♪",
    "(I heard the hand rapping.)", "(She watches as the driver vomits.)",
    "Gun fires", "Driver vomits", "(hand raps)\nCome in.",
    "(seagulls mewing)\n♪ I can hear you ♪",
])
def test_action_words_do_not_hide_dialogue(source):
    assert not is_sound_description_source(source)
    assert run_quality_checks([block(1, source)]).summary["by_type"]["missing_translation"] == 1


def test_mixed_cue_preserves_dialogue():
    assert dialogue_only_qa_source_text("(hand rapping) Come in.") == "Come in."


def test_sound_cues_do_not_retry_or_block_export(tmp_path):
    blocks = [block(1, "Come in.", "进来。")]
    blocks.extend(block(i, cue) for i, cue in enumerate(CUES, 2))
    translator = Mock()
    assert _retry_missing_translations_before_quality(
        {"translation": {"missing_translation_retries": 2}},
        translator, blocks, "简体中文", {}, {},
    ) == []
    translator.primary.translate_batch.assert_not_called()
    assert _translation_completion_counts(blocks) == (1, 1, 0)
    assert _incomplete_translation_message(blocks) is None
    path = tmp_path / "translated.srt"
    report = write_srt(blocks, str(path), use_translation=True, return_report=True)
    assert report.written_ids == [1]
    assert report.omitted_sound_description_ids == list(range(2, len(CUES) + 2))
    assert [b.text for b in parse_srt_file(str(path))] == ["进来。"]
