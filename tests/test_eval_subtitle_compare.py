import json


def _srt(*rows):
    parts = []
    for index, text in rows:
        start = f"00:00:{index:02d},000"
        end = f"00:00:{index + 1:02d},000"
        parts.append(f"{index}\n{start} --> {end}\n{text}\n")
    return "\n".join(parts) + "\n"


def test_compare_subtitle_files_reports_core_metrics(tmp_path):
    from app.evaluation.subtitle_compare import compare_subtitle_files

    source = tmp_path / "source.srt"
    old = tmp_path / "old.srt"
    new = tmp_path / "new.srt"
    reference = tmp_path / "reference.srt"
    source.write_text(
        _srt(
            (1, "Hudson Oaks is quiet."),
            (2, "Are you okay?"),
            (3, "Please wait outside."),
        ),
        encoding="utf-8",
    )
    old.write_text(
        _srt(
            (1, "哈德森橡树很安静。"),
            (2, "Are you okay? Please answer now."),
        ),
        encoding="utf-8",
    )
    new.write_text(
        _srt(
            (1, "哈德逊奥克斯很安静。"),
            (2, "你还好吗？"),
            (3, "请在外面等。"),
        ),
        encoding="utf-8",
    )
    reference.write_text(
        _srt(
            (1, "哈德逊奥克斯很安静。"),
            (2, "你还好吗？"),
            (3, "请在外面等。"),
        ),
        encoding="utf-8",
    )

    report = compare_subtitle_files(
        source_path=source,
        old_path=old,
        new_path=new,
        reference_path=reference,
        target_language="简体中文",
        expected_terms=[{"source": "Hudson Oaks", "target": "哈德逊奥克斯"}],
        max_chars=18,
    )

    assert report["summary"]["source_count"] == 3
    assert report["old"]["missing_translation"]["missing_count"] == 1
    assert report["old"]["missing_translation"]["source_missing_ids"] == ["3"]
    assert report["new"]["missing_translation"]["missing_count"] == 0
    assert report["old"]["english_residue"]["count"] == 1
    assert report["new"]["english_residue"]["count"] == 0
    assert report["old"]["length"]["count"] == 1
    assert report["old"]["length"]["ids"] == ["2"]
    assert report["new"]["length"]["count"] == 0
    assert report["old"]["terminology"]["hit_rate"] == 0.0
    assert report["new"]["terminology"]["hit_rate"] == 1.0
    assert report["new"]["reference_similarity"]["exact_match_rate"] == 1.0
    assert report["delta"]["missing_translation_count"] == -1
    assert report["delta"]["english_residue_count"] == -1
    assert report["delta"]["length_violation_count"] == -1
    json.dumps(report, ensure_ascii=False)


def test_compare_subtitle_files_rejects_missing_paths(tmp_path):
    from app.evaluation.subtitle_compare import SubtitleCompareError, compare_subtitle_files

    source = tmp_path / "source.srt"
    source.write_text(_srt((1, "Hello.")), encoding="utf-8")

    try:
        compare_subtitle_files(
            source_path=source,
            old_path=tmp_path / "missing-old.srt",
            new_path=tmp_path / "missing-new.srt",
        )
    except SubtitleCompareError as exc:
        assert "missing-old.srt" in str(exc)
    else:
        raise AssertionError("expected missing path error")


def test_compare_subtitle_files_accepts_ass_reference(tmp_path):
    from app.evaluation.subtitle_compare import compare_subtitle_files

    source = tmp_path / "source.srt"
    old = tmp_path / "old.srt"
    new = tmp_path / "new.srt"
    reference = tmp_path / "reference.ass"
    source.write_text(_srt((1, "Are you okay?")), encoding="utf-8")
    old.write_text(_srt((1, "Are you okay?")), encoding="utf-8")
    new.write_text(_srt((1, "你还好吗？")), encoding="utf-8")
    reference.write_text(
        "\n".join([
            "[Script Info]",
            "Title: unit",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,你还好吗？",
        ]) + "\n",
        encoding="utf-8",
    )

    report = compare_subtitle_files(
        source_path=source,
        old_path=old,
        new_path=new,
        reference_path=reference,
    )

    assert report["new"]["reference_similarity"]["exact_match_rate"] == 1.0
