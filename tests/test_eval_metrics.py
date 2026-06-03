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
