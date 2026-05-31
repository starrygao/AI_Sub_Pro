def test_build_prompt_snippet_empty_kb_returns_empty_string():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb
    assert build_prompt_snippet(None) == ""
    assert build_prompt_snippet(ProjectKb(show_title="Foo")) == ""


def test_build_prompt_snippet_includes_characters_as_strict_terms():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, TermEntry
    kb = ProjectKb(
        show_title="Elsbeth",
        characters=[
            TermEntry(source="Elsbeth Tascioni", target="艾尔斯贝丝·塔西奥尼"),
            TermEntry(source="Matlock", target="马特洛克"),
        ],
    )
    out = build_prompt_snippet(kb)
    assert ("EXACTLY" in out) or ("必须" in out) or ("strictly" in out.lower())
    assert "Elsbeth Tascioni" in out and "艾尔斯贝丝·塔西奥尼" in out
    assert "Matlock" in out and "马特洛克" in out


def test_build_prompt_snippet_groups_by_category():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, TermEntry
    kb = ProjectKb(
        show_title="Test",
        characters=[TermEntry(source="Name", target="名字")],
        places=[TermEntry(source="Place", target="地点")],
        brands=[TermEntry(source="Brand", target="品牌")],
        slang=[TermEntry(source="Slang", target="俚语")],
    )
    out = build_prompt_snippet(kb)
    for label in ("CHARACTERS", "PLACES", "BRANDS", "SLANG"):
        assert label in out.upper()


def test_build_prompt_snippet_includes_style_notes():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, StyleNotes
    kb = ProjectKb(
        show_title="Test",
        style_notes=StyleNotes(
            tone="conversational, sharp",
            perspective="first-person feel",
            rules=["preserve wit", "use modern idioms"],
        ),
    )
    out = build_prompt_snippet(kb)
    assert "conversational" in out
    assert "preserve wit" in out


def test_build_prompt_snippet_includes_notes_as_context():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, TermEntry
    kb = ProjectKb(
        show_title="Test",
        slang=[TermEntry(source="Glamazons", target="魅力女战士", notes="pop culture")],
    )
    out = build_prompt_snippet(kb)
    assert "Glamazons" in out
    assert "魅力女战士" in out
    assert "pop culture" in out


def test_build_prompt_snippet_only_style_notes_no_terms():
    """Style-only KB (no term lists) should still produce output."""
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, StyleNotes
    kb = ProjectKb(
        show_title="StyleOnly",
        style_notes=StyleNotes(tone="melancholy", rules=["poetic"]),
    )
    out = build_prompt_snippet(kb)
    # Style-only: should not include "EXACTLY" strict-terms header
    assert "melancholy" in out
    assert "poetic" in out


def test_build_prompt_snippet_preserves_rules_without_tone():
    from app.engines.knowledge import build_prompt_snippet
    from app.engines.kb_models import ProjectKb, StyleNotes

    kb = ProjectKb(
        show_title="RulesOnly",
        style_notes=StyleNotes(rules=["preserve honorifics"]),
    )

    out = build_prompt_snippet(kb)

    assert "preserve honorifics" in out
