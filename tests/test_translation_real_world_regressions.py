"""Failures observed in the September seven-episode subtitle audit."""
from datetime import timedelta
import pytest

from app.utils.srt import SubtitleBlock
from app.evaluation.metrics import proper_name_consistency_score
from app.engines.proper_name_normalizer import normalize_inferred_proper_name_variants


def block(index, source, target):
    return SubtitleBlock(index, timedelta(seconds=index * 3),
                         timedelta(seconds=index * 3 + 2), source, target)


def test_possessive_name_normalization_never_replaces_foot_with_room():
    blocks = [
        block(1, "the size of Shen Jia's foot", "尺码和沈佳的脚相符，"),
        block(2, "in Shen Jia's room", "在沈佳的房间里。"),
        block(3, "Shen Jia's room was searched", "搜查了沈佳的房间。"),
    ]
    before = [b.translation for b in blocks]
    assert normalize_inferred_proper_name_variants(blocks) == []
    assert [b.translation for b in blocks] == before


def test_name_normalization_does_not_duplicate_a_translated_title():
    blocks = [block(1, "[Chef Mesing] Copy.", "[厨师梅辛]收到。"),
              block(2, "[Chef Mesing] Come in.", "[梅辛大厨]进来。"),
              block(3, "[Chef Mesing] Go.", "[梅辛大厨]走。")]
    normalize_inferred_proper_name_variants(blocks)
    assert blocks[0].translation == "[厨师梅辛]收到。"


def test_short_chinese_name_and_title_are_not_whole_sentence_variants():
    source = {"1": "Shen Jia, come here.", "2": "Find Shen Jia.",
              "3": "Shen Jia's room", "4": "Shen Jia's foot",
              "5": "Director Becken, help.", "6": "Call Director Becken.",
              "7": "If Chen knows.", "8": "If Chen sees it."}
    target = {"1": "沈佳，过来。", "2": "寻找沈佳。", "3": "沈佳的房间",
              "4": "沈佳的脚", "5": "贝肯局长，帮忙。", "6": "给贝肯局长打电话。",
              "7": "如果陈知道。", "8": "要是陈看到了。"}
    assert proper_name_consistency_score(source, target)["issues"] == []


def test_actual_transliterated_name_difference_is_still_reported():
    result = proper_name_consistency_score(
        {"1": "Jasmine Kelly came.", "2": "Call Jasmine Kelly."},
        {"1": "贾丝明·凯利来过。", "2": "联系贾丝敏·凯利。"},
    )
    assert result["issue_count"] == 1


def test_consistent_minister_title_is_not_compared_as_whole_sentences():
    source = {"1": "The Home Secretary has pre-authorised her deportation.",
              "2": "Contravening a direct order from the Home Secretary",
              "3": "The Home Secretary knows that."}
    target = {"1": "内政大臣已事先批准将她遣返。", "2": "违抗内政大臣的直接命令，",
              "3": "内政大臣知道这一点。"}
    assert proper_name_consistency_score(source, target)["issues"] == []


def test_real_title_difference_is_not_silenced_by_shared_person_name():
    source = {"1": "What about Director Becken?", "2": "Director Becken was found."}
    target = {"1": "贝肯局长呢？", "2": "发现了贝肯行政长官。"}
    assert proper_name_consistency_score(source, target)["issue_count"] == 1


def test_single_word_speaker_labels_detect_real_name_drift():
    result = proper_name_consistency_score(
        {"1": "[Cockenspiel] Hello.", "2": "[Cockenspiel] Go.",
         "3": "[grunts]", "4": "[grunts]"},
        {"1": "［考肯斯皮尔］你好。", "2": "[科肯施皮尔]走。",
         "3": "[闷哼]", "4": "[哼声]"},
    )
    assert [i["source"] for i in result["issues"]] == ["Cockenspiel"]
    assert result["issues"][0]["target_forms"] == ["考肯斯皮尔", "科肯施皮尔"]


def test_semantic_targets_keep_read_only_neighbors_across_batches():
    from app.services.translation_tasks import _semantic_qa_requested_items
    blocks = [block(i, f"Line {i}", f"台词{i}") for i in range(1, 43)]
    items = _semantic_qa_requested_items(blocks)
    assert items[39]["preceding_context"][-1]["id"] == 39
    assert items[39]["following_context"][0]["id"] == 41
    assert len(items[39]["preceding_context"]) <= 3
    assert "preceding_context" not in items[39]["preceding_context"][0]
    assert [item["id"] for item in items] == list(range(1, 43))


def test_export_layout_check_matches_written_subtitle(tmp_path):
    from app.engines.translation_qa import run_quality_checks
    from app.utils.srt import write_srt, parse_srt
    blocks = [block(1, "We tried everything. Yeah.", "都试过了。\n-对")]
    path = tmp_path / "final.srt"
    write_srt(blocks, str(path), use_translation=True)
    assert "\n" not in parse_srt(path.read_text())[0].text
    report = run_quality_checks(blocks, export_layout=True)
    assert not any(i.type == "weak_semantic_line_break" for i in report.issues)


def test_successful_recheck_clears_only_matching_execution_failure():
    from app.services.translation_tasks import (
        _semantic_block_content_hash, _update_and_overlay_semantic_issue_ledger,
    )
    from app.engines.translation_qa import TranslationQaReport
    b = block(1, "You're coming with me.", "跟我走。")
    h = _semantic_block_content_hash(b)
    ledger = {"outstanding": [{"block_id": 1, "content_hash": h,
        "type": "semantic_qa_failed", "severity": "error", "message": "timeout",
        "source_text": b.text, "translation": b.translation, "expected": ""}], "resolved": []}
    trace = {"semantic_qa": {"checked_content_hashes": {"1": h},
                            "checked_block_ids": [1], "failed_block_ids": []}}
    report = TranslationQaReport(status="ok")
    _update_and_overlay_semantic_issue_ledger(
        report, [b], ledger, trace, strict_quality_gate=True, fresh_semantic_check=True,
    )
    assert report.issues == []
    assert ledger["outstanding"] == []
    assert ledger["resolved"][0]["resolution"] == "semantic_recheck_completed"


@pytest.mark.parametrize("checked_hash,fresh", [("old-hash", True), (None, False)])
def test_stale_recheck_cannot_clear_failure_for_changed_translation(checked_hash, fresh):
    from app.services.translation_tasks import (
        _semantic_block_content_hash, _update_and_overlay_semantic_issue_ledger,
    )
    from app.engines.translation_qa import TranslationQaReport
    b = block(1, "You're coming with me.", "跟我走。")
    h = _semantic_block_content_hash(b)
    ledger = {"outstanding": [{"block_id": 1, "content_hash": h,
        "type": "semantic_qa_failed", "severity": "error", "message": "timeout",
        "source_text": b.text, "translation": b.translation, "expected": ""}], "resolved": []}
    trace = {"semantic_qa": {"checked_content_hashes": {"1": checked_hash or h},
                            "checked_block_ids": [1], "failed_block_ids": []}}
    report = TranslationQaReport(status="ok")
    _update_and_overlay_semantic_issue_ledger(
        report, [b], ledger, trace, strict_quality_gate=True, fresh_semantic_check=fresh,
    )
    assert [i.type for i in report.issues] == ["semantic_qa_failed"]
