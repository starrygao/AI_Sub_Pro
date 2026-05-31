def test_term_entry_defaults():
    from app.engines.kb_models import TermEntry
    t = TermEntry(source="Elsbeth", target="艾尔斯贝丝")
    assert t.source == "Elsbeth"
    assert t.target == "艾尔斯贝丝"
    assert t.notes == ""


def test_term_entry_with_notes():
    from app.engines.kb_models import TermEntry
    t = TermEntry(source="Glamazons", target="魅力女战士", notes="pop culture reference")
    assert t.notes == "pop culture reference"


def test_style_notes_defaults():
    from app.engines.kb_models import StyleNotes
    s = StyleNotes()
    assert s.tone == ""
    assert s.perspective == ""
    assert s.rules == []


def test_style_notes_with_values():
    from app.engines.kb_models import StyleNotes
    s = StyleNotes(tone="conversational", perspective="first person feel", rules=["preserve wit", "use modern idioms"])
    assert s.tone == "conversational"
    assert len(s.rules) == 2


def test_project_kb_defaults():
    from app.engines.kb_models import ProjectKb, StyleNotes
    kb = ProjectKb(show_title="Elsbeth")
    assert kb.show_title == "Elsbeth"
    assert kb.tmdb_id is None
    assert kb.characters == []
    assert kb.places == []
    assert kb.brands == []
    assert kb.slang == []
    assert isinstance(kb.style_notes, StyleNotes)


def test_project_kb_serialize_roundtrip():
    from app.engines.kb_models import ProjectKb, TermEntry, StyleNotes
    kb = ProjectKb(
        show_title="Elsbeth",
        tmdb_id=123,
        characters=[TermEntry(source="Elsbeth", target="艾尔斯贝丝")],
        places=[TermEntry(source="NJ", target="新泽西")],
        style_notes=StyleNotes(tone="sharp legal humor"),
    )
    data = kb.to_dict()
    restored = ProjectKb.from_dict(data)
    assert restored.show_title == "Elsbeth"
    assert restored.tmdb_id == 123
    assert len(restored.characters) == 1
    assert restored.characters[0].target == "艾尔斯贝丝"
    assert restored.style_notes.tone == "sharp legal humor"


def test_project_kb_from_dict_handles_missing_fields():
    from app.engines.kb_models import ProjectKb
    kb = ProjectKb.from_dict({"show_title": "Foo"})
    assert kb.characters == []
    assert kb.style_notes.tone == ""


def test_project_kb_is_empty():
    from app.engines.kb_models import ProjectKb, TermEntry
    assert ProjectKb(show_title="Foo").is_empty() is True
    assert ProjectKb(show_title="Foo", characters=[TermEntry("a", "b")]).is_empty() is False


def test_project_kb_from_dict_sanitizes_malformed_legacy_values():
    from app.engines.kb_models import ProjectKb

    kb = ProjectKb.from_dict({
        "show_title": " Show ",
        "tmdb_id": 123,
        "characters": [
            "bad-entry",
            {"source": " Name ", "target": " 名字 ", "notes": 42},
            {"source": "NoTarget", "target": ""},
        ],
        "style_notes": {
            "tone": 99,
            "perspective": " first person ",
            "rules": " keep jokes ",
        },
    })

    assert kb.show_title == "Show"
    assert len(kb.characters) == 1
    assert kb.characters[0].source == "Name"
    assert kb.characters[0].target == "名字"
    assert kb.characters[0].notes == ""
    assert kb.style_notes.tone == ""
    assert kb.style_notes.perspective == "first person"
    assert kb.style_notes.rules == ["keep jokes"]


def test_project_kb_from_dict_rejects_non_positive_tmdb_id():
    from app.engines.kb_models import ProjectKb

    assert ProjectKb.from_dict({"tmdb_id": 0}).tmdb_id is None
    assert ProjectKb.from_dict({"tmdb_id": -7}).tmdb_id is None
