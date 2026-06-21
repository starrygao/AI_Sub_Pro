def test_infer_content_metadata_from_filename_detects_academic_lecture():
    from app.engines.project_metadata import infer_content_metadata_from_filename

    meta = infer_content_metadata_from_filename(
        "MIT.Physics.Lecture.03.Quantum.Entanglement.1080p.mp4"
    )

    assert meta["content_type"] == "academic_lecture"
    assert meta["academic_field"] == "physics"
    assert meta["metadata_source"] == "filename"


def test_build_project_metadata_prompt_snippet_includes_manual_context_and_terms():
    from app.engines.project_metadata import build_project_metadata_prompt_snippet

    snippet, hits = build_project_metadata_prompt_snippet({
        "content_type": "academic_lecture",
        "academic_field": "machine learning",
        "content_notes": "Guest lecture on transformers and scaling laws.",
        "manual_terms": "transformer=Transformer\nscaling law=缩放定律",
    })

    assert "Project content metadata" in snippet
    assert "academic lecture" in snippet.lower()
    assert "machine learning" in snippet
    assert "Guest lecture on transformers" in snippet
    assert "transformer -> Transformer" in snippet
    assert "scaling law -> 缩放定律" in snippet
    assert {hit["scope"] for hit in hits} == {"project_metadata", "manual_terms"}


def test_build_project_metadata_prompt_snippet_includes_network_video_source_context():
    from app.engines.project_metadata import build_project_metadata_prompt_snippet

    snippet, hits = build_project_metadata_prompt_snippet({
        "source_title": "MIT 6.S191 Lecture 1: Deep Learning Basics",
        "source_uploader": "MIT Introduction to Deep Learning",
        "source_channel": "MIT Deep Learning",
        "source_language": "en",
        "subtitle_source": "native",
        "native_subtitle_language": "en",
        "source_has_subtitles": True,
    })

    assert "Project content metadata" in snippet
    assert "MIT 6.S191 Lecture 1" in snippet
    assert "MIT Introduction to Deep Learning" in snippet
    assert "Source language: en" in snippet
    assert "Native subtitle language: en" in snippet
    assert any(hit["scope"] == "project_metadata" for hit in hits)


def test_build_translation_strategy_explains_profiles_retrieval_and_qa():
    from app.engines.translation_strategy import build_translation_strategy

    strategy = build_translation_strategy(
        {
            "id": "p1",
            "name": "Stanford CS229 Lecture 04",
            "content_type": "academic_lecture",
            "academic_field": "machine learning",
            "manual_terms": "gradient descent=梯度下降\nconvexity=凸性",
            "source_title": "CS229 Lecture 04: Convexity",
            "source_language": "en",
            "subtitle_source": "native",
            "native_subtitle_language": "en",
            "source_has_subtitles": True,
        },
        {
            "translation": {
                "use_translation_memory": True,
                "use_phrase_library": True,
                "quality_mode": "professional",
                "qa_auto_repair": True,
                "qa_auto_repair_rounds": 1,
                "max_memory_examples": 6,
                "max_phrase_examples": 4,
            }
        },
    )

    assert strategy["status"] == "ready"
    assert strategy["content_type"] == "academic_lecture"
    assert strategy["content_type_label"] == "academic lecture"
    assert strategy["summary"].startswith("已启用")
    assert [profile["id"] for profile in strategy["active_profiles"]] == ["academic_lecture"]
    assert "Academic lecture / research talk" in strategy["active_profiles"][0]["label"]
    assert strategy["manual_terms_count"] == 2
    assert strategy["manual_terms"][0] == {"source": "gradient descent", "target": "梯度下降"}
    assert strategy["retrieval"]["translation_memory"] is True
    assert strategy["retrieval"]["phrase_library"] is True
    assert strategy["retrieval"]["max_phrase_examples"] == 4
    assert strategy["quality_mode"]["id"] == "professional"
    assert strategy["quality_mode"]["label"] == "专业辅助"
    assert strategy["quality_mode"]["requires_kb_review"] is False
    assert strategy["quality_mode"]["quality_gate"] is True
    assert strategy["qa"]["auto_repair"] is True
    assert strategy["qa"]["auto_repair_rounds"] == 1
    assert strategy["source"]["native_subtitle_language"] == "en"
    assert any(item["id"] == "native_subtitles" for item in strategy["recommendations"])


def test_build_translation_strategy_allows_explicit_kb_review_gate():
    from app.engines.translation_strategy import build_translation_strategy

    strategy = build_translation_strategy(
        {"id": "p1", "name": "Show S01E01"},
        {
            "translation": {
                "quality_mode": "professional",
                "require_kb_suggestion_review": True,
            }
        },
    )

    assert strategy["quality_mode"]["id"] == "professional"
    assert strategy["quality_mode"]["requires_kb_review"] is True


def test_build_translation_strategy_warns_when_auto_has_no_profile_or_terms():
    from app.engines.translation_strategy import build_translation_strategy

    strategy = build_translation_strategy(
        {"id": "p2", "name": "unknown-video.mp4", "content_type": "auto"},
        {"translation": {"use_translation_memory": False, "use_phrase_library": False}},
    )

    assert strategy["status"] == "needs_context"
    assert strategy["active_profiles"] == []
    assert strategy["manual_terms_count"] == 0
    assert strategy["quality_mode"]["id"] == "fast"
    assert strategy["quality_mode"]["requires_kb_review"] is False
    assert any(item["id"] == "professional_mode_available" for item in strategy["recommendations"])
    assert any(item["id"] == "choose_content_type" for item in strategy["recommendations"])
    assert any(item["id"] == "add_terms" for item in strategy["recommendations"])
