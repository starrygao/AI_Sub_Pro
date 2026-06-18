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
    assert report.summary["far"]["functional"] >= 2
    assert report.summary["far"]["acceptability"] >= 1
    assert report.summary["far"]["readability"] >= 1


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


def test_repair_prompt_gives_reading_speed_compression_guidance():
    from app.engines.translation_qa import QualityIssue, build_repair_prompt

    items = [
        {
            "id": 7,
            "original": "-Bracken Mountain, North Carolina? -Yes, sir.",
            "draft": "-北卡州布拉肯山？ -是，长官。",
        }
    ]
    issues = [
        QualityIssue(
            type="reading_speed_too_fast",
            severity="warning",
            block_id=7,
            message="reading speed 11.2 chars/sec exceeds 9.0",
            source_text="-Bracken Mountain, North Carolina? -Yes, sir.",
            translation="-北卡州布拉肯山？ -是，长官。",
            expected="9.0",
        )
    ]

    prompt = build_repair_prompt("简体中文", items, issues)

    assert "读速超标时必须压缩译文" in prompt
    assert "删除可省略称呼" in prompt
    assert "双人对话" in prompt


def test_quality_checks_flag_inferred_proper_name_inconsistency():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "哈德逊奥克斯今晚很安静。"),
        _block(2, "I came from Hudson Oaks.", "我从哈德逊橡树来。"),
        _block(3, "Hudson Oaks is closed now.", "哈德逊橡树现在关门了。", filtered=True),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert report.summary["by_type"]["proper_name_inconsistent"] == 2
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
    assert {issue.block_id for issue in flagged} == {1, 2}
    assert report.unresolved_blocks == [1, 2]
    assert all(issue.severity == "warning" for issue in flagged)
    assert all(issue.source_text == "Hudson Oaks" for issue in flagged)


def test_quality_checks_flag_divergent_long_names_without_shared_anchor():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "哈德逊奥克斯"),
        _block(2, "I came from Hudson Oaks.", "赫德森橡树"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert report.summary["by_type"]["proper_name_inconsistent"] == 2
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
    assert {issue.block_id for issue in flagged} == {1, 2}


def test_quality_checks_run_proper_name_metric_for_traditional_chinese_targets():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "哈德遜奧克斯"),
        _block(2, "I came from Hudson Oaks.", "赫德森橡樹"),
    ]

    report = run_quality_checks(blocks, target_language="繁體中文", max_chars=18)

    assert report.summary["by_type"]["proper_name_inconsistent"] == 2
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
    assert {issue.block_id for issue in flagged} == {1, 2}


def test_quality_checks_run_proper_name_metric_for_common_chinese_aliases():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "哈德逊奥克斯"),
        _block(2, "I came from Hudson Oaks.", "赫德森橡树"),
    ]

    for target_language in ("Simplified Chinese", "zh-Hant-TW"):
        report = run_quality_checks(blocks, target_language=target_language, max_chars=18)

        assert report.summary["by_type"]["proper_name_inconsistent"] == 2
        flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
        assert {issue.block_id for issue in flagged} == {1, 2}


def test_quality_checks_do_not_flag_same_long_cjk_name_in_different_contexts():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "I am going to Hudson Oaks.", "我去哈德逊奥克斯。"),
        _block(2, "She is going to Hudson Oaks.", "她去哈德逊奥克斯。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert "proper_name_inconsistent" not in report.summary["by_type"]


def test_quality_checks_do_not_flag_short_consistent_cjk_names():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Li Na arrived.", "李娜到了。"),
        _block(2, "I saw Li Na run.", "我看见李娜跑了。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert "proper_name_inconsistent" not in report.summary["by_type"]


def test_quality_checks_flag_inconsistent_short_cjk_names_with_shared_context():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Li Na arrived.", "李娜到了。"),
        _block(2, "Li Na arrived too.", "丽娜到了。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=18)

    assert report.summary["by_type"]["proper_name_inconsistent"] == 2
    flagged = [issue for issue in report.issues if issue.type == "proper_name_inconsistent"]
    assert {issue.block_id for issue in flagged} == {1, 2}


def test_quality_checks_skip_proper_name_metric_for_non_chinese_targets():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Hudson Oaks is quiet tonight.", "Hudson Oaks is quiet tonight."),
        _block(2, "I came from Hudson Oaks.", "I came from Hudson Oaks yesterday."),
    ]

    report = run_quality_checks(blocks, target_language="English", max_chars=40)

    assert "proper_name_inconsistent" not in report.summary["by_type"]


def test_quality_checks_flag_curated_science_term_misses_without_project_kb():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "These little climbers are Suminia.", "这些小小攀爬者是苏米尼亚兽。"),
        _block(2, "A female Dongusuchus.", "一只雌性东乌鳄。"),
        _block(3, "called proto-Pterosaurs, head for the sand.", "新型滑翔爬行动物，正飞向沙滩。"),
    ]

    report = run_quality_checks(blocks, target_language="简体中文", max_chars=40)

    assert report.summary["by_type"]["canonical_term_missing"] == 3
    flagged = [issue for issue in report.issues if issue.type == "canonical_term_missing"]
    assert {issue.block_id for issue in flagged} == {1, 2, 3}
    assert {issue.expected for issue in flagged} == {"苏美尼兽", "顿古兹鳄", "原翼龙类"}
    assert all(issue.severity == "warning" for issue in flagged)


def test_quality_checks_project_kb_overrides_curated_science_terms():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "These little climbers are Suminia.", "这些小小攀爬者是苏米尼亚兽。"),
    ]
    kb = ProjectKb(slang=[TermEntry(source="Suminia", target="苏米尼亚兽")])

    report = run_quality_checks(blocks, project_kb=kb, target_language="简体中文", max_chars=40)

    assert "canonical_term_missing" not in report.summary["by_type"]
    assert "kb_term_missing" not in report.summary["by_type"]


def test_quality_checks_apply_subtitle_style_profile_rules():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Fast line", "这是一条非常非常非常非常非常长的字幕"),
        _block(2, "Too many lines", "第一行\n第二行\n第三行"),
        _block(3, "Bad semantic break", "我\n知道你来了"),
        _block(4, "No, no, no!", "不，不，不！"),
        _block(5, "Are you okay?", "你好吗?"),
    ]

    report = run_quality_checks(
        blocks,
        target_language="简体中文",
        max_chars=32,
        meta_info={"genres": ["Drama"]},
    )
    by_type = report.summary["by_type"]

    assert by_type["line_too_long"] == 1
    assert by_type["reading_speed_too_fast"] >= 1
    assert by_type["too_many_lines"] == 1
    assert by_type["weak_semantic_line_break"] == 1
    assert by_type["repetition_not_compressed"] == 1
    assert by_type["punctuation_style"] == 1
    assert report.summary["far"]["readability"] >= 5
    assert report.summary["far"]["acceptability"] >= 1
    assert report.summary["style_profile"]["id"] == "zh_cn_general"


def test_quality_checks_allow_technical_identifiers_for_tutorials():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "The API returns a JSON object.", "API 会返回 JSON 对象。"),
    ]

    report = run_quality_checks(
        blocks,
        target_language="简体中文",
        max_chars=40,
        meta_info={"tags": ["tutorial", "programming"]},
    )

    assert "english_residue" not in report.summary["by_type"]


def test_quality_checks_apply_manual_metadata_terms():
    from app.engines.translation_qa import run_quality_checks

    blocks = [
        _block(1, "Gradient descent converges here.", "梯度递减在这里收敛。"),
    ]

    report = run_quality_checks(
        blocks,
        target_language="简体中文",
        max_chars=40,
        meta_info={
            "content_type": "academic_lecture",
            "manual_terms": "Gradient descent=梯度下降",
        },
    )

    manual = [issue for issue in report.issues if issue.type == "manual_term_missing"]
    assert manual
    assert manual[0].expected == "梯度下降"
