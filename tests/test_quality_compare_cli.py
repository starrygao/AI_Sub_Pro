import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "quality" / "compare_translation_outputs.py"


def _srt(text):
    return f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n"


def test_quality_compare_cli_writes_json_and_markdown(tmp_path):
    source = tmp_path / "source.srt"
    old = tmp_path / "old.srt"
    new = tmp_path / "new.srt"
    reference = tmp_path / "reference.srt"
    out = tmp_path / "report"
    source.write_text(_srt("Hudson Oaks is quiet."), encoding="utf-8")
    old.write_text(_srt("哈德森橡树很安静。"), encoding="utf-8")
    new.write_text(_srt("哈德逊奥克斯很安静。"), encoding="utf-8")
    reference.write_text(_srt("哈德逊奥克斯很安静。"), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source", str(source),
            "--old", str(old),
            "--new", str(new),
            "--reference", str(reference),
            "--term", "Hudson Oaks=哈德逊奥克斯",
            "--out-dir", str(out),
        ],
        cwd=str(tmp_path),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads((out / "translation_accuracy_report.json").read_text(encoding="utf-8"))
    assert data["new"]["terminology"]["hit_rate"] == 1.0
    assert "# Translation Accuracy Report" in (out / "translation_accuracy_report.md").read_text(encoding="utf-8")


def test_quality_compare_cli_rejects_bad_term(tmp_path):
    source = tmp_path / "source.srt"
    old = tmp_path / "old.srt"
    new = tmp_path / "new.srt"
    source.write_text(_srt("Hello."), encoding="utf-8")
    old.write_text(_srt("你好。"), encoding="utf-8")
    new.write_text(_srt("你好。"), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source", str(source),
            "--old", str(old),
            "--new", str(new),
            "--term", "missing-separator",
            "--out-dir", str(tmp_path / "out"),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--term must use SOURCE=TARGET" in result.stderr


def test_quality_compare_cli_rejects_missing_input_path(tmp_path):
    source = tmp_path / "source.srt"
    old = tmp_path / "missing-old.srt"
    new = tmp_path / "new.srt"
    source.write_text(_srt("Hello."), encoding="utf-8")
    new.write_text(_srt("你好。"), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source", str(source),
            "--old", str(old),
            "--new", str(new),
            "--out-dir", str(tmp_path / "out"),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "missing-old.srt" in result.stderr


def test_quality_compare_cli_reports_output_write_failure_without_traceback(tmp_path):
    source = tmp_path / "source.srt"
    old = tmp_path / "old.srt"
    new = tmp_path / "new.srt"
    out = tmp_path / "report"
    source.write_text(_srt("Hello."), encoding="utf-8")
    old.write_text(_srt("你好。"), encoding="utf-8")
    new.write_text(_srt("你好。"), encoding="utf-8")
    out.write_text("not a directory", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source", str(source),
            "--old", str(old),
            "--new", str(new),
            "--out-dir", str(out),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "report" in result.stderr
    assert "Traceback" not in result.stderr
