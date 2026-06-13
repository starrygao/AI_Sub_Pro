def test_simplified_chinese_style_profile_defaults_to_industry_limits():
    from app.engines.subtitle_style_profiles import (
        build_subtitle_style_prompt_snippet,
        infer_subtitle_style_profile,
    )

    profile = infer_subtitle_style_profile("简体中文", {"genres": ["Drama"]})
    snippet, hits = build_subtitle_style_prompt_snippet("简体中文", {"genres": ["Drama"]})

    assert profile.id == "zh_cn_general"
    assert profile.max_line_chars == 16
    assert profile.max_lines == 2
    assert profile.max_chars_per_second == 9.0
    assert "16 Chinese characters per line" in snippet
    assert hits == [{
        "id": "zh_cn_general",
        "scope": "subtitle_style",
        "max_line_chars": 16,
        "max_lines": 2,
        "max_chars_per_second": 9.0,
    }]


def test_simplified_chinese_children_profile_uses_stricter_reading_speed():
    from app.engines.subtitle_style_profiles import infer_subtitle_style_profile

    profile = infer_subtitle_style_profile(
        "Simplified Chinese",
        {"genres": ["Kids", "Family"], "tags": ["children"]},
    )

    assert profile.id == "zh_cn_children"
    assert profile.max_chars_per_second == 7.0
