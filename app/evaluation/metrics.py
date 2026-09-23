"""Deterministic translation quality metrics."""
from __future__ import annotations

import re
from typing import Any

from app.evaluation.corpus import CorpusCase
from app.engines.entity_registry import aligned_name_span, build_entity_registry


_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_PROPER_NAME_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:['-][A-Za-z]+)*)(?:\s+(?:[A-Z][a-z]+(?:['-][A-Za-z]+)*)){1,}\b"
)
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")
_LEADING_NAME_STOPWORDS = {"A", "An", "The", "This", "That", "These", "Those"}
_LEADING_EVENT_STOPWORDS = {
    "If",
    "Unless",
    "After",
    "Before",
    "During",
    "Once",
    "When",
    "While",
}
_LEADING_CONTEXT_PREPOSITIONS = {
    "At",
    "By",
    "For",
    "From",
    "In",
    "Into",
    "Near",
    "On",
    "Over",
    "To",
    "Through",
}
_DIRECTIONAL_REGION_MODIFIERS = {
    "Central",
    "East",
    "Eastern",
    "North",
    "Northeast",
    "Northeastern",
    "Northern",
    "Northwest",
    "Northwestern",
    "South",
    "Southeast",
    "Southeastern",
    "Southern",
    "Southwest",
    "Southwestern",
    "West",
    "Western",
}
_BROAD_REGION_TERMS = {
    "Africa",
    "America",
    "Americas",
    "Arctic",
    "Asia",
    "Atlantic",
    "Caribbean",
    "Europe",
    "Mediterranean",
    "Pacific",
}
_SOURCE_PERSON_TITLE_TOKENS = {
    "Director",
    "Chef",
    "Secretary",
    "Admiral",
    "Captain",
    "Colonel",
    "Commander",
    "Doctor",
    "Dr",
    "Flight",
    "General",
    "Group",
    "Lieutenant",
    "Major",
    "Marshal",
    "Officer",
    "Private",
    "Professor",
    "Princess",
    "Prof",
    "Sergeant",
}
_SOURCE_ORG_UNIT_TOKENS = {
    "Agency",
    "Airport",
    "Bureau",
    "Command",
    "Committee",
    "Department",
    "Desk",
    "Division",
    "Headquarters",
    "House",
    "Office",
    "Republic",
    "Section",
    "Service",
    "Station",
    "Tree",
    "Unit",
}
_COMMON_TITLE_PHRASES = {
    "Are You",
    "Good Morning",
    "Good Afternoon",
    "Good Evening",
    "Good Night",
    "How Are You",
    "Where Are You",
    "What Are You",
    "Who Are You",
    "Why Are You",
    "Thank You",
    "Excuse Me",
    "I Love You",
}
_COMMON_TITLE_WORDS = {
    "are",
    "good",
    "how",
    "morning",
    "afternoon",
    "evening",
    "night",
    "where",
    "what",
    "who",
    "why",
    "thank",
    "you",
    "excuse",
    "me",
    "please",
    "sorry",
    "hello",
    "hi",
    "welcome",
}
_SHORT_NAME_CONTEXT_CHARS = {
    "的",
    "了",
    "到",
    "看",
    "见",
    "来",
    "跑",
    "走",
    "说",
    "在",
    "去",
    "是",
    "有",
    "会",
    "想",
    "要",
    "让",
    "把",
    "被",
    "很",
    "真",
    "太",
    "都",
    "也",
    "还",
    "又",
    "呢",
    "吗",
}
_LONG_NAME_IDENTITY_SUFFIXES = (
    "宫",
    "屋",
    "树",
    "医院",
    "大学",
    "学院",
    "中学",
    "小学",
    "车站",
    "机场",
    "公园",
    "广场",
    "中心",
    "酒店",
    "饭店",
    "公司",
    "集团",
    "社区",
    "小区",
    "大厦",
    "城",
    "镇",
    "市",
    "县",
    "区",
    "乡",
    "村",
    "庄",
    "街",
    "路",
    "桥",
)
_SHORT_PLACE_IDENTITY_SUFFIXES = (
    "宫",
    "屋",
    "树",
    "机场",
    "共和国",
)
_LONG_NAME_IDENTITY_PREFIXES = (
    "老",
    "小",
    "新",
    "旧",
    "大",
    "东",
    "西",
    "南",
    "北",
    "中",
)
_LONG_NAME_CONTEXT_ANCHORS = (
    "一切正常",
    "很安静",
    "看起来",
    "灯火通明",
    "美极了",
    "空荡",
    "正常",
)
_LONG_NAME_CONTEXT_PREFIX_HINTS = (
    "我",
    "你",
    "他",
    "她",
    "它",
    "这",
    "那",
    "们",
    "在",
    "从",
    "到",
    "去",
    "来",
    "住",
    "看",
    "见",
    "喜欢",
    "讨厌",
    "非常",
    "特别",
    "真的",
    "了",
)
_LONG_NAME_CONTEXT_PREFIX_TOKENS = (
    "喂",
    "你好",
    "您好",
    "长官",
    "先生",
    "女士",
    "介绍",
    "介绍一下",
    "喜欢",
    "讨厌",
    "昨天",
    "今天",
    "明天",
    "突然",
    "随后",
    "然后",
    "后来",
    "之前",
    "之后",
    "以前",
    "过去",
    "当时",
    "那时",
    "此时",
    "刚才",
    "刚刚",
    "现在",
    "今晚",
    "昨晚",
    "明晚",
    "我们",
    "你们",
    "他们",
    "她们",
    "它们",
    "这",
    "那",
    "这个",
    "那个",
    "这位",
    "那位",
    "这只",
    "那只",
    "这头",
    "那头",
    "这匹",
    "那匹",
    "这条",
    "那条",
    "这群",
    "那群",
    "这对",
    "那对",
    "一只",
    "一头",
    "一匹",
    "一条",
    "一群",
    "一对",
    "我",
    "你",
    "他",
    "她",
    "它",
    "们",
    "在",
    "从",
    "到",
    "去",
    "来",
    "住",
    "看",
    "见",
    "了",
)


def _by_id(blocks: list[dict[str, str]], text_key: str) -> dict[str, str]:
    result = {}
    for block in blocks:
        block_id = str(block.get("id", "")).strip()
        if block_id:
            value = block.get(text_key, "")
            result[block_id] = value if isinstance(value, str) else ""
    return result


def _tags(text: str) -> list[str]:
    return _TAG_RE.findall(text if isinstance(text, str) else "")


def _round(value: float) -> float:
    return round(value, 4)


def _clean_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", _clean_text(text))


def _is_sentence_start(source_text: str, start: int) -> bool:
    if start <= 0:
        return True
    prefix = _clean_text(source_text)[:start].rstrip()
    if not prefix:
        return True
    return prefix[-1] in ".!?;:\n\r\"'()[]{}"


def _looks_like_common_title_phrase(source_text: str, start: int, name: str) -> bool:
    if name in _COMMON_TITLE_PHRASES:
        return True
    if not _is_sentence_start(source_text, start):
        return False
    tokens = [token.lower() for token in name.split()]
    return bool(tokens) and all(token in _COMMON_TITLE_WORDS for token in tokens)


def _is_supported_proper_name(source_text: str, start: int, name: str) -> bool:
    tokens = name.split()
    if len(tokens) < 2:
        return False
    if any(len(token) < 2 for token in tokens):
        return False
    if all(token.strip(".") in _SOURCE_PERSON_TITLE_TOKENS for token in tokens):
        return False
    if tokens[0] in _LEADING_EVENT_STOPWORDS:
        return False
    if tokens[0] in _LEADING_NAME_STOPWORDS and len(tokens) < 3:
        return False
    if _looks_like_common_title_phrase(source_text, start, name):
        return False
    return True


def _strip_leading_context_preposition(name: str, start: int) -> tuple[str, int]:
    tokens = name.split()
    if len(tokens) >= 3 and tokens[0] in _LEADING_CONTEXT_PREPOSITIONS:
        stripped = " ".join(tokens[1:])
        return stripped, start + len(tokens[0]) + 1
    return name, start


def _looks_like_broad_region_phrase(name: str) -> bool:
    tokens = name.split()
    return (
        len(tokens) == 2
        and tokens[0] in _DIRECTIONAL_REGION_MODIFIERS
        and tokens[1] in _BROAD_REGION_TERMS
    )


def _has_source_person_title(proper_name: str) -> bool:
    return any(token.strip(".") in _SOURCE_PERSON_TITLE_TOKENS for token in proper_name.split())


def _is_source_title_only(proper_name: str) -> bool:
    tokens = proper_name.split()
    qualifiers = {"Police", "Chief", "Deputy", "Assistant"}
    return _has_source_person_title(proper_name) and all(
        token in _SOURCE_PERSON_TITLE_TOKENS or token in qualifiers
        for token in tokens
    )


def _has_source_org_unit(proper_name: str) -> bool:
    return any(token.strip(".") in _SOURCE_ORG_UNIT_TOKENS for token in proper_name.split())


def _has_source_person_title_context(proper_name: str, source_texts: list[str]) -> bool:
    if _has_source_person_title(proper_name):
        return True
    matcher = re.compile(rf"\b{re.escape(proper_name)}\b")
    for source_text in source_texts:
        for match in matcher.finditer(_clean_text(source_text)):
            prefix = source_text[:match.start()]
            prefix_tokens = re.findall(r"[A-Za-z]+", prefix[-80:])
            if any(token in _SOURCE_PERSON_TITLE_TOKENS for token in prefix_tokens[-6:]):
                return True
    return False


def _extract_proper_names(source_text: str) -> list[str]:
    names = []
    for match in _PROPER_NAME_RE.finditer(_clean_text(source_text)):
        name, start = _strip_leading_context_preposition(match.group(0), match.start())
        tokens = name.split()
        if len(tokens) >= 3 and tokens[0] in {"A", "An", "The"}:
            start += len(tokens[0]) + 1
            name = " ".join(tokens[1:])
            tokens = name.split()
        if len(tokens) >= 3 and tokens[0] in {"Call", "Find", "Contact", "Ask"}:
            start += len(tokens[0]) + 1
            name = " ".join(tokens[1:])
        # Possession belongs to the surrounding sentence, never to the name.
        name = re.sub(r"['’]s$", "", name)
        if _looks_like_broad_region_phrase(name):
            continue
        if _is_supported_proper_name(source_text, start, name):
            names.append(name)
    return names


def _repeated_proper_names(source_by_id: dict[str, str]) -> list[str]:
    counts: dict[str, int] = {}
    for source_text in source_by_id.values():
        for name in _extract_proper_names(source_text):
            counts[name] = counts.get(name, 0) + 1
    return sorted(name for name, count in counts.items() if count > 1)


def _is_short_source_name(proper_name: str) -> bool:
    tokens = proper_name.split()
    return (
        len(tokens) == 2
        and sum(len(token) for token in tokens) <= 8
        and max((len(token) for token in tokens), default=0) <= 4
    )


def _cjk_compact_text(text: str) -> str:
    return "".join(_CJK_RE.findall(_compact_whitespace(text)))


def _cjk_substrings(text: str, min_length: int = 2) -> set[str]:
    if len(text) < min_length:
        return set()
    limit = min(len(text), 12)
    substrings = set()
    for start in range(len(text)):
        max_end = min(len(text), start + limit)
        for end in range(start + min_length, max_end + 1):
            substrings.add(text[start:end])
    return substrings


def _common_cjk_substrings(translations: list[str], min_length: int = 2) -> list[str]:
    if not translations:
        return []
    shared = _cjk_substrings(translations[0], min_length=min_length)
    for translation in translations[1:]:
        shared &= _cjk_substrings(translation, min_length=min_length)
        if not shared:
            return []
    return sorted(shared, key=lambda item: (-len(item), item))


def _anchor_neighbors(text: str, anchor: str) -> tuple[str, str]:
    index = text.find(anchor)
    if index < 0:
        return "", ""
    before = text[index - 1] if index > 0 else ""
    after_index = index + len(anchor)
    after = text[after_index] if after_index < len(text) else ""
    return before, after


def _has_conflicting_neighbor(chars: list[str]) -> bool:
    return len({char for char in chars if char}) > 1


def _is_unsafe_shared_anchor(anchor: str, translations: list[str]) -> bool:
    before_chars = []
    after_chars = []
    for translation in translations:
        before, after = _anchor_neighbors(translation, anchor)
        before_chars.append(before)
        after_chars.append(after)
    return _has_conflicting_neighbor(before_chars) or _has_conflicting_neighbor(after_chars)


def _contains_context_chars(anchor: str) -> bool:
    return any(char in _SHORT_NAME_CONTEXT_CHARS for char in anchor)


def _is_context_anchor(anchor: str) -> bool:
    if _contains_context_chars(anchor):
        return True
    return any(anchor in phrase or phrase in anchor for phrase in _LONG_NAME_CONTEXT_ANCHORS)


def _prefix_before_anchor(text: str, anchor: str) -> str:
    index = text.find(anchor)
    return text[:index] if index > 0 else ""


def _suffix_after_anchor(text: str, anchor: str) -> str:
    index = text.find(anchor)
    if index < 0:
        return ""
    return text[index + len(anchor):]


def _looks_like_sentence_prefix(prefix: str, min_name_prefix_length: int = 4) -> bool:
    if len(prefix) < min_name_prefix_length:
        return True
    if not _anchor_adjacent_name_prefix(prefix):
        return True
    return any(hint in prefix for hint in _LONG_NAME_CONTEXT_PREFIX_HINTS)


def _anchor_adjacent_name_prefix(prefix: str) -> str:
    chunk = prefix
    while chunk:
        context = next(
            (item for item in _LONG_NAME_CONTEXT_PREFIX_TOKENS if chunk.startswith(item)),
            "",
        )
        if not context:
            break
        chunk = chunk[len(context):]
    return chunk[-3:]


def _looks_like_name_prefix_chunk(prefix: str) -> bool:
    chunk = _anchor_adjacent_name_prefix(prefix)
    if not chunk or len(chunk) > 3:
        return False
    if _contains_context_chars(chunk):
        return False
    return not any(hint in chunk for hint in _LONG_NAME_CONTEXT_PREFIX_HINTS)


def _has_conflicting_name_prefixes(
    anchor: str, translations: list[str], min_name_prefix_length: int = 4
) -> bool:
    prefixes = [_prefix_before_anchor(text, anchor) for text in translations]
    nonempty = [prefix for prefix in prefixes if prefix]
    if len(nonempty) != len(prefixes):
        return False
    if len(set(nonempty)) < 2:
        return False
    return all(
        not _looks_like_sentence_prefix(prefix, min_name_prefix_length)
        for prefix in nonempty
    )


def _looks_like_ordinary_context_prefix(prefix: str) -> bool:
    if not prefix:
        return True
    if len(prefix) <= 2 and _contains_context_chars(prefix):
        return True
    return any(
        prefix == token or prefix.endswith(token)
        for token in _LONG_NAME_CONTEXT_PREFIX_TOKENS
    )


def _has_competing_name_prefix_chunks(
    anchor: str,
    translations: list[str],
    allow_context_prefixes: bool = False,
) -> bool:
    prefixes = [_prefix_before_anchor(text, anchor) for text in translations]
    if allow_context_prefixes:
        prefixes = [
            "" if _looks_like_ordinary_context_prefix(prefix) else prefix
            for prefix in prefixes
        ]
    chunks = [_anchor_adjacent_name_prefix(prefix) for prefix in prefixes]
    nonempty = [chunk for chunk in chunks if chunk]
    if len(nonempty) != len(chunks):
        return False
    if len(set(nonempty)) < 2:
        return False
    return all(_looks_like_name_prefix_chunk(chunk) for chunk in nonempty)


def _estimated_cjk_name_length_floor(
    proper_name: str, has_title_context: bool = False
) -> int:
    letter_count = sum(len(re.sub(r"[^A-Za-z]", "", token)) for token in proper_name.split())
    if has_title_context or _has_source_person_title(proper_name):
        return 3
    return max(4, (letter_count + 2) // 3)


def _looks_like_ordinary_context_suffix(suffix: str) -> bool:
    if len(suffix) < 3:
        return True
    if _contains_context_chars(suffix[:3]):
        return True
    return any(suffix.startswith(anchor) for anchor in _LONG_NAME_CONTEXT_ANCHORS)


def _has_competing_name_suffixes(
    anchor: str,
    translations: list[str],
    proper_name: str,
    has_title_context: bool = False,
) -> bool:
    if any(anchor.endswith(suffix) for suffix in _SHORT_PLACE_IDENTITY_SUFFIXES):
        return False
    if len(anchor) >= _estimated_cjk_name_length_floor(proper_name, has_title_context):
        return False
    suffixes = [_suffix_after_anchor(text, anchor) for text in translations]
    if len(set(suffixes)) < 2:
        return False
    substantive = [
        suffix for suffix in suffixes if suffix and not _looks_like_ordinary_context_suffix(suffix)
    ]
    return len(substantive) >= 2 or (bool(substantive) and "" in suffixes)


def _is_valid_long_name_anchor(
    anchor: str,
    translations: list[str],
    proper_name: str = "",
    has_title_context: bool = False,
) -> bool:
    # Safe anchors are plausible full target-name cores that may appear with
    # different sentence context. Unsafe anchors are repeated context phrases
    # or shared subparts of competing prefix/suffix transliterations.
    if _is_context_anchor(anchor):
        return False
    allow_context_prefixes = True
    if _has_competing_name_prefix_chunks(
        anchor,
        translations,
        allow_context_prefixes=allow_context_prefixes,
    ):
        return False
    if proper_name and _has_competing_name_suffixes(
        anchor,
        translations,
        proper_name,
        has_title_context,
    ):
        return False
    return not _has_conflicting_name_prefixes(anchor, translations)


def _is_valid_short_name_anchor(anchor: str, translations: list[str]) -> bool:
    if _contains_context_chars(anchor):
        return False
    return not _has_conflicting_name_prefixes(
        anchor, translations, min_name_prefix_length=1
    )


def _shared_cjk_anchor(translations: list[str]) -> str:
    common = _common_cjk_substrings(translations, min_length=2)
    if not common:
        return ""

    unsafe = {
        anchor for anchor in common if _is_unsafe_shared_anchor(anchor, translations)
    }
    for anchor in common:
        if anchor in unsafe:
            continue
        if any(anchor != other and anchor in other for other in unsafe):
            continue
        return anchor
    return ""


def _long_name_cjk_anchor(
    translations: list[str],
    proper_name: str = "",
    has_title_context: bool = False,
) -> str:
    common = _common_cjk_substrings(translations, min_length=4)
    for anchor in common:
        if _is_valid_long_name_anchor(anchor, translations, proper_name, has_title_context):
            return anchor
    return ""


def _fallback_long_name_anchor(
    translations: list[str],
    proper_name: str = "",
    has_title_context: bool = False,
) -> str:
    common = _common_cjk_substrings(translations, min_length=2)
    for anchor in common:
        if _is_valid_long_name_anchor(anchor, translations, proper_name, has_title_context):
            return anchor
    return ""


def _short_name_cjk_anchor(translations: list[str]) -> str:
    common = _common_cjk_substrings(translations, min_length=2)
    for anchor in common:
        if len(anchor) <= 3 and _is_valid_short_name_anchor(anchor, translations):
            return anchor
    return ""


def _explicit_book_title_anchor(translations: list[str]) -> str:
    """Use visible title boundaries, never a short substring of another title."""
    title_sets = [set(re.findall(r"《([\u3400-\u9fff]{2,12})》", text))
                  for text in translations]
    candidates = set().union(*title_sets)
    anchors = []
    for title in candidates:
        if any(titles and titles != {title} for titles in title_sets):
            continue
        # Unquoted mentions must end at a visible boundary as well. This
        # prevents a title prefix from hiding a longer, different rendering.
        if all(re.search(re.escape(title) + r"(?![\u3400-\u9fff])", text)
               for text in translations):
            anchors.append(title)
    return anchors[0] if len(anchors) == 1 else ""


def _target_signature(translation: str, shared_anchor: str = "") -> str:
    cjk_text = _cjk_compact_text(translation)
    if shared_anchor and shared_anchor in cjk_text:
        return shared_anchor
    if cjk_text:
        return cjk_text
    return _compact_whitespace(translation)


def _consume_identity_suffixes(text: str, start: int) -> int:
    end = start
    while True:
        tail = text[end:]
        marker = next(
            (item for item in _LONG_NAME_IDENTITY_SUFFIXES if tail.startswith(item)),
            "",
        )
        if not marker:
            return end
        end += len(marker)


def _consume_identity_prefixes(text: str, start: int) -> int:
    begin = start
    while True:
        head = text[:begin]
        marker = next(
            (item for item in _LONG_NAME_IDENTITY_PREFIXES if head.endswith(item)),
            "",
        )
        if not marker:
            return begin
        begin -= len(marker)


def _long_name_signature(
    translation: str,
    shared_anchor: str,
    proper_name: str = "",
    has_title_context: bool = False,
) -> str:
    """Return a plausible translated-name chunk for long CJK names.

    Examples:
    - `我去哈德逊奥克斯` and `她讨厌哈德逊奥克斯` -> `哈德逊奥克斯` (no issue)
    - `哈德逊奥克斯镇很安静` and `哈德逊奥克斯市看起来空荡` -> different chunks (issue)
    - `哈德逊奥克斯` and `哈德逊橡树` -> different chunks (issue)
    """
    cjk_text = _cjk_compact_text(translation)
    if _has_source_person_title(proper_name):
        titles = re.findall(r"(?:副|代理|助理)?(?:警督|警长|局长|行政长官|上校|少校)", translation)
        if len(set(titles)) == 1 and (not shared_anchor or len(shared_anchor) < 3):
            span = aligned_name_span(proper_name, "", translation)
            return (_cjk_compact_text(span[0]) if span and not _is_source_title_only(proper_name) else "") + titles[0]
    if not shared_anchor or shared_anchor not in cjk_text:
        span = aligned_name_span(proper_name, "", translation)
        return _cjk_compact_text(span[0]) if span else ""
    if _is_source_title_only(proper_name):
        # A rank such as Police Lieutenant may translate to just two CJK
        # characters. Surrounding speaker names are not part of that rank.
        start = cjk_text.find(shared_anchor)
        prefix = cjk_text[:start]
        qualifier = next((q for q in ("代理", "助理", "副") if prefix.endswith(q)), "")
        return qualifier + shared_anchor
    if (has_title_context or _has_source_person_title(proper_name)) and len(shared_anchor) >= 3:
        # Rank/title-led names often appear as `克里克上校`, `克里克说的`,
        # or `克里克来不来` across subtitle context. Compare the stable
        # translated name core instead of the whole sentence.
        return shared_anchor
    anchor_start = cjk_text.find(shared_anchor)
    start = _consume_identity_prefixes(cjk_text, anchor_start)
    end = anchor_start + len(shared_anchor)
    end = _consume_identity_suffixes(cjk_text, end)
    if _has_source_org_unit(proper_name) and len(shared_anchor) >= 2:
        return shared_anchor
    if len(shared_anchor) < 4:
        span = aligned_name_span(proper_name, "", translation)
        return _cjk_compact_text(span[0]) if span else ""
    return cjk_text[start:end] or shared_anchor


def terminology_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    combined = "\n".join(candidate_by_id.values())
    hits = []
    misses = []
    for term in case.expected_terms:
        target = term["target"]
        if target and target in combined:
            hits.append(term)
        else:
            misses.append(term)
    total = len(case.expected_terms)
    return {
        "hit_count": len(hits),
        "total": total,
        "hit_rate": _round(len(hits) / total) if total else 1.0,
        "misses": misses,
    }


def missing_translation_score(
    candidate_by_id: dict[str, str], source_ids: list[str] | None = None
) -> dict[str, Any]:
    missing_ids = [
        block_id for block_id, text in candidate_by_id.items() if not text.strip()
    ]
    if source_ids is None:
        source_missing_ids = []
        missing_count = len(missing_ids)
        total = len(candidate_by_id)
    else:
        source_missing_ids = [
            block_id
            for block_id in source_ids
            if not candidate_by_id.get(block_id, "").strip()
        ]
        missing_count = len(source_missing_ids)
        total = len(source_ids)
    return {
        "missing_ids": missing_ids,
        "source_missing_ids": source_missing_ids,
        "missing_count": missing_count,
        "source_missing_count": len(source_missing_ids),
        "candidate_missing_count": len(missing_ids),
        "total": total,
        "rate": _round(missing_count / total) if total else 0.0,
    }


def row_alignment_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    source_ids = {str(block["id"]) for block in case.source_blocks}
    candidate_ids = set(candidate_by_id)
    missing = sorted(source_ids - candidate_ids)
    extra = sorted(candidate_ids - source_ids)
    aligned = len(source_ids & candidate_ids)
    total_ids = len(source_ids | candidate_ids)
    return {
        "source_count": len(source_ids),
        "candidate_count": len(candidate_ids),
        "missing_ids": missing,
        "extra_ids": extra,
        "rate": _round(aligned / total_ids) if total_ids else 1.0,
    }


def format_score(case: CorpusCase, candidate_by_id: dict[str, str]) -> dict[str, Any]:
    source_by_id = _by_id(case.source_blocks, "text")
    broken = []
    for block_id, source_text in source_by_id.items():
        expected_tags = _tags(source_text)
        candidate_tags = _tags(candidate_by_id.get(block_id, ""))
        if candidate_tags != expected_tags:
            broken.append(block_id)
    total_tagged = sum(
        1
        for block_id, source_text in source_by_id.items()
        if _tags(source_text) or _tags(candidate_by_id.get(block_id, ""))
    )
    return {
        "broken_ids": broken,
        "tagged_count": total_tagged,
        "breakage_rate": _round(len(broken) / total_tagged) if total_tagged else 0.0,
    }


def _single_word_speaker_name_issues(source_by_id, candidate_by_id):
    """Use explicit label boundaries; never infer a name from its dialogue."""
    label_re = re.compile(r"[\[［]([^\]］]+)[\]］]")
    cue_labels = {
        "Music", "Applause", "Laughing", "Laughter", "Groans", "Grunts",
        "Sighs", "Cheering", "Screams", "Panting", "Radio", "Phone",
        "News", "Voicemail",
    }
    observations = {}
    for bid, source in source_by_id.items():
        source_labels = label_re.findall(source)
        target = candidate_by_id.get(bid, "")
        target_labels = label_re.findall(target)
        # Missing/removed cues make positional pairing ambiguous.
        if len(source_labels) != len(target_labels):
            continue
        for name, translated_name in zip(source_labels, target_labels):
            if (not re.fullmatch(r"[A-Z][a-z]+(?:['-][A-Za-z]+)*", name)
                    or name in cue_labels or not _CJK_RE.search(translated_name)):
                continue
            observations.setdefault(name, []).append({
                "block_id": bid, "source_text": source, "translation": target,
                "target_signature": _cjk_compact_text(translated_name),
                "target_anchor": "",
            })
    issues = []
    for name, items in observations.items():
        forms = list(dict.fromkeys(item["target_signature"] for item in items))
        if len(forms) > 1:
            issues.append({"source": name, "target_forms": forms, "observations": items})
    return issues


def proper_name_consistency_score(
    source_by_id: dict[str, str], candidate_by_id: dict[str, str]
) -> dict[str, Any]:
    normalized_source_by_id = {
        str(block_id).strip(): _clean_text(source_text)
        for block_id, source_text in source_by_id.items()
        if str(block_id).strip()
    }
    normalized_candidate_by_id = {
        str(block_id).strip(): _clean_text(translation)
        for block_id, translation in candidate_by_id.items()
        if str(block_id).strip()
    }

    issues = []
    repeated_names = _repeated_proper_names(normalized_source_by_id)
    for proper_name in repeated_names:
        matcher = re.compile(rf"\b{re.escape(proper_name)}\b")
        observations = []

        for block_id, source_text in normalized_source_by_id.items():
            if not matcher.search(source_text):
                continue
            translation = normalized_candidate_by_id.get(block_id, "")
            if not translation.strip():
                continue
            observations.append({
                "block_id": block_id,
                "source_text": source_text,
                "translation": translation,
            })

        if len(observations) < 2:
            continue

        has_title_context = _has_source_person_title_context(
            proper_name,
            [item["source_text"] for item in observations],
        )
        cjk_translations = [
            cjk_text
            for cjk_text in (_cjk_compact_text(item["translation"]) for item in observations)
            if cjk_text
        ]
        # With multiple source entities a shared book title cannot identify
        # which translated span belongs to the entity being checked.
        explicit_title_anchor = ""
        if all(not _extract_proper_names(matcher.sub("", item["source_text"]))
               for item in observations):
            explicit_title_anchor = _explicit_book_title_anchor(
                [item["translation"] for item in observations]
            )
        shared_anchor = ""
        if _is_short_source_name(proper_name):
            shared_anchor = _short_name_cjk_anchor(cjk_translations)
        else:
            shared_anchor = _long_name_cjk_anchor(
                cjk_translations,
                proper_name,
                has_title_context,
            )
        if not shared_anchor and not _is_short_source_name(proper_name):
            shared_anchor = _fallback_long_name_anchor(
                cjk_translations,
                proper_name,
                has_title_context,
            )

        target_forms = []
        for item in observations:
            aligned = aligned_name_span(
                proper_name, item["source_text"], item["translation"],
                source_aliases=[name for name in _extract_proper_names(item["source_text"])
                                if name.endswith(" " + proper_name)],
            )
            if aligned and "·" in aligned[0] and any(
                name != proper_name and name.endswith(" " + proper_name)
                for name in _extract_proper_names(item["source_text"])
            ):
                aligned = (aligned[0].split("·")[-1], aligned[1])
            # Keep rank/place qualifier checks in the existing title path;
            # a person's transliterated core must not include sentence text.
            use_bounded = aligned and not has_title_context and (not _has_source_person_title(proper_name)
                                      or "Agent" in proper_name.split())
            book_titles = re.findall(r"《([^》]+)》", item["translation"])
            if explicit_title_anchor:
                signature = explicit_title_anchor
            elif len(book_titles) == 1 and len(_extract_proper_names(item["source_text"])) == 1:
                signature = book_titles[0]
            elif use_bounded:
                signature = _cjk_compact_text(aligned[0])
                item["target_span"] = aligned[0]
                item["evidence"] = aligned[1]
            elif _is_short_source_name(proper_name):
                signature = shared_anchor
            else:
                signature = _long_name_signature(
                    item["translation"],
                    shared_anchor,
                    proper_name,
                    has_title_context,
                )
            item["target_signature"] = signature
            item["target_anchor"] = explicit_title_anchor or shared_anchor
            if signature and signature not in target_forms:
                target_forms.append(signature)

        # An explicitly dotted full target licenses its surname address;
        # different full names still remain distinct observations.
        surnames = {t.split("·")[-1] for t in
                    [o.get("target_span", "") for o in observations] if "·" in t}
        if surnames:
            target_forms = [f for f in target_forms if f not in surnames]
            observations = [o for o in observations if o.get("target_signature") not in surnames]
        if len(target_forms) > 1:
            issues.append({
                "source": proper_name,
                "target_forms": target_forms,
                "observations": [o for o in observations if o["target_signature"]],
            })

    entities = build_entity_registry(normalized_source_by_id, normalized_candidate_by_id)
    for entity in entities:
        if len(entity["target_forms"]) < 2:
            continue
        if entity["aliases"] and re.fullmatch(r"(?:[A-Z]\.){2,}", entity["source"]):
            # Initials, expanded given name and surname are address forms;
            # this deterministic pass cannot declare one a wrong identity.
            continue
        parents = [name for name in repeated_names
                   if re.search(r"(?<!\w)" + re.escape(entity["source"]) + r"(?!\w)", name, re.I)]
        if parents and all(any(name.casefold() in o["source_text"].casefold() for name in parents)
                           for o in entity["observations"]):
            continue
        # A reported full-name difference already includes its components.
        if any(re.search(r"(?<!\w)" + re.escape(entity["source"]) + r"(?!\w)",
                         issue["source"], re.I) for issue in issues):
            continue
        issues.append(entity)
    return {
        "issue_count": len(issues),
        "issues": issues,
        "entities": entities,
    }


def evaluate_case(case: CorpusCase) -> dict[str, Any]:
    candidate_by_id = _by_id(case.candidate_blocks, "translation")
    source_ids = list(_by_id(case.source_blocks, "text"))
    return {
        "case_id": case.id,
        "tags": list(case.tags),
        "terminology": terminology_score(case, candidate_by_id),
        "missing_translation": missing_translation_score(candidate_by_id, source_ids),
        "row_alignment": row_alignment_score(case, candidate_by_id),
        "format": format_score(case, candidate_by_id),
    }
