def _profile_ids(meta):
    from app.engines.content_profiles import infer_content_profiles

    return [profile.id for profile in infer_content_profiles(meta)]


def test_infer_content_profiles_covers_requested_content_types():
    cases = [
        (
            {
                "name": "Blue Harbor S02E03",
                "original_language": "en",
                "tmdb_type": "tv",
                "genres": ["Drama"],
            },
            "us_series",
        ),
        (
            {
                "name": "Director Interview",
                "overview": "A long interview with the cast and host.",
                "tags": ["interview"],
            },
            "interview",
        ),
        (
            {
                "name": "Korean Drama S01E01",
                "original_language": "ko",
                "tmdb_type": "tv",
            },
            "korean_drama",
        ),
        (
            {
                "name": "Japanese Drama S01E01",
                "original_language": "ja",
                "tmdb_type": "tv",
            },
            "japanese_drama",
        ),
        (
            {
                "name": "Studio AV Release",
                "tags": ["adult"],
                "overview": "Legal adult content with consenting adults.",
            },
            "legal_adult",
        ),
        (
            {
                "name": "The Last Signal",
                "original_language": "en",
                "tmdb_type": "movie",
                "genres": ["Thriller"],
            },
            "movie",
        ),
        (
            {
                "name": "Planet Archive",
                "genres": ["Documentary"],
                "tags": ["unscripted"],
            },
            "documentary_unscripted",
        ),
        (
            {
                "name": "Roommates S03E04",
                "original_language": "en",
                "tmdb_type": "tv",
                "genres": ["Comedy", "Sitcom"],
            },
            "sitcom_comedy",
        ),
        (
            {
                "name": "Late Night Anime",
                "original_language": "ja",
                "genres": ["Anime"],
            },
            "anime",
        ),
        (
            {
                "name": "Python Async Tutorial",
                "tags": ["tutorial", "programming"],
            },
            "technical_tutorial",
        ),
    ]

    for meta, expected_id in cases:
        assert expected_id in _profile_ids(meta)


def test_infer_content_profiles_uses_network_video_source_title():
    assert "academic_lecture" in _profile_ids({
        "name": "YouTube 视频",
        "source_title": "MIT 6.S191 Lecture 1: Deep Learning Basics",
        "source_channel": "MIT Deep Learning",
        "original_language": "en",
    })


def test_build_content_profile_prompt_snippet_is_bounded_and_traceable():
    from app.engines.content_profiles import build_content_profile_prompt_snippet

    snippet, hits = build_content_profile_prompt_snippet({
        "name": "Korean Drama Cast Interview",
        "original_language": "ko",
        "tmdb_type": "tv",
        "tags": ["interview"],
    })

    assert "Content profile guidance" in snippet
    assert "[Korean drama]" in snippet
    assert "[Interview]" in snippet
    assert "honorific" in snippet.lower()
    assert "filler" in snippet.lower()
    assert len(hits) == 2
    assert {hit["id"] for hit in hits} == {"korean_drama", "interview"}
    assert all(hit["scope"] == "content_profile" for hit in hits)


def test_adult_profile_uses_legal_adult_safety_framing():
    from app.engines.content_profiles import build_content_profile_prompt_snippet

    snippet, hits = build_content_profile_prompt_snippet({
        "name": "AV Behind The Scenes",
        "tags": ["adult"],
    })

    assert hits[0]["id"] == "legal_adult"
    assert "legal adult content" in snippet.lower()
    assert "成年" in snippet
    assert "自愿" in snippet


def test_legal_adult_profile_includes_explicit_subtitle_examples():
    from app.engines.content_profiles import build_content_profile_prompt_snippet

    snippet, hits = build_content_profile_prompt_snippet({
        "name": "Studio AV Release",
        "tags": ["adult"],
    })

    assert hits[0]["id"] == "legal_adult"
    assert hits[0]["example_count"] >= 3
    assert "Explicit adult subtitle examples" in snippet
    assert "Fuck me. → 操我。" in snippet
    assert "I'm coming. → 我要去了。" in snippet
    assert "Harder. → 用力点。" in snippet


def test_non_adult_profiles_do_not_include_explicit_adult_examples():
    from app.engines.content_profiles import build_content_profile_prompt_snippet

    snippet, hits = build_content_profile_prompt_snippet({
        "name": "Blue Harbor S02E03",
        "original_language": "en",
        "tmdb_type": "tv",
    })

    assert "Explicit adult subtitle examples" not in snippet
    assert "操我" not in snippet
    assert all(hit.get("example_count", 0) == 0 for hit in hits)


def test_new_researched_profiles_add_targeted_guidance():
    from app.engines.content_profiles import build_content_profile_prompt_snippet

    snippet, hits = build_content_profile_prompt_snippet({
        "name": "Anime Documentary Coding Tutorial S01E01",
        "original_language": "ja",
        "genres": ["Anime", "Documentary", "Comedy"],
        "tags": ["tutorial", "unscripted"],
    })

    ids = {hit["id"] for hit in hits}
    assert {"anime", "documentary_unscripted", "sitcom_comedy", "technical_tutorial"} <= ids
    assert "speaker titles only when they first appear" in snippet
    assert "preserve punchline timing" in snippet.lower()
    assert "attack names" in snippet.lower()
    assert "commands, code identifiers, API names" in snippet


def test_academic_profile_adds_lecture_and_research_guidance():
    from app.engines.content_profiles import build_content_profile_prompt_snippet

    snippet, hits = build_content_profile_prompt_snippet({
        "name": "MIT Physics Lecture 03",
        "content_type": "academic_lecture",
        "academic_field": "physics",
        "overview": "Research seminar on quantum entanglement.",
    })

    ids = {hit["id"] for hit in hits}
    assert "academic_lecture" in ids
    assert "equations, symbols, variables" in snippet
    assert "citations, paper titles" in snippet


def test_content_profiles_do_not_overapply_adult_or_drama_profiles():
    assert "legal_adult" not in _profile_ids({
        "name": "Adult Animation S01E01",
        "original_language": "en",
        "tmdb_type": "tv",
        "genres": ["Animation"],
    })
    assert "legal_adult" not in _profile_ids({
        "name": "Young Adult Movie",
        "tmdb_type": "movie",
        "genres": ["Drama"],
    })
    assert "japanese_drama" not in _profile_ids({
        "name": "Late Night Anime",
        "original_language": "ja",
        "tmdb_type": "tv",
        "genres": ["Anime"],
    })
    assert "japanese_drama" not in _profile_ids({
        "name": "Tokyo Documentary",
        "original_language": "ja",
        "tmdb_type": "movie",
        "genres": ["Documentary"],
    })
