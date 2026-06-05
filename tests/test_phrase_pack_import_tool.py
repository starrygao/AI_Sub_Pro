import json
import subprocess
import sys


def test_phrase_pack_import_tool_requires_license_metadata(tmp_path):
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({
        "source": "unit",
        "source_language": "en",
        "target_language": "zh-CN",
        "phrases": [{"source_text": "Hello", "target_text": "你好"}],
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "tools/phrase_packs/import_phrase_pack.py", str(pack), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "license is required" in result.stderr


def test_phrase_pack_import_tool_imports_valid_pack(tmp_path):
    pack = tmp_path / "pack.json"
    db = tmp_path / "phrases.sqlite3"
    pack.write_text(json.dumps({
        "id": "unit.tool-pack",
        "version": 1,
        "source": "unit",
        "license": "local-test",
        "source_language": "en",
        "target_language": "zh-CN",
        "phrases": [{"source_text": "Hello", "target_text": "你好"}],
    }), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/phrase_packs/import_phrase_pack.py",
            str(pack),
            "--database",
            str(db),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Imported 1 phrase example" in result.stdout

    from app.engines.phrase_library import PhraseLibrary

    library = PhraseLibrary(db)
    results = library.retrieve("Hello", source_language="en", target_language="zh-CN")
    assert len(results) == 1
    assert results[0].license == "local-test"
