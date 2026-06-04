from datetime import timedelta

from app.utils.srt import SubtitleBlock


def _block(index, text, translation="", filtered=False):
    return SubtitleBlock(
        index=index,
        start=timedelta(seconds=index),
        end=timedelta(seconds=index + 1),
        text=text,
        translation=translation,
        filtered=filtered,
    )


def test_quality_checks_detect_common_deterministic_issues():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet.", "哈德森橡树很安静。"),
        _block(1, "Hello there.", ""),
        _block(3, "Are you okay?", "Are you okay?"),
        _block(4, "[ Dramatic music plays ]", "戏剧性音乐响起"),
        _block(5, "Long line", "这是一条非常非常非常非常非常非常非常非常非常非常长的字幕"),
    ]
    kb = ProjectKb(places=[TermEntry(source="Hudson Oaks", target="哈德逊奥克斯")])

    report = run_quality_checks(blocks, project_kb=kb, target_language="简体中文", max_chars=18)
    issue_types = {issue.type for issue in report.issues}

    assert "kb_term_missing" in issue_types
    assert "missing_translation" in issue_types
    assert "english_residue" in issue_types
    assert "duplicate_id" in issue_types
    assert "sound_description_translated" in issue_types
    assert "line_too_long" in issue_types
    assert report.summary["issue_count"] == len(report.issues)


def test_quality_report_serializes_json_and_markdown(tmp_path):
    from app.engines.translation_qa import QualityIssue, TranslationQaReport, save_quality_report

    report = TranslationQaReport(
        status="needs_review",
        issues=[
            QualityIssue(
                type="missing_translation",
                severity="error",
                block_id=2,
                message="missing",
                source_text="Hello",
                translation="",
            )
        ],
        summary={"issue_count": 1},
    )

    json_path = tmp_path / "translation_qa_report.json"
    md_path = tmp_path / "translation_qa_report.md"
    save_quality_report(report, json_path=json_path, markdown_path=md_path)

    assert '"missing_translation"' in json_path.read_text(encoding="utf-8")
    markdown = md_path.read_text(encoding="utf-8")
    assert "# Translation QA Report" in markdown
    assert "missing_translation" in markdown


def test_repair_prompt_contains_only_failing_blocks():
    from app.engines.translation_qa import QualityIssue, build_repair_items, build_repair_prompt

    blocks = [
        _block(1, "Good", "好"),
        _block(2, "Hudson Oaks", "哈德森橡树"),
    ]
    issues = [
        QualityIssue(
            type="kb_term_missing",
            severity="error",
            block_id=2,
            message="Use 哈德逊奥克斯",
            source_text="Hudson Oaks",
            translation="哈德森橡树",
        )
    ]

    items = build_repair_items(blocks, issues)
    prompt = build_repair_prompt("简体中文", items, issues, kb_terms={"Hudson Oaks": "哈德逊奥克斯"})

    assert items == [{"id": 2, "original": "Hudson Oaks", "draft": "哈德森橡树"}]
    assert "Good" not in prompt
    assert "Hudson Oaks" in prompt
    assert "哈德逊奥克斯" in prompt
