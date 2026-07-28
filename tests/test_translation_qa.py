from datetime import timedelta
import json

import pytest

from app.utils.srt import SubtitleBlock


def _block(index, text, translation="", filtered=False):
    return SubtitleBlock(
        index=index,
        start=timedelta(seconds=index),
        end=timedelta(seconds=index + 1),
        text=text,
        translation=translation,
        filtered=filtered,
    )


def test_quality_checks_detect_common_deterministic_issues():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet.", "哈德森橡树很安静。"),
        _block(1, "Hello there.", ""),
        _block(3, "Are you okay?", "Are you okay?"),
        _block(4, "[ Dramatic music plays ]", "戏剧性音乐响起"),
        _block(5, "Long line", "这是一条非常非常非常非常非常非常非常非常非常非常长的字幕"),
    ]
    kb = ProjectKb(places=[TermEntry(source="Hudson Oaks", target="哈德逊奥克斯")])

    report = run_quality_checks(blocks, project_kb=kb, target_language="简体中文", max_chars=18)
    issue_types = {issue.type for issue in report.issues}

    assert "kb_term_missing" in issue_types
    assert "missing_translation" in issue_types
    assert "english_residue" in issue_types
    assert "duplicate_id" in issue_types
    assert "sound_description_translated" in issue_types
    assert "line_too_long" in issue_types
    assert report.summary["issue_count"] == len(report.issues)
    assert report.summary["far"]["functional"] >= 2
    assert report.summary["far"]["acceptability"] >= 1
    assert report.summary["far"]["readability"] >= 1


def test_quality_checks_block_collapsed_or_unmarked_two_speaker_lines():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(
            21,
            "- Did you see it?\n- Yes.",
            "你看见了吗？看见了。",
        ),
        _block(
            22,
            "MARA: Stay here.\nIVO: No.",
            "玛拉：留在这里。伊沃：不。",
        ),
        _block(
            23,
            "This ordinary source wrap\nis not a speaker boundary.",
            "这只是普通换行，不是说话人边界。",
        ),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    issues = [
        issue for issue in report.issues
        if issue.type == "speaker_line_structure_mismatch"
    ]
    assert [(issue.block_id, issue.expected) for issue in issues] == [
        (21, "2 dialogue-marker lines"),
        (22, "2 speaker-label lines"),
    ]
    assert report.status == "needs_review"
    assert report.unresolved_blocks == [21, 22]


def test_quality_checks_accept_preserved_two_speaker_line_structure():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(
            31,
            "- Did you see it?\n- Yes.",
            "- 你看见了吗？\n- 看见了。",
        ),
        _block(
            32,
            "MARA: Stay here.\nIVO: No.",
            "玛拉：留在这里。\n伊沃：不。",
        ),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert "speaker_line_structure_mismatch" not in report.summary["by_type"]


def test_quality_checks_detect_mixed_and_long_speaker_structures():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(
            33,
            "-No space after marker\nSECONDARY COORDINATOR: Hold.",
            "先等等，协调员让我们别动。",
        ),
        _block(
            34,
            "INTERNATIONAL RESPONSE COORDINATOR: Hold.\n"
            "SECONDARY OPERATIONS DIRECTOR: Go.",
            "先等等，然后行动。",
        ),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    issues = [
        issue for issue in report.issues
        if issue.type == "speaker_line_structure_mismatch"
    ]
    assert [issue.block_id for issue in issues] == [33, 34]


def test_quality_checks_do_not_classify_single_marker_plus_continuation_as_two_speakers():
    from app.engines.translation_qa import run_quality_checks

    report = run_quality_checks(
        [
            _block(
                35,
                "- Wait,\nthis is still the same speaker.",
                "等等，这仍然是同一个人说的话。",
            ),
        ],
        target_language="简体中文",
        max_chars=40,
    )

    assert "speaker_line_structure_mismatch" not in report.summary["by_type"]


def test_quality_checks_enforce_context_selected_domain_term_drift():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(41, "The Aether Gate is open.", "以太之门已经打开。"),
        _block(42, "Return to the Aether Gate.", "回到艾瑟门。"),
        _block(43, "Guard the Aether Gate.", "守住以太之门。"),
    ]
    trace = {
        "kb_hits": [{
            "source": "Aether Gate",
            "target": "以太之门",
            "scope": "curated_domain",
        }],
    }

    report = run_quality_checks(
        blocks,
        target_language="简体中文",
        max_chars=40,
        trace=trace,
    )

    issues = [
        issue for issue in report.issues
        if issue.type == "context_term_missing"
    ]
    assert [(issue.block_id, issue.expected) for issue in issues] == [
        (42, "以太之门"),
    ]
    assert report.status == "needs_review"


def test_quality_checks_enforce_repeated_cjk_project_place_term():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(44, "北港已经封锁。", "North Harbor is closed."),
        _block(45, "返回北港基地。", "Return to Northern Port base."),
    ]
    kb = ProjectKb(
        places=[TermEntry(source="北港", target="North Harbor")],
    )

    report = run_quality_checks(
        blocks,
        project_kb=kb,
        target_language="English",
        max_chars=40,
    )

    issues = [issue for issue in report.issues if issue.type == "kb_term_missing"]
    assert [(issue.block_id, issue.expected) for issue in issues] == [
        (45, "North Harbor"),
    ]


def test_quality_checks_match_ascii_terms_inside_cjk_and_respect_ascii_boundaries():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.translation_qa import run_quality_checks

    kb = ProjectKb(
        characters=[TermEntry(source="Ann", target="安")],
        brands=[TermEntry(source="API", target="应用接口")],
    )
    blocks = [
        _block(46, "调用API接口。", "调用接口。"),
        _block(47, "Annette arrived.", "安妮特到了。"),
    ]

    report = run_quality_checks(
        blocks,
        project_kb=kb,
        target_language="简体中文",
        max_chars=40,
    )

    issues = [issue for issue in report.issues if issue.type == "kb_term_missing"]
    assert [(issue.block_id, issue.expected) for issue in issues] == [
        (46, "应用接口"),
    ]


def test_quality_checks_normalize_target_whitespace_and_boundaries():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.translation_qa import run_quality_checks

    kb = ProjectKb(
        characters=[TermEntry(source="阿安", target="Ann")],
        places=[TermEntry(source="北港", target="North Harbor")],
        brands=[TermEntry(source="接口", target="API")],
    )
    blocks = [
        _block(48, "返回北港。", "Return to North\nHarbor."),
        _block(49, "阿安到了。", "Annette arrived."),
        _block(50, "调用接口。", "调用API接口。"),
    ]

    report = run_quality_checks(
        blocks,
        project_kb=kb,
        target_language="English",
        max_chars=40,
    )

    issues = [issue for issue in report.issues if issue.type == "kb_term_missing"]
    assert [(issue.block_id, issue.expected) for issue in issues] == [
        (49, "Ann"),
    ]


def test_quality_checks_allow_uppercase_acronyms_in_chinese_subtitles():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "That's James Richardson from SIS.", "那是SIS的詹姆斯·理查森。"),
        _block(2, "the UAE and the RSF.", "阿联酋和RSF。"),
        _block(3, "a new partnership CEO.", "新合资公司的CEO。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert "english_residue" not in report.summary["by_type"]


def test_quality_checks_treat_positioned_sound_descriptions_as_report_only():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "{\\an8}[Sami crying]", "{\\an8}[萨米哭泣]"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=10)

    assert report.status == "ok"
    assert report.unresolved_blocks == []
    assert report.summary["by_type"] == {"sound_description_translated": 1}
    assert report.summary["report_only_warning_count"] == 1


def test_quality_checks_skip_style_rules_for_inaudible_music_markers():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "- ♪ - [dialogue inaudible]", "♪\n[对话听不清]"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=4)

    assert report.status == "ok"
    assert report.unresolved_blocks == []
    assert "weak_semantic_line_break" not in report.summary["by_type"]
    assert "line_too_long" not in report.summary["by_type"]
    assert report.summary["by_type"] == {"sound_description_translated": 1}


def test_quality_checks_allow_blank_music_only_rows():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "♪", ""),
        _block(2, "🎵", ""),
        _block(3, "(UNSETTLING MUSIC PLAYING)", ""),
        _block(4, "(PANTS)\n(MUSIC CONCLUDES)", ""),
        _block(5, "{\\an8}<i>[speaking Arabic]</i>", ""),
        _block(6, "{\\an8}<i>[in Arabic]</i>", ""),
        _block(7, "[insects trilling]", ""),
        _block(8, "[bullets ricocheting off car]", ""),
        _block(9, "[Ischigualastia cries]", ""),
        _block(10, "[drawer opens, closes]", ""),
        _block(11, "(HAUNTING MUSICAL STING PLAYS)", ""),
        _block(12, "- [loud thud]\n- [squelch]", ""),
        _block(13, "- [laughter]\n- [phone ringing]", ""),
        _block(14, "[typing]", ""),
        _block(15, "[giggles]", ""),
        _block(16, "[waves lapping]", ""),
        _block(17, "[kissing sounds]", ""),
        _block(18, "[wings fluttering]", ""),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=4)

    assert report.status == "ok"
    assert report.issues == []
    assert report.unresolved_blocks == []


@pytest.mark.parametrize("source", [
    "[gunshots]\n[people shouting]",
    "[tense music continues]\n[shouting]",
    "[cork popping]\n[cheering]",
    "[gentle music]\n[cup popping]",
    "[walkers groaning]",
    "-[Negan grunting]\n-[walkers snarling]",
    "[The Croat breathing heavily]",
    "[Negan sighs]",
    "[lock rattling]",
    "[machines beeping]",
    "[sobs hysterically]",
    "[lively chatter]",
])
def test_sound_description_classifier_covers_export_regression_cues(source):
    from app.engines.translation_qa import is_sound_description_source

    assert is_sound_description_source(source) is True


@pytest.mark.parametrize(
    "source",
    [
        "♪\n-Go!",
        "♪ instrumental music ♪\n-Go!",
        "RUNNING WATER\n-Go!",
        "APPLAUSE\n-Go!",
    ],
)
def test_mixed_sound_lines_keep_dialogue_translatable_and_visible_to_qa(source):
    from app.engines.translation_qa import (
        dialogue_only_qa_source_text,
        is_sound_description_source,
        run_quality_checks,
    )

    assert is_sound_description_source(source) is False
    assert dialogue_only_qa_source_text(source) == "-Go!"

    report = run_quality_checks(
        [_block(70, source, "")],
        target_language="简体中文",
        max_chars=40,
    )
    assert report.summary["by_type"]["missing_translation"] == 1


def test_quality_checks_exclude_pure_sound_rows_from_translation_and_term_contracts():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.translation_qa import run_quality_checks

    source = "[Hershel coughing]\n[walkers growling]"
    report = run_quality_checks(
        [_block(71, source, "")],
        project_kb=ProjectKb(
            characters=[TermEntry(source="Hershel", target="赫歇尔")],
        ),
        target_language="简体中文",
        meta_info={"manual_terms": "walkers=行尸"},
        trace={
            "kb_hits": [{
                "source": "Hershel",
                "target": "赫歇尔",
                "scope": "project",
            }],
        },
    )

    forbidden = {
        "missing_translation",
        "kb_term_missing",
        "manual_term_missing",
        "context_term_missing",
        "canonical_term_missing",
    }
    assert forbidden.isdisjoint(report.summary["by_type"])
    assert report.status == "ok"


@pytest.mark.parametrize(
    ("source", "draft", "expected"),
    [
        ("-[Negan scoffing]\n-Armstrong...", "-[内根嗤笑]\n-阿姆斯特朗……", "-阿姆斯特朗……"),
        ("-[Maggie] Here.\n-[chuckling]", "-[玛吉] 给你。\n-[轻笑]", "-[玛吉] 给你。"),
    ],
)
def test_mixed_sound_and_dialogue_rows_allow_omitted_sound_without_speaker_mismatch(
    source,
    draft,
    expected,
):
    from app.engines.translation_qa import (
        normalize_sound_description_translations,
        run_quality_checks,
    )

    block = _block(72, source, draft)
    normalize_sound_description_translations([block])
    report = run_quality_checks(
        [block],
        target_language="简体中文",
        max_chars=40,
    )

    assert block.translation == expected
    assert "speaker_line_structure_mismatch" not in report.summary["by_type"]
    assert "missing_translation" not in report.summary["by_type"]


def test_mixed_sound_cue_terms_are_not_dialogue_terminology_obligations():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.translation_qa import run_quality_checks

    source = "-[Hershel coughing]\n-Go!"
    term_context = {
        "project_kb": ProjectKb(
            characters=[TermEntry(source="Hershel", target="赫歇尔")],
        ),
        "meta_info": {"manual_terms": "Hershel=赫歇尔"},
        "trace": {
            "kb_hits": [{
                "source": "Hershel",
                "target": "赫歇尔",
                "scope": "project",
            }],
        },
    }

    sound_report = run_quality_checks(
        [_block(74, source, "-走！")],
        target_language="简体中文",
        max_chars=40,
        **term_context,
    )
    dialogue_report = run_quality_checks(
        [_block(75, "-[Maggie] Hershel, go!", "-[玛吉] 走！")],
        target_language="简体中文",
        max_chars=40,
        **term_context,
    )
    sound_core_domain_report = run_quality_checks(
        [
            _block(76, "-[D-Day explosion]\n-Go!", "-走！"),
            _block(77, "-[Pangaea rumbling]\n-Go!", "-走！"),
        ],
        target_language="简体中文",
        max_chars=40,
    )
    dialogue_core_domain_report = run_quality_checks(
        [_block(78, "-[Maggie] D-Day and Pangaea, go!", "-[玛吉] 走！")],
        target_language="简体中文",
        max_chars=40,
    )

    term_issue_types = {
        "kb_term_missing",
        "manual_term_missing",
        "context_term_missing",
    }
    assert term_issue_types.isdisjoint(sound_report.summary["by_type"])
    assert term_issue_types <= set(dialogue_report.summary["by_type"])
    assert {
        "core_term_inconsistent",
        "canonical_term_missing",
    }.isdisjoint(sound_core_domain_report.summary["by_type"])
    assert {
        "core_term_inconsistent",
        "canonical_term_missing",
    } <= set(dialogue_core_domain_report.summary["by_type"])


def test_quality_checks_still_require_both_real_dialogue_speaker_lines():
    from app.engines.translation_qa import run_quality_checks

    report = run_quality_checks(
        [_block(73, "- First answer.\n- Second answer.", "- 第一个回答。")],
        target_language="简体中文",
        max_chars=40,
    )

    assert report.summary["by_type"]["speaker_line_structure_mismatch"] == 1


def test_quality_checks_do_not_treat_speaker_labels_as_sound_descriptions():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "[The Martian]", "[火星人]"),
        _block(2, "A young Ischigualastia calls.", "幼年伊斯基瓜拉兽在呼唤。"),
        _block(3, "David Selznick calls me up.", "大卫·塞尔兹尼克给我打电话。"),
        _block(4, "Wind 18 knots, west, southwest.", "西南偏西风，18节。"),
        _block(5, "That car,", "那辆车，"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=20)

    assert "sound_description_translated" not in report.summary["by_type"]


def test_quality_checks_do_not_treat_scientific_action_sentences_as_sound_descriptions():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Panphagia runs.", "泛食龙跑过。"),
        _block(2, "Novaraptor runs.", "诺瓦盗龙跑过。"),
        _block(3, "[drawer opens]", ""),
        _block(4, "RUNNING WATER", ""),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert "sound_description_translated" not in report.summary["by_type"]
    assert "missing_translation" not in report.summary["by_type"]


def test_normalize_sound_description_translations_blanks_non_dialogue_rows():
    from app.engines.translation_qa import normalize_sound_description_translations

    blocks = [
        _block(1, "{\\an8}[phone ringing]", "{\\an8}[电话响]"),
        _block(2, "- [elevator bell chimes]\n- [phone vibrating]", "[电梯铃响]\n[手机振动]"),
        _block(3, "<i>- Please leave a message.</i>\n- [phone vibrates]", "请留言。\n[手机振动]"),
        _block(4, "Owen, are you okay?", "[尖叫] 欧文没事吧？"),
        _block(5, "The Martian said it mattered.", "[火星人] 有很多因素会影响。"),
        _block(6, "Hello.", "你好。"),
        _block(7, "That car,", "那辆车，"),
    ]

    applied = normalize_sound_description_translations(blocks)

    assert applied == [
        {
            "id": 1,
            "source": "{\\an8}[phone ringing]",
            "from": "{\\an8}[电话响]",
            "to": "",
            "reason": "sound_description_blank",
        },
        {
            "id": 2,
            "source": "- [elevator bell chimes]\n- [phone vibrating]",
            "from": "[电梯铃响]\n[手机振动]",
            "to": "",
            "reason": "sound_description_blank",
        },
        {
            "id": 3,
            "source": "<i>- Please leave a message.</i>\n- [phone vibrates]",
            "from": "请留言。\n[手机振动]",
            "to": "请留言。",
            "reason": "translation_sound_description_clean",
        },
        {
            "id": 4,
            "source": "Owen, are you okay?",
            "from": "[尖叫] 欧文没事吧？",
            "to": "欧文没事吧？",
            "reason": "translation_sound_description_clean",
        },
    ]
    assert blocks[0].translation == ""
    assert blocks[1].translation == ""
    assert blocks[2].translation == "请留言。"
    assert blocks[3].translation == "欧文没事吧？"
    assert blocks[4].translation == "[火星人] 有很多因素会影响。"
    assert blocks[5].translation == "你好。"
    assert blocks[6].translation == "那辆车，"


def test_clean_sound_description_translation_text_keeps_speaker_labels():
    from app.engines.translation_qa import clean_sound_description_translation_text

    assert clean_sound_description_translation_text("（激昂音乐响起）") == ""
    assert clean_sound_description_translation_text("- [女人们大笑]") == ""
    assert clean_sound_description_translation_text("[轻笑] 你这一来，真及时。") == "你这一来，真及时。"
    assert clean_sound_description_translation_text("[婴儿哭] -嘘。") == "嘘。"
    assert clean_sound_description_translation_text("[亨利] 还能查她的手机吗？") == "[亨利] 还能查她的手机吗？"


def test_clean_sound_description_translation_text_handles_safe_unbracketed_labels():
    from app.engines.translation_qa import clean_sound_description_translation_text

    assert clean_sound_description_translation_text("无可闻对白") == ""
    assert clean_sound_description_translation_text("无可闻对白 你好。") == "你好。"
    assert clean_sound_description_translation_text("POUNDING") == "POUNDING"
    assert (
        clean_sound_description_translation_text("POUNDING ON DOOR - 你好。")
        == "POUNDING ON DOOR - 你好。"
    )
    assert (
        clean_sound_description_translation_text("NO AUDIBLE DIALOGUE")
        == "NO AUDIBLE DIALOGUE"
    )
    assert (
        clean_sound_description_translation_text(
            "POUNDING",
            source_text="POUNDING",
        )
        == ""
    )
    assert (
        clean_sound_description_translation_text(
            "POUNDING ON DOOR - 你好。",
            source_text="[POUNDING ON DOOR]\nHello.",
        )
        == "你好。"
    )


@pytest.mark.parametrize(
    "dialogue",
    [
        "我听不到对白里那句话。",
        "听不到对白",
        "你好。门上有人重重敲打。",
        "That pounding headache is awful.",
        "I laugh",
        "We knock",
        "Please whistle",
        "Stop pounding - 你好。",
    ],
)
def test_clean_sound_description_translation_text_keeps_unbracketed_dialogue(dialogue):
    from app.engines.translation_qa import clean_sound_description_translation_text

    assert clean_sound_description_translation_text(dialogue) == dialogue


def test_normalize_sound_description_translations_aligns_unbracketed_target_to_source():
    from app.engines.translation_qa import normalize_sound_description_translations

    blocks = [
        _block(1, "I laugh.", "I LAUGH"),
        _block(2, "We knock before entering.", "WE KNOCK"),
        _block(3, "Please whistle when ready.", "PLEASE WHISTLE"),
        _block(4, "Stop pounding and listen.", "STOP POUNDING - 你好。"),
        _block(5, "The car is here.", "CAR IS HERE"),
        _block(6, "[POUNDING ON DOOR]\nHello.", "POUNDING ON DOOR - 你好。"),
        _block(7, "POUNDING", "POUNDING"),
        _block(8, "Hello.", "无可闻对白 你好。"),
    ]

    normalize_sound_description_translations(blocks)

    assert [block.translation for block in blocks] == [
        "I LAUGH",
        "WE KNOCK",
        "PLEASE WHISTLE",
        "STOP POUNDING - 你好。",
        "CAR IS HERE",
        "你好。",
        "",
        "你好。",
    ]


def test_annotate_contextual_speaker_translations_marks_background_sources():
    from app.engines.translation_qa import annotate_contextual_speaker_translations

    blocks = [
        _block(1, "ANNOUNCER: Welcome to trivia night.", "欢迎来到问答之夜。"),
        _block(2, "ON TV: Breaking news.", "突发新闻。"),
        _block(3, "NIKKI: I need air.", "我需要透透气。"),
        _block(4, "HOST: Last call.", "主持人：最后一轮。"),
        _block(5, "RADIO: Weather update.", "【广播】天气更新。"),
        _block(6, "M.C.: Take it away.", "开始吧。"),
    ]

    applied = annotate_contextual_speaker_translations(blocks, target_language="简体中文")

    assert [(item["id"], item["marker"]) for item in applied] == [
        (1, "【主持人】"),
        (2, "【电视】"),
        (4, "【主持人】"),
        (6, "【主持人】"),
    ]
    assert blocks[0].translation == "【主持人】欢迎来到问答之夜。"
    assert blocks[1].translation == "【电视】突发新闻。"
    assert blocks[2].translation == "我需要透透气。"
    assert blocks[3].translation == "【主持人】最后一轮。"
    assert blocks[4].translation == "【广播】天气更新。"
    assert blocks[5].translation == "【主持人】开始吧。"


def test_quality_report_serializes_json_and_markdown(tmp_path):
    from app.engines.translation_qa import (
        QualityIssue,
        TranslationQaReport,
        quality_content_hash,
        save_quality_report,
    )

    report = TranslationQaReport(
        status="needs_review",
        run_id="qa-run-123",
        content_hash=quality_content_hash([
            _block(1, "Hello", "你好"),
            _block(2, "World", "世界"),
        ]),
        issues=[
            QualityIssue(
                type="missing_translation",
                severity="error",
                block_id=2,
                message="missing",
                source_text="Hello",
                translation="",
            )
        ],
        summary={"issue_count": 1},
    )

    json_path = tmp_path / "translation_qa_report.json"
    md_path = tmp_path / "translation_qa_report.md"
    save_quality_report(report, json_path=json_path, markdown_path=md_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "qa-run-123"
    assert payload["content_hash"] == "sha256:d2fdf133c0218be6633b3784826e140e2db21de774ccf4579c62bd671c386f52"
    assert payload["issues"][0]["type"] == "missing_translation"
    markdown = md_path.read_text(encoding="utf-8")
    assert "# Translation QA Report" in markdown
    assert "qa-run-123" in markdown
    assert payload["content_hash"] in markdown
    assert "missing_translation" in markdown


def test_repair_prompt_contains_only_failing_blocks():
    from app.engines.translation_qa import QualityIssue, build_repair_items, build_repair_prompt

    blocks = [
        _block(1, "Good", "好"),
        _block(2, "Hudson Oaks", "哈德森橡树"),
    ]
    issues = [
        QualityIssue(
            type="kb_term_missing",
            severity="error",
            block_id=2,
            message="Use 哈德逊奥克斯",
            source_text="Hudson Oaks",
            translation="哈德森橡树",
        )
    ]

    items = build_repair_items(blocks, issues)
    prompt = build_repair_prompt("简体中文", items, issues, kb_terms={"Hudson Oaks": "哈德逊奥克斯"})

    assert items == [{
        "id": 2,
        "original": "Hudson Oaks",
        "draft": "哈德森橡树",
        "preceding_context": [{
            "id": 1,
            "original": "Good",
            "draft": "好",
        }],
        "following_context": [],
    }]
    assert '"preceding_context": [{"id": 1, "original": "Good"' in prompt
    assert "Hudson Oaks" in prompt
    assert "哈德逊奥克斯" in prompt


def test_repair_prompt_requires_speaker_line_structure_and_context_terms():
    from app.engines.translation_qa import QualityIssue, build_repair_prompt

    issues = [
        QualityIssue(
            type="speaker_line_structure_mismatch",
            severity="error",
            block_id=51,
            message="two speaker lines were merged",
            source_text="- Are you ready?\n- Ready.",
            translation="准备好了吗？好了。",
            expected="2 dialogue-marker lines",
        ),
        QualityIssue(
            type="context_term_missing",
            severity="error",
            block_id=51,
            message="expected selected term Aether Gate → 以太之门",
            source_text="- Aether Gate?\n- Aether Gate.",
            translation="- 艾瑟门？\n- 艾瑟门。",
            expected="以太之门",
        ),
    ]

    prompt = build_repair_prompt(
        "简体中文",
        [{
            "id": 51,
            "original": "- Aether Gate?\n- Aether Gate.",
            "draft": "- 艾瑟门？\n- 艾瑟门。",
        }],
        issues,
        kb_terms={"Aether Gate": "以太之门"},
    )

    assert "每位说话人独占一行" in prompt
    assert "不得合并说话人行" in prompt
    assert "expected 指定的译法" in prompt


def test_repair_items_include_bounded_context_and_group_adjacent_semantic_findings():
    from app.engines.translation_qa import QualityIssue, build_repair_items

    blocks = [
        _block(10, "He never came back.", "他再也没回来。"),
        _block(11, "Not after what happened.", "那件事之后就没有。"),
        _block(12, "You know why.", "你知道为什么。"),
        _block(13, "I wish I did.", "我倒希望自己知道。"),
        _block(14, "Let's go.", "走吧。"),
    ]
    issues = [
        QualityIssue(
            type="semantic_mismatch",
            severity="error",
            block_id=11,
            message="meaning crosses the cue boundary",
        ),
        QualityIssue(
            type="semantic_mismatch",
            severity="error",
            block_id=12,
            message="meaning crosses the cue boundary",
        ),
    ]

    items = build_repair_items(blocks, issues)

    assert [item["id"] for item in items] == [11, 12]
    assert items[0]["preceding_context"] == [{
        "id": 10,
        "original": "He never came back.",
        "draft": "他再也没回来。",
    }]
    assert items[0]["following_context"] == [{
        "id": 12,
        "original": "You know why.",
        "draft": "你知道为什么。",
    }]
    assert items[1]["preceding_context"] == [{
        "id": 11,
        "original": "Not after what happened.",
        "draft": "那件事之后就没有。",
    }]
    assert items[1]["following_context"] == [{
        "id": 13,
        "original": "I wish I did.",
        "draft": "我倒希望自己知道。",
    }]
    assert items[0]["semantic_group_ids"] == [11, 12]
    assert items[1]["semantic_group_ids"] == [11, 12]
    assert all(14 not in item["semantic_group_ids"] for item in items)


@pytest.mark.parametrize(
    "source",
    [
        "[POUNDING]",
        "[WHISTLES]",
        "[GURGLING]",
        "[FROGS CROAKING]",
        "[NO AUDIBLE DIALOGUE]",
        "NO DISCERNIBLE DIALOGUE",
    ],
)
def test_sound_description_source_recognizes_common_production_forms(source):
    from app.engines.translation_qa import is_sound_description_source

    assert is_sound_description_source(source) is True


@pytest.mark.parametrize(
    "translation",
    [
        "[POUNDING]",
        "[WHISTLES]",
        "[GURGLING]",
        "[FROGS CROAKING]",
        "[NO AUDIBLE DIALOGUE]",
        "[无可闻对白]",
    ],
)
def test_sound_description_target_recognizes_common_production_forms(translation):
    from app.engines.translation_qa import clean_sound_description_translation_text

    assert clean_sound_description_translation_text(translation) == ""


def test_repair_prompt_gives_reading_speed_compression_guidance():
    from app.engines.translation_qa import QualityIssue, build_repair_items, build_repair_prompt

    blocks = [
        _block(
            7,
            "-Bracken Mountain, North Carolina? -Yes, sir.",
            "-北卡州布拉肯山？ -是，长官。",
        )
    ]
    issues = [
        QualityIssue(
            type="reading_speed_too_fast",
            severity="warning",
            block_id=7,
            message="reading speed 11.2 chars/sec exceeds 9.0",
            source_text="-Bracken Mountain, North Carolina? -Yes, sir.",
            translation="-北卡州布拉肯山？ -是，长官。",
            expected="9.0",
        )
    ]
    items = build_repair_items(blocks, issues)

    prompt = build_repair_prompt("简体中文", items, issues)

    assert items[0]["duration_seconds"] == 1.0
    assert items[0]["max_compact_chars"] == 9
    assert items[0]["current_compact_chars"] > items[0]["max_compact_chars"]
    assert "读速超标时必须压缩译文" in prompt
    assert "删除可省略称呼" in prompt
    assert "双人对话" in prompt
    assert "max_compact_chars" in prompt
    assert "必须小于等于该值" in prompt
    assert "超过 max_compact_chars 会再次判失败" in prompt
    assert "删除可省略的重复头衔" in prompt


def test_repair_prompt_gives_core_term_consistency_guidance():
    from app.engines.translation_qa import QualityIssue, build_repair_prompt

    prompt = build_repair_prompt(
        "简体中文",
        [{"id": 5, "original": "The proposed D-Day is Monday.", "draft": "拟定登陆日是星期一。"}],
        [
            QualityIssue(
                type="core_term_inconsistent",
                severity="warning",
                block_id=5,
                message="expected D-Day → D日",
                source_text="The proposed D-Day is Monday.",
                translation="拟定登陆日是星期一。",
                expected="D日",
            )
        ],
    )

    assert "核心术语不一致" in prompt
    assert "expected D-Day → D日" in prompt


def test_repairable_quality_issues_require_expected_for_inferred_consistency():
    from app.engines.translation_qa import QualityIssue, repairable_quality_issues

    issues = [
        QualityIssue(
            type="scientific_term_inconsistent",
            severity="warning",
            block_id=1,
            message="auto-detected scientific term has inconsistent target forms",
        ),
        QualityIssue(
            type="scientific_term_inconsistent",
            severity="warning",
            block_id=2,
            message="auto-detected scientific term has inconsistent target forms",
            expected="伊斯基瓜拉斯兽",
        ),
        QualityIssue(
            type="proper_name_inconsistent",
            severity="warning",
            block_id=3,
            message="inferred proper name uses inconsistent target forms",
        ),
        QualityIssue(
            type="proper_name_inconsistent",
            severity="warning",
            block_id=6,
            message="inferred proper name uses inconsistent target forms",
            expected="萨米娅·扎希尔",
        ),
        QualityIssue(
            type="line_too_long",
            severity="warning",
            block_id=4,
            message="too long",
        ),
        QualityIssue(
            type="kb_term_missing",
            severity="error",
            block_id=5,
            message="expected KB term",
            expected="哈德逊奥克斯",
        ),
    ]

    repairable = repairable_quality_issues(issues)

    assert [issue.block_id for issue in repairable] == [2, 6, 4, 5]


def test_quality_checks_flag_inferred_proper_name_inconsistency():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "哈德逊奥克斯今晚很安静。"),
        _block(2, "I came from Hudson Oaks.", "我从哈德逊橡树来。"),
        _block(3, "Hudson Oaks is closed now.", "哈德逊橡树现在关门了。", filtered=True),
    ]
    for block in blocks:
        block.end = block.start + timedelta(seconds=4)

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert report.summary["by_type"]["proper_name_inconsistent"] == 2
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
    assert {issue.block_id for issue in flagged} == {1, 2}
    assert report.status == "ok"
    assert report.unresolved_blocks == []
    assert report.summary["blocking_issue_count"] == 0
    assert report.summary["report_only_warning_count"] == 2
    assert all(issue.severity == "warning" for issue in flagged)
    assert all(issue.source_text == "Hudson Oaks" for issue in flagged)


def test_quality_checks_mark_majority_proper_name_variant_as_repairable():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "哈德逊奥克斯很安静。"),
        _block(2, "I came from Hudson Oaks.", "我从哈德逊奥克斯来。"),
        _block(3, "Hudson Oaks is closed now.", "哈德逊奥克斯镇已关闭。"),
    ]
    for block in blocks:
        block.end = block.start + timedelta(seconds=4)

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
    repairable = [issue for issue in flagged if issue.expected]

    assert report.status == "ok"
    assert report.summary["blocking_issue_count"] == 0
    assert report.summary["report_only_warning_count"] == 3
    assert report.unresolved_blocks == []
    assert [(issue.block_id, issue.expected) for issue in repairable] == [
        (3, "哈德逊奥克斯")
    ]


def test_quality_checks_do_not_block_when_expected_name_ends_question_phrase():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(441, '"One Wish Willow.', "“一愿柳。"),
        _block(1083, "One Wish Willow?", "一愿柳？"),
        _block(1494, "What's a One Wish Willow?", "什么是一愿柳？"),
    ]
    for block in blocks:
        block.end = block.start + timedelta(seconds=3)

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]

    assert flagged
    assert report.status == "ok"
    assert report.summary["blocking_issue_count"] == 0
    assert report.unresolved_blocks == []


def test_quality_checks_do_not_flag_rank_name_context_as_name_inconsistency():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(36, "Colonel Krick, he requested them.", "克里克上校要的。"),
        _block(62, "It's just, Colonel Krick instructed us otherwise, sir.", "只是克里克上校\n另有指示，长官。"),
        _block(507, "whether Colonel Krick attends or not.", "克里克来不来，预报不变。"),
        _block(924, "what Colonel Krick's just said, that it's going to be safe", "信克里克上校说的："),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert "proper_name_inconsistent" not in report.summary["by_type"]


def test_quality_checks_allow_titled_context_for_core_person_name():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(15, "Group Captain Dr. James Stagg,", "斯塔格博士，空军上校，"),
        _block(95, "Group Captain Dr. James Stagg,", "斯塔格博士，空军上校，"),
        _block(103, "Sir, may I introduce Group Captain James Stagg,", "长官，这位是\n詹姆斯·斯塔格空军上校，"),
        _block(434, "Good afternoon. My name is James Stagg.", "您好，我是詹姆斯·斯塔格。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert "proper_name_inconsistent" not in report.summary["by_type"]


def test_quality_checks_flag_divergent_long_names_without_shared_anchor():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "哈德逊奥克斯"),
        _block(2, "I came from Hudson Oaks.", "赫德森橡树"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert report.summary["by_type"]["proper_name_inconsistent"] == 2
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
    assert {issue.block_id for issue in flagged} == {1, 2}


def test_quality_checks_run_proper_name_metric_for_traditional_chinese_targets():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "哈德遜奧克斯"),
        _block(2, "I came from Hudson Oaks.", "赫德森橡樹"),
    ]

    report = run_quality_checks(blocks, target_language="繁體中文", max_chars=18)

    assert report.summary["by_type"]["proper_name_inconsistent"] == 2
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
    assert {issue.block_id for issue in flagged} == {1, 2}


def test_quality_checks_run_proper_name_metric_for_common_chinese_aliases():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "哈德逊奥克斯"),
        _block(2, "I came from Hudson Oaks.", "赫德森橡树"),
    ]

    for target_language in ("Simplified Chinese", "zh-Hant-TW"):
        report = run_quality_checks(blocks, target_language=target_language, max_chars=18)

        assert report.summary["by_type"]["proper_name_inconsistent"] == 2
        flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
        assert {issue.block_id for issue in flagged} == {1, 2}


def test_normalize_inferred_proper_name_variants_uses_majority_form():
    from app.engines.proper_name_normalizer import normalize_inferred_proper_name_variants

    blocks = [
        _block(1, "You see Samia Zahir today?", "你今天见到萨米娅·扎希尔了？"),
        _block(
            2,
            "Samia Zahir spilled to him when we tried to recruit her.",
            "我们招募萨米娅·查希尔时 她向他泄了底",
        ),
        _block(3, "Through Samia Zahir.", "通过萨米娅·扎希尔。"),
        _block(4, "Mikkel De Bruyne.", "米克尔·德布劳内。"),
        _block(5, "De Bruyne is the vehicle here?", "德布鲁因就是这次行动的载体吗？"),
        _block(6, "Mr. De Bruyne deserves as much as I do.", "德布劳内先生也功不可没。"),
    ]

    applied = normalize_inferred_proper_name_variants(blocks)

    assert {
        (item["id"], item["from"], item["to"])
        for item in applied
    } == {
        (2, "萨米娅·查希尔", "萨米娅·扎希尔"),
        (5, "德布鲁因", "德布劳内"),
    }
    assert blocks[1].translation == "我们招募萨米娅·扎希尔时 她向他泄了底"
    assert blocks[4].translation == "德布劳内就是这次行动的载体吗？"


def test_normalize_inferred_proper_name_variants_skips_ties():
    from app.engines.proper_name_normalizer import normalize_inferred_proper_name_variants

    blocks = [
        _block(1, "Li Na arrived.", "李娜到了。"),
        _block(2, "Li Na smiled.", "丽娜笑了。"),
    ]

    assert normalize_inferred_proper_name_variants(blocks) == []
    assert blocks[0].translation == "李娜到了。"
    assert blocks[1].translation == "丽娜笑了。"


def test_quality_checks_do_not_flag_same_long_cjk_name_in_different_contexts():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "I am going to Hudson Oaks.", "我去哈德逊奥克斯。"),
        _block(2, "She is going to Hudson Oaks.", "她去哈德逊奥克斯。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert "proper_name_inconsistent" not in report.summary["by_type"]


def test_quality_checks_allow_deictic_classifier_prefixes_for_same_name():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(164, "Our Nanuqsaurus couple watch...", "这对纳努克龙伴侣在一旁观察……"),
        _block(
            401,
            "Our Nanuqsaurus is\nnow the last of his kind.",
            "这只纳努克龙\n如今已是同类中的最后一员。",
        ),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert "proper_name_inconsistent" not in report.summary["by_type"]


def test_quality_checks_do_not_flag_short_consistent_cjk_names():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Li Na arrived.", "李娜到了。"),
        _block(2, "I saw Li Na run.", "我看见李娜跑了。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert "proper_name_inconsistent" not in report.summary["by_type"]


def test_quality_checks_flag_inconsistent_short_cjk_names_with_shared_context():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Li Na arrived.", "李娜到了。"),
        _block(2, "Li Na arrived too.", "丽娜到了。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert report.summary["by_type"]["proper_name_inconsistent"] == 2
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
    assert {issue.block_id for issue in flagged} == {1, 2}


def test_quality_checks_skip_proper_name_metric_for_non_chinese_targets():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "Hudson Oaks is quiet tonight."),
        _block(2, "I came from Hudson Oaks.", "I came from Hudson Oaks yesterday."),
    ]

    report = run_quality_checks(blocks, target_language="English", max_chars=40)

    assert "proper_name_inconsistent" not in report.summary["by_type"]


def test_quality_checks_flag_curated_science_term_misses_without_project_kb():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "These little climbers are Suminia.", "这些小小攀爬者是苏米尼亚兽。"),
        _block(2, "A female Dongusuchus.", "一只雌性东乌鳄。"),
        _block(3, "called proto-Pterosaurs, head for the sand.", "新型滑翔爬行动物，正飞向沙滩。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert report.summary["by_type"]["canonical_term_missing"] == 3
    flagged = [issue for issue in report.issues if issue.type == "canonical_term_missing"]
    assert {issue.block_id for issue in flagged} == {1, 2, 3}
    assert {issue.expected for issue in flagged} == {"苏美尼兽", "顿古兹鳄", "原翼龙类"}
    assert all(issue.severity == "warning" for issue in flagged)


def test_quality_checks_project_kb_overrides_curated_science_terms():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "These little climbers are Suminia.", "这些小小攀爬者是苏米尼亚兽。"),
    ]
    kb = ProjectKb(slang=[TermEntry(source="Suminia", target="苏米尼亚兽")])

    report = run_quality_checks(blocks, project_kb=kb, target_language="简体中文", max_chars=40)

    assert "canonical_term_missing" not in report.summary["by_type"]
    assert "kb_term_missing" not in report.summary["by_type"]


def test_quality_checks_flag_auto_scientific_term_inconsistency():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Novaraptor grazes nearby.", "诺瓦盗龙在附近觅食。"),
        _block(2, "A young Novaraptor calls.", "幼年诺法猛禽在呼唤。"),
        _block(3, "The Novaraptor keeps moving.", "诺瓦盗龙继续前进。"),
        _block(4, "Without the Ventosuchus, food is scarce.", "没有温托鳄，食物变少。"),
        _block(5, "Ventosuchus spreads across the valley.", "文都鳄遍布山谷。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    flagged = [issue for issue in report.issues if issue.type == "scientific_term_inconsistent"]
    assert len(flagged) == 5
    assert {issue.block_id for issue in flagged} == {1, 2, 3, 4, 5}
    assert report.summary["by_type"]["scientific_term_inconsistent"] == 5
    messages = {issue.message for issue in flagged}
    assert any("Novaraptor" in message for message in messages)
    assert any("Ventosuchus" in message for message in messages)
    assert all(issue.severity == "warning" for issue in flagged)
    assert {
        (issue.block_id, issue.expected)
        for issue in flagged
        if issue.expected
    } == {(2, "诺瓦盗龙")}


def test_quality_checks_allow_consistent_auto_scientific_term():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Novaraptor grazes nearby.", "诺瓦盗龙在附近觅食。"),
        _block(2, "A young Novaraptor calls.", "幼年诺瓦盗龙在呼唤。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert "scientific_term_inconsistent" not in report.summary["by_type"]


def test_quality_checks_use_curated_paleontology_terms():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Ischigualastia grazes nearby.", "伊斯基瓜拉斯兽在附近觅食。"),
        _block(2, "Dicroidium spreads across the valley.", "双脉蕨遍布山谷。"),
        _block(3, "Panphagia runs.", "泛食龙跑过。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    flagged = [issue for issue in report.issues if issue.type == "canonical_term_missing"]
    assert {issue.block_id for issue in flagged} == {2, 3}
    assert {issue.expected for issue in flagged} == {"双扇蕨", "泛噬龙"}


def test_normalize_curated_domain_term_translations_uses_expected_target():
    from app.engines.translation_qa import normalize_curated_domain_term_translations

    blocks = [
        _block(1, "Ischigualastia grazes nearby.", "伊斯基瓜拉兽在附近觅食。"),
        _block(2, "Dicroidium spreads across the valley.", "双脉蕨遍布山谷。"),
        _block(3, "Panphagia runs.", "泛食龙跑过。"),
    ]

    applied = normalize_curated_domain_term_translations(blocks)

    assert {
        (item["id"], item["source"], item["from"], item["to"])
        for item in applied
    } == {
        (1, "Ischigualastia", "伊斯基瓜拉兽", "伊斯基瓜拉斯兽"),
        (2, "Dicroidium", "双脉蕨", "双扇蕨"),
        (3, "Panphagia", "泛食龙", "泛噬龙"),
    }
    assert blocks[0].translation == "伊斯基瓜拉斯兽在附近觅食。"
    assert blocks[1].translation == "双扇蕨遍布山谷。"
    assert blocks[2].translation == "泛噬龙跑过。"


def test_normalize_scientific_term_translations_uses_majority_suffix_form():
    from app.engines.translation_qa import normalize_scientific_term_translations

    blocks = [
        _block(1, "Novaraptor grazes nearby.", "诺瓦盗龙在附近觅食。"),
        _block(2, "A young Novaraptor calls.", "幼年诺瓦盗兽在呼唤。"),
        _block(3, "The Novaraptor keeps moving.", "诺瓦盗龙继续前进。"),
        _block(4, "Novaraptor returns.", "幼年诺法猛禽在返回。"),
    ]

    applied = normalize_scientific_term_translations(blocks)

    assert applied == [{
        "id": 2,
        "source": "Novaraptor",
        "from": "诺瓦盗兽",
        "to": "诺瓦盗龙",
        "reason": "scientific_term_majority_variant",
    }]
    assert blocks[1].translation == "幼年诺瓦盗龙在呼唤。"
    assert blocks[3].translation == "幼年诺法猛禽在返回。"


def test_quality_checks_flag_core_term_inconsistency():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "D-Day is approaching.", "D日快到了。"),
        _block(2, "The proposed D-Day is Monday.", "拟定登陆日是星期一。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    flagged = [issue for issue in report.issues if issue.type == "core_term_inconsistent"]
    assert len(flagged) == 1
    assert flagged[0].block_id == 2
    assert flagged[0].expected == "D日"


def test_quality_checks_allow_consistent_core_term():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "D-Day is approaching.", "D日快到了。"),
        _block(2, "The proposed D-Day is Monday.", "拟定D日是星期一。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert "core_term_inconsistent" not in report.summary["by_type"]


def test_quality_checks_apply_subtitle_style_profile_rules():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Fast line", "这是一条非常非常非常非常非常非常非常非常非常非常非常非常长的字幕"),
        _block(2, "Too many lines", "第一行\n第二行\n第三行"),
        _block(3, "Bad semantic break", "我\n知道你来了"),
        _block(4, "No, no, no!", "不，不，不！"),
        _block(5, "Are you okay?", "你好吗?"),
    ]

    report = run_quality_checks(
        blocks,
        target_language="简体中文",
        max_chars=32,
        meta_info={"genres": ["Drama"]},
    )
    by_type = report.summary["by_type"]

    assert by_type["line_too_long"] == 1
    assert by_type["reading_speed_too_fast"] >= 1
    assert by_type["too_many_lines"] == 1
    assert by_type["weak_semantic_line_break"] == 1
    assert by_type["repetition_not_compressed"] == 1
    assert by_type["punctuation_style"] == 1
    assert report.summary["far"]["readability"] >= 5
    assert report.summary["far"]["acceptability"] >= 1
    assert report.summary["style_profile"]["id"] == "zh_cn_general"


def test_quality_checks_allow_technical_identifiers_for_tutorials():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "The API returns a JSON object.", "API 会返回 JSON 对象。"),
    ]

    report = run_quality_checks(
        blocks,
        target_language="简体中文",
        max_chars=40,
        meta_info={"tags": ["tutorial", "programming"]},
    )

    assert "english_residue" not in report.summary["by_type"]


def test_quality_checks_apply_manual_metadata_terms():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Gradient descent converges here.", "梯度递减在这里收敛。"),
    ]

    report = run_quality_checks(
        blocks,
        target_language="简体中文",
        max_chars=40,
        meta_info={
            "content_type": "academic_lecture",
            "manual_terms": "Gradient descent=梯度下降",
        },
    )

    manual = [issue for issue in report.issues if issue.type == "manual_term_missing"]
    assert manual
    assert manual[0].expected == "梯度下降"
