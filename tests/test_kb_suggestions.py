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


def test_suggest_kb_entries_preserves_full_metadata_titles():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {
            "title": "The Last of Us",
            "name": "Lord of the Rings",
            "original_title": "The Last of Us",
        },
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert "The Last of Us" in by_source
    assert "Lord of the Rings" in by_source
    assert "Last" not in by_source
    assert "Lord" not in by_source
    assert by_source["The Last of Us"].evidence == ["title"]


def test_suggest_kb_entries_uses_show_title_as_metadata_title():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"show_title": "The Matrix"},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["The Matrix"]
    assert by_source["The Matrix"].evidence == ["title"]


def test_suggest_kb_entries_keeps_short_high_confidence_terms():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {
            "title": "Up",
            "name": "It",
            "show_title": "HP",
            "cast": ["Li"],
        },
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Li", "Up", "It", "HP"]
    assert by_source["Li"].category == "characters"
    assert by_source["Up"].evidence == ["title"]
    assert by_source["It"].evidence == ["title"]
    assert by_source["HP"].evidence == ["title"]


def test_suggest_kb_entries_preserves_connected_overview_phrase():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "we watched The Last of Us tonight."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["The Last of Us"]
    assert "The Last of Us" in by_source
    assert "The Last" not in by_source
    assert by_source["The Last of Us"].evidence == ["overview"]


def test_suggest_kb_entries_preserves_connected_subtitle_phrase():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {},
        [{"index": 4, "text": "He quotes Lord of the Rings."}],
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Lord of the Rings"]
    assert "Lord of the Rings" in by_source
    assert "Lord" not in by_source
    assert "Rings" not in by_source
    assert by_source["Lord of the Rings"].evidence == ["subtitle:4"]


def test_suggest_kb_entries_keeps_apostrophe_names_from_prose():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "O'Neill visits the Moonlit Club."},
        None,
        None,
    )

    sources = {item.source for item in suggestions}
    assert "O'Neill" in sources
    assert "Moonlit Club" in sources


def test_suggest_kb_entries_splits_parallel_character_phrases():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "Maya Chen and Detective Chen arrive."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Maya Chen", "Detective Chen"]
    assert "Maya Chen and Detective Chen" not in by_source


def test_suggest_kb_entries_splits_parallel_connected_titles():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "The Last of Us and Lord of the Rings."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["The Last of Us", "Lord of the Rings"]
    assert "The Last of Us and Lord of the Rings" not in by_source


def test_suggest_kb_entries_drops_sentence_start_adverb_from_entity():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "Tonight Maya Chen arrives."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Maya Chen"]
    assert "Tonight Maya Chen" not in by_source
    assert "Tonight" not in by_source


def test_suggest_kb_entries_drops_sentence_start_pronoun():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "She meets Maya Chen."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Maya Chen"]
    assert "She" not in by_source


def test_suggest_kb_entries_preserves_in_the_connected_title():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "Only Murders in the Building returns."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Only Murders in the Building"]
    assert "Only Murders" not in by_source
    assert "Building" not in by_source


def test_suggest_kb_entries_preserves_a_connected_title():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "Once Upon a Time ended."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Once Upon a Time"]
    assert "Once Upon" not in by_source
    assert "Time" not in by_source


def test_suggest_kb_entries_splits_at_relational_phrase():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "Maya Chen at the Moonlit Club."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Maya Chen", "Moonlit Club"]
    assert "Maya Chen at the Moonlit Club" not in by_source


def test_suggest_kb_entries_splits_in_relational_phrase():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "Maya Chen in New York."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Maya Chen", "New York"]
    assert "Maya Chen in New York" not in by_source


def test_suggest_kb_entries_splits_the_relational_phrase():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "The Matrix at the Moonlit Club."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["The Matrix", "Moonlit Club"]
    assert "The Matrix at the Moonlit Club" not in by_source


def test_suggest_kb_entries_keeps_acronym_after_denied_starter():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "Tonight NASA launches."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["NASA"]
    assert "Tonight NASA" not in by_source
    assert "Tonight" not in by_source


def test_suggest_kb_entries_splits_newline_separated_subtitle_phrases():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {},
        [{"index": 8, "text": "Maya Chen\nDetective Chen"}],
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Maya Chen", "Detective Chen"]
    assert "Maya Chen Detective Chen" not in by_source


def test_suggest_kb_entries_reports_ambiguous_existing_collisions():
    from app.engines.kb_models import ProjectKb, TermEntry
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"title": "Acme"},
        None,
        ProjectKb(
            characters=[TermEntry(source="Acme", target="艾克米")],
            brands=[TermEntry(source="ACME", target="阿克米", notes="company")],
        ),
    )

    by_source = {item.source: item for item in suggestions}
    assert by_source["Acme"].collision == "ambiguous"
    assert by_source["Acme"].existing_entries == [
        {"category": "characters", "source": "Acme", "target": "艾克米", "notes": ""},
        {"category": "brands", "source": "ACME", "target": "阿克米", "notes": "company"},
    ]
    assert by_source["Acme"].to_dict()["existing_entries"] == by_source["Acme"].existing_entries


def test_suggest_kb_entries_keeps_uppercase_acronyms_but_ignores_noise():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "NASA meets FBI at IKEA. OK. TV."},
        None,
        None,
    )

    sources = {item.source for item in suggestions}
    assert {"NASA", "FBI", "IKEA"} <= sources
    assert "OK" not in sources
    assert "TV" not in sources
