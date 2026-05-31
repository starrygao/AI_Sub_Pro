def test_migrate_v1_flat_to_v2_structured():
    from app.engines.kb_migration import migrate_v1_to_v2

    v1 = {
        "Elsbeth": {
            "keywords": ["Elsbeth", "Matlock", "legal"],
            "style": "conversational, sharp legal humor",
            "terms": {"Elsbeth Tascioni": "艾尔斯贝丝·塔西奥尼", "Matlock": "马特洛克"},
        },
        "通用": {"keywords": [], "style": "", "terms": {}},
    }

    v2 = migrate_v1_to_v2(v1)
    assert "Elsbeth" in v2
    proj = v2["Elsbeth"]
    assert proj["show_title"] == "Elsbeth"
    sources = {t["source"] for t in proj["characters"]}
    assert "Elsbeth Tascioni" in sources
    assert "Matlock" in sources
    tone = proj["style_notes"]["tone"]
    rules_joined = " ".join(proj["style_notes"].get("rules", []))
    assert ("legal humor" in tone.lower()) or ("legal humor" in rules_joined.lower()) or (tone == "conversational, sharp legal humor")


def test_migrate_v2_data_passes_through_unchanged():
    from app.engines.kb_migration import migrate_v1_to_v2, is_v2_shape

    v2_input = {
        "Elsbeth": {
            "show_title": "Elsbeth",
            "characters": [{"source": "Elsbeth", "target": "艾尔斯贝丝", "notes": ""}],
            "places": [], "brands": [], "slang": [],
            "style_notes": {"tone": "", "perspective": "", "rules": []},
        },
    }
    assert is_v2_shape(v2_input) is True
    assert migrate_v1_to_v2(v2_input) == v2_input


def test_migrate_handles_swapped_src_dst_entries():
    from app.engines.kb_migration import migrate_v1_to_v2
    v1 = {"Test": {"keywords": [], "style": "", "terms": {"不": "No.", "Hello": "你好"}}}
    v2 = migrate_v1_to_v2(v1)
    sources = {t["source"] for t in v2["Test"]["characters"]}
    assert "不" in sources
    assert "Hello" in sources


def test_is_v2_shape_detects_both():
    from app.engines.kb_migration import is_v2_shape
    assert is_v2_shape({"X": {"show_title": "X", "characters": []}}) is True
    assert is_v2_shape({"X": {"keywords": [], "terms": {}}}) is False
    assert is_v2_shape({}) is True


def test_migrate_v1_skips_malformed_terms():
    from app.engines.kb_migration import migrate_v1_to_v2

    v1 = {"Broken": {"keywords": ["x"], "style": "tone", "terms": ["not", "a", "dict"]}}

    v2 = migrate_v1_to_v2(v1)

    assert v2["Broken"]["characters"] == []
    assert v2["Broken"]["style_notes"]["tone"] == "tone"


def test_migrate_v1_keeps_string_keyword_as_one_keyword():
    from app.engines.kb_migration import migrate_v1_to_v2

    v1 = {"Show": {"keywords": "Elsbeth", "style": "", "terms": {}}}

    v2 = migrate_v1_to_v2(v1)

    assert v2["Show"]["_legacy_keywords"] == ["Elsbeth"]


def test_migrate_v1_skips_non_string_terms():
    from app.engines.kb_migration import migrate_v1_to_v2

    v1 = {"Show": {"keywords": [], "style": "", "terms": {"Good": "好", "Bad": None, 7: "七"}}}

    v2 = migrate_v1_to_v2(v1)

    assert v2["Show"]["characters"] == [{"source": "Good", "target": "好", "notes": ""}]
