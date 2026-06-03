import json

import pytest


def test_load_golden_corpus_validates_required_fields(tmp_path):
    from app.evaluation.corpus import CorpusValidationError, load_corpus_file

    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"cases": [{"id": "missing-blocks"}]}), encoding="utf-8")

    with pytest.raises(CorpusValidationError, match="source_blocks"):
        load_corpus_file(path)


def test_load_golden_corpus_normalizes_cases():
    from pathlib import Path

    from app.evaluation.corpus import load_corpus_file

    corpus = load_corpus_file(Path("tests/fixtures/golden_corpus/milestone1.json"))

    assert len(corpus.cases) >= 7
    assert {case.id for case in corpus.cases}
    assert {"film", "series", "trailer", "pun", "proper_noun", "long_sentence", "colloquial"} <= {
        tag for case in corpus.cases for tag in case.tags
    }
    first = corpus.cases[0]
    assert first.source_blocks[0]["id"] == "1"
    assert first.source_blocks[0]["text"]
    assert first.expected_terms
