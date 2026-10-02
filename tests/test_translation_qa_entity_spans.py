"""Real subtitle contexts must not become replacement name candidates."""
import json
from datetime import timedelta

import pytest

from app.evaluation.metrics import proper_name_consistency_score
from app.engines.entity_registry import build_entity_registry, entity_context_json
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


@pytest.mark.parametrize("word,source_targets", [
    ("Forza", [("Forza.", "快点。"), ("- Forza! Sai fare di meglio?", "来啊！你能开得更好？"),
               ("Ok... Forza, fa' pressione.", "好了……来，用力按住。")]),
    ("Andiamo", [("Andiamo.", "走吧。"), ("[uomo] Andiamo, dai.", "[男人]走吧，快点。"),
                 ("- Andiamo! No, fermo...", "得了吧！不，等等……")]),
    ("Ciao", [("Ciao!", "你好啊！"), ("- Ciao, Hank.\n- Ciao, Mon.", "- 嗨，汉克。\n- 嗨，蒙。"),
              ('- Di\': "Ciao", Jack.', '- 杰克，说声“你好”。')]),
    ("Mercy", [("Mercy.", "发发慈悲吧。"), ("- Move!\n- Mercy.", "- 让开！\n- 饶命。"),
               ("Mercy on my brothers, my lord.", "大人，饶了我的弟兄们吧。")]),
    ("Justice", [("Justice!", "公道！"), ("- Cut their heads off!\n- Justice!", "- 砍下他们的脑袋！\n- 伸张正义！")]),
    ("Heave", [("Heave!", "用力！"), ("Heave! Heave!", "使劲！使劲！"), ("- Heave!", "- 使劲！")]),
])
def test_dialogue_boundaries_do_not_make_capitalized_common_words_entities(word, source_targets):
    sources = {str(i): source for i, (source, _) in enumerate(source_targets)}
    targets = {str(i): target for i, (_, target) in enumerate(source_targets)}
    result = proper_name_consistency_score(sources, targets)
    assert not any(e["source"] == word for e in result["entities"])
    assert not any(i["source"] == word for i in result["issues"])


@pytest.mark.parametrize("name,sources,targets,expected", [
    ("Brooklyn", ["Brooklyn!", "I like Brooklyn."], ["布鲁克林！", "比布鲁克林好多了。"], "布鲁克林"),
    ("Gina", ["[Gina] Hello.", "I think Gina is a killer."], ["[吉娜]你好。", "我觉得吉娜是个杀人犯。"], "吉娜"),
    ("Hollingsworth", ["Agent Hollingsworth.", "Agent Hollingsworth?", "Thank you, Agent Hollingsworth."],
     ["霍林斯沃思探员。", "霍林斯沃思探员？", "谢谢你，霍林斯沃思探员。"], "霍林斯沃思"),
])
def test_known_names_do_not_absorb_context_or_lose_nonphonetic_characters(name, sources, targets, expected):
    result = proper_name_consistency_score(dict(enumerate(sources)), dict(enumerate(targets)))
    entity = next(e for e in result["entities"] if e["source"] == name)
    assert entity["target_forms"] == [expected]
    assert result["issues"] == []


@pytest.mark.parametrize("name,forms", [("Sarah", ["莎拉", "萨拉"]), ("Doyle", ["道尔", "多伊尔"])])
def test_independent_name_drift_remains_visible_and_available_to_translation_context(name, forms):
    sources = {"1": f"{name}!", "2": f"Where is {name}?"}
    targets = {"1": f"{forms[0]}！", "2": f"{forms[1]}在哪里？"}
    result = proper_name_consistency_score(sources, targets)
    issue = next(i for i in result["issues"] if i["source"] == name)
    assert set(issue["target_forms"]) == set(forms)
    context = json.loads(entity_context_json(result["entities"]))
    item = next(e for e in context if e["source"] == name)
    assert set(item["observed_targets"]) == set(forms)


def test_common_word_can_still_be_a_person_when_speaker_label_supplies_identity():
    entities = build_entity_registry(
        {"1": "[Mercy] Hello.", "2": "Where is Mercy?"},
        {"1": "[默西]你好。", "2": "默西在哪里？"},
    )
    assert next(e for e in entities if e["source"] == "Mercy")["target_forms"] == ["默西"]


def test_repeated_lexical_evidence_does_not_turn_comparative_prefix_into_name_drift():
    sources = {
        "13": '"Authentic Brooklyn pizza..."',
        "264": "It's real Brooklyn pizza.",
        "693": "Because what's better\nthan Brooklyn pizza?",
    }
    targets = {
        "13": "“正宗布鲁克林披萨……”",
        "264": "这可是正宗的布鲁克林披萨。",
        "693": "什么比布鲁克林披萨更好吃？",
    }
    result = proper_name_consistency_score(sources, targets)
    brooklyn = next(e for e in result["entities"] if e["source"] == "Brooklyn")
    assert brooklyn["target_forms"] == ["布鲁克林"]
    assert not any(i["source"] == "Brooklyn" for i in result["issues"])


def test_independent_longer_name_is_not_discarded_as_context_contamination():
    entities = build_entity_registry(
        {"1": "Where is Sarah?", "2": "I saw Sarah.", "3": "Sarah!"},
        {"1": "莎拉在哪里？", "2": "我看见莎拉了。", "3": "莎拉赫！"},
    )
    assert next(e for e in entities if e["source"] == "Sarah")["target_forms"] == ["莎拉", "莎拉赫"]


def test_adjacent_delivery_and_speaker_labels_preserve_real_doyle_drift():
    result = proper_name_consistency_score(
        {"463": "Mel: You're in a heap of trouble, Doyle.",
         "523": "Not really how we do things,\nDoyle, but...",
         "696": "[ Trackpad clicks ]\nDoyle: Yes, sir."},
        {"463": "梅尔：你这回麻烦大了，道尔。",
         "523": "多伊尔，我们不这么办案，但……",
         "696": "［触控板点击声］道尔：是的，警官。"},
    )
    issue = next(i for i in result["issues"] if i["source"] == "Doyle")
    assert set(issue["target_forms"]) == {"道尔", "多伊尔"}


def test_standalone_acronym_instruction_does_not_enter_person_context():
    entities = build_entity_registry(
        {"1": "Do it ASAP.", "2": "ASAP!"},
        {"1": "尽快做。", "2": "尽快！"},
    )
    assert entity_context_json(entities) == ""


def test_full_name_truncation_does_not_replace_independently_backed_doyle_drift():
    result = proper_name_consistency_score(
        {"463": "Mel: You're in a heap of trouble, Doyle.",
         "523": "Not really how we do things,\nDoyle, but...",
         "548": "Doyle Koven's arrest.",
         "693": "Couple hours after we dropped\nDoyle Koven in holding,",
         "696": "[ Trackpad clicks ]\nDoyle: Yes, sir.",
         "734": "A man named Doyle Koven"},
        {"463": "梅尔：你这回麻烦大了，道尔。",
         "523": "多伊尔，我们不这么办案，但……",
         "548": "多伊尔·科文被捕的事。",
         "693": "我们把道尔·科文关进拘留室几小时后，",
         "696": "［触控板点击声］道尔：是的，警官。",
         "734": "一个叫道尔·科文的人"},
    )
    issue = next(i for i in result["issues"] if i["source"] == "Doyle")
    assert set(issue["target_forms"]) == {"道尔", "多伊尔"}
    assert not any(
        observation["target_signature"] == "尔科文"
        for entity in result["issues"] + result["entities"]
        for observation in entity["observations"]
    )


@pytest.mark.parametrize("prefix", ["我是", "把", "叫"])
def test_grammatical_prefixes_preserve_complete_dotted_name_drift(prefix):
    result = proper_name_consistency_score(
        {"1": "I met Miriam Crace.", "2": "I met Miriam Crace."},
        {"1": f"{prefix}米丽娅姆·克雷斯。", "2": f"{prefix}米里亚姆·克雷斯。"},
    )
    issue = next(i for i in result["issues"] if i["source"] == "Miriam Crace")
    assert set(issue["target_forms"]) == {"米丽娅姆克雷斯", "米里亚姆克雷斯"}


def test_complete_full_name_addresses_retain_nonphonetic_characters():
    result = proper_name_consistency_score(
        {"1": "Doyle Koven!", "2": "Doyle Koven?"},
        {"1": "道尔·科文！", "2": "多伊尔·科文？"},
    )
    issue = next(i for i in result["issues"] if i["source"] == "Doyle Koven")
    assert set(issue["target_forms"]) == {"道尔科文", "多伊尔科文"}


def test_long_shared_anchor_cannot_resurrect_rejected_full_name_suffix():
    result = proper_name_consistency_score(
        {"1": "I met Elliott Crace.", "2": "I met Elliott Crace."},
        {"1": "我是艾略特·克雷斯。", "2": "我是埃利奥特·克雷斯。"},
    )
    assert not any(
        observation["target_signature"] == "特克雷斯"
        for entity in result["issues"] + result["entities"]
        for observation in entity["observations"]
    )


def test_whole_dotted_name_cues_keep_internal_nonphonetic_characters():
    result = proper_name_consistency_score(
        {"1": "Eliot Crace, hello.", "2": "Eliot Crace, hello."},
        {"1": "艾略特·克雷斯。", "2": "埃利奥特·克雷斯。"},
    )
    issue = next(i for i in result["issues"] if i["source"] == "Eliot Crace")
    assert set(issue["target_forms"]) == {"艾略特克雷斯", "埃利奥特克雷斯"}


@pytest.mark.parametrize("title,name,form,first_title,second_title", [
    ("Aunt", "Sarah", "萨拉", "姨妈", "阿姨"),
    ("Aunt", "Sarah", "萨拉", "姑妈", "姑姑"),
    ("Uncle", "Bob", "鲍勃", "叔叔", "舅舅"),
])
def test_family_titles_are_not_first_names_or_target_name_characters(title, name, form, first_title, second_title):
    result = proper_name_consistency_score(
        {"1": f"[{name}] Hello.", "2": f"I saw {title} {name}.", "3": f"Where is {title} {name}?"},
        {"1": f"[{form}]你好。", "2": f"我见到{form}{first_title}了。", "3": f"{form}{second_title}在哪里？"},
    )
    assert result["issues"] == []
    entity = next(e for e in result["entities"] if e["source"] == name)
    assert entity["target_forms"] == [form]
    assert entity["aliases"] == []


def test_family_title_variation_does_not_hide_real_sarah_spelling_drift():
    result = proper_name_consistency_score(
        {"1": "[Sarah] Hello.",
         "2": "I can't be everywhere at once, Aunt Sarah.",
         "3": "you will abide by all of Aunt Sarah's rules"},
        {"1": "[莎拉]你好。",
         "2": "萨拉姨妈，我也不能分身啊。",
         "3": "就得遵守萨拉阿姨的所有规矩，"},
    )
    assert [(i["source"], set(i["target_forms"])) for i in result["issues"]] == [
        ("Sarah", {"莎拉", "萨拉"})
    ]


def test_full_name_deduplication_requires_coverage_of_each_component_variant():
    result = proper_name_consistency_score(
        {"1": "[Sarah] Hello.", "2": "Sarah Smith arrived.", "3": "I saw Sarah Smith."},
        {"1": "[莎拉]你好。", "2": "萨拉·史密斯来了。", "3": "萨拉·史密兹，我见过。"},
    )
    assert {i["source"] for i in result["issues"]} == {"Sarah Smith", "Sarah"}
    assert set(next(i for i in result["issues"] if i["source"] == "Sarah")["target_forms"]) == {"莎拉", "萨拉"}


@pytest.mark.parametrize("source_targets", [
    [("John Ball.", "约翰·鲍尔。"),
     ("When John Ball raised me from darkness.", "约翰·鲍尔带我走出黑暗时，我就离开了。"),
     ("Are you certain, John Ball?", "你确定吗，约翰·鲍尔？")],
    [("Where's Tyler?", "泰勒在哪儿？"),
     ("- What?\n- Where's Tyler?", "- 什么？\n- 泰勒在哪儿？")],
    [("Gabe Prescott.", "盖布·普雷斯科特。"),
     ("Gabe!", "盖布！"),
     ("You'll be shocked, but Gabe Prescott is not a winner.", "你可能不信，盖布真不怎么样。")],
    [("The Victor Ochoa case had been moving slowly.", "维克托·奥乔亚的案子一直进展缓慢。"),
     ("they had Victor in their pocket, didn't they?", "他们收买了维克托，对吧？"),
     ("about Victor's dirty laundry than we do.", "显然比我们知道得多。")],
    [("Hank Malone?", "汉克·马龙？"),
     ("Kate, sono Hank Malone.", "凯特，我是汉克·马龙。"),
     ("- Ben?\n- Ehi, Kate. Sono Hank Malone.", "- 本？\n- 喂，凯特，我是汉克·马龙。")],
    [("I cannot move to New York with you.", "我不能跟你搬去纽约。"),
     ("you can come to New York.", "你也能来纽约。"),
     ("-New York.", "-去纽约。")],
    [("Meanwhile, Port Wenn has been sitting", "可我们温港在"),
     ("and it will be so great for Port Wenn,", "对温港大有好处。"),
     ("But right now, more than ever, Port Wenn needs its sheriff.",
      "但眼下，温港比以往任何时候都更需要它的警长。")],
])
def test_approved_translation_context_does_not_manufacture_entity_drift(source_targets):
    result = proper_name_consistency_score(
        {str(i): source for i, (source, _) in enumerate(source_targets)},
        {str(i): target for i, (_, target) in enumerate(source_targets)},
    )
    assert result["issues"] == []


def test_missing_known_full_name_cannot_be_aligned_to_another_person_in_the_cue():
    result = proper_name_consistency_score(
        {"1": "Hank Malone?", "2": "Kate, sono Hank Malone."},
        {"1": "汉克·马龙？", "2": "凯特。"},
    )
    assert result["issues"] == []


def test_given_name_shortening_does_not_license_a_different_given_name():
    result = proper_name_consistency_score(
        {"1": "Gabe Prescott.", "2": "Gabe!", "3": "I saw Gabe Prescott."},
        {"1": "盖布·普雷斯科特。", "2": "盖布！", "3": "盖文来了。"},
    )
    issue = next(i for i in result["issues"] if i["source"] == "Gabe Prescott")
    assert set(issue["target_forms"]) == {"盖布普雷斯科特", "盖文"}


def test_independent_semantic_place_name_difference_remains_visible():
    result = proper_name_consistency_score(
        {"1": "Port Wenn.", "2": "Port Wenn?"},
        {"1": "温港。", "2": "温湾？"},
    )
    assert result["issue_count"] == 1
    assert set(result["issues"][0]["target_forms"]) == {"温港", "温湾"}
