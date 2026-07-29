from datetime import timedelta
from types import SimpleNamespace

from app.utils.srt import SubtitleBlock


def _blocks():
    return [
        SubtitleBlock(
            index=84,
            start=timedelta(seconds=0),
            end=timedelta(seconds=1),
            text="With your boy here as leverage?",
            translation="拿你儿子做人质？",
        ),
        SubtitleBlock(
            index=85,
            start=timedelta(seconds=2),
            end=timedelta(seconds=3),
            text="The plan is easier.",
            translation="计划更容易了。",
        ),
        SubtitleBlock(
            index=86,
            start=timedelta(seconds=4),
            end=timedelta(seconds=5),
            text="My boy?",
            translation="我儿子？",
        ),
    ]


def test_targeted_singleton_binds_read_only_discourse_link_hash():
    from app.api.translate import (
        _targeted_semantic_items,
        _targeted_semantic_result_stage,
    )

    items = _targeted_semantic_items(
        _blocks(),
        {86},
        SimpleNamespace(issues=[]),
        [],
    )

    assert [item["id"] for item in items] == [86]
    link = items[0]["discourse_links"][0]
    assert link["read_only_ids"] == [84, 85]
    assert link["antecedent"]["draft"] == "拿你儿子做人质？"
    result = {
        "id": 86,
        "translation": "OK",
        "verdict": "OK",
        "taxonomy": "none",
        "source_evidence": "My boy?",
        "target_evidence": "我儿子？",
    }
    assert (
        _targeted_semantic_result_stage(result, items[0])
        == "link_binding_mismatch"
    )
    result["discourse_link_hashes"] = [link["link_hash"]]
    assert _targeted_semantic_result_stage(result, items[0]) == "explicit_ok"


def test_targeted_groups_linked_ends_only_when_both_are_candidates():
    from app.api.translate import (
        _targeted_semantic_items,
        _targeted_semantic_verification_units,
    )

    singleton_member_items = _targeted_semantic_items(
        _blocks(),
        {86},
        SimpleNamespace(issues=[]),
        [],
    )
    singleton_items, group_items = _targeted_semantic_verification_units(
        singleton_member_items,
        {86},
        [],
    )
    assert [item["id"] for item in singleton_items] == [86]
    assert group_items == []

    linked_member_items = _targeted_semantic_items(
        _blocks(),
        {84, 86},
        SimpleNamespace(issues=[]),
        [],
    )
    singleton_items, group_items = _targeted_semantic_verification_units(
        linked_member_items,
        {84, 86},
        [],
    )
    assert singleton_items == []
    assert len(group_items) == 1
    assert group_items[0]["group_ids"] == [84, 86]
    assert group_items[0]["discourse_link_hashes"] == [
        linked_member_items[0]["discourse_links"][0]["link_hash"]
    ]
    assert group_items[0]["discourse_links"][0]["possessive_pair"] == "your->my"
    assert group_items[0]["discourse_links"][0]["read_only_ids"] == [85]
    assert [item["id"] for item in group_items[0]["group_context"]] == [85]


def test_non_contiguous_semantic_group_is_one_repair_batch_unit():
    from app.api.translate import _repair_batch_positions

    items = [
        {"id": 84, "semantic_group_ids": [84, 86]},
        {"id": 85},
        {"id": 86, "semantic_group_ids": [84, 86]},
    ]

    positions = _repair_batch_positions(items, max_blocks=2)

    assert [[items[position]["id"] for position in batch] for batch in positions] == [
        [84, 86],
        [85],
    ]


def test_non_contiguous_group_endpoints_apply_atomically():
    from app.api.translate import _apply_nonempty_repair_results

    blocks = _blocks()
    original_by_id = {block.index: block.translation for block in blocks}

    rejected = _apply_nonempty_repair_results(
        blocks,
        [{"id": 84, "translation": "新译84"}],
        target_language="简体中文",
        semantic_groups=[[84, 86]],
    )
    assert rejected == []
    assert {
        block.index: block.translation for block in blocks
    } == original_by_id

    applied = _apply_nonempty_repair_results(
        blocks,
        [
            {"id": 84, "translation": "新译84"},
            {"id": 86, "translation": "新译86"},
        ],
        target_language="简体中文",
        semantic_groups=[[84, 86]],
    )
    assert [item["id"] for item in applied] == [84, 86]
    assert blocks[0].translation == "新译84"
    assert blocks[2].translation == "新译86"


def test_targeted_detection_keeps_filtered_bridge_in_read_only_timeline():
    from app.api.translate import _targeted_semantic_items

    blocks = _blocks()
    blocks[1].filtered = True

    items = _targeted_semantic_items(
        blocks,
        {86},
        SimpleNamespace(issues=[]),
        [],
    )

    assert [item["id"] for item in items] == [86]
    link = items[0]["discourse_links"][0]
    assert [item["id"] for item in link["bridge_context"]] == [85]
    assert link["distance_cues"] == 2
    assert link["read_only_ids"] == [84, 85]


def test_targeted_filtered_bridge_can_block_link_by_reintroducing_noun():
    from app.api.translate import _targeted_semantic_items

    blocks = _blocks()
    blocks[1].filtered = True
    blocks[1].text = "That boy is waiting."

    items = _targeted_semantic_items(
        blocks,
        {86},
        SimpleNamespace(issues=[]),
        [],
    )

    assert "discourse_links" not in items[0]


def test_targeted_filtered_bridge_still_counts_toward_cue_distance():
    from app.api.translate import _targeted_semantic_items

    blocks = [
        SubtitleBlock(
            index=84,
            start=timedelta(seconds=0),
            end=timedelta(seconds=1),
            text="With your boy here as leverage?",
            translation="拿你儿子做人质？",
        ),
        SubtitleBlock(
            index=85,
            start=timedelta(seconds=1),
            end=timedelta(seconds=2),
            text="First bridge.",
            filtered=True,
        ),
        SubtitleBlock(
            index=86,
            start=timedelta(seconds=2),
            end=timedelta(seconds=3),
            text="Second bridge.",
        ),
        SubtitleBlock(
            index=87,
            start=timedelta(seconds=3),
            end=timedelta(seconds=4),
            text="Third bridge.",
        ),
        SubtitleBlock(
            index=88,
            start=timedelta(seconds=4),
            end=timedelta(seconds=5),
            text="My boy?",
            translation="我儿子？",
        ),
    ]

    items = _targeted_semantic_items(
        blocks,
        {88},
        SimpleNamespace(issues=[]),
        [],
    )

    assert "discourse_links" not in items[0]
