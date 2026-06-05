#!/usr/bin/env python3
"""Generate bundled synthetic phrase packs.

These packs are hand-authored/template-authored project data. They intentionally
do not include copied subtitles or downloaded public corpus rows.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = ROOT / "app" / "resources" / "phrase_packs"

SOURCE = "AI Sub Pro bundled synthetic subtitle phrase pack"
LICENSE = "Project-local synthetic examples, MIT-compatible"

EXISTING_PACKS = [
    {
        "id": "ai-sub-pro.en-zh.subtitle_colloquial_starter",
        "file": "en-zh.subtitle_colloquial_starter.v1.json",
        "version": 1,
    },
    {
        "id": "ai-sub-pro.ja-zh.subtitle_colloquial_starter",
        "file": "ja-zh.subtitle_colloquial_starter.v1.json",
        "version": 1,
    },
    {
        "id": "ai-sub-pro.ko-zh.subtitle_colloquial_starter",
        "file": "ko-zh.subtitle_colloquial_starter.v1.json",
        "version": 1,
    },
]


def phrase(source: str, target: str, tags=(), quality: float = 0.82) -> dict:
    return {
        "source_text": source,
        "target_text": target,
        "quality": quality,
        "tags": list(tags),
    }


def from_pairs(pairs, tags=(), quality: float = 0.82) -> list[dict]:
    rows = []
    for item in pairs:
        if len(item) == 2:
            source, target = item
            item_tags = tags
            item_quality = quality
        elif len(item) == 3:
            source, target, item_tags = item
            item_quality = quality
        else:
            source, target, item_tags, item_quality = item
        rows.append(phrase(source, target, item_tags, item_quality))
    return rows


def unique_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for row in rows:
        key = (row["source_text"], row["target_text"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def pack(pack_id: str, filename: str, source_language: str, tags: list[str], rows: list[dict]) -> dict:
    return {
        "id": pack_id,
        "version": 1,
        "source": SOURCE,
        "license": LICENSE,
        "source_language": source_language,
        "target_language": "zh-CN",
        "tags": tags,
        "quality": 0.82,
        "phrases": unique_rows(rows),
        "_filename": filename,
    }


def build_en_core() -> list[dict]:
    direct = [
        ("Give me a break.", "饶了我吧。", ["colloquial", "reaction"]),
        ("You lost me.", "我没听懂。", ["dialogue"]),
        ("That explains a lot.", "这就解释得通了。", ["reaction"]),
        ("That is not the point.", "重点不是这个。", ["dialogue"]),
        ("Let's not get ahead of ourselves.", "先别想太远。", ["dialogue"]),
        ("We are not doing this right now.", "我们现在不谈这个。", ["conflict"]),
        ("I don't buy it.", "我不信。", ["reaction"]),
        ("You don't get to say that.", "你没资格这么说。", ["conflict"]),
        ("This stays between us.", "这事别让别人知道。", ["secret"]),
        ("I can live with that.", "这样我能接受。", ["agreement"]),
        ("That was uncalled for.", "你刚才那话太过了。", ["conflict"]),
        ("Take it down a notch.", "冷静点。", ["conflict"]),
        ("I said what I said.", "我话就放这儿了。", ["conflict"]),
        ("Don't make this weird.", "别把气氛搞尴尬。", ["colloquial"]),
        ("You're overthinking it.", "你想太多了。", ["dialogue"]),
        ("I have a bad feeling about this.", "我有种不好的预感。", ["suspense"]),
        ("This is getting out of hand.", "事情快失控了。", ["conflict"]),
        ("I am not in the mood.", "我现在没心情。", ["dialogue"]),
        ("I'm not proud of it.", "这事我也不光彩。", ["confession"]),
        ("It slipped out.", "我一不小心说漏嘴了。", ["dialogue"]),
        ("You made your point.", "你的意思我明白了。", ["dialogue"]),
        ("Let's call it a night.", "今晚就到这吧。", ["party"]),
        ("I'm all ears.", "我洗耳恭听。", ["dialogue"]),
        ("Don't leave me hanging.", "别吊我胃口。", ["colloquial"]),
        ("I walked right into that.", "我这是自己撞上去了。", ["colloquial"]),
        ("That's on me.", "这事怪我。", ["apology"]),
        ("I'll take the blame.", "责任我来担。", ["dialogue"]),
        ("You had one job.", "这么简单你都能搞砸。", ["sarcasm"]),
        ("Now is not the time.", "现在不是时候。", ["dialogue"]),
        ("We're running out of time.", "我们没时间了。", ["urgency"]),
        ("Keep your voice down.", "小声点。", ["dialogue"]),
        ("Don't look at me like that.", "别那样看着我。", ["dialogue"]),
        ("I didn't sign up for this.", "我可没说要干这个。", ["colloquial"]),
        ("You are missing the point.", "你没抓住重点。", ["dialogue"]),
        ("I need a minute.", "给我一点时间。", ["dialogue"]),
        ("That was close.", "刚才好险。", ["reaction"]),
        ("Not helping.", "你这话一点忙都帮不上。", ["sarcasm"]),
        ("Good to know.", "知道了。", ["dialogue"]),
        ("Point taken.", "我明白你的意思。", ["dialogue"]),
        ("I'm working on it.", "我正在处理。", ["workplace"]),
        ("We have a situation.", "出事了。", ["urgency"]),
        ("This changes everything.", "这下情况全变了。", ["suspense"]),
        ("I'm not going anywhere.", "我哪儿也不去。", ["dialogue"]),
        ("You can't be serious.", "你不是认真的吧。", ["reaction"]),
        ("Let's hear him out.", "先听他说完。", ["dialogue"]),
        ("Don't start.", "别又来了。", ["conflict"]),
        ("I know that look.", "我知道你这个表情是什么意思。", ["dialogue"]),
        ("You look like hell.", "你看起来糟透了。", ["dialogue"]),
        ("I'll pretend I didn't hear that.", "我就当没听见。", ["sarcasm"]),
        ("Let's keep it moving.", "别耽误了，继续吧。", ["dialogue"]),
        ("I was getting to that.", "我正要说到这点。", ["dialogue"]),
        ("That is beside the point.", "这不是重点。", ["dialogue"]),
        ("This is not up for debate.", "这事没得商量。", ["conflict"]),
        ("You owe me an explanation.", "你得给我个解释。", ["conflict"]),
        ("Don't make me regret this.", "别让我后悔帮你。", ["dialogue"]),
        ("I need you to trust me.", "我需要你相信我。", ["dialogue"]),
        ("You have no idea.", "你根本不知道。", ["dialogue"]),
        ("I wouldn't count on it.", "我劝你别指望这个。", ["dialogue"]),
        ("It is what it is.", "事已至此。", ["colloquial"]),
        ("I'll deal with it.", "我会处理。", ["dialogue"]),
        ("You did the right thing.", "你做得对。", ["encouragement"]),
        ("Don't beat yourself up.", "别太责怪自己。", ["encouragement"]),
        ("I'm trying to help.", "我是在帮你。", ["dialogue"]),
        ("You're not making sense.", "你说不通。", ["conflict"]),
        ("I didn't see that coming.", "这我真没想到。", ["reaction"]),
    ]
    intensifiers = [
        ("I am so done with this.", "我真的受够了。"),
        ("I am way out of my depth.", "这事已经超出我的能力范围了。"),
        ("I am barely holding it together.", "我已经快撑不住了。"),
        ("I am not falling for that again.", "我不会再上这个当了。"),
        ("I am trying to be reasonable.", "我已经在尽量讲道理了。"),
        ("You are not listening.", "你根本没在听。"),
        ("You are making this worse.", "你只会把事情弄得更糟。"),
        ("You are better than this.", "你不该这样。"),
        ("We are past that now.", "现在说这个已经晚了。"),
        ("We are in this together.", "我们是一条船上的人。"),
        ("This is between you and me.", "这是你我之间的事。"),
        ("This is bigger than us.", "这事不是我们能左右的。"),
        ("That sounds like a trap.", "听起来像个陷阱。"),
        ("That sounds about right.", "听起来差不多。"),
        ("That sounds personal.", "听起来像私人恩怨。"),
        ("It feels different this time.", "这次感觉不一样。"),
        ("It feels too easy.", "这也太顺利了。"),
        ("It feels like a setup.", "感觉像有人设了局。"),
        ("Let's not make a scene.", "别当众闹起来。"),
        ("Let's not push our luck.", "别再碰运气了。"),
    ]
    return from_pairs(direct + intensifiers, ["subtitle", "colloquial"], 0.84)


def build_en_medical() -> list[dict]:
    rows = []
    procedures = [
        ("run a CT scan", "做 CT 扫描"),
        ("order blood work", "安排血检"),
        ("call neurology", "请神经科会诊"),
        ("start antibiotics", "开始用抗生素"),
        ("monitor his vitals", "监测他的生命体征"),
        ("check her pupils", "检查她的瞳孔"),
        ("review the chart", "查看病历"),
        ("prep the OR", "准备手术室"),
        ("page the attending", "呼叫主治医生"),
        ("update the family", "通知家属"),
        ("repeat the labs", "复查化验"),
        ("get consent", "取得同意"),
        ("rule out infection", "排除感染"),
        ("stabilize the patient", "稳定病人情况"),
        ("keep the airway open", "保持气道通畅"),
    ]
    for source, target in procedures:
        rows.append(phrase(f"We need to {source}.", f"我们需要{target}。", ["medical", "procedure"], 0.88))
        rows.append(phrase(f"Can you {source}?", f"你能{target}吗？", ["medical", "procedure"], 0.84))

    symptoms = [
        ("chest pain", "胸痛"),
        ("shortness of breath", "呼吸困难"),
        ("dizziness", "头晕"),
        ("nausea", "恶心"),
        ("numbness", "麻木"),
        ("blurred vision", "视物模糊"),
        ("a headache", "头痛"),
        ("abdominal pain", "腹痛"),
        ("a fever", "发烧"),
        ("weakness", "无力"),
        ("memory loss", "记忆缺失"),
        ("a seizure", "癫痫发作"),
    ]
    for source, target in symptoms:
        rows.append(phrase(f"Any {source}?", f"有没有{target}？", ["medical", "symptom"], 0.86))

    direct = [
        ("His vitals are stable.", "他的生命体征稳定。"),
        ("Her pressure is dropping.", "她的血压在下降。"),
        ("The scan came back clean.", "扫描结果没发现异常。"),
        ("The labs are back.", "化验结果出来了。"),
        ("He is crashing.", "他的情况急转直下。"),
        ("She is coding.", "她心跳骤停了。"),
        ("Start compressions.", "开始胸外按压。"),
        ("Push one milligram of epi.", "推一毫克肾上腺素。"),
        ("We got a pulse.", "有脉搏了。"),
        ("Tell me where it hurts.", "告诉我哪里疼。"),
        ("Stay with me.", "坚持住，别睡。"),
        ("Look at my finger.", "看着我的手指。"),
        ("This could be neurological.", "这可能是神经系统问题。"),
        ("It is too early to diagnose.", "现在诊断还太早。"),
        ("The differential is broad.", "鉴别诊断范围很广。"),
        ("We are missing something.", "我们漏掉了什么。"),
        ("The symptoms do not add up.", "这些症状对不上。"),
        ("He needs surgery now.", "他现在就需要手术。"),
        ("She is refusing treatment.", "她拒绝治疗。"),
        ("I need a tox screen.", "我需要毒理筛查。"),
        ("Keep him on observation.", "让他继续留观。"),
        ("The medication is not working.", "药物没有起效。"),
        ("Increase the dosage.", "加大剂量。"),
        ("Watch for side effects.", "注意副作用。"),
        ("This is not psychosomatic.", "这不是心理因素造成的。"),
    ]
    rows.extend(from_pairs(direct, ["medical", "dialogue"], 0.86))
    return rows


def build_en_crime() -> list[dict]:
    rows = []
    actions = [
        ("secure the scene", "封锁现场"),
        ("canvass the block", "排查这一街区"),
        ("pull the security footage", "调取监控录像"),
        ("check his alibi", "核实他的不在场证明"),
        ("run the plates", "查一下车牌"),
        ("dust for prints", "提取指纹"),
        ("call for backup", "请求支援"),
        ("track the phone", "追踪手机"),
        ("notify next of kin", "通知近亲"),
        ("reopen the case", "重启案件"),
        ("hold the perimeter", "守住警戒线"),
        ("follow the money", "追查资金流向"),
        ("compare the DNA", "比对 DNA"),
        ("question the witness", "询问证人"),
        ("bring him in", "把他带回来问话"),
    ]
    for source, target in actions:
        rows.append(phrase(f"We need to {source}.", f"我们需要{target}。", ["crime", "procedure"], 0.87))
        rows.append(phrase(f"Did you {source}?", f"你{target}了吗？", ["crime", "procedure"], 0.83))

    direct = [
        ("Where were you last night?", "你昨晚在哪？"),
        ("That is not an alibi.", "那算不上不在场证明。"),
        ("The timeline does not fit.", "时间线对不上。"),
        ("We found a match.", "我们找到匹配结果了。"),
        ("The evidence was planted.", "证据是被人栽赃的。"),
        ("He lawyered up.", "他请律师了。"),
        ("She is not talking.", "她什么都不肯说。"),
        ("This was personal.", "这是私人恩怨。"),
        ("The killer knew the victim.", "凶手认识受害者。"),
        ("No one leaves this room.", "谁都不许离开这个房间。"),
        ("You are obstructing an investigation.", "你在妨碍调查。"),
        ("We have probable cause.", "我们有合理根据。"),
        ("Get me a warrant.", "给我弄一张搜查令。"),
        ("That confession was coerced.", "那份供词是被逼出来的。"),
        ("The witness changed her story.", "证人改口了。"),
        ("Something about this feels staged.", "这事感觉像被人布置过。"),
        ("The suspect is on the move.", "嫌疑人正在转移。"),
        ("We are looking at the wrong guy.", "我们盯错人了。"),
        ("The case just went federal.", "这案子现在归联邦管了。"),
        ("Do not contaminate the scene.", "别污染现场。"),
        ("Bag it and tag it.", "装袋标记。"),
        ("Chain of custody matters.", "证物保管链很重要。"),
        ("The motive is still unclear.", "动机还不清楚。"),
        ("This is an open investigation.", "这是一起正在调查的案件。"),
        ("He fits the profile.", "他符合侧写特征。"),
    ]
    rows.extend(from_pairs(direct, ["crime", "dialogue"], 0.86))
    return rows


def build_en_workplace() -> list[dict]:
    rows = []
    actions = [
        ("circle back after the meeting", "会后再跟进"),
        ("loop in legal", "把法务拉进来"),
        ("send the deck", "把演示文稿发过去"),
        ("move the deadline", "调整截止日期"),
        ("talk to the client", "和客户谈谈"),
        ("get this approved", "把这个批下来"),
        ("clean up the numbers", "把数据整理清楚"),
        ("prepare a fallback plan", "准备一个备用方案"),
        ("escalate this", "把这事升级处理"),
        ("keep this off email", "这事别写进邮件"),
        ("book a room", "订个会议室"),
        ("cut the budget", "削减预算"),
        ("protect the team", "保护团队"),
        ("ship by Friday", "周五前交付"),
        ("own the mistake", "承担这个错误"),
    ]
    for source, target in actions:
        rows.append(phrase(f"We need to {source}.", f"我们需要{target}。", ["workplace", "procedure"], 0.86))
        rows.append(phrase(f"Can you {source}?", f"你能{target}吗？", ["workplace", "dialogue"], 0.83))

    direct = [
        ("The client is pushing back.", "客户在反对。"),
        ("We are over budget.", "我们超预算了。"),
        ("The numbers do not work.", "这些数字说不通。"),
        ("This is above my pay grade.", "这事超出我的权限了。"),
        ("I need this by end of day.", "我今天下班前就要。"),
        ("Let's take this offline.", "我们私下再谈这个。"),
        ("That is not in scope.", "这不在范围内。"),
        ("We are aligned.", "我们意见一致。"),
        ("I need a straight answer.", "我要一个明确答复。"),
        ("Do not bury the lead.", "别把重点藏起来。"),
        ("This meeting could have been an email.", "这个会完全可以发邮件解决。"),
        ("The board wants answers.", "董事会要一个交代。"),
        ("We cannot miss this window.", "我们不能错过这个窗口期。"),
        ("This is a hard deadline.", "这是硬性截止日期。"),
        ("I will take first pass.", "我先过第一遍。"),
        ("Send me the latest version.", "把最新版发我。"),
        ("We need to manage expectations.", "我们得管理预期。"),
        ("That is a conflict of interest.", "那是利益冲突。"),
        ("The deal is not dead yet.", "这笔交易还没黄。"),
        ("Do not put that in writing.", "别把那件事写下来。"),
        ("You are putting me in a bad spot.", "你让我很难办。"),
        ("This is not sustainable.", "这样撑不了多久。"),
        ("We need buy-in.", "我们需要大家认可。"),
        ("The launch is at risk.", "上线有风险。"),
        ("Let's not overpromise.", "别承诺过头。"),
    ]
    rows.extend(from_pairs(direct, ["workplace", "dialogue"], 0.85))
    return rows


JA_EXPANDED = [
    ("信じられない。", "真不敢相信。"), ("もう一度言って。", "再说一遍。"),
    ("聞いてないよ。", "我可没听说。"), ("そんなつもりじゃなかった。", "我不是那个意思。"),
    ("今は無理。", "现在不行。"), ("やめておこう。", "还是算了吧。"),
    ("話を聞いて。", "听我说。"), ("誤解しないで。", "别误会。"),
    ("冗談じゃない。", "开什么玩笑。"), ("放っておけない。", "我不能坐视不管。"),
    ("顔に出てるよ。", "你都写脸上了。"), ("隠しても無駄だ。", "你藏也没用。"),
    ("時間がない。", "没时间了。"), ("急いで。", "快点。"),
    ("後で説明する。", "我之后再解释。"), ("信じてくれ。", "相信我。"),
    ("本当に大丈夫？", "你真的没事吗？"), ("無理しないで。", "别勉强。"),
    ("私のせいだ。", "是我的错。"), ("謝るよ。", "我道歉。"),
    ("それは違う。", "不是那样。"), ("黙ってて。", "别说话。"),
    ("冗談でしょ？", "你开玩笑吧？"), ("助かったよ。", "帮大忙了。"),
    ("約束しただろ。", "你答应过的吧。"), ("考え直して。", "再考虑一下。"),
    ("手遅れだ。", "已经太晚了。"), ("まだ間に合う。", "还来得及。"),
    ("何かおかしい。", "有点不对劲。"), ("気づかなかった。", "我没注意到。"),
    ("ちゃんと説明して。", "好好解释一下。"), ("落ち着いて。", "冷静点。"),
    ("こっちを見て。", "看着我。"), ("一人にしないで。", "别丢下我一个人。"),
    ("任せられない。", "我不能交给你。"), ("任せてくれ。", "交给我。"),
    ("逃げるな。", "别逃。"), ("もう終わりだ。", "已经结束了。"),
    ("始めよう。", "开始吧。"), ("やるしかない。", "只能这么做了。"),
    ("言い過ぎた。", "我说得太过了。"), ("悪気はなかった。", "我没有恶意。"),
    ("それでいい。", "这样就好。"), ("納得できない。", "我不能接受。"),
    ("忘れて。", "忘了吧。"), ("覚えてる？", "你还记得吗？"),
    ("嘘をつかないで。", "别撒谎。"), ("本当のことを言って。", "说实话。"),
    ("ここにいて。", "待在这儿。"), ("先に行って。", "你先走。"),
    ("後悔するよ。", "你会后悔的。"), ("後悔してない。", "我不后悔。"),
    ("何とかする。", "我会想办法。"), ("何とかして。", "想想办法。"),
    ("見なかったことにする。", "我就当没看见。"), ("聞かなかったことにする。", "我就当没听见。"),
    ("空気を読んで。", "看点气氛。"), ("それはまずい。", "这下麻烦了。"),
    ("間違いない。", "肯定没错。"), ("そうとは限らない。", "也不一定。"),
    ("連絡して。", "联系我。"), ("電話に出て。", "接电话。"),
    ("私を信じて。", "相信我。"), ("自分を責めないで。", "别责怪自己。"),
    ("今さら遅い。", "现在说太晚了。"), ("話は終わってない。", "话还没说完。"),
    ("それは命令？", "这是命令吗？"), ("質問に答えて。", "回答问题。"),
    ("笑えない。", "一点都不好笑。"), ("いい加減にして。", "够了吧。"),
]

KO_EXPANDED = [
    ("믿을 수가 없어.", "真不敢相信。"), ("다시 말해 봐.", "再说一遍。"),
    ("난 들은 적 없어.", "我可没听说过。"), ("그런 뜻이 아니었어.", "我不是那个意思。"),
    ("지금은 안 돼.", "现在不行。"), ("그만두자.", "还是算了吧。"),
    ("내 말 좀 들어.", "听我说。"), ("오해하지 마.", "别误会。"),
    ("장난해?", "开什么玩笑？"), ("그냥 둘 수 없어.", "我不能坐视不管。"),
    ("얼굴에 다 써 있어.", "你都写脸上了。"), ("숨겨도 소용없어.", "你藏也没用。"),
    ("시간이 없어.", "没时间了。"), ("서둘러.", "快点。"),
    ("나중에 설명할게.", "我之后再解释。"), ("날 믿어.", "相信我。"),
    ("정말 괜찮아?", "你真的没事吗？"), ("무리하지 마.", "别勉强。"),
    ("내 잘못이야.", "是我的错。"), ("사과할게.", "我道歉。"),
    ("그건 아니야.", "不是那样。"), ("조용히 해.", "别说话。"),
    ("농담이지?", "你开玩笑吧？"), ("덕분에 살았어.", "帮大忙了。"),
    ("약속했잖아.", "你答应过的吧。"), ("다시 생각해 봐.", "再考虑一下。"),
    ("이미 늦었어.", "已经太晚了。"), ("아직 늦지 않았어.", "还来得及。"),
    ("뭔가 이상해.", "有点不对劲。"), ("눈치 못 챘어.", "我没注意到。"),
    ("제대로 설명해.", "好好解释一下。"), ("진정해.", "冷静点。"),
    ("나를 봐.", "看着我。"), ("혼자 두지 마.", "别丢下我一个人。"),
    ("너한테 맡길 수 없어.", "我不能交给你。"), ("나한테 맡겨.", "交给我。"),
    ("도망치지 마.", "别逃。"), ("이제 끝이야.", "已经结束了。"),
    ("시작하자.", "开始吧。"), ("할 수밖에 없어.", "只能这么做了。"),
    ("말이 심했어.", "我说得太过了。"), ("악의는 없었어.", "我没有恶意。"),
    ("그거면 됐어.", "这样就好。"), ("납득할 수 없어.", "我不能接受。"),
    ("잊어버려.", "忘了吧。"), ("기억나?", "你还记得吗？"),
    ("거짓말하지 마.", "别撒谎。"), ("사실대로 말해.", "说实话。"),
    ("여기 있어.", "待在这儿。"), ("먼저 가.", "你先走。"),
    ("후회할 거야.", "你会后悔的。"), ("후회 안 해.", "我不后悔。"),
    ("내가 어떻게든 할게.", "我会想办法。"), ("어떻게든 해 봐.", "想想办法。"),
    ("못 본 걸로 할게.", "我就当没看见。"), ("못 들은 걸로 할게.", "我就当没听见。"),
    ("분위기 좀 읽어.", "看点气氛。"), ("이건 곤란한데.", "这下麻烦了。"),
    ("틀림없어.", "肯定没错。"), ("꼭 그런 건 아니야.", "也不一定。"),
    ("연락해.", "联系我。"), ("전화 받아.", "接电话。"),
    ("나를 믿어 줘.", "相信我。"), ("자책하지 마.", "别责怪自己。"),
    ("이제 와서 늦었어.", "现在说太晚了。"), ("얘기 아직 안 끝났어.", "话还没说完。"),
    ("그거 명령이야?", "这是命令吗？"), ("질문에 대답해.", "回答问题。"),
    ("웃을 일이 아니야.", "一点都不好笑。"), ("그만 좀 해.", "够了吧。"),
]

ES_STARTER = [
    ("No puede ser.", "不会吧。"), ("Dime la verdad.", "跟我说实话。"),
    ("No te preocupes.", "别担心。"), ("Estoy en ello.", "我正在处理。"),
    ("No es asunto tuyo.", "这不关你的事。"), ("Déjalo estar.", "算了吧。"),
    ("Espera un momento.", "等一下。"), ("¿Estás bien?", "你没事吧？"),
    ("No lo hagas raro.", "别把气氛搞尴尬。"), ("No me mires así.", "别那样看着我。"),
    ("Te debo una.", "我欠你个人情。"), ("No era mi intención.", "我不是故意的。"),
    ("No tenemos tiempo.", "我们没时间了。"), ("Baja la voz.", "小声点。"),
    ("Confía en mí.", "相信我。"), ("No me dejes aquí.", "别把我丢在这儿。"),
    ("Eso explica mucho.", "这就解释得通了。"), ("No tiene sentido.", "这说不通。"),
    ("No te lo tomes personal.", "别往心里去。"), ("Eso fue demasiado.", "那太过分了。"),
    ("Voy contigo.", "我跟你一起去。"), ("No puedo prometerlo.", "我不能保证。"),
    ("Tienes razón.", "你说得对。"), ("Me equivoqué.", "我错了。"),
    ("No estoy de humor.", "我现在没心情。"), ("Hablemos luego.", "我们之后再谈。"),
    ("No quiero problemas.", "我不想惹麻烦。"), ("Esto se queda entre nosotros.", "这事只有我们知道。"),
    ("No lo vi venir.", "这我真没想到。"), ("Dame un minuto.", "给我一分钟。"),
    ("No puedo seguir así.", "我不能再这样下去了。"), ("Eso suena a trampa.", "听起来像陷阱。"),
    ("No empieces.", "别又来了。"), ("No me hagas arrepentirme.", "别让我后悔。"),
    ("Estoy intentando ayudar.", "我是在帮忙。"), ("No estás escuchando.", "你根本没在听。"),
    ("Vámonos de aquí.", "我们离开这里吧。"), ("Quédate conmigo.", "陪着我。"),
    ("No digas nada.", "什么都别说。"), ("Lo tengo controlado.", "我能控制住。"),
    ("Eso cambia todo.", "这下情况全变了。"), ("No cuentes con eso.", "别指望这个。"),
    ("No es tan sencillo.", "没那么简单。"), ("Ya lo veremos.", "到时候再说。"),
    ("No me queda otra.", "我别无选择。"), ("No te culpes.", "别责怪自己。"),
    ("Vamos paso a paso.", "一步一步来。"), ("No hay vuelta atrás.", "没有回头路了。"),
    ("Esto no ha terminado.", "这事还没完。"), ("Te lo explicaré después.", "我之后再解释。"),
]

FR_STARTER = [
    ("Ce n'est pas possible.", "不会吧。"), ("Dis-moi la vérité.", "跟我说实话。"),
    ("Ne t'inquiète pas.", "别担心。"), ("Je m'en occupe.", "我来处理。"),
    ("Ce ne sont pas tes affaires.", "这不关你的事。"), ("Laisse tomber.", "算了吧。"),
    ("Attends une seconde.", "等一下。"), ("Ça va ?", "你没事吧？"),
    ("Ne rends pas ça bizarre.", "别把气氛搞尴尬。"), ("Ne me regarde pas comme ça.", "别那样看着我。"),
    ("Je te dois une fière chandelle.", "我欠你个人情。"), ("Ce n'était pas mon intention.", "我不是故意的。"),
    ("On n'a pas le temps.", "我们没时间了。"), ("Parle moins fort.", "小声点。"),
    ("Fais-moi confiance.", "相信我。"), ("Ne me laisse pas ici.", "别把我丢在这儿。"),
    ("Ça explique beaucoup de choses.", "这就解释得通了。"), ("Ça n'a aucun sens.", "这说不通。"),
    ("Ne le prends pas personnellement.", "别往心里去。"), ("C'était déplacé.", "那太过分了。"),
    ("Je viens avec toi.", "我跟你一起去。"), ("Je ne peux rien promettre.", "我不能保证。"),
    ("Tu as raison.", "你说得对。"), ("Je me suis trompé.", "我错了。"),
    ("Je ne suis pas d'humeur.", "我现在没心情。"), ("On en reparle plus tard.", "我们之后再谈。"),
    ("Je ne veux pas d'ennuis.", "我不想惹麻烦。"), ("Ça reste entre nous.", "这事只有我们知道。"),
    ("Je ne l'avais pas vu venir.", "这我真没想到。"), ("Donne-moi une minute.", "给我一分钟。"),
    ("Je ne peux pas continuer comme ça.", "我不能再这样下去了。"), ("Ça ressemble à un piège.", "听起来像陷阱。"),
    ("Ne commence pas.", "别又来了。"), ("Ne me fais pas regretter.", "别让我后悔。"),
    ("J'essaie d'aider.", "我是在帮忙。"), ("Tu ne m'écoutes pas.", "你根本没在听。"),
    ("Partons d'ici.", "我们离开这里吧。"), ("Reste avec moi.", "陪着我。"),
    ("Ne dis rien.", "什么都别说。"), ("Je gère la situation.", "我能控制住。"),
    ("Ça change tout.", "这下情况全变了。"), ("Ne compte pas là-dessus.", "别指望这个。"),
    ("Ce n'est pas si simple.", "没那么简单。"), ("On verra bien.", "到时候再说。"),
    ("Je n'ai pas le choix.", "我别无选择。"), ("Ne t'en veux pas.", "别责怪自己。"),
    ("On y va étape par étape.", "一步一步来。"), ("Il n'y a pas de retour en arrière.", "没有回头路了。"),
    ("Ce n'est pas terminé.", "这事还没完。"), ("Je t'expliquerai plus tard.", "我之后再解释。"),
]

DE_STARTER = [
    ("Das kann nicht sein.", "不会吧。"), ("Sag mir die Wahrheit.", "跟我说实话。"),
    ("Mach dir keine Sorgen.", "别担心。"), ("Ich kümmere mich darum.", "我来处理。"),
    ("Das geht dich nichts an.", "这不关你的事。"), ("Lass es gut sein.", "算了吧。"),
    ("Warte kurz.", "等一下。"), ("Geht es dir gut?", "你没事吧？"),
    ("Mach es nicht komisch.", "别把气氛搞尴尬。"), ("Sieh mich nicht so an.", "别那样看着我。"),
    ("Ich schulde dir was.", "我欠你个人情。"), ("Das war nicht meine Absicht.", "我不是故意的。"),
    ("Wir haben keine Zeit.", "我们没时间了。"), ("Sprich leiser.", "小声点。"),
    ("Vertrau mir.", "相信我。"), ("Lass mich nicht hier.", "别把我丢在这儿。"),
    ("Das erklärt einiges.", "这就解释得通了。"), ("Das ergibt keinen Sinn.", "这说不通。"),
    ("Nimm es nicht persönlich.", "别往心里去。"), ("Das war unangebracht.", "那太过分了。"),
    ("Ich komme mit dir.", "我跟你一起去。"), ("Ich kann nichts versprechen.", "我不能保证。"),
    ("Du hast recht.", "你说得对。"), ("Ich lag falsch.", "我错了。"),
    ("Ich bin nicht in Stimmung.", "我现在没心情。"), ("Wir reden später darüber.", "我们之后再谈。"),
    ("Ich will keinen Ärger.", "我不想惹麻烦。"), ("Das bleibt unter uns.", "这事只有我们知道。"),
    ("Damit habe ich nicht gerechnet.", "这我真没想到。"), ("Gib mir eine Minute.", "给我一分钟。"),
    ("So kann ich nicht weitermachen.", "我不能再这样下去了。"), ("Das klingt nach einer Falle.", "听起来像陷阱。"),
    ("Fang nicht damit an.", "别又来了。"), ("Lass mich das nicht bereuen.", "别让我后悔。"),
    ("Ich versuche zu helfen.", "我是在帮忙。"), ("Du hörst nicht zu.", "你根本没在听。"),
    ("Lass uns hier verschwinden.", "我们离开这里吧。"), ("Bleib bei mir.", "陪着我。"),
    ("Sag nichts.", "什么都别说。"), ("Ich habe das im Griff.", "我能控制住。"),
    ("Das ändert alles.", "这下情况全变了。"), ("Darauf würde ich nicht zählen.", "别指望这个。"),
    ("So einfach ist das nicht.", "没那么简单。"), ("Das werden wir sehen.", "到时候再说。"),
    ("Ich habe keine Wahl.", "我别无选择。"), ("Gib dir nicht die Schuld.", "别责怪自己。"),
    ("Schritt für Schritt.", "一步一步来。"), ("Es gibt kein Zurück.", "没有回头路了。"),
    ("Das ist noch nicht vorbei.", "这事还没完。"), ("Ich erkläre es dir später.", "我之后再解释。"),
]


def build_packs() -> list[dict]:
    return [
        pack(
            "ai-sub-pro.en-zh.subtitle_colloquial_expanded",
            "en-zh.subtitle_colloquial_expanded.v1.json",
            "en",
            ["subtitle", "dialogue", "colloquial", "expanded"],
            build_en_core(),
        ),
        pack(
            "ai-sub-pro.en-zh.domain_medical",
            "en-zh.domain_medical.v1.json",
            "en",
            ["subtitle", "dialogue", "medical", "hospital", "doctor"],
            build_en_medical(),
        ),
        pack(
            "ai-sub-pro.en-zh.domain_crime",
            "en-zh.domain_crime.v1.json",
            "en",
            ["subtitle", "dialogue", "crime", "police", "procedural"],
            build_en_crime(),
        ),
        pack(
            "ai-sub-pro.en-zh.domain_workplace",
            "en-zh.domain_workplace.v1.json",
            "en",
            ["subtitle", "dialogue", "workplace", "office"],
            build_en_workplace(),
        ),
        pack(
            "ai-sub-pro.ja-zh.subtitle_colloquial_expanded",
            "ja-zh.subtitle_colloquial_expanded.v1.json",
            "ja",
            ["subtitle", "dialogue", "colloquial", "expanded"],
            from_pairs(JA_EXPANDED, ["subtitle", "dialogue", "colloquial"], 0.83),
        ),
        pack(
            "ai-sub-pro.ko-zh.subtitle_colloquial_expanded",
            "ko-zh.subtitle_colloquial_expanded.v1.json",
            "ko",
            ["subtitle", "dialogue", "colloquial", "expanded"],
            from_pairs(KO_EXPANDED, ["subtitle", "dialogue", "colloquial"], 0.83),
        ),
        pack(
            "ai-sub-pro.es-zh.subtitle_colloquial_starter",
            "es-zh.subtitle_colloquial_starter.v1.json",
            "es",
            ["subtitle", "dialogue", "colloquial", "starter"],
            from_pairs(ES_STARTER, ["subtitle", "dialogue", "colloquial"], 0.82),
        ),
        pack(
            "ai-sub-pro.fr-zh.subtitle_colloquial_starter",
            "fr-zh.subtitle_colloquial_starter.v1.json",
            "fr",
            ["subtitle", "dialogue", "colloquial", "starter"],
            from_pairs(FR_STARTER, ["subtitle", "dialogue", "colloquial"], 0.82),
        ),
        pack(
            "ai-sub-pro.de-zh.subtitle_colloquial_starter",
            "de-zh.subtitle_colloquial_starter.v1.json",
            "de",
            ["subtitle", "dialogue", "colloquial", "starter"],
            from_pairs(DE_STARTER, ["subtitle", "dialogue", "colloquial"], 0.82),
        ),
    ]


def render_pack(payload: dict) -> str:
    clean = {key: value for key, value in payload.items() if key != "_filename"}
    return json.dumps(clean, ensure_ascii=False, indent=2) + "\n"


def render_manifest(packs: list[dict]) -> str:
    generated = [
        {
            "id": payload["id"],
            "file": payload["_filename"],
            "version": payload["version"],
        }
        for payload in packs
    ]
    manifest = {
        "schema_version": 1,
        "description": "Bundled synthetic subtitle phrase packs.",
        "packs": EXISTING_PACKS + generated,
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def write_or_check(path: Path, content: str, *, check: bool) -> bool:
    if check:
        return path.exists() and path.read_text(encoding="utf-8") == content
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated packs are out of date")
    args = parser.parse_args()

    packs = build_packs()
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for payload in packs:
        ok = write_or_check(PACK_DIR / payload["_filename"], render_pack(payload), check=args.check) and ok
    ok = write_or_check(PACK_DIR / "manifest.json", render_manifest(packs), check=args.check) and ok
    if args.check and not ok:
        print("Generated phrase packs are out of date. Run tools/phrase_packs/generate_synthetic_packs.py")
        return 1
    print(f"Generated {len(packs)} packs with {sum(len(pack['phrases']) for pack in packs)} examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
