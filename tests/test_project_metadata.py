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
