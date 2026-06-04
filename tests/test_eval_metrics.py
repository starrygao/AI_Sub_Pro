from pathlib import Path


def test_evaluation_metrics_report_quality_counts():
    from app.evaluation.corpus import load_corpus_file
    from app.evaluation.metrics import evaluate_corpus

    corpus = load_corpus_file(Path("tests/fixtures/golden_corpus/translation_quality_loop.json"))
    report = evaluate_corpus(corpus, max_chars=18)

    assert report["case_count"] == 4
    assert report["metrics"]["terminology_hit_rate"] < 1
    assert report["metrics"]["missing_translation_count"] == 1
    assert report["metrics"]["english_residue_count"] == 1
    assert report["metrics"]["length_violation_count"] >= 1
    assert report["cases"][0]["id"] == "proper-place"
