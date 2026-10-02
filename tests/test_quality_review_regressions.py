from datetime import timedelta

import pytest

from app.engines.translation_qa import (
    QualityIssue,
    classify_subtitle_source,
    clean_sound_description_translation_text,
    grouped_issue_summary,
    normalize_sound_description_translations,
    run_quality_checks,
    translation_candidate_contract_error,
)
from app.utils.srt import SubtitleBlock


def _block(source, translation, *, seconds=4):
    return SubtitleBlock(
        index=1,
        start=timedelta(),
        end=timedelta(seconds=seconds),
        text=source,
        translation=translation,
    )


@pytest.mark.parametrize(("source", "translation"), [
    (
        "Wait, are you sure about this\nbecause I watched this TikTok",
        "等等，你确定吗？我在TikTok上看过一个视频，",
    ),
    ("Set an alarm reminding me\nto TikTok tonight", "设个闹钟，提醒我今晚发TikTok，"),
    ('<i>E adesso di\':</i> "Rouge".', '现在跟着念：“Rouge”。'),
    ('[marcando la "R"] <i>Rouge, rouge...</i>', '[加重R音]Rouge，rouge……'),
    ("Watch it on YouTube.", "去YouTube看。"),
    ("She bought an iPhone.", "她买了台iPhone。"),
    ("We sold it on eBay.", "我们在eBay上卖掉了。"),
    ('Repeat "merci".', '跟着念：“merci”。'),
    ('Pronounce the word "bonjour".', '练习发音：“bonjour”。'),
    ('Adesso di\': "bleu".', '现在念：“bleu”。'),
    ('[marcando la "S"] Soleil, soleil...', '[加重S音]Soleil，soleil……'),
    ('[stressing the "T"] Toto, toto...', '[加重T音]Toto，toto……'),
])
def test_source_backed_brand_and_pronunciation_are_not_english_residue(source, translation):
    report = run_quality_checks([_block(source, translation)], target_language="简体中文")
    assert not any(issue.type == "english_residue" for issue in report.issues)
    assert translation_candidate_contract_error(
        source, translation, target_language="简体中文",
    ) == ""


@pytest.mark.parametrize(("source", "translation"), [
    ("Watch this video.", "去TikTok看视频。"),
    ("I watched this TikTok", "I watched this TikTok"),
    ("I watched this TikTok", "我看了this TikTok"),
    ('E adesso di\': "Rouge".', 'E adesso di\': "Rouge".'),
    ('[marcando la "R"] Rouge, rouge...', 'Rouge，rouge，keep repeating……'),
    ("Her rouge was bright red.", "她的rouge很鲜艳。"),
    ("Rouge is the name of this place.", "Rouge是地名。"),
    ("Say hello.", "现在念Rouge。"),
    ("I watched MyTikTokChannel", "我看了TikTok。"),
    ("I watched YouTube yesterday.", "I watched YouTube yesterday."),
    ("She bought an iPhone.", "她bought了iPhone。"),
    ("We sold it on eBay.", "我们在ebay上卖掉了。"),
    ('Say "hello world".', '念hello world。'),
    ('The word "merci" is written here.', '这里写着merci。'),
    ('Repeat "merci".', '念bonjour。'),
    ('[stressing the "T"] Take the train.', 'Take the train.'),
    ('[marcando la "Z"] Bonjour, bonjour...', 'Bonjour，bonjour……'),
])
def test_retention_exceptions_do_not_hide_untranslated_or_unsupported_words(source, translation):
    report = run_quality_checks([_block(source, translation)], target_language="简体中文")
    assert any(issue.type == "english_residue" for issue in report.issues)


def test_retained_brand_still_counts_toward_reading_load():
    report = run_quality_checks([
        _block(
            "Wait, are you sure about this\nbecause I watched this TikTok",
            "等等，你确定吗？我在TikTok上看过一个视频，",
            seconds=1.535,
        ),
    ], target_language="简体中文")
    types = {issue.type for issue in report.issues}
    assert "english_residue" not in types
    assert "reading_speed_too_fast" in types


def test_fullwidth_sound_cleanup_preserves_mixed_dialogue():
    source = "Do not move. [Eden exhaling]"
    block = _block(source, "别动。［伊登呼气］")
    assert clean_sound_description_translation_text(
        block.translation, source_text=source,
    ) == "别动。"
    normalize_sound_description_translations([block])
    assert block.translation == "别动。"
    decision = classify_subtitle_source("Do not move. ［Eden exhaling］")
    assert decision.kind == "mixed"
    assert decision.dialogue_text == "Do not move."


def test_fullwidth_sound_only_cue_obeys_source_omission_policy():
    block = _block("［Eden exhaling］", "［伊登呼气］")
    assert classify_subtitle_source(block.text).kind == "sound"
    normalize_sound_description_translations([block])
    assert block.translation == ""
    report = run_quality_checks([block], target_language="简体中文")
    assert not any(issue.type == "missing_translation" for issue in report.issues)


@pytest.mark.parametrize("translation", [
    "［我听见音乐了。］",
    "［亨利］还能查她的手机吗？",
    "［火星人］有很多因素会影响。",
])
def test_fullwidth_brackets_do_not_authorize_removing_dialogue_or_labels(translation):
    assert clean_sound_description_translation_text(translation) == translation


@pytest.mark.parametrize("brackets", [("[", "]"), ("［", "］")])
@pytest.mark.parametrize("marker", ["- ", "– ", "—"])
def test_sound_cleanup_keeps_dual_speaker_lines_and_contract(brackets, marker):
    left, right = brackets
    source = f"{marker}[sighs]Do not move.\n{marker}Okay."
    translation = f"{marker}{left}叹气{right}别动。\n{marker}好。"
    block = _block(source, translation)
    normalize_sound_description_translations([block])
    assert block.translation == f"{marker}别动。\n{marker}好。"
    assert translation_candidate_contract_error(
        source, block.translation, target_language="简体中文",
    ) == ""
    assert translation_candidate_contract_error(
        source, "别动。好。", target_language="简体中文",
    ) == "candidate_contract:speaker_structure"


@pytest.mark.parametrize("action", [
    "inhale", "inhales", "inhaled", "inhaling",
    "exhale", "exhales", "exhaled", "exhaling",
])
def test_breathing_sound_inflections_are_not_missing_dialogue(action):
    assert classify_subtitle_source(f"[Eden {action}]").kind == "sound"


@pytest.mark.parametrize("source", [
    "[I am exhaling.]",
    "Eden is inhaling deeply.",
    "［我正在呼气。］",
])
def test_breathing_words_in_dialogue_are_not_sound_omissions(source):
    decision = classify_subtitle_source(source)
    assert decision.requires_translation
    assert decision.dialogue_text == source


def test_unknown_source_brackets_are_preserved_for_review():
    block = _block("[unrecognized annotation] Hello.", "［伊登呼气］你好。")
    assert classify_subtitle_source(block.text).kind == "uncertain"
    normalize_sound_description_translations([block])
    assert block.translation == "［伊登呼气］你好。"


def test_residue_category_does_not_confuse_substring_with_subtitle_id():
    residue = QualityIssue("english_residue", "warning", 1, "Untranslated content")
    duplicate = QualityIssue("duplicate_id", "error", 1, "Repeated subtitle ID")
    assert residue.to_dict()["category"] == "content"
    assert duplicate.to_dict()["category"] == "format"
    assert grouped_issue_summary([residue, duplicate])["by_category"] == {
        "content": 1, "format": 1,
    }


@pytest.mark.parametrize("origin", ["project", "manual", "context"])
@pytest.mark.parametrize(("source", "translation", "has_residue"), [
    ("North Star called.", "North Star来电了。", False),
    ("The company called.", "North Star来电了。", True),
    ("North Star called.", "North Star called.", True),
    ("North Star called.", "North来电了。", True),
    ("North Star called.", "North Starship来电了。", True),
    ("North Starling called.", "North Star来电了。", True),
    ("North Star called.", "north star来电了。", True),
])
def test_approved_latin_terms_require_source_evidence_and_exact_target_span(
    origin, source, translation, has_residue,
):
    from app.engines.kb_models import ProjectKb, TermEntry

    if origin == "project":
        options = {"project_kb": ProjectKb(brands=[
            TermEntry(source="North Star", target="North Star"),
        ])}
    elif origin == "manual":
        options = {"meta_info": {"manual_terms": "North Star=North Star"}}
    else:
        options = {"trace": {"kb_hits": [{
            "scope": "project", "source": "North Star", "target": "North Star",
        }]}}
    report = run_quality_checks(
        [_block(source, translation)], target_language="简体中文", **options,
    )
    assert any(issue.type == "english_residue" for issue in report.issues) is has_residue


@pytest.mark.parametrize("options", [
    {},
    {"trace": {"kb_hits": [{
        "scope": "external", "source": "North Star", "target": "North Star",
    }]}},
    {"meta_info": {"manual_terms": "North Star=北极星"}},
])
def test_source_term_alone_or_translated_target_does_not_authorize_latin_retention(options):
    report = run_quality_checks(
        [_block("North Star called.", "North Star来电了。")],
        target_language="简体中文",
        **options,
    )
    assert any(issue.type == "english_residue" for issue in report.issues)


@pytest.mark.parametrize(("source", "translation", "has_warning"), [
    ("No, no, no!", "不，不，不！", False),
    ("Oh, no, no, no. I'm making an ice rink.", "不不不，我在建溜冰场呢。", False),
    ("Move back, move back, move back!", "退，退，退！", False),
    ("Bah-bah-bah-noo-mah.", "巴巴巴努玛。", False),
    ("不不不！", "不不不！", False),
    ("No, no, no. Go, go, go.", "不不不，走走走。", False),
    ("No.", "不不不。", True),
    ("Move back.", "退，退，退！", True),
    ("No, no, no.", "不不不不。", True),
    ("No, no, no. Go.", "不不不，走走走。", True),
])
def test_repetition_warning_requires_target_growth_beyond_source_evidence(
    source, translation, has_warning,
):
    block = _block(source, translation)
    report = run_quality_checks([block], target_language="简体中文")
    assert any(
        issue.type == "repetition_not_compressed" for issue in report.issues
    ) is has_warning
    assert block.translation == translation


def test_deliberate_repetition_still_counts_toward_display_load():
    report = run_quality_checks(
        [_block("No, no, no, no, no!", "不，不，不，不，不！", seconds=0.5)],
        target_language="简体中文",
    )
    types = {issue.type for issue in report.issues}
    assert "repetition_not_compressed" not in types
    assert "reading_speed_too_fast" in types
