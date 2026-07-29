"""Conservative, bounded discourse links for local subtitle disambiguation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import math
import re
from typing import Iterable


_MAX_LOOKBACK_CUES = 3
_MAX_GAP_SECONDS = 8.0
_MAX_LINK_CONTEXTS = 32
_MAX_SERIALIZED_CONTEXT_CHARS = 24_000
_AMBIGUOUS_NOUNS = frozenset({
    "business",
    "case",
    "kind",
    "one",
    "part",
    "place",
    "point",
    "thing",
    "time",
    "way",
})
_COMPLEMENTARY_POSSESSIVES = {
    "my": frozenset({"your"}),
    "our": frozenset({"your"}),
    "your": frozenset({"my", "our"}),
}
_ECHO_QUESTION_RE = re.compile(
    r"^(my|your|our)\s+([a-z][a-z'-]{1,30})\s*\?$",
    re.IGNORECASE | re.ASCII,
)
_BRACKETED_SPEAKER_PREFIX_RE = re.compile(
    r"^\s*\[(?P<speaker>[^\]\r\n]+)\]\s*(?P<dialogue>.*)$"
)
_INLINE_SPEAKER_RE = re.compile(
    r"^\s*(?P<speaker>[A-Za-z][A-Za-z .'-]{1,30}):\s*",
)
_MUSIC_MARK_RE = re.compile(r"[♪♫♬🎵🎶]")


@dataclass(frozen=True)
class DiscourseLink:
    kind: str
    antecedent_id: int
    echo_id: int
    bridge_ids: tuple[int, ...]
    noun: str
    antecedent_possessive: str
    echo_possessive: str
    distance_cues: int
    gap_seconds: float


def _context_item(block) -> dict:
    original = getattr(block, "text", "")
    draft = getattr(block, "translation", "")
    return {
        "id": getattr(block, "index", None),
        "original": original if isinstance(original, str) else "",
        "draft": draft if isinstance(draft, str) else "",
    }


def _link_context(
    link: DiscourseLink,
    block_by_id: dict[int, object],
    mutable_ids: set[int],
) -> dict | None:
    antecedent = block_by_id.get(link.antecedent_id)
    echo = block_by_id.get(link.echo_id)
    if antecedent is None or echo is None:
        return None
    bridge_context = [
        _context_item(block_by_id[block_id])
        for block_id in link.bridge_ids
        if block_id in block_by_id
    ]
    payload = {
        "kind": link.kind,
        "noun": link.noun,
        "possessive_pair": (
            f"{link.antecedent_possessive}->{link.echo_possessive}"
        ),
        "antecedent": _context_item(antecedent),
        "echo": _context_item(echo),
        "bridge_context": bridge_context,
        "distance_cues": link.distance_cues,
        "gap_seconds": link.gap_seconds,
    }
    payload["read_only_ids"] = [
        block_id
        for block_id in (
            link.antecedent_id,
            *link.bridge_ids,
            link.echo_id,
        )
        if block_id in link.bridge_ids or block_id not in mutable_ids
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["link_hash"] = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    return payload


def _serialized_context_chars(context: dict) -> int:
    return len(json.dumps(
        context,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ))


def serialized_discourse_link_contexts_chars(contexts: Iterable[dict]) -> int:
    return sum(
        _serialized_context_chars(context)
        for context in contexts or []
        if isinstance(context, dict)
    )


def index_discourse_link_contexts(
    contexts: Iterable[dict],
) -> dict[int, list[dict]]:
    """Index complete link contexts by their two mutable endpoint identities."""

    indexed: dict[int, list[dict]] = {}
    for context in contexts or []:
        if not isinstance(context, dict):
            continue
        antecedent = context.get("antecedent")
        echo = context.get("echo")
        if not isinstance(antecedent, dict) or not isinstance(echo, dict):
            continue
        for block_id in (antecedent.get("id"), echo.get("id")):
            if (
                isinstance(block_id, int)
                and not isinstance(block_id, bool)
                and block_id > 0
            ):
                indexed.setdefault(block_id, []).append(context)
    return indexed


def build_discourse_link_contexts(
    blocks: Iterable,
    *,
    focus_ids: set[int] | None = None,
    mutable_ids: set[int] | None = None,
    links: Iterable[DiscourseLink] | None = None,
    max_contexts: int = _MAX_LINK_CONTEXTS,
    max_serialized_chars: int = _MAX_SERIALIZED_CONTEXT_CHARS,
) -> list[dict]:
    """Return hash-bound local contexts without promoting them to terminology."""

    if (
        not isinstance(max_contexts, int)
        or isinstance(max_contexts, bool)
        or max_contexts <= 0
        or not isinstance(max_serialized_chars, int)
        or isinstance(max_serialized_chars, bool)
        or max_serialized_chars <= 0
    ):
        return []
    timeline = list(blocks or [])
    positive_ids = [
        getattr(block, "index", None)
        for block in timeline
        if (
            isinstance(getattr(block, "index", None), int)
            and not isinstance(getattr(block, "index", None), bool)
            and getattr(block, "index", None) > 0
        )
    ]
    if len(positive_ids) != len(set(positive_ids)):
        return []
    block_by_id = {
        getattr(block, "index", None): block
        for block in timeline
        if (
            isinstance(getattr(block, "index", None), int)
            and not isinstance(getattr(block, "index", None), bool)
        )
    }
    selected_ids = set(focus_ids or ())
    mutable = set(mutable_ids or ())
    contexts = []
    detected_links = (
        list(links)
        if links is not None
        else detect_possessive_echo_links(timeline)
    )
    serialized_chars = 0
    for link in detected_links:
        if len(contexts) >= max_contexts:
            break
        endpoint_ids = {link.antecedent_id, link.echo_id}
        if selected_ids and not selected_ids.intersection(endpoint_ids):
            continue
        context = _link_context(link, block_by_id, mutable)
        if context is None:
            continue
        context_chars = _serialized_context_chars(context)
        if serialized_chars + context_chars > max_serialized_chars:
            continue
        contexts.append(context)
        serialized_chars += context_chars
    return contexts


def _explicit_endpoint_dialogue(block) -> tuple[str, str | None] | None:
    if getattr(block, "filtered", False):
        return None
    text = getattr(block, "text", "")
    if not isinstance(text, str):
        return None
    if _MUSIC_MARK_RE.search(text):
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    def is_sdh_or_action_label(label: str) -> bool:
        try:
            from app.engines.translation_qa import (
                is_sound_description_source,
            )
        except ImportError:  # pragma: no cover - defensive cycle guard
            return False
        return (
            is_sound_description_source(label)
            or is_sound_description_source(f"[{label}]")
        )

    try:
        from app.engines.translation_qa import is_sound_description_source
        if is_sound_description_source(text):
            return None
    except ImportError:  # pragma: no cover - defensive import cycle guard
        pass
    speaker = None
    bracketed = _BRACKETED_SPEAKER_PREFIX_RE.fullmatch(lines[0])
    if bracketed is not None:
        raw_speaker = bracketed.group("speaker").strip()
        if is_sdh_or_action_label(raw_speaker):
            return None
        speaker = raw_speaker.casefold()
        inline_dialogue = bracketed.group("dialogue").strip()
        lines = ([inline_dialogue] if inline_dialogue else []) + lines[1:]
    dialogue = " ".join(lines).strip()
    inline = _INLINE_SPEAKER_RE.match(dialogue)
    if inline is not None:
        raw_inline_speaker = inline.group("speaker").strip()
        if is_sdh_or_action_label(raw_inline_speaker):
            return None
        inline_speaker = raw_inline_speaker.casefold()
        if speaker is not None and speaker != inline_speaker:
            return None
        speaker = inline_speaker
        dialogue = dialogue[inline.end():].strip()
    if not dialogue:
        return None
    return dialogue, speaker


def _seconds(value: object) -> float | None:
    if isinstance(value, timedelta):
        seconds = value.total_seconds()
        return seconds if math.isfinite(seconds) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds if math.isfinite(seconds) else None
    return None


def _contains_phrase(text: str, possessive: str, noun: str) -> bool:
    return bool(re.search(
        rf"\b{re.escape(possessive)}\s+{re.escape(noun)}\b",
        text,
        re.IGNORECASE | re.ASCII,
    ))


def _contains_noun(text: object, noun: str) -> bool:
    return bool(
        isinstance(text, str)
        and re.search(
            rf"\b{re.escape(noun)}\b",
            text,
            re.IGNORECASE | re.ASCII,
        )
    )


def detect_possessive_echo_links(
    blocks: Iterable,
    *,
    max_lookback_cues: int = _MAX_LOOKBACK_CUES,
    max_gap_seconds: float = _MAX_GAP_SECONDS,
) -> list[DiscourseLink]:
    """Detect only high-confidence whole-question possessive echoes.

    Cue distance is measured on the supplied original timeline, including any
    intervening non-dialogue cue. The temporal gap is measured from the
    antecedent's end to the echo's start.
    """

    if (
        not isinstance(max_lookback_cues, int)
        or isinstance(max_lookback_cues, bool)
        or max_lookback_cues <= 0
        or not isinstance(max_gap_seconds, (int, float))
        or isinstance(max_gap_seconds, bool)
        or not math.isfinite(float(max_gap_seconds))
        or max_gap_seconds < 0
    ):
        return []
    timeline = list(blocks or [])
    links: list[DiscourseLink] = []
    for echo_position, echo_block in enumerate(timeline):
        echo_endpoint = _explicit_endpoint_dialogue(echo_block)
        if echo_endpoint is None:
            continue
        echo_dialogue, echo_speaker = echo_endpoint
        echo_match = _ECHO_QUESTION_RE.fullmatch(
            echo_dialogue
        )
        if echo_match is None:
            continue
        echo_possessive = echo_match.group(1).lower()
        noun = echo_match.group(2).lower()
        if noun in _AMBIGUOUS_NOUNS:
            continue
        echo_id = getattr(echo_block, "index", None)
        echo_start = _seconds(getattr(echo_block, "start", None))
        if (
            not isinstance(echo_id, int)
            or isinstance(echo_id, bool)
            or echo_start is None
        ):
            continue

        candidates: list[tuple[int, object, str, float]] = []
        first_position = max(0, echo_position - max_lookback_cues)
        for antecedent_position in range(first_position, echo_position):
            antecedent_block = timeline[antecedent_position]
            antecedent_endpoint = _explicit_endpoint_dialogue(
                antecedent_block
            )
            if antecedent_endpoint is None:
                continue
            antecedent_text, antecedent_speaker = antecedent_endpoint
            if (
                antecedent_speaker is not None
                and echo_speaker is not None
                and antecedent_speaker == echo_speaker
            ):
                continue
            antecedent_end = _seconds(
                getattr(antecedent_block, "end", None)
            )
            if antecedent_end is None:
                continue
            gap_seconds = echo_start - antecedent_end
            if gap_seconds < 0 or gap_seconds > max_gap_seconds:
                continue
            matching_possessives = [
                possessive
                for possessive in _COMPLEMENTARY_POSSESSIVES[
                    echo_possessive
                ]
                if _contains_phrase(antecedent_text, possessive, noun)
            ]
            if len(matching_possessives) == 1:
                candidates.append((
                    antecedent_position,
                    antecedent_block,
                    matching_possessives[0],
                    gap_seconds,
                ))
        if len(candidates) != 1:
            continue

        (
            antecedent_position,
            antecedent_block,
            antecedent_possessive,
            gap_seconds,
        ) = candidates[0]
        bridge_blocks = timeline[antecedent_position + 1:echo_position]
        if any(
            _contains_noun(getattr(block, "text", ""), noun)
            for block in bridge_blocks
        ):
            continue
        antecedent_id = getattr(antecedent_block, "index", None)
        span_ids = [
            getattr(block, "index", None)
            for block in timeline[antecedent_position:echo_position + 1]
        ]
        if (
            not isinstance(antecedent_id, int)
            or isinstance(antecedent_id, bool)
            or any(
                not isinstance(block_id, int)
                or isinstance(block_id, bool)
                or block_id <= 0
                for block_id in span_ids
            )
            or len(set(span_ids)) != len(span_ids)
        ):
            continue
        bridge_ids = tuple(span_ids[1:-1])
        links.append(DiscourseLink(
            kind="possessive_echo",
            antecedent_id=antecedent_id,
            echo_id=echo_id,
            bridge_ids=bridge_ids,
            noun=noun,
            antecedent_possessive=antecedent_possessive,
            echo_possessive=echo_possessive,
            distance_cues=echo_position - antecedent_position,
            gap_seconds=round(gap_seconds, 3),
        ))
    return links
