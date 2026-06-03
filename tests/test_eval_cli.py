import json
import subprocess
from pathlib import Path


def test_eval_cli_writes_json_and_markdown(tmp_path):
    json_out = tmp_path / "report.json"
    md_out = tmp_path / "report.md"

    result = subprocess.run(
        [
            "python3",
            "-m",
            "app.evaluation.cli",
            "--corpus",
            "tests/fixtures/golden_corpus/milestone1.json",
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(md_out),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["summary"]["case_count"] >= 7
    assert "terminology_hit_rate" in data["summary"]
    assert "manual_scores" in data
    markdown = md_out.read_text(encoding="utf-8")
    assert "# Translation Quality Evaluation" in markdown
    assert "Manual scoring" in markdown


def test_eval_cli_markdown_includes_source_missing_translation_ids(tmp_path):
    json_out = tmp_path / "report.json"
    md_out = tmp_path / "report.md"

    result = subprocess.run(
        [
            "python3",
            "-m",
            "app.evaluation.cli",
            "--corpus",
            "tests/fixtures/golden_corpus/milestone1.json",
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(md_out),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    markdown = md_out.read_text(encoding="utf-8")
    assert "missing-translation-fixture" in markdown
    assert "Source missing translation IDs: 2" in markdown
