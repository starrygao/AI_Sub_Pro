"""Real subtitle contexts must not become replacement name candidates."""
from datetime import timedelta

import pytest

from app.evaluation.metrics import proper_name_consistency_score
from app.engines.proper_name_normalizer import normalize_inferred_proper_name_variants
from app.engines.translation_qa import run_quality_checks
from app.utils.srt import SubtitleBlock


@pytest.mark.parametrize("name,targets", [
    ("Police Lieutenant", ["我是阿喀琉斯·瓦西利科斯警督。", "警督，有什么我能帮忙的吗？",
                           "警督，你的英语说得真好。", "不，警督。", "瓦西利科斯警督想"]),
    ("Tiny People", ["我们是小小人，个头小小，这就来", "点兵点将，小小人",
                     "出发啦！我们是小小人。", "《小小人》系列共有六十三本书，",
                     "你喜欢《小小人》吗？"]),
])
def test_consistent_entities_do_not_turn_dialogue_into_name_variants(name, targets):
    blocks = [SubtitleBlock(i, timedelta(seconds=i*5), timedelta(seconds=i*5+4),
                           f"{name}, hello.", target)
              for i, target in enumerate(targets, 1)]
    if name == "Tiny People":
        blocks[0].text = "We are the Tiny People We're\ntiny That's why we're coming"
    report = run_quality_checks(blocks)
    assert not [i for i in report.issues if i.type == "proper_name_inconsistent"]
    assert normalize_inferred_proper_name_variants(blocks) == []
    assert [b.translation for b in blocks] == targets


@pytest.mark.parametrize("name,targets", [
    ("Police Lieutenant", ["警督，请进。", "警长，你好。"]),
    ("Police Lieutenant", ["警督，请进。", "副警督，你好。"]),
    ("Tiny People", ["你读过《小小人》吗？", "我喜欢《小不点》。"]),
    ("Tiny People", ["《小小人》系列。", "《小小人历险记》系列。"]),
    ("Director Becken", ["贝肯局长呢？", "发现了贝肯行政长官。"]),
    ("Eliot Crace", ["艾略特·克雷斯。", "埃利奥特·克雷斯。"]),
    ("Miriam Crace", ["米丽娅姆·克雷斯来了。", "米里亚姆·克雷斯在哪儿？"]),
])
def test_actual_entity_differences_remain_visible(name, targets):
    assert proper_name_consistency_score(
        {str(i): f"{name}, hello." for i in range(len(targets))},
        {str(i): target for i, target in enumerate(targets)},
    )["issue_count"] == 1


def test_shared_book_title_does_not_hide_a_different_person_name():
    result = proper_name_consistency_score(
        {"1": "Miriam Crace likes Tiny People.",
         "2": "Miriam Crace wrote Tiny People."},
        {"1": "米丽娅姆·克雷斯喜欢《小小人》。",
         "2": "米里亚姆·克雷斯写了《小小人》。"},
    )
    assert any(i["source"] == "Miriam Crace" for i in result["issues"])
