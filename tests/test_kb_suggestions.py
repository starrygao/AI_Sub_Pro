def test_suggest_kb_entries_from_tmdb_and_subtitles():
    from app.engines.kb_suggestions import suggest_kb_entries
    from app.engines.kb_models import ProjectKb, TermEntry

    project = {
        "name": "Moonlit Case",
        "tmdb_id": 101,
        "title": "Moonlit Case",
        "original_title": "Moonlit Case",
        "cast": ["Elsbeth Tascioni", {"name": "Maya Chen", "character": "Detective Chen"}],
        "overview": "Elsbeth follows a case at the Moonlit Club.",
    }
    subtitles = [
        {"index": 1, "text": "Elsbeth meets Maya Chen at the Moonlit Club."},
        {"index": 2, "text": "Detective Chen waits."},
    ]
    existing = ProjectKb(characters=[TermEntry(source="Elsbeth Tascioni", target="艾尔斯贝丝")])

    suggestions = suggest_kb_entries(project, subtitles, existing)

    by_source = {item.source: item for item in suggestions}
    assert by_source["Maya Chen"].category == "characters"
    assert by_source["Moonlit Club"].category in {"places", "brands", "slang"}
    assert by_source["Elsbeth Tascioni"].collision == "existing"
    assert by_source["Maya Chen"].evidence


def test_suggest_kb_entries_ignores_short_noise():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"name": "A", "cast": ["A"]},
        [{"index": 1, "text": "OK. TV. A."}],
        None,
    )

    assert suggestions == []


def test_suggest_kb_entries_dedupes_and_collides_case_insensitively():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {
            "title": "Moonlit Case",
            "cast": [{"name": "Maya Chen", "character": "Detective Chen"}],
            "overview": "Maya Chen returns to the Moonlit Case.",
        },
        [{"index": 3, "text": "maya chen saw Detective Chen."}],
        ProjectKb(characters=[TermEntry(source="detective chen", target="陈警探")]),
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source).count("Maya Chen") == 1
    assert by_source["Detective Chen"].collision == "existing"
