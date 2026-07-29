from datetime import timedelta
import json

import pytest

from app.utils.srt import SubtitleBlock


def _block(
    index: int,
    text: str,
    *,
    start: float,
    duration: float = 1.0,
    translation: str = "",
) -> SubtitleBlock:
    return SubtitleBlock(
        index=index,
        start=timedelta(seconds=start),
        end=timedelta(seconds=start + duration),
        text=text,
        translation=translation,
    )


def test_detects_bounded_non_contiguous_possessive_echo():
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(
            84,
            "[Luis]\nWith your boy here as leverage?",
            start=0,
            translation="有你儿子做人质？",
        ),
        _block(
            85,
            "Our plan just got a hell of a lot easier.",
            start=2,
            translation="我们的计划容易多了。",
        ),
        _block(86, "My boy?", start=4, translation="我儿子？"),
    ]

    links = detect_possessive_echo_links(blocks)

    assert len(links) == 1
    link = links[0]
    assert link.kind == "possessive_echo"
    assert link.antecedent_id == 84
    assert link.echo_id == 86
    assert link.bridge_ids == (85,)
    assert link.noun == "boy"
    assert link.antecedent_possessive == "your"
    assert link.echo_possessive == "my"
    assert link.distance_cues == 2


def test_accepts_exact_three_cue_and_eight_second_bounds():
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(10, "You brought your badge.", start=0, duration=1),
        _block(11, "First bridge.", start=2),
        _block(12, "Second bridge.", start=5),
        _block(13, "My badge?", start=9),
    ]

    links = detect_possessive_echo_links(blocks)

    assert [(link.antecedent_id, link.echo_id) for link in links] == [(10, 13)]


@pytest.mark.parametrize(
    ("antecedent", "echo"),
    [
        ("That is your badge.", "Our badge?"),
        ("That is our badge.", "Your badge?"),
    ],
)
def test_accepts_only_supported_complementary_possessive_pairs(
    antecedent,
    echo,
):
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(15, antecedent, start=0),
        _block(16, echo, start=2),
    ]

    assert len(detect_possessive_echo_links(blocks)) == 1


@pytest.mark.parametrize(
    "blocks",
    [
        [
            _block(10, "You brought your badge.", start=0),
            _block(11, "First bridge.", start=1),
            _block(12, "Second bridge.", start=2),
            _block(13, "Third bridge.", start=3),
            _block(14, "My badge?", start=4),
        ],
        [
            _block(20, "You brought your badge.", start=0, duration=1),
            _block(21, "Bridge.", start=4),
            _block(22, "My badge?", start=9.01),
        ],
    ],
)
def test_rejects_links_outside_cue_or_time_bounds(blocks):
    from app.engines.discourse_links import detect_possessive_echo_links

    assert detect_possessive_echo_links(blocks) == []


def test_rejects_bridge_that_reintroduces_the_noun():
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(30, "You brought your badge.", start=0),
        _block(31, "That badge is fake.", start=2),
        _block(32, "My badge?", start=4),
    ]

    assert detect_possessive_echo_links(blocks) == []


@pytest.mark.parametrize(
    ("antecedent", "echo"),
    [
        ("What about your way?", "My way?"),
        ("I saw his boy.", "Your boy?"),
        ("I saw her boy.", "Your boy?"),
        ("I saw their boy.", "Your boy?"),
        ("I saw your boy.", "His boy?"),
        ("I saw your boy.", "Her boy?"),
        ("I saw your boy.", "Their boy?"),
        ("I saw your son.", "My boy?"),
        ("I saw your boy.", "Is that my boy?"),
        ("I saw your boy.", "My little boy?"),
    ],
)
def test_rejects_ambiguous_nouns_and_disallowed_possessives(antecedent, echo):
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(40, antecedent, start=0),
        _block(41, echo, start=2),
    ]

    assert detect_possessive_echo_links(blocks) == []


def test_later_unrelated_noun_does_not_create_or_extend_a_link():
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(84, "With your boy here as leverage?", start=0),
        _block(85, "The plan is easier.", start=2),
        _block(86, "My boy?", start=4),
        _block(87, "That boy ran toward the station.", start=6),
    ]

    links = detect_possessive_echo_links(blocks)

    assert [(link.antecedent_id, link.echo_id) for link in links] == [(84, 86)]


@pytest.mark.parametrize("filtered_position", [0, 1])
def test_rejects_filtered_endpoints(filtered_position):
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(84, "With your boy here as leverage?", start=0),
        _block(86, "My boy?", start=2),
    ]
    blocks[filtered_position].filtered = True

    assert detect_possessive_echo_links(blocks) == []


@pytest.mark.parametrize(
    ("antecedent", "echo"),
    [
        ("[MUSIC]\nWith your boy here as leverage?", "My boy?"),
        ("With your boy here as leverage?", "[MUSIC]\nMy boy?"),
        ("♪ With your boy here as leverage? ♪", "My boy?"),
        ("With your boy here as leverage?", "♪ My boy? ♪"),
    ],
)
def test_rejects_endpoints_with_explicit_non_dialogue_or_music_markers(
    antecedent,
    echo,
):
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(84, antecedent, start=0),
        _block(86, echo, start=2),
    ]

    assert detect_possessive_echo_links(blocks) == []


def test_fails_closed_when_both_endpoints_name_the_same_speaker():
    from app.engines.discourse_links import detect_possessive_echo_links

    same_speaker = [
        _block(
            84,
            "[Luis]\nWith your boy here as leverage?",
            start=0,
        ),
        _block(86, "Luis: My boy?", start=2),
    ]
    different_speakers = [
        _block(
            84,
            "[Luis]\nWith your boy here as leverage?",
            start=0,
        ),
        _block(86, "Mara: My boy?", start=2),
    ]

    assert detect_possessive_echo_links(same_speaker) == []
    assert len(detect_possessive_echo_links(different_speakers)) == 1


@pytest.mark.parametrize(
    ("timestamp_field", "value"),
    [
        (("antecedent", "end"), float("nan")),
        (("antecedent", "end"), float("inf")),
        (("echo", "start"), float("nan")),
        (("echo", "start"), float("-inf")),
    ],
)
def test_rejects_non_finite_endpoint_timestamps(timestamp_field, value):
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(84, "With your boy here as leverage?", start=0),
        _block(86, "My boy?", start=2),
    ]
    endpoint, field = timestamp_field
    target = blocks[0] if endpoint == "antecedent" else blocks[1]
    setattr(target, field, value)

    assert detect_possessive_echo_links(blocks) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_lookback_cues": 0},
        {"max_lookback_cues": float("inf")},
        {"max_gap_seconds": float("nan")},
        {"max_gap_seconds": float("inf")},
        {"max_gap_seconds": -1},
    ],
)
def test_rejects_non_finite_or_non_positive_detector_limits(kwargs):
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(84, "With your boy here as leverage?", start=0),
        _block(86, "My boy?", start=2),
    ]

    assert detect_possessive_echo_links(blocks, **kwargs) == []


@pytest.mark.parametrize(
    "ids",
    [
        (0, 85, 86),
        (84, -1, 86),
        (84, 85, 0),
        (84, 84, 86),
        (84, 86, 86),
        (True, 85, 86),
    ],
)
def test_rejects_invalid_or_duplicate_ids_across_the_link_span(ids):
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(ids[0], "With your boy here as leverage?", start=0),
        _block(ids[1], "The plan is easier.", start=1),
        _block(ids[2], "My boy?", start=2),
    ]

    assert detect_possessive_echo_links(blocks) == []


def test_link_hash_binds_read_only_ids_before_hashing():
    from app.engines.discourse_links import build_discourse_link_contexts

    blocks = [
        _block(84, "With your boy here as leverage?", start=0),
        _block(85, "The plan is easier.", start=1),
        _block(86, "My boy?", start=2),
    ]

    echo_only = build_discourse_link_contexts(
        blocks,
        focus_ids={86},
        mutable_ids={86},
    )[0]
    both_ends = build_discourse_link_contexts(
        blocks,
        focus_ids={84, 86},
        mutable_ids={84, 86},
    )[0]

    assert echo_only["read_only_ids"] == [84, 85]
    assert both_ends["read_only_ids"] == [85]
    assert echo_only["link_hash"] != both_ends["link_hash"]


def test_discourse_context_caps_omit_whole_links_without_truncating_hashes():
    from app.engines.discourse_links import build_discourse_link_contexts

    blocks = [
        _block(1, "That is your badge.", start=0),
        _block(2, "My badge?", start=1),
        _block(3, "That is your jacket.", start=2),
        _block(4, "My jacket?", start=3),
    ]

    one_context = build_discourse_link_contexts(
        blocks,
        focus_ids={1, 2, 3, 4},
        mutable_ids={1, 2, 3, 4},
        max_contexts=1,
    )
    assert len(one_context) == 1
    assert one_context[0]["link_hash"].startswith("sha256:")
    serialized_chars = len(json.dumps(
        one_context[0],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ))
    assert build_discourse_link_contexts(
        blocks[:2],
        focus_ids={1, 2},
        mutable_ids={1, 2},
        max_serialized_chars=serialized_chars - 1,
    ) == []
    exact_fit = build_discourse_link_contexts(
        blocks[:2],
        focus_ids={1, 2},
        mutable_ids={1, 2},
        max_serialized_chars=serialized_chars,
    )
    assert len(exact_fit) == 1
    assert exact_fit[0]["link_hash"] == one_context[0]["link_hash"]


def test_endpoint_index_attaches_links_without_indexing_read_only_bridge():
    from app.engines.discourse_links import (
        build_discourse_link_contexts,
        index_discourse_link_contexts,
    )

    blocks = [
        _block(84, "With your boy here as leverage?", start=0),
        _block(85, "The plan is easier.", start=1),
        _block(86, "My boy?", start=2),
    ]
    contexts = build_discourse_link_contexts(
        blocks,
        focus_ids={84, 86},
        mutable_ids={84, 86},
    )

    by_endpoint = index_discourse_link_contexts(contexts)

    assert by_endpoint[84] == contexts
    assert by_endpoint[86] == contexts
    assert 85 not in by_endpoint


@pytest.mark.parametrize(
    "antecedent",
    [
        "[MUSIC] With your boy here as leverage?",
        "[DOOR SLAMS] With your boy here as leverage?",
        "MUSIC: With your boy here as leverage?",
    ],
)
def test_rejects_inline_sdh_music_or_action_labels_as_endpoints(antecedent):
    from app.engines.discourse_links import detect_possessive_echo_links

    blocks = [
        _block(84, antecedent, start=0),
        _block(86, "My boy?", start=2),
    ]

    assert detect_possessive_echo_links(blocks) == []


def test_inline_bracketed_speaker_participates_in_same_speaker_veto():
    from app.engines.discourse_links import detect_possessive_echo_links

    same_speaker = [
        _block(
            84,
            "[Luis] With your boy here as leverage?",
            start=0,
        ),
        _block(86, "Luis: My boy?", start=2),
    ]
    different_speakers = [
        _block(
            84,
            "[Luis] With your boy here as leverage?",
            start=0,
        ),
        _block(86, "[Mara] My boy?", start=2),
    ]

    assert detect_possessive_echo_links(same_speaker) == []
    assert len(detect_possessive_echo_links(different_speakers)) == 1


@pytest.mark.parametrize("duplicated_id", [84, 85])
def test_context_build_fails_closed_on_positive_id_duplicate_outside_span(
    duplicated_id,
):
    from app.engines.discourse_links import build_discourse_link_contexts

    blocks = [
        _block(84, "With your boy here as leverage?", start=0),
        _block(85, "The plan is easier.", start=1),
        _block(86, "My boy?", start=2),
        _block(duplicated_id, "Later unrelated cue.", start=3),
    ]

    assert build_discourse_link_contexts(
        blocks,
        focus_ids={86},
        mutable_ids={86},
    ) == []
