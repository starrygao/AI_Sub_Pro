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
