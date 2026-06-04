import json
import subprocess
import sys


def test_eval_cli_outputs_json():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.evaluation.cli",
            "--corpus",
            "tests/fixtures/golden_corpus/translation_quality_loop.json",
            "--format",
            "json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert payload["case_count"] == 4
    assert "terminology_hit_rate" in payload["metrics"]


def test_eval_cli_outputs_markdown():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.evaluation.cli",
            "--corpus",
            "tests/fixtures/golden_corpus/translation_quality_loop.json",
            "--format",
            "markdown",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "# Translation Evaluation Report" in result.stdout
    assert "terminology_hit_rate" in result.stdout
