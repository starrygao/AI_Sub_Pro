import json
from pathlib import Path

import pytest


def test_load_corpus_validates_required_fields(tmp_path):
    from app.evaluation.corpus import CorpusValidationError, load_corpus_file

    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"cases": [{"id": "bad"}]}), encoding="utf-8")

    with pytest.raises(CorpusValidationError, match="source_blocks"):
        load_corpus_file(path)


def test_load_corpus_normalizes_fixture():
    from app.evaluation.corpus import load_corpus_file

    corpus = load_corpus_file(Path("tests/fixtures/golden_corpus/translation_quality_loop.json"))

    assert corpus.version == 1
    assert len(corpus.cases) >= 4
    assert {"proper_noun", "colloquial", "english_residue", "long_sentence"} <= {
        tag for case in corpus.cases for tag in case.tags
    }
    assert corpus.cases[0].source_blocks[0]["id"] == "1"
