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


@pytest.mark.parametrize('source_targets', [
    [
        ('So, Lady Chiyome, what happened upon your return to the village?', '那么千代女大人，你回村后怎么样了？'),
        ('Lady Chiyome, Lady Tsubone, I take it that your visit to Lalatoya is related?', '千代女大人、局大人，你们来拉拉托亚也是为此吗？'),
        ('My aid is yours, Lady Chiyome, Lady Tsubone.', '千代女大人、局大人，我愿助你们一臂之力。'),
    ],
    [
        ('The Hilk Church did it.', '是希尔克教会干的。'),
        ('I feel like the Hilk Church might be behind this.', '我觉得希尔克教会可能在幕后。'),
        ('I dislike the Hilk Church.', '我不喜欢希尔克教会。'),
    ],
    [
        ('It seems the Holy Hilk Kingdom is making its move.', '看来圣希尔克王国已经开始行动了。'),
        ('The Holy Hilk Kingdom.', '圣希尔克王国。'),
        ('The Holy Hilk Kingdom has been a topic of interest.', '圣希尔克王国一直备受关注。'),
    ],
])
def test_inferred_name_replacement_preserves_other_entities_and_sentence_context(source_targets):
    blocks = [SubtitleBlock(i, timedelta(seconds=i * 5), timedelta(seconds=i * 5 + 4), source, target)
              for i, (source, target) in enumerate(source_targets, 1)]
    before = [b.translation for b in blocks]
    assert normalize_inferred_proper_name_variants(blocks) == []
    assert [b.translation for b in blocks] == before
