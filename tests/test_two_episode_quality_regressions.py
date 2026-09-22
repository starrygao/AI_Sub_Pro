"""Minimal, review-backed excerpts from the September 18 two-episode audit."""
from datetime import timedelta

import pytest

from app.engines.translation_qa import classify_subtitle_source, run_quality_checks
from app.utils.srt import SubtitleBlock
from app.evaluation.metrics import proper_name_consistency_score


def cue(source, target="", index=1):
    return SubtitleBlock(index, timedelta(seconds=index * 10),
                         timedelta(seconds=index * 10 + 8), source, target)


@pytest.mark.parametrize("source", [
    "<i>- M'BENGA: And your mind?\n- LA'AN: Confused.</i>",
    "{\\i1}- M'BENGA: And your mind?\n- LA'AN: Confused.{\\i0}",
])
def test_formatted_speakers_are_compared_as_visible_text(source):
    good = cue(source, "- 姆本加：精神呢？\n- 拉安：混乱。")
    assert not any(i.type == "speaker_structure" for i in run_quality_checks([good]).issues)
    from app.engines.translation_qa import translation_candidate_contract_error
    assert translation_candidate_contract_error(source, good.translation, target_language="简体中文") == ""
    assert translation_candidate_contract_error(source, "精神呢？混乱。", target_language="简体中文")


@pytest.mark.parametrize("source", [
    "(phaser charging)", "(yelps)", "(squeals)", "(whooshing impacts)",
    "- (cheering, whistling)\n- (belches)", "(cackling)", "(whines softly)",
    "(whining softly)", "(alert sounding)", "- (sighs)\n- (whines softly)",
    "(barks)", '[♪ "Everybody (Backstreet\'s Back)"\nplaying]',
    "[guns cock]", "[R.J. chuckles]", "[huffs]", "[metal scrapes]",
    "[R.J. sighs]", '[♪ "(Rock) Superstar" playing]', '[♪ "Only You" playing]',
])
def test_reviewed_sound_cues_are_not_dialogue(source):
    assert classify_subtitle_source(source).kind == "sound"


@pytest.mark.parametrize("source", [
    "Funeral bell\nmushrooms", "Music\nlessons", "[R.J. sighs when I lie.]",
    "[Only you can help me]", "♪ Only you can help me ♪",
    "[the phaser charging station is broken]", "[barks are worse than bites]",
])
def test_sound_expansion_keeps_dialogue_and_lyrics(source):
    assert classify_subtitle_source(source).requires_translation


def test_named_sound_is_removed_only_from_mixed_source():
    decision = classify_subtitle_source("[R.J. chuckles] I know.")
    assert decision.kind == "mixed"
    assert decision.dialogue_text == "I know."


def test_source_backed_website_is_not_english_residue():
    b = cue("Captioned by WGBH\naccess.wgbh.org", "字幕由WGBH制作\naccess.wgbh.org")
    assert not any(i.type == "english_residue" for i in run_quality_checks([b]).issues)
    b.translation = "字幕由WGBH制作\nPlease visit access.wgbh.org"
    assert any(i.type == "english_residue" for i in run_quality_checks([b]).issues)


@pytest.mark.parametrize("name,targets", [
    ("Carl Jung", ["不过，卡尔·荣格可就……", "想找卡尔·荣格聊几句。"]),
    ("Elysian Kingdom", ["奥黛丽：谁想统治极乐王国，", "我就能把极乐王国", "你在极乐王国都经历了什么？"]),
    ("Iron Dragon", ["就必须掌控铁龙。", "而铁龙已经来了。", "摧毁铁龙。"]),
    ("Special Agent Clark", ["克拉克特工的招牌口味。", "我怀疑克拉克探员就是大老板。"]),
])
def test_name_context_is_not_a_name_variant(name, targets):
    result = proper_name_consistency_score(
        {str(i): f"We know {name}." for i in range(len(targets))},
        {str(i): t for i, t in enumerate(targets)},
    )
    assert result["issues"] == []


@pytest.mark.parametrize("name,targets", [
    ("Zardoz", ["上面写着“萨杜斯”。", "狗叫扎多兹。"]),
    ("Rukiya", ["鲁琪娅已经离开了。", "露琪娅让我们扮演角色。"]),
    ("Enterprise", ["企业号代表舰队。", "要返回进取号吗？"]),
    ("Apalachee", ["阿巴拉契监狱。", "在阿帕拉奇监狱一起蹲过。"]),
    ("Emi", ["埃米知道什么。", "艾米最近联系过你吗？"]),
    ("Runa", ["鲁娜是谁。", "露娜？"]),
    ("Stevie", ["斯蒂维。", "史蒂维察觉到了危险。"]),
    ("Virgil Osgood", ["维吉尔·奥斯古德。", "弗吉尔·奥斯古德那边。"]),
    ("P.C.M.", ["P.C.M.的枪。", "皮西艾姆军牌。"]),
])
def test_single_names_and_initials_detect_real_variants(name, targets):
    result = proper_name_consistency_score(
        {str(i): f"We know {name}." for i in range(len(targets))},
        {str(i): t for i, t in enumerate(targets)},
    )
    assert result["issue_count"] == 1
    assert all(len(o["target_signature"]) <= 12 for o in result["issues"][0]["observations"])


@pytest.mark.parametrize("name,targets", [
    ("AUDREY", ["奥黛丽", "奥德莉"]), ("NEVE", ["妮芙", "奈芙"]),
    ("SALAZAR", ["萨拉萨尔", "萨拉扎"]), ("ADYA", ["阿迪亚", "阿迪娅"]),
])
def test_uppercase_colon_speakers_detect_real_variants(name, targets):
    assert proper_name_consistency_score(
        {"1": f"<i>{name}: Hello.</i>", "2": f"- {name}: Go."},
        {"1": f"{targets[0]}：你好。", "2": f"- {targets[1]}：走。"},
    )["issue_count"] == 1


def test_entity_report_groups_occurrences_without_losing_locations():
    blocks = [cue("I saw Zardoz.", t, i) for i, t in enumerate(
        ["我看见萨杜斯。", "我看见扎多兹。", "扎多兹在这儿。"], 1)]
    report = run_quality_checks(blocks)
    issues = [i.to_dict() for i in report.issues if i.type == "proper_name_inconsistent"]
    assert len(issues) == 1
    assert issues[0]["related_block_ids"] == [1, 2, 3]
    assert report.summary["affected_block_count"] == 3


def test_semantic_prompt_receives_document_alias_evidence():
    from app.services.translation_tasks import _semantic_qa_prompt
    blocks = [cue("R.J. Decker, hello.", "阿尔·杰·德克尔，你好。"),
              cue("[R.J.] Go.", "[阿杰]走。", 2),
              cue("Call Decker.", "联系德克尔。", 3)]
    prompt = _semantic_qa_prompt("简体中文", blocks=blocks)
    assert '"source":"R.J."' in prompt
    assert "R.J. Decker" in prompt
    assert "称呼" in prompt and "不可信" in prompt


def test_compression_cannot_remove_possibility_from_semantic_group():
    from app.services.translation_tasks import _apply_nonempty_repair_results
    blocks = [cue("You may become dangerous.", "你可能变得危险。"),
              cue("To yourself.", "对你自己而言。", 2)]
    trace = {}
    result = _apply_nonempty_repair_results(blocks,
        [{"id": 1, "translation": "你变危险。"}, {"id": 2, "translation": "危及自己。"}],
        repair_trace=trace, target_language="简体中文", semantic_groups=[[1, 2]])
    assert result == []
    assert [b.translation for b in blocks] == ["你可能变得危险。", "对你自己而言。"]
    assert trace["atomic_rejected_group_ids"] == [[1, 2]]


def test_compression_can_move_modality_within_verified_group():
    from app.services.translation_tasks import _apply_nonempty_repair_results
    blocks = [cue("You may become", "你可能变得"), cue("dangerous.", "危险。", 2)]
    result = _apply_nonempty_repair_results(blocks,
        [{"id": 1, "translation": "你"}, {"id": 2, "translation": "或许会变危险。"}],
        target_language="简体中文", semantic_groups=[[1, 2]])
    assert len(result) == 2


@pytest.mark.parametrize("sources,targets", [
    (["My name is La'An Noonien-Singh.", "[LA'AN] Go."], ["我是拉安·努尼恩·辛格。", "[拉安]走。"]),
    (["We met Benny Russell.", "Benny?", "Call Benny."], ["见过拉塞尔。", "本尼？", "联系本尼。"]),
    (["We met Emi Ochoa.", "We met Victor Ochoa."], ["见过埃米·奥乔亚。", "见过维克托·奥乔亚。"]),
])
def test_explicit_full_names_do_not_conflate_address_forms(sources, targets):
    assert proper_name_consistency_score(dict(enumerate(sources)), dict(enumerate(targets)))["issues"] == []


def test_display_metrics_ignore_ass_tags_and_decode_entities():
    from app.engines.translation_qa import _compact_subtitle_text
    assert _compact_subtitle_text('{\\i1}<i>你 &amp; 我</i>{\\i0}') == "你&我"


def test_report_distinguishes_advice_and_uncertainty_and_keeps_locations():
    from app.engines.translation_qa import QualityIssue, TranslationQaReport
    report = TranslationQaReport(status="ok", issues=[
        QualityIssue("proper_name_inconsistent", "warning", 1, "name drift", related_block_ids=[1, 4]),
        QualityIssue("reading_speed_too_fast", "warning", 3, "fast"),
        QualityIssue("semantic_uncertain", "warning", 9, "needs scene"),
    ])
    payload = report.to_dict()
    assert payload["summary"]["affected_block_count"] == 4
    assert payload["summary"]["by_category"] == {"consistency": 1, "readability": 1, "needs_context": 1}
    assert "#1, #4" in report.to_markdown()


def test_inferred_majority_never_overrides_an_explicit_term():
    from app.engines.proper_name_normalizer import normalize_inferred_proper_name_variants
    blocks = [cue("Samia Zahir is here.", t, i) for i, t in enumerate(
        ["萨米娅·扎希尔来了。", "萨米娅·扎希尔。", "萨米娅·查希尔。"], 1)]
    before = [b.translation for b in blocks]
    assert normalize_inferred_proper_name_variants(blocks, protected_terms={"Samia Zahir": "萨米娅·查希尔"}) == []
    assert [b.translation for b in blocks] == before


def test_titled_name_and_standalone_address_keep_real_dashing_conflict():
    result = proper_name_consistency_score(
        {"1": "Prince Dashing.", "2": "Prince Dashing.", "3": "LA'AN: Dashing.", "4": "DASHING: No."},
        {"1": "潇洒王子。", "2": "达辛王子。", "3": "拉安：真潇洒。", "4": "达辛：不。"})
    assert any("Dashing" in i["source"] or "DASHING" in i["source"] for i in result["issues"])


def test_person_variant_is_not_also_assigned_to_the_book_in_same_line():
    result = proper_name_consistency_score(
        {"1": "Miriam Crace likes Tiny People.", "2": "Miriam Crace wrote Tiny People."},
        {"1": "米丽娅姆·克雷斯喜欢《小小人》。", "2": "米里亚姆·克雷斯写了《小小人》。"})
    assert [issue["source"] for issue in result["issues"]] == ["Miriam Crace"]


def test_bounded_entity_context_prioritizes_current_batch_then_frequent_identities():
    from app.engines.entity_registry import entity_context_json
    def record(name, ids):
        return {"source": name, "aliases": [name + " Smith"], "provenance": "source_mentions",
                "confidence": "inferred", "target_forms": [], "source_ids": ids}
    entities = [record(f"A{chr(97+i)}", [i]) for i in range(20)] + [record("R.J.", list(range(50)))]
    assert '"source":"R.J."' in entity_context_json(entities, limit=500)
    assert '"source":"Az"' in entity_context_json(entities + [record("Az", [88])], relevant_source="Az?", limit=500)


def test_credit_website_keeps_its_own_line_in_final_export(tmp_path):
    from app.utils.srt import write_srt, parse_srt_file
    b = cue("Captioned by WGBH access.wgbh.org", "字幕由WGBH媒体无障碍小组制作\naccess.wgbh.org")
    path = tmp_path / "credits.srt"
    write_srt([b], str(path), use_translation=True)
    assert parse_srt_file(str(path))[0].text.splitlines()[-1] == "access.wgbh.org"
    assert not any(i.type in {"english_residue", "line_too_long"} for i in run_quality_checks([b], export_layout=True).issues)
