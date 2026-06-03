import json

import pytest


def _valid_case(**overrides):
    case = {
        "id": "valid-case",
        "tags": ["film"],
        "source_language": "en",
        "target_language": "zh-CN",
        "project": {"name": "Valid Case"},
        "source_blocks": [{"id": "1", "text": "Hello."}],
        "candidate_blocks": [{"id": "1", "translation": "你好。"}],
        "expected_terms": [],
    }
    case.update(overrides)
    return case


def test_load_golden_corpus_validates_required_fields(tmp_path):
    from app.evaluation.corpus import CorpusValidationError, load_corpus_file

    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps({"version": 1, "cases": [{"id": "missing-blocks"}]}),
        encoding="utf-8",
    )

    with pytest.raises(CorpusValidationError, match="source_blocks"):
        load_corpus_file(path)


def test_load_golden_corpus_rejects_missing_source_block_text(tmp_path):
    from app.evaluation.corpus import CorpusValidationError, load_corpus_file

    path = tmp_path / "missing-source-text.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [_valid_case(source_blocks=[{"id": "1"}])],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CorpusValidationError, match="source_blocks|text"):
        load_corpus_file(path)


def test_load_golden_corpus_rejects_missing_candidate_block_translation(tmp_path):
    from app.evaluation.corpus import CorpusValidationError, load_corpus_file

    path = tmp_path / "missing-candidate-translation.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [_valid_case(candidate_blocks=[{"id": "1"}])],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CorpusValidationError, match="candidate_blocks|translation"):
        load_corpus_file(path)


@pytest.mark.parametrize("reference_blocks", ["", 0, False])
def test_load_golden_corpus_rejects_supplied_invalid_reference_blocks(tmp_path, reference_blocks):
    from app.evaluation.corpus import CorpusValidationError, load_corpus_file

    path = tmp_path / "bad-reference-blocks.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    _valid_case(
                        id="invalid-reference-blocks",
                        reference_blocks=reference_blocks,
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CorpusValidationError, match="reference_blocks"):
        load_corpus_file(path)


def test_load_golden_corpus_accepts_explicit_empty_reference_blocks(tmp_path):
    from app.evaluation.corpus import load_corpus_file

    path = tmp_path / "empty-reference-blocks.json"
    path.write_text(
        json.dumps({"version": 1, "cases": [_valid_case(reference_blocks=[])]}),
        encoding="utf-8",
    )

    corpus = load_corpus_file(path)

    assert corpus.cases[0].reference_blocks == []


@pytest.mark.parametrize("version", [0, False, "1"])
def test_load_golden_corpus_rejects_invalid_version(tmp_path, version):
    from app.evaluation.corpus import CorpusValidationError, load_corpus_file

    path = tmp_path / "bad-version.json"
    path.write_text(
        json.dumps(
            {
                "version": version,
                "cases": [{"id": "case-validation-should-not-run"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CorpusValidationError, match="version"):
        load_corpus_file(path)


def test_load_golden_corpus_normalizes_cases():
    from pathlib import Path

    from app.evaluation.corpus import load_corpus_file

    corpus = load_corpus_file(Path("tests/fixtures/golden_corpus/milestone1.json"))

    assert len(corpus.cases) >= 7
    assert all(isinstance(case.id, str) and case.id for case in corpus.cases)
    assert {"film", "series", "trailer", "pun", "proper_noun", "long_sentence", "colloquial"} <= {
        tag for case in corpus.cases for tag in case.tags
    }
    first = corpus.cases[0]
    assert first.source_blocks[0]["id"] == "1"
    assert first.source_blocks[0]["text"]
    assert first.expected_terms
