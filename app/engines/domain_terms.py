"""Small curated domain terminology helpers for hard-to-translate subtitles."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable


@dataclass(frozen=True)
class DomainTerm:
    source: str
    target: str
    accepted_targets: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    category: str = "slang"
    notes: str = "curated science terminology"
    tags: tuple[str, ...] = ("science", "paleontology")

    @property
    def sources(self) -> tuple[str, ...]:
        return (self.source, *self.aliases)

    def target_is_present(self, translation: str) -> bool:
        if not isinstance(translation, str) or not translation:
            return False
        return any(target and target in translation for target in self.accepted_targets)


@dataclass(frozen=True)
class DomainTermMatch:
    term: DomainTerm
    matched_source: str
    start: int
    end: int


@dataclass(frozen=True)
class ScientificTermMatch:
    source: str
    matched_source: str
    start: int
    end: int
    category: str = "slang"
    notes: str = "auto-detected scientific/Latinized term; keep one target form consistent"
    confidence: float = 0.72
    tags: tuple[str, ...] = ("auto_detected", "terminology")


_SCIENCE_TERMS: tuple[DomainTerm, ...] = (
    DomainTerm(
        source="Pangaea",
        target="盘古大陆",
        accepted_targets=("盘古大陆", "盤古大陸", "泛大陆", "泛大陸"),
        notes="curated science terminology: supercontinent",
    ),
    DomainTerm(
        source="Gorgonopsian",
        target="丽齿兽类",
        accepted_targets=("丽齿兽", "麗齒獸"),
        aliases=("Gorgonopsians",),
        notes="curated science terminology: gorgonopsian therapsid",
    ),
    DomainTerm(
        source="Gorgon",
        target="丽齿兽",
        accepted_targets=("丽齿兽", "麗齒獸"),
        aliases=("Gorgons",),
        notes="curated science terminology: short-form gorgonopsian reference",
    ),
    DomainTerm(
        source="Elph",
        target="埃尔夫兽",
        accepted_targets=("埃尔夫兽", "埃爾夫獸"),
        notes="curated science terminology: therapsid genus",
    ),
    DomainTerm(
        source="Scutosaurus",
        target="盾甲龙",
        accepted_targets=("盾甲龙", "盾甲龍"),
        notes="curated science terminology: pareiasaur genus",
    ),
    DomainTerm(
        source="Suminia",
        target="苏美尼兽",
        accepted_targets=("苏美尼兽", "蘇美尼獸"),
        notes="curated science terminology: anomodont genus",
    ),
    DomainTerm(
        source="Ischigualastia",
        target="伊斯基瓜拉斯兽",
        accepted_targets=("伊斯基瓜拉斯兽", "伊斯基瓜拉斯獸"),
        notes="curated science terminology: kannemeyeriiform dicynodont genus",
    ),
    DomainTerm(
        source="Dicroidium",
        target="双扇蕨",
        accepted_targets=("双扇蕨", "雙扇蕨"),
        notes="curated science terminology: Triassic seed fern genus",
    ),
    DomainTerm(
        source="Panphagia",
        target="泛噬龙",
        accepted_targets=("泛噬龙", "泛噬龍"),
        notes="curated science terminology: early sauropodomorph dinosaur genus",
    ),
    DomainTerm(
        source="Cyamodus",
        target="豆齿龙",
        accepted_targets=("豆齿龙", "豆齒龍"),
        notes="curated science terminology: placodont genus",
    ),
    DomainTerm(
        source="Dongusuchus",
        target="顿古兹鳄",
        accepted_targets=("顿古兹鳄", "頓古茲鳄", "頓古茲鱷"),
        notes="curated science terminology: aphanosaur genus",
    ),
    DomainTerm(
        source="proto-Pterosaurs",
        target="原翼龙类",
        accepted_targets=("原翼龙", "原翼龍", "翼龙", "翼龍"),
        aliases=("proto pterosaurs", "proto-pterosaurs"),
        notes="curated science terminology: early pterosaur-like reptiles",
    ),
    DomainTerm(
        source="Cymbospondylus",
        target="杯椎鱼龙",
        accepted_targets=("杯椎鱼龙", "杯椎魚龍"),
        notes="curated science terminology: ichthyosaur genus",
    ),
    DomainTerm(
        source="Permian",
        target="二叠纪",
        accepted_targets=("二叠纪", "二疊紀"),
        notes="curated science terminology: geologic period",
    ),
    DomainTerm(
        source="Triassic",
        target="三叠纪",
        accepted_targets=("三叠纪", "三疊紀"),
        notes="curated science terminology: geologic period",
    ),
)

_SCIENTIFIC_SOURCE_RE = re.compile(r"\b[A-Z][A-Za-z-]{4,}(?:'s)?\b")
_SCIENTIFIC_SUFFIXES = (
    "aetus",
    "aspis",
    "astia",
    "ceratops",
    "dactylus",
    "draco",
    "gnathus",
    "ichthys",
    "ichthus",
    "inia",
    "lestes",
    "mimus",
    "odon",
    "odus",
    "opsian",
    "opsians",
    "phagia",
    "pithecus",
    "pondylus",
    "pteryx",
    "pterus",
    "raptor",
    "sauria",
    "saurus",
    "suchus",
    "therium",
    "venator",
    "oidium",
)
_SCIENTIFIC_STOPWORDS = {
    "auditorium",
    "calcium",
    "english",
    "helium",
    "lithium",
    "magnesium",
    "medium",
    "millennium",
    "museum",
    "premium",
    "potassium",
    "sodium",
    "stadium",
}
_SCIENTIFIC_CONTEXT_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "baby",
    "but",
    "female",
    "male",
    "of",
    "old",
    "or",
    "the",
    "to",
    "unlike",
    "while",
    "without",
    "young",
}


def curated_domain_terms() -> tuple[DomainTerm, ...]:
    return _SCIENCE_TERMS


def _normalize_source(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


@lru_cache(maxsize=1)
def _terms_by_source() -> dict[str, DomainTerm]:
    result: dict[str, DomainTerm] = {}
    for term in _SCIENCE_TERMS:
        for source in term.sources:
            result[_normalize_source(source)] = term
    return result


def lookup_domain_term(source: str) -> DomainTerm | None:
    if not isinstance(source, str) or not source.strip():
        return None
    return _terms_by_source().get(_normalize_source(source))


@lru_cache(maxsize=None)
def _source_pattern(source: str) -> re.Pattern:
    return re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(source) + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def find_domain_terms(text: str) -> list[DomainTermMatch]:
    if not isinstance(text, str) or not text:
        return []
    matches: list[DomainTermMatch] = []
    seen: set[str] = set()
    for term in _SCIENCE_TERMS:
        for source in term.sources:
            match = _source_pattern(source).search(text)
            if match is None:
                continue
            key = term.source.casefold()
            if key in seen:
                break
            seen.add(key)
            matches.append(DomainTermMatch(
                term=term,
                matched_source=text[match.start():match.end()],
                start=match.start(),
                end=match.end(),
            ))
            break
    return sorted(matches, key=lambda item: item.start)


def find_domain_terms_in_texts(texts: Iterable[str]) -> list[DomainTermMatch]:
    collected: dict[str, DomainTermMatch] = {}
    for text in texts or []:
        for match in find_domain_terms(text):
            collected.setdefault(match.term.source.casefold(), match)
    return list(collected.values())


def _normalize_scientific_source(value: str) -> str:
    source = re.sub(r"\s+", " ", value.strip()).strip(" \t\r\n.,:;!?()[]{}\"'")
    if source.endswith("'s"):
        source = source[:-2]
    return source


def is_scientific_term_source(source: str) -> bool:
    """Return True for curated terms or auto-detected Latin/scientific-looking terms."""
    source = _normalize_scientific_source(source) if isinstance(source, str) else ""
    if not source:
        return False
    if lookup_domain_term(source) is not None:
        return True
    folded = source.casefold()
    if folded in _SCIENTIFIC_STOPWORDS:
        return False
    letters = re.sub(r"[^A-Za-z]", "", source)
    if len(letters) < 6:
        return False
    if not source[0].isupper() or source.upper() == source:
        return False
    return any(folded.endswith(suffix) for suffix in _SCIENTIFIC_SUFFIXES)


def find_scientific_terms(text: str) -> list[ScientificTermMatch]:
    """Find non-curated scientific/Latinized term candidates in free text.

    The detector intentionally favors high-signal Latinized names and genus-like
    terms. Curated terms are handled by find_domain_terms() so they are not
    returned here.
    """
    if not isinstance(text, str) or not text:
        return []
    matches: list[ScientificTermMatch] = []
    seen: set[str] = set()
    for match in _SCIENTIFIC_SOURCE_RE.finditer(text):
        source = _normalize_scientific_source(match.group(0))
        if not source or lookup_domain_term(source) is not None:
            continue
        if not is_scientific_term_source(source):
            continue
        key = source.casefold()
        if key in seen:
            continue
        seen.add(key)
        matches.append(ScientificTermMatch(
            source=source,
            matched_source=text[match.start():match.end()],
            start=match.start(),
            end=match.end(),
        ))
    return matches


def find_scientific_terms_in_texts(texts: Iterable[str]) -> list[ScientificTermMatch]:
    collected: dict[str, ScientificTermMatch] = {}
    for text in texts or []:
        for match in find_scientific_terms(text):
            collected.setdefault(match.source.casefold(), match)
    return list(collected.values())


def is_scientific_context_phrase(source: str) -> bool:
    """Return True for noisy phrases like 'Without the Dicroidium'.

    The clean scientific term is still emitted separately by find_scientific_terms().
    """
    if not isinstance(source, str) or not source.strip():
        return False
    matches = find_scientific_terms(source)
    domain_matches = find_domain_terms(source)
    if not matches:
        if not domain_matches:
            return False
    if any(source.strip().casefold() == match.source.casefold() for match in matches):
        return False
    if any(source.strip().casefold() == match.term.source.casefold() for match in domain_matches):
        return False
    candidate_words = {
        word.casefold()
        for match in matches
        for word in re.findall(r"[A-Za-z]+", match.source)
    }
    for match in domain_matches:
        for word in re.findall(r"[A-Za-z]+", match.term.source):
            candidate_words.add(word.casefold())
    words = [word.casefold() for word in re.findall(r"[A-Za-z]+", source)]
    extras = [word for word in words if word not in candidate_words]
    return bool(extras) and all(word in _SCIENTIFIC_CONTEXT_WORDS for word in extras)


def project_kb_source_keys(project_kb) -> set[str]:
    keys: set[str] = set()
    if project_kb is None:
        return keys
    for attr in ("characters", "places", "brands", "slang"):
        for entry in getattr(project_kb, attr, []) or []:
            source = getattr(entry, "source", "")
            if isinstance(source, str) and source.strip():
                keys.add(_normalize_source(source))
    return keys


def match_is_overridden_by_project_kb(match: DomainTermMatch, project_kb) -> bool:
    keys = project_kb_source_keys(project_kb)
    if not keys:
        return False
    return any(_normalize_source(source) in keys for source in match.term.sources)


def scientific_match_is_overridden_by_project_kb(match: ScientificTermMatch, project_kb) -> bool:
    keys = project_kb_source_keys(project_kb)
    if not keys:
        return False
    return _normalize_source(match.source) in keys


def build_domain_prompt_snippet(matches: list[DomainTermMatch], project_kb=None) -> tuple[str, list[dict]]:
    lines: list[str] = []
    hits: list[dict] = []
    for match in matches:
        if match_is_overridden_by_project_kb(match, project_kb):
            continue
        term = match.term
        lines.append(f"  - {term.source} → {term.target} ({term.notes})")
        hits.append({
            "source": term.source,
            "target": term.target,
            "matched_source": match.matched_source,
            "notes": term.notes,
            "scope": "curated_domain",
            "tags": list(term.tags),
        })
    if not lines:
        return "", []
    return "\n".join([
        "Curated domain terminology (lower priority than project KB; use when source appears):",
        *lines,
    ]), hits


def build_auto_scientific_prompt_snippet(
    matches: list[ScientificTermMatch],
    project_kb=None,
    *,
    limit: int = 16,
) -> tuple[str, list[dict]]:
    lines: list[str] = []
    hits: list[dict] = []
    for match in matches:
        if scientific_match_is_overridden_by_project_kb(match, project_kb):
            continue
        if len(lines) >= limit:
            break
        lines.append(
            f"  - {match.source}: preserve the standard source form when conventional; "
            "otherwise choose one concise Chinese rendering and reuse it consistently"
        )
        hits.append({
            "source": match.source,
            "target": "",
            "matched_source": match.matched_source,
            "notes": match.notes,
            "scope": "auto_scientific_term",
            "tags": list(match.tags),
        })
    if not lines:
        return "", []
    return "\n".join([
        "Auto-detected terminology (lower priority than project KB; no approved target yet):",
        *lines,
    ]), hits
