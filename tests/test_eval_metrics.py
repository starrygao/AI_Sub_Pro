from app.evaluation.corpus import CorpusCase


def make_case(candidate_blocks):
    return CorpusCase(
        id="metric-case",
        tags=["film"],
        source_language="en",
        target_language="zh-CN",
        project={"name": "Metric Case"},
        source_blocks=[
            {"id": "1", "text": "<i>Elsbeth enters.</i>"},
            {"id": "2", "text": "Moonlit Club waits."},
        ],
        candidate_blocks=candidate_blocks,
        expected_terms=[
            {"source": "Elsbeth", "target": "艾尔斯贝丝"},
            {"source": "Moonlit Club", "target": "月光俱乐部"},
        ],
        reference_blocks=[],
    )


def test_evaluate_case_scores_perfect_output():
    from app.evaluation.metrics import evaluate_case

    result = evaluate_case(
        make_case(
            [
                {"id": "1", "translation": "<i>艾尔斯贝丝进来了。</i>"},
                {"id": "2", "translation": "月光俱乐部在等。"},
            ]
        )
    )

    assert result["terminology"]["hit_rate"] == 1.0
    assert result["missing_translation"]["rate"] == 0.0
    assert result["row_alignment"]["rate"] == 1.0
    assert result["format"]["breakage_rate"] == 0.0


def test_evaluate_case_catches_bad_output():
    from app.evaluation.metrics import evaluate_case

    result = evaluate_case(
        make_case(
            [
                {"id": "1", "translation": "Elsbeth enters."},
                {"id": "3", "translation": ""},
            ]
        )
    )

    assert result["terminology"]["hit_rate"] == 0.0
    assert result["missing_translation"]["missing_ids"] == ["3"]
    assert result["row_alignment"]["missing_ids"] == ["2"]
    assert result["row_alignment"]["extra_ids"] == ["3"]
    assert result["format"]["broken_ids"] == ["1"]


def test_missing_translation_accounts_for_absent_source_rows():
    from app.evaluation.metrics import evaluate_case

    result = evaluate_case(
        make_case(
            [
                {"id": "1", "translation": "<i>艾尔斯贝丝进来了。</i>"},
            ]
        )
    )

    assert result["missing_translation"]["missing_ids"] == []
    assert result["missing_translation"]["source_missing_ids"] == ["2"]
    assert result["missing_translation"]["missing_count"] == 1
    assert result["missing_translation"]["total"] == 2
    assert result["missing_translation"]["rate"] == 0.5


def test_row_alignment_rate_penalizes_extra_candidate_rows():
    from app.evaluation.metrics import evaluate_case

    result = evaluate_case(
        make_case(
            [
                {"id": "1", "translation": "<i>艾尔斯贝丝进来了。</i>"},
                {"id": "2", "translation": "月光俱乐部在等。"},
                {"id": "999", "translation": "额外的一行。"},
            ]
        )
    )

    assert result["row_alignment"]["missing_ids"] == []
    assert result["row_alignment"]["extra_ids"] == ["999"]
    assert result["row_alignment"]["rate"] == 0.6667


def test_format_score_counts_added_tags_on_untagged_source_rows():
    from app.evaluation.metrics import evaluate_case

    result = evaluate_case(
        make_case(
            [
                {"id": "1", "translation": "<i>艾尔斯贝丝进来了。</i>"},
                {"id": "2", "translation": "<b>月光俱乐部在等。</b>"},
            ]
        )
    )

    assert result["format"]["broken_ids"] == ["2"]
    assert result["format"]["tagged_count"] == 2
    assert result["format"]["breakage_rate"] == 0.5


def test_proper_name_consistency_score_detects_inconsistent_target_forms():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet tonight.",
            "2": "I still remember Hudson Oaks.",
            "3": "This subtitle does not matter.",
        },
        {
            "1": "哈德逊奥克斯今晚很安静。",
            "2": "我还记得哈德森橡树。",
            "3": "这条字幕不重要。",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"
    assert [item["block_id"] for item in result["issues"][0]["observations"]] == ["1", "2"]


def test_proper_name_consistency_score_detects_partial_different_cjk_target_forms():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet tonight.",
            "2": "I came from Hudson Oaks.",
        },
        {
            "1": "哈德逊奥克斯很安静。",
            "2": "我从哈德逊橡树来。",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"


def test_proper_name_consistency_score_flags_shared_prefix_long_transliteration():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Alexander Hamilton arrived.",
            "2": "Alexander Hamilton spoke.",
        },
        {
            "1": "亚历山大汉密尔顿",
            "2": "亚历山大哈密顿",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Alexander Hamilton"


def test_proper_name_consistency_score_flags_competing_prefix_transliteration():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet.",
            "2": "Hudson Oaks is closed.",
        },
        {
            "1": "哈德森奥克斯",
            "2": "赫德森奥克斯",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"


def test_proper_name_consistency_score_flags_competing_prefix_after_sentence_context():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet.",
            "2": "Hudson Oaks is closed.",
        },
        {
            "1": "我去哈德森奥克斯",
            "2": "我去赫德森奥克斯",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"


def test_proper_name_consistency_score_flags_divergent_long_names_without_shared_anchor():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet tonight.",
            "2": "I came from Hudson Oaks.",
        },
        {
            "1": "哈德逊奥克斯",
            "2": "赫德森橡树",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"


def test_proper_name_consistency_score_rejects_shared_context_as_long_name_anchor():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is okay.",
            "2": "Hudson Oaks is okay too.",
        },
        {
            "1": "哈德逊奥克斯一切正常",
            "2": "赫德森橡树一切正常",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"


def test_proper_name_consistency_score_rejects_unlisted_shared_context_anchor():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is bright tonight.",
            "2": "Hudson Oaks is bright again.",
        },
        {
            "1": "哈德逊奥克斯灯火辉煌",
            "2": "赫德森橡树灯火辉煌",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"


def test_proper_name_consistency_score_allows_same_long_cjk_name_in_different_contexts():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "I am going to Hudson Oaks.",
            "2": "She is going to Hudson Oaks.",
        },
        {
            "1": "我去哈德逊奥克斯。",
            "2": "她去哈德逊奥克斯。",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_allows_same_long_name_in_natural_contexts():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "I like Hudson Oaks.",
            "2": "She hates Hudson Oaks.",
        },
        {
            "1": "我喜欢哈德逊奥克斯。",
            "2": "她讨厌哈德逊奥克斯。",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_allows_temporal_prefix_context():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet.",
            "2": "Hudson Oaks is closed.",
        },
        {
            "1": "昨天哈德逊奥克斯",
            "2": "今天哈德逊奥克斯",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_allows_adverbial_prefix_context():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks lost power.",
            "2": "Hudson Oaks reopened.",
        },
        {
            "1": "突然哈德逊奥克斯停电了",
            "2": "随后哈德逊奥克斯重新开放",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_allows_normal_long_name_suffix_context():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "I live near Hudson Oaks.",
            "2": "I arrived at Hudson Oaks.",
        },
        {
            "1": "我住在哈德逊奥克斯附近",
            "2": "我到了哈德逊奥克斯",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_allows_ordinary_adjacent_suffix_context():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "I am beside Hudson Oaks.",
            "2": "I arrived at Hudson Oaks.",
        },
        {
            "1": "我在哈德逊奥克斯旁边",
            "2": "我到了哈德逊奥克斯",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_allows_ordinary_predicate_suffix_context():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is beautiful.",
            "2": "Hudson Oaks is quiet.",
        },
        {
            "1": "哈德逊奥克斯美极了",
            "2": "哈德逊奥克斯很安静",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_allows_descriptive_suffix_context():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is bright tonight.",
            "2": "Hudson Oaks is quiet.",
        },
        {
            "1": "哈德逊奥克斯灯火通明",
            "2": "哈德逊奥克斯很安静",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_flags_longer_shared_prefix_extension():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet tonight.",
            "2": "I came from Hudson Oaks.",
        },
        {
            "1": "哈德逊奥克斯",
            "2": "哈德逊奥克斯镇",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"


def test_proper_name_consistency_score_flags_long_name_prefix_variant():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet tonight.",
            "2": "I came from Hudson Oaks.",
        },
        {
            "1": "老哈德逊奥克斯很安静",
            "2": "哈德逊奥克斯很安静",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"


def test_proper_name_consistency_score_flags_source_initial_long_name_extensions():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet.",
            "2": "Hudson Oaks looks empty.",
        },
        {
            "1": "哈德逊奥克斯镇很安静",
            "2": "哈德逊奥克斯市看起来空荡",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"


def test_proper_name_consistency_score_skips_blank_observations_but_keeps_nonblank_mismatch():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet tonight.",
            "2": "I came from Hudson Oaks.",
            "3": "Hudson Oaks is closed now.",
        },
        {
            "1": "哈德逊奥克斯很安静。",
            "2": " ",
            "3": "哈德逊橡树现在关门了。",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Hudson Oaks"
    assert [item["block_id"] for item in result["issues"][0]["observations"]] == ["1", "3"]


def test_proper_name_consistency_score_skips_blank_translations():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet tonight.",
            "2": "I still remember Hudson Oaks.",
        },
        {
            "1": "哈德逊奥克斯今晚很安静。",
            "2": " ",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_does_not_flag_name_seen_once():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet tonight.",
            "2": "Nothing relevant happens here.",
        },
        {
            "1": "哈德逊奥克斯今晚很安静。",
            "2": "这里没什么相关内容。",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_does_not_flag_whitespace_compacted_identical_forms():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Hudson Oaks is quiet tonight.",
            "2": "I came from Hudson Oaks.",
        },
        {
            "1": "哈德逊 奥克斯",
            "2": "哈德逊奥克斯",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_allows_short_shared_cjk_names_in_different_sentences():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Li Na arrived.",
            "2": "I saw Li Na run.",
        },
        {
            "1": "李娜到了。",
            "2": "我看见李娜跑了。",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_flags_inconsistent_short_name_with_shared_context():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Li Na arrived.",
            "2": "Li Na arrived too.",
        },
        {
            "1": "李娜到了。",
            "2": "丽娜到了。",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Li Na"


def test_proper_name_consistency_score_flags_inconsistent_short_name_with_shared_predicate_anchor():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Li Na smiled.",
            "2": "Li Na smiled again.",
        },
        {
            "1": "李娜微笑。",
            "2": "丽娜微笑。",
        },
    )

    assert result["issue_count"] == 1
    assert result["issues"][0]["source"] == "Li Na"


def test_proper_name_consistency_score_ignores_common_sentence_initial_phrases():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "Good Morning, everyone.",
            "2": "Good Morning, officer.",
        },
        {
            "1": "早上好，各位。",
            "2": "早安，警官。",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_proper_name_consistency_score_ignores_common_title_question_phrases():
    from app.evaluation.metrics import proper_name_consistency_score

    result = proper_name_consistency_score(
        {
            "1": "How Are You, John?",
            "2": "How Are You, officer?",
        },
        {
            "1": "约翰，你好吗？",
            "2": "长官，近来可好？",
        },
    )

    assert result["issue_count"] == 0
    assert result["issues"] == []
