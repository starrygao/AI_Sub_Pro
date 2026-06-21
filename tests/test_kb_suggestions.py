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


def test_suggest_kb_entries_splits_multiple_relational_phrases():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "Maya Chen at the Moonlit Club in New York."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Maya Chen", "Moonlit Club", "New York"]
    assert "Maya Chen at the Moonlit Club in New York" not in by_source
    assert "Moonlit Club in New York" not in by_source


def test_suggest_kb_entries_drops_quoted_sentence_start_adverb():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "\"Tonight Maya Chen arrives.\""},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Maya Chen"]
    assert "Tonight Maya Chen" not in by_source
    assert "Tonight" not in by_source


def test_suggest_kb_entries_drops_dash_sentence_start_adverb():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "- Tonight Maya Chen arrives."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["Maya Chen"]
    assert "Tonight Maya Chen" not in by_source
    assert "Tonight" not in by_source


def test_suggest_kb_entries_preserves_denied_starter_connected_title():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"overview": "This Is Us returns."},
        None,
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert list(by_source) == ["This Is Us"]
    assert "Is Us" not in by_source


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


def test_suggest_kb_entries_drops_single_word_subtitle_noise_but_keeps_entities():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {},
        [{
            "index": 9,
            "text": "Here. Right? Are you ready? Thank you. James Stagg briefs NASA. Sofia arrives.",
        }],
        None,
    )

    sources = {item.source for item in suggestions}
    assert {"James Stagg", "NASA", "Sofia"} <= sources
    assert "Here" not in sources
    assert "Right" not in sources
    assert "Are" not in sources
    assert "Thank" not in sources


def test_load_suggestions_filters_legacy_pending_single_word_subtitle_noise(tmp_path):
    from app.engines.kb_suggestions import KbSuggestion, load_suggestions, save_suggestions

    path = tmp_path / "kb_suggestions.json"
    save_suggestions(path, [
        KbSuggestion(source="Here", evidence=["subtitle:1"]),
        KbSuggestion(source="Right", evidence=["subtitle:1"], status="accepted"),
        KbSuggestion(source="Sofia", evidence=["subtitle:1"]),
        KbSuggestion(source="James Stagg", evidence=["subtitle:1"]),
        KbSuggestion(source="Here", evidence=["title"]),
    ])

    loaded = load_suggestions(path)
    rows = [(item.source, item.evidence, item.status) for item in loaded]
    assert ("Here", ["subtitle:1"], "pending") not in rows
    assert ("Right", ["subtitle:1"], "accepted") in rows
    assert ("Sofia", ["subtitle:1"], "pending") in rows
    assert ("James Stagg", ["subtitle:1"], "pending") in rows
    assert ("Here", ["title"], "pending") in rows


def test_suggest_kb_entries_prefills_curated_science_terms():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"name": "Surviving Earth", "overview": "Permian and Triassic life."},
        [
            {"index": 141, "text": "These little climbers are Suminia."},
            {"index": 330, "text": "A female Dongusuchus."},
            {"index": 342, "text": "called proto-Pterosaurs, head for the sand."},
        ],
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert by_source["Suminia"].target == "苏美尼兽"
    assert by_source["Suminia"].category == "slang"
    assert by_source["Suminia"].confidence >= 0.8
    assert "subtitle:141" in by_source["Suminia"].evidence
    assert "curated science terminology" in by_source["Suminia"].notes
    assert by_source["Dongusuchus"].target == "顿古兹鳄"
    assert by_source["proto-Pterosaurs"].target == "原翼龙类"


def test_suggest_kb_entries_extracts_auto_scientific_terms_without_context_fragments():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"name": "Surviving Earth"},
        [
            {"index": 1, "text": "Without the Dicroidium, the forest thins."},
            {"index": 2, "text": "As the Ischigualastia feeds, a predator waits."},
            {"index": 3, "text": "[baby Ischigualastia cries]"},
            {"index": 4, "text": "A Saurosuchus watches from the riverbank."},
        ],
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert {"Dicroidium", "Ischigualastia", "Saurosuchus"} <= set(by_source)
    assert "Without the Dicroidium" not in by_source
    assert "As the Ischigualastia" not in by_source
    assert "The Ischigualastia" not in by_source
    assert by_source["Ischigualastia"].target == ""
    assert by_source["Ischigualastia"].confidence >= 0.72
    assert "auto-detected scientific" in by_source["Ischigualastia"].notes
    assert set(by_source["Ischigualastia"].evidence) == {"subtitle:2", "subtitle:3"}


def test_suggest_kb_entries_filters_curated_science_context_fragments():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {},
        [
            {"index": 1, "text": "Without the Permian climate shift, life would be different."},
            {"index": 2, "text": "As the Triassic begins, new species spread."},
        ],
        None,
    )

    by_source = {item.source: item for item in suggestions}
    assert {"Permian", "Triassic"} <= set(by_source)
    assert "Without the Permian" not in by_source
    assert "As the Triassic" not in by_source


def test_suggest_kb_entries_does_not_treat_common_ium_technical_names_as_science_terms():
    from app.engines.kb_suggestions import suggest_kb_entries

    suggestions = suggest_kb_entries(
        {"name": "Browser Automation Tutorial", "tags": ["tutorial", "programming"]},
        [{"index": 1, "text": "Chromium renders the page while Selenium drives the browser."}],
        None,
    )

    sources = {item.source for item in suggestions}
    assert "Chromium" not in sources
    assert "Selenium" not in sources
