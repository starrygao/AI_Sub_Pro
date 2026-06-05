import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.engines.corpus_import import CorpusImportError, import_corpus
from app.engines.phrase_library import PhraseLibrary

ROOT = Path(__file__).resolve().parents[1]


def test_import_jsonl_corpus_validates_metadata_and_limits_rows(tmp_path):
    corpus = tmp_path / "phrases.jsonl"
    corpus.write_text(
        "\n".join([
            json.dumps({"source": " Hello there ", "target": " 你好啊 "}, ensure_ascii=False),
            json.dumps({"source": "Nice to meet you", "target": "很高兴见到你"}, ensure_ascii=False),
            json.dumps({"source": "See you soon", "target": "回头见"}, ensure_ascii=False),
        ]),
        encoding="utf-8",
    )
    library = PhraseLibrary(tmp_path / "phrases.sqlite3")

    with pytest.raises(CorpusImportError, match="source_name is required"):
        import_corpus(
            corpus,
            input_format="jsonl",
            source_name=" ",
            license_name="CC-BY",
            source_language="en",
            target_language="zh-CN",
            library=library,
        )

    report = import_corpus(
        corpus,
        input_format="JSONL",
        source_name="unit-jsonl",
        license_name="CC-BY",
        source_language="en",
        target_language="zh-CN",
        max_rows=2,
        tags=["subtitle", "dialogue"],
        library=library,
    )

    assert report.accepted == 2
    assert report.rejected == 0
    assert report.duplicates == 0
    assert report.limited is True
    assert report.sampled_rows[0]["source_text"] == "Hello there"

    results = library.retrieve(
        "Hello there",
        source_language="en",
        target_language="zh-CN",
        limit=5,
    )
    assert len(results) == 1
    assert results[0].target_text == "你好啊"
    assert results[0].source_name == "unit-jsonl"
    assert results[0].license == "CC-BY"
    assert results[0].tags == "subtitle,dialogue"


def test_import_jsonl_corpus_rejects_empty_and_malformed_rows(tmp_path):
    corpus = tmp_path / "phrases.jsonl"
    too_long = "x" * 241
    corpus.write_text(
        "\n".join([
            json.dumps({"source": "   ", "target": "空"}, ensure_ascii=False),
            json.dumps({"source": "Valid line", "target": "有效台词"}, ensure_ascii=False),
            "{bad json",
            json.dumps({"source": "Long target", "target": too_long}, ensure_ascii=False),
            json.dumps({"source": "No target", "target": "   "}, ensure_ascii=False),
        ]),
        encoding="utf-8",
    )
    library = PhraseLibrary(tmp_path / "phrases.sqlite3")

    report = import_corpus(
        corpus,
        input_format="jsonl",
        source_name="unit-errors",
        license_name="local-test",
        source_language="en",
        target_language="zh-CN",
        library=library,
    )

    assert report.accepted == 1
    assert report.rejected == 4
    assert report.duplicates == 0
    assert report.limited is False
    assert [error["error"] for error in report.errors] == [
        "source text is empty",
        "invalid JSON: Expecting property name enclosed in double quotes",
        "target text exceeds 240 characters",
        "target text is empty",
    ]

    results = library.retrieve(
        "Valid line",
        source_language="en",
        target_language="zh-CN",
        limit=5,
    )
    assert len(results) == 1
    assert results[0].source_name == "unit-errors"
    assert results[0].license == "local-test"


def test_import_tsv_corpus_drops_duplicates(tmp_path):
    corpus = tmp_path / "phrases.tsv"
    corpus.write_text(
        "\n".join([
            "source\ttarget",
            "Same line\t同一句",
            "Same line\t同一句",
            "Another line\t另一句",
        ]),
        encoding="utf-8",
    )
    library = PhraseLibrary(tmp_path / "phrases.sqlite3")

    first_report = import_corpus(
        corpus,
        input_format="tsv",
        source_name="unit-tsv",
        license_name="internal",
        source_language="en",
        target_language="zh-CN",
        library=library,
    )
    second_report = import_corpus(
        corpus,
        input_format="tsv",
        source_name="unit-tsv",
        license_name="internal",
        source_language="en",
        target_language="zh-CN",
        library=library,
    )

    assert first_report.accepted == 2
    assert first_report.duplicates == 1
    assert first_report.rejected == 0
    assert second_report.accepted == 0
    assert second_report.duplicates == 3

    results = library.retrieve(
        "Same line",
        source_language="en",
        target_language="zh-CN",
        limit=5,
    )
    exact_matches = [row for row in results if row.source_text == "Same line"]
    assert len(exact_matches) == 1
    assert exact_matches[0].source_name == "unit-tsv"


@pytest.mark.parametrize(
    ("filename", "input_format", "body"),
    [
        ("phrases.csv", "csv", "source,target\nHello,world,你好\n"),
        ("phrases.tsv", "tsv", "source\ttarget\nHello\tworld\t你好\n"),
    ],
)
def test_import_delimited_corpus_rejects_rows_with_extra_fields(
    tmp_path,
    filename,
    input_format,
    body,
):
    corpus = tmp_path / filename
    corpus.write_text(body, encoding="utf-8")
    library = PhraseLibrary(tmp_path / "phrases.sqlite3")

    report = import_corpus(
        corpus,
        input_format=input_format,
        source_name="unit-delimited",
        license_name="local-test",
        source_language="en",
        target_language="zh-CN",
        library=library,
    )

    assert report.accepted == 0
    assert report.rejected == 1
    assert report.duplicates == 0
    assert report.errors == [{"row_number": 2, "error": "line 2: row has extra fields"}]
    assert library.retrieve(
        "Hello",
        source_language="en",
        target_language="zh-CN",
        limit=5,
    ) == []


def test_import_delimited_corpus_rejects_missing_custom_columns(tmp_path):
    corpus = tmp_path / "phrases.csv"
    corpus.write_text(
        "\n".join([
            "source,target",
            "Hello,你好",
        ]),
        encoding="utf-8",
    )

    with pytest.raises(CorpusImportError, match="missing required column\\(s\\): english, chinese"):
        import_corpus(
            corpus,
            input_format="csv",
            source_name="unit-columns",
            license_name="local-test",
            source_language="en",
            target_language="zh-CN",
            source_column="english",
            target_column="chinese",
        )


@pytest.mark.parametrize(
    ("filename", "input_format", "body", "message"),
    [
        (
            "phrases.csv",
            "csv",
            "source,source,target\noriginal,shifted,译文\n",
            "duplicate header name\\(s\\): source",
        ),
        (
            "phrases.tsv",
            "tsv",
            "source\tsource\ttarget\noriginal\tshifted\t译文\n",
            "duplicate header name\\(s\\): source",
        ),
        (
            "phrases.csv",
            "csv",
            "source,target,note,note\nhello,你好,a,b\n",
            "duplicate header name\\(s\\): note",
        ),
    ],
)
def test_import_delimited_corpus_rejects_duplicate_headers(
    tmp_path,
    filename,
    input_format,
    body,
    message,
):
    corpus = tmp_path / filename
    corpus.write_text(body, encoding="utf-8")

    with pytest.raises(CorpusImportError, match=message):
        import_corpus(
            corpus,
            input_format=input_format,
            source_name="unit-headers",
            license_name="local-test",
            source_language="en",
            target_language="zh-CN",
        )


def test_import_corpus_cli_dry_run_supports_quoted_csv_fields(tmp_path):
    corpus = tmp_path / "phrases.csv"
    corpus.write_text(
        '\n'.join([
            "source,target",
            '"Hello, world","你好，世界"',
        ]),
        encoding="utf-8",
    )
    data_dir = tmp_path / "quoted-csv-data"
    env = os.environ.copy()
    env["AI_SUB_PRO_DATA_DIR"] = str(data_dir)

    result = subprocess.run(
        [
            sys.executable,
            "tools/phrase_packs/import_corpus.py",
            str(corpus),
            "--format",
            "csv",
            "--source-name",
            "unit-quoted",
            "--license",
            "CC0",
            "--source-language",
            "en",
            "--target-language",
            "zh-CN",
            "--dry-run",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["accepted"] == 1
    assert report["rejected"] == 0
    assert report["sampled_rows"] == [{
        "row_number": 2,
        "source_text": "Hello, world",
        "target_text": "你好，世界",
    }]
    assert not (data_dir / "phrase_library.sqlite3").exists()


def test_import_corpus_cli_dry_run(tmp_path):
    corpus = tmp_path / "phrases.csv"
    corpus.write_text(
        "\n".join([
            "source,target",
            "First line,第一句",
            "Second line,第二句",
            "Second line,第二句",
        ]),
        encoding="utf-8",
    )
    data_dir = tmp_path / "dry-run-data"
    env = os.environ.copy()
    env["AI_SUB_PRO_DATA_DIR"] = str(data_dir)

    result = subprocess.run(
        [
            sys.executable,
            "tools/phrase_packs/import_corpus.py",
            str(corpus),
            "--format",
            "csv",
            "--source-name",
            "unit-csv",
            "--license",
            "CC0",
            "--source-language",
            "en",
            "--target-language",
            "zh-CN",
            "--dry-run",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["accepted"] == 2
    assert report["duplicates"] == 1
    assert report["rejected"] == 0
    assert report["limited"] is False
    assert not (data_dir / "phrase_library.sqlite3").exists()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "path": "missing.jsonl",
                "input_format": "jsonl",
                "source_name": "unit",
                "license_name": "local",
                "source_language": "en",
                "target_language": "zh-CN",
            },
            "corpus file does not exist",
        ),
        (
            {
                "path": __file__,
                "input_format": "yaml",
                "source_name": "unit",
                "license_name": "local",
                "source_language": "en",
                "target_language": "zh-CN",
            },
            "unsupported input_format",
        ),
        (
            {
                "path": __file__,
                "input_format": "jsonl",
                "source_name": "unit",
                "license_name": "local",
                "source_language": "en",
                "target_language": "zh-CN",
                "max_rows": True,
            },
            "max_rows must be a positive integer",
        ),
    ],
)
def test_import_corpus_rejects_invalid_inputs(kwargs, message):
    with pytest.raises(CorpusImportError, match=message):
        import_corpus(**kwargs)
